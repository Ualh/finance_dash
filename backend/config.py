"""Application configuration utilities for the finance_dash backend.

This module centralises environment-driven configuration so the rest of the
code base does not need to read environment variables directly.  The module
adheres to the single-responsibility principle by only handling configuration
concerns.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load any variables defined in a local .env file. The call is idempotent and
# inexpensive, so importing it at module import time keeps the API ergonomic.
load_dotenv()


@dataclass(frozen=True)
class AppConfig:
    """Strongly-typed container for runtime configuration.

    Attributes:
        project_root: Root directory of the project. Used to derive default
            paths so the app works out of the box after cloning the repo.
        data_file: Absolute path to the Excel workbook containing the raw bank
            transactions that seed the local database.
        database_file: Absolute path to the SQLite database file that should be
            created and owned by the current process.
        alpha_vantage_key: Optional API key for the Alpha Vantage service. The
            key is required to retrieve FX rates and equity quotes.
        coinranking_key: Optional API key for the Coinranking service. The key
            is required to retrieve crypto quotes.
        alpha_vantage_endpoint: Endpoint URL used when talking to Alpha
            Vantage. Defaults to the public REST API endpoint.
        coinranking_host: Host header required by the Coinranking RapidAPI
            gateway.
    """

    project_root: Path
    data_file: Path
    database_file: Path
    alpha_vantage_key: Optional[str]
    coinranking_key: Optional[str]
    alpha_vantage_endpoint: str
    coinranking_host: str

    @property
    def database_uri(self) -> str:
        """Return a SQLite URI pointing at :attr:`database_file`.

        The URI form is understood by both the built-in :mod:`sqlite3` module
        and higher-level ORMs. Keeping the logic in the configuration avoids
        sprinkling string formatting throughout the code base.
        """

        return f"file:{self.database_file}?mode=rwc"


def load_config() -> AppConfig:
    """Create a new :class:`AppConfig` instance based on environment settings.

    Environment variables override the default values, allowing users to
    customise the runtime without touching the source code. The function keeps
    the implementation small and self-contained so unit tests can easily supply
    patched environments.
    """

    project_root = Path(__file__).resolve().parent.parent
    data_file = Path(
        getenv_with_default(
            "FINANCE_DASH_DATA_FILE",
            project_root / "data" / "transactions_v3.xlsx",
        )
    )
    database_file = Path(
        getenv_with_default(
            "FINANCE_DASH_DB_FILE",
            project_root / "finance_dash.db",
        )
    )

    alpha_vantage_key = getenv_with_default("ALPHAVANTAGE_API_KEY")
    coinranking_key = getenv_with_default("COINRANKING_API_KEY")
    alpha_vantage_endpoint = getenv_with_default(
        "ALPHAVANTAGE_ENDPOINT",
        "https://www.alphavantage.co/query",
    )
    coinranking_host = getenv_with_default(
        "COINRANKING_HOST",
        "coinranking1.p.rapidapi.com",
    )

    # Ensure the directories exist so later code can safely create files.
    database_file.parent.mkdir(parents=True, exist_ok=True)

    return AppConfig(
        project_root=project_root,
        data_file=data_file,
        database_file=database_file,
        alpha_vantage_key=alpha_vantage_key,
        coinranking_key=coinranking_key,
        alpha_vantage_endpoint=alpha_vantage_endpoint,
        coinranking_host=coinranking_host,
    )


def getenv_with_default(name: str, default: Optional[Path | str] = None) -> Optional[str]:
    """Return the value of an environment variable or a sensible default.

    ``None`` values are propagated so callers can make explicit decisions about
    optional configuration values. Paths are converted to strings, keeping the
    return type uniform and easy to serialise.
    """

    from os import getenv

    value = getenv(name)
    if value is not None:
        return value
    if default is None:
        return None
    return str(default)
