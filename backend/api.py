"""FastAPI application exposing the finance_dash backend."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Annotated, Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .config import AppConfig, load_config
from .database import SQLiteRepository
from .price_service import PriceService
from .services import PortfolioService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialise shared services once and reuse them across requests."""

    config = load_config()
    repository = SQLiteRepository(config.database_file)
    repository.initialise_schema()
    price_service = PriceService(config)
    portfolio_service = PortfolioService(config, repository, price_service)

    app.state.config = config
    app.state.repository = repository
    app.state.portfolio = portfolio_service

    yield

    repository.close()


app = FastAPI(lifespan=lifespan, title="finance_dash backend", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Dependency injection ------------------------------------------------------

def get_portfolio_service() -> PortfolioService:
    service: PortfolioService = app.state.portfolio
    return service


def get_repository() -> SQLiteRepository:
    repository: SQLiteRepository = app.state.repository
    return repository


# Routes --------------------------------------------------------------------


@app.get("/health")
def health_check() -> dict[str, str]:
    """Return a basic heartbeat payload for monitoring purposes."""

    return {"status": "ok"}


@app.post("/import")
def import_workbook(
    sheet_names: Annotated[list[str] | None, Query(description="Workbook sheet names to import")]=None,
    portfolio_service: Annotated[PortfolioService, Depends(get_portfolio_service)] = None,
) -> dict[str, object]:
    """Import the Excel workbook and persist normalised transactions."""

    sheets = sheet_names or ["crypto_transac", "stocks_transac"]
    imported = portfolio_service.import_workbook(sheets)
    return {"imported": imported, "sheets": sheets}


@app.get("/transactions")
def list_transactions(
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    portfolio_service: Annotated[PortfolioService, Depends(get_portfolio_service)] = None,
) -> dict[str, object]:
    transactions = portfolio_service.recent_transactions(limit)
    return {"transactions": transactions, "count": len(transactions)}


@app.get("/summary")
def cash_summary(
    display_currency: Annotated[str, Query(regex="^[A-Za-z]{3}$")] = "CHF",
    portfolio_service: Annotated[PortfolioService, Depends(get_portfolio_service)] = None,
) -> dict[str, object]:
    summary = portfolio_service.cash_summary(display_currency.upper())
    summary["requested_currency"] = display_currency.upper()
    return summary


@app.post("/fx/refresh")
def refresh_fx_rate(
    base: Annotated[str, Query(regex="^[A-Za-z]{3}$")],
    quote: Annotated[str, Query(regex="^[A-Za-z]{3}$")],
    portfolio_service: Annotated[PortfolioService, Depends(get_portfolio_service)] = None,
) -> dict[str, object]:
    rate = portfolio_service.refresh_fx_rate(base.upper(), quote.upper())
    if not rate:
        raise HTTPException(status_code=503, detail="FX rate unavailable. Ensure the Alpha Vantage API key is configured.")
    return {
        "base": rate.base,
        "quote": rate.quote,
        "valuation_date": rate.valuation_date.isoformat(),
        "rate": rate.rate,
        "source": rate.source,
    }


@app.post("/quotes/equity/{symbol}")
def refresh_equity_quote(
    symbol: str,
    portfolio_service: Annotated[PortfolioService, Depends(get_portfolio_service)] = None,
) -> dict[str, object]:
    quote = portfolio_service.refresh_equity_quote(symbol)
    if not quote:
        raise HTTPException(status_code=503, detail="Equity quote unavailable. Check the Alpha Vantage API key.")
    return {
        "symbol": quote.symbol,
        "valuation_date": quote.valuation_date.isoformat(),
        "price": quote.price,
        "currency": quote.currency,
        "source": quote.source,
    }


@app.post("/quotes/crypto/{uuid}")
def refresh_crypto_quote(
    uuid: str,
    portfolio_service: Annotated[PortfolioService, Depends(get_portfolio_service)] = None,
) -> dict[str, object]:
    quote = portfolio_service.refresh_crypto_quote(uuid)
    if not quote:
        raise HTTPException(status_code=503, detail="Crypto quote unavailable. Check the Coinranking API key.")
    return {
        "symbol": quote.symbol,
        "valuation_date": quote.valuation_date.isoformat(),
        "price": quote.price,
        "currency": quote.currency,
        "source": quote.source,
    }


@app.get("/settings/display-currency")
def get_display_currency(repository: Annotated[SQLiteRepository, Depends(get_repository)]) -> dict[str, str]:
    currency = repository.get_setting("display_currency", "CHF")
    return {"display_currency": currency}


@app.put("/settings/display-currency")
def set_display_currency(
    currency: Annotated[str, Query(regex="^[A-Za-z]{3}$")],
    repository: Annotated[SQLiteRepository, Depends(get_repository)] = None,
) -> dict[str, str]:
    repository.set_setting("display_currency", currency.upper())
    return {"display_currency": currency.upper()}
