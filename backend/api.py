from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import date as date_type
from datetime import datetime, timezone
from typing import Annotated

from pathlib import Path

import mimetypes
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from .config import load_config
from .csv_source.neon import archive_csv, parse_neon_csv
from .database import LIQUIDITY_BUCKET, SQLiteRepository
from .freshness import STALE_AFTER_DAYS, source_freshness
from .fx import convert as fx_convert
from .fx import convert_to_chf
from .snapshots import monthly_history, record_snapshot
from .spending import recent_spending
from .sync.engine import run_sync_all

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    config = load_config()
    repository = SQLiteRepository(config.database_file)
    repository.initialise_schema()
    app.state.repository = repository
    yield
    repository.close()


app = FastAPI(lifespan=lifespan, title="finance_dash backend", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_repository() -> SQLiteRepository:
    return app.state.repository


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


class HoldingInput(BaseModel):
    value_chf: float
    label: str | None = None


class SettingInput(BaseModel):
    value: str

class HoldingUpdateInput(BaseModel):
    value_chf: float


class ManualHoldingInput(BaseModel):
    label: str
    asset_class: str
    amount: float
    currency: str = "CHF"


def _slugify(text: str) -> str:
    return "_".join(text.lower().split())


class CashWithdrawalInput(BaseModel):
    amount_chf: float
    date: date_type
    note: str | None = None


def _today() -> date_type:
    return datetime.now(timezone.utc).date()


@app.get("/dashboard")
def dashboard(repo: Annotated[SQLiteRepository, Depends(get_repository)], currency: str = "CHF") -> dict:
    agg = repo.get_aggregate_holdings()
    today = _today()
    history = monthly_history(repo, agg["total_chf"], today)

    freshness = source_freshness(repo, today)
    sources: dict[str, dict] = {}
    for entry in freshness:
        info = agg["sources"].get(entry["source"])
        last_log = repo.get_last_sync_log(entry["source"])
        failed = bool(last_log and last_log["status"] == "error")
        sources[entry["source"]] = {
            **entry,
            "total_chf": info["total_chf"] if info else None,
            "last_updated": info["last_updated"] if info else None,
            "last_sync": last_log["started_at"] if last_log else None,
            "sync_error": failed,
            "sync_message": last_log["message"] if failed else None,
        }

    payload = {
        "total_chf": agg["total_chf"],
        "buckets": agg["buckets"],
        "change_since_last_month": history["change_since_last_month"],
        "history": history["months"],
        "spending": recent_spending(repo, today),
        "sources": sources,
        "stale_after_days": STALE_AFTER_DAYS,
        "last_sync_at": repo.get_last_sync_run(),
        "last_neon_import_at": repo.get_last_neon_upload(),
    }

    target = currency.upper()
    if target != "CHF":
        def conv(amount):
            return None if amount is None else fx_convert(repo, amount, target)["amount"]

        rate = fx_convert(repo, 1.0, target)
        payload["_fx"] = {"rate": rate["rate"], "stale": rate["stale"], "currency": target}
        payload["total_chf"] = conv(agg["total_chf"])
        payload["buckets"] = {k: conv(v) for k, v in agg["buckets"].items()}
        if payload["change_since_last_month"]:
            payload["change_since_last_month"]["amount_chf"] = conv(payload["change_since_last_month"]["amount_chf"])
        for point in payload["history"]:
            point["total_chf"] = conv(point["total_chf"])
        for month in payload["spending"]:
            month["total_chf"], month["cash_chf"] = conv(month["total_chf"]), conv(month["cash_chf"])
        for src in sources.values():
            src["total_chf"] = conv(src["total_chf"])

    return payload


@app.get("/freshness")
def freshness(repo: Annotated[SQLiteRepository, Depends(get_repository)]) -> dict:
    """What the monthly reminder needs: which sources are older than the stale threshold and what to do."""
    entries = source_freshness(repo, _today())
    stale = [e for e in entries if e["stale"]]
    return {
        "stale_after_days": STALE_AFTER_DAYS,
        "sources": entries,
        "stale": [e["source"] for e in stale],
        "actions": [e["action"] for e in stale],
    }


@app.post("/cash-withdrawals")
def add_cash_withdrawal(body: CashWithdrawalInput, repo: Annotated[SQLiteRepository, Depends(get_repository)]) -> dict:
    if body.amount_chf <= 0:
        raise HTTPException(400, "Amount must be greater than zero")
    note = (body.note or "").strip() or None
    return {"withdrawal": repo.add_cash_withdrawal(body.date.isoformat(), round(body.amount_chf, 2), note)}


@app.get("/cash-withdrawals")
def list_cash_withdrawals(repo: Annotated[SQLiteRepository, Depends(get_repository)]) -> dict:
    return {"withdrawals": repo.list_cash_withdrawals()}


@app.delete("/cash-withdrawals/{withdrawal_id}")
def delete_cash_withdrawal(withdrawal_id: int, repo: Annotated[SQLiteRepository, Depends(get_repository)]) -> dict:
    if not repo.delete_cash_withdrawal(withdrawal_id):
        raise HTTPException(404, "Cash withdrawal not found")
    return {"deleted": withdrawal_id}


@app.get("/sync/all")
@app.post("/sync/all")
def sync_all(repo: Annotated[SQLiteRepository, Depends(get_repository)]) -> dict:
    result = run_sync_all(repo)
    return result


@app.post("/holdings/finpension")
def upsert_finpension_holding(body: HoldingInput, repo: Annotated[SQLiteRepository, Depends(get_repository)]) -> dict:
    holding = repo.upsert_holding(
        source="finpension",
        source_type="manual",
        asset_class="pension",
        value_chf=body.value_chf,
        label=body.label,
    )
    record_snapshot(repo)
    return {"holding": holding}


@app.post("/holdings/neon/upload")
async def upload_neon_csv(
    file: Annotated[UploadFile, File()],
    repo: Annotated[SQLiteRepository, Depends(get_repository)],
) -> dict:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Only .csv files are accepted")

    content = await file.read()
    if not content:
        raise HTTPException(400, "Uploaded file is empty")

    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 10 MB)")

    try:
        rows = parse_neon_csv(content)
    except Exception as exc:
        raise HTTPException(400, str(exc))

    if not rows:
        raise HTTPException(400, "CSV contains no valid transaction rows")

    config = load_config()
    archive_csv(config.project_root, content)

    imported = repo.import_neon_transactions(content, file.filename, rows)

    balance = repo.recompute_neon_balance(*_load_neon_anchor(repo))

    holding = repo.upsert_holding(
        source="neon",
        source_type="csv",
        asset_class="cash",
        value_chf=balance,
        label="Neon",
    )
    record_snapshot(repo)

    return {
        "balance": balance,
        "transactions_parsed": imported,
        "total_transactions": repo.get_neon_transaction_count(),
        "holding": holding,
    }


