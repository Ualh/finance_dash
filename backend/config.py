from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    database_file: Path


def load_config() -> AppConfig:
    project_root = Path(__file__).resolve().parent.parent
    database_file = Path(
        getenv_with_default(
            "FINANCE_DASH_DB_FILE",
            project_root / "finance_dash.db",
        )
    )
    database_file.parent.mkdir(parents=True, exist_ok=True)
    return AppConfig(
        project_root=project_root,
        database_file=database_file,
    )


def getenv_with_default(name: str, default: Optional[Path | str] = None) -> Optional[str]:
    from os import getenv
    value = getenv(name)
    if value is not None:
        return value
    if default is None:
        return None
    return str(default)
