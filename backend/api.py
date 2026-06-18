from __future__ import annotations

import logging
from contextlib import asynccontextmanager
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
from .database import SQLiteRepository
from .fx import convert as fx_convert
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


@app.get("/dashboard")
def dashboard(repo: Annotated[SQLiteRepository, Depends(get_repository)], currency: str = "CHF") -> dict:
    agg = repo.get_aggregate_holdings()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    previous_snapshot = repo.get_latest_snapshot_before(today)
    delta_chf = None
    delta_pct = None
    if previous_snapshot:
        delta_chf = agg["total_chf"] - previous_snapshot["total_chf"]
        if previous_snapshot["total_chf"]:
            delta_pct = round(delta_chf / previous_snapshot["total_chf"] * 100, 2)

    sources = {}
    for src_name, src_info in agg["sources"].items():
        last_log = repo.get_last_sync_log(src_name)
        sync_error = bool(last_log and last_log["status"] == "error")
        sources[src_name] = {
            "total_chf": src_info["total_chf"],
            "last_updated": src_info["last_updated"],
            "last_sync": last_log["started_at"] if last_log else None,
            "sync_error": sync_error,
        }

    payload = {
        "total_chf": agg["total_chf"],
        "buckets": agg["buckets"],
        "delta_chf": delta_chf,
        "delta_pct": delta_pct,
        "sources": sources,
    }

    target = currency.upper()
    if target != "CHF":
        conv = fx_convert(repo, agg["total_chf"], target)
        payload["total_chf"] = conv["amount"]
        payload["_fx"] = {"rate": conv["rate"], "stale": conv["stale"], "currency": target}
        for bucket_name in ("available", "invested", "locked"):
            bconv = fx_convert(repo, agg["buckets"].get(bucket_name, 0.0), target)
            payload["buckets"][bucket_name] = bconv["amount"]
        for src_name, src_info in sources.items():
            sconv = fx_convert(repo, src_info["total_chf"], target)
            payload["sources"][src_name]["total_chf"] = sconv["amount"]

    return payload


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
        anchor_date = repo.get_setting("neon_anchor_date")
        anchor_amount_str = repo.get_setting("neon_anchor_amount")
        anchor_amount = float(anchor_amount_str) if anchor_amount_str is not None else None
        all_transactions = repo.get_all_neon_transactions()
        balance = compute_balance_from_ledger(all_transactions, anchor_date, anchor_amount)
        repo.upsert_holding(
            source="neon",
            source_type="csv",
            asset_class="cash",
            value_chf=balance,
            label="Neon",
        )

    return {"key": key, "value": body.value}


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
    return {"holding": holding}


dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if dist.is_dir():

    @app.exception_handler(404)
    async def serve_spa(request: Request, exc):
        path = request.url.path.lstrip("/")
        is_api = any(
            path.startswith(p) or path == p.strip("/")
            for p in ("dashboard", "health", "sync/", "holdings/", "settings/")
        )
        if is_api:
            return JSONResponse(status_code=404, content={"detail": exc.detail or "Not Found"})
        file_path = dist / path
        if file_path.is_file():
            content_type, _ = mimetypes.guess_type(str(file_path))
            return FileResponse(str(file_path), media_type=content_type)
        return FileResponse(str(dist / "index.html"))
