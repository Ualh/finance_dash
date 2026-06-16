from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import load_config
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


@app.get("/settings/{key}")
def get_setting(key: str, repo: Annotated[SQLiteRepository, Depends(get_repository)]) -> dict:
    value = repo.get_setting(key)
    return {"key": key, "value": value}


@app.put("/settings/{key}")
def put_setting(key: str, body: SettingInput, repo: Annotated[SQLiteRepository, Depends(get_repository)]) -> dict:
    repo.set_setting(key, body.value)
    return {"key": key, "value": body.value}
