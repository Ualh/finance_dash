from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import load_config
from .database import SQLiteRepository

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


@app.get("/dashboard")
def dashboard(repo: Annotated[SQLiteRepository, Depends(get_repository)]) -> dict:
    agg = repo.get_aggregate_holdings()
    latest_snapshot = repo.get_latest_snapshot()
    delta_chf = None
    if latest_snapshot:
        delta_chf = agg["total_chf"] - latest_snapshot["total_chf"]
    return {
        "total_chf": agg["total_chf"],
        "buckets": agg["buckets"],
        "delta_chf": delta_chf,
        "sources": agg["sources"],
    }


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