def _load_neon_anchor(repo: SQLiteRepository) -> tuple[str | None, float | None]:
    anchor_date = repo.get_setting("neon_anchor_date")
    anchor_amount_str = repo.get_setting("neon_anchor_amount")
    anchor_amount = float(anchor_amount_str) if anchor_amount_str is not None else None
    return anchor_date, anchor_amount


@app.post("/holdings/neon/recompute")
def recompute_neon_holding(repo: Annotated[SQLiteRepository, Depends(get_repository)]) -> dict:
    balance = repo.recompute_neon_balance(*_load_neon_anchor(repo))

    holding = repo.upsert_holding(
        source="neon",
        source_type="csv",
        asset_class="cash",
        value_chf=balance,
        label="Neon",
    )
    record_snapshot(repo)

    return {
        "balance": balance,
        "total_transactions": repo.get_neon_transaction_count(),
        "holding": holding,
    }


@app.get("/settings/{key}")
def get_setting(key: str, repo: Annotated[SQLiteRepository, Depends(get_repository)]) -> dict:
    value = repo.get_setting(key)
    return {"key": key, "value": value}


@app.put("/settings/{key}")
def put_setting(key: str, body: SettingInput, repo: Annotated[SQLiteRepository, Depends(get_repository)]) -> dict:
    repo.set_setting(key, body.value)

    if key in ("neon_anchor_date", "neon_anchor_amount"):
        balance = repo.recompute_neon_balance(*_load_neon_anchor(repo))
        repo.upsert_holding(
            source="neon",
            source_type="csv",
            asset_class="cash",
            value_chf=balance,
            label="Neon",
        )
        record_snapshot(repo)

    return {"key": key, "value": body.value}


@app.post("/holdings")
def add_manual_holding(body: ManualHoldingInput, repo: Annotated[SQLiteRepository, Depends(get_repository)]) -> dict:
    label = body.label.strip()
    if not label:
        raise HTTPException(400, "Label is required")
    if body.asset_class not in LIQUIDITY_BUCKET:
        raise HTTPException(400, f"Unknown asset_class '{body.asset_class}'")

    conv = convert_to_chf(repo, body.amount, body.currency)
    holding = repo.upsert_holding(
        source=_slugify(label),
        source_type="manual",
        asset_class=body.asset_class,
        value_chf=conv["amount_chf"],
        label=label,
        native_amount=body.amount,
        native_currency=conv["currency"],
    )
    record_snapshot(repo)
    return {"holding": holding, "fx": {"rate": conv["rate"], "stale": conv["stale"], "currency": conv["currency"]}}


@app.get("/holdings")
def list_holdings(repo: Annotated[SQLiteRepository, Depends(get_repository)]) -> dict:
    holdings = repo.list_holdings()
    return {"holdings": holdings}


@app.put("/holdings/{holding_id}")
def update_holding_value(
    holding_id: int,
    body: HoldingUpdateInput,
    repo: Annotated[SQLiteRepository, Depends(get_repository)],
) -> dict:
    holding = repo.update_holding_value(holding_id, body.value_chf)
    if holding is None:
        raise HTTPException(404, "Holding not found")
    record_snapshot(repo)
    return {"holding": holding}


FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@app.exception_handler(404)
async def serve_spa(request: Request, exc):
    """Serve the built frontend for anything the API does not answer.

    Static files are served as-is. A browser navigation (GET asking for HTML) to any
    other path gets index.html so client routes like /settings survive a refresh or a
    direct link. API clients (fetch sends no text/html Accept) keep the JSON 404.
    """
    not_found = JSONResponse(status_code=404, content={"detail": getattr(exc, "detail", None) or "Not Found"})
    dist = FRONTEND_DIST.resolve()
    if request.method != "GET" or not dist.is_dir():
        return not_found
    file_path = (dist / request.url.path.lstrip("/")).resolve()
    if file_path.is_file() and file_path.is_relative_to(dist):
        content_type, _ = mimetypes.guess_type(str(file_path))
        return FileResponse(str(file_path), media_type=content_type)
    if request.url.path == "/" or "text/html" in request.headers.get("accept", ""):
        return FileResponse(str(dist / "index.html"))
    return not_found
