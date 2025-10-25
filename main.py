"""Entrypoint for running the finance_dash FastAPI backend locally."""
from __future__ import annotations

import uvicorn

from backend import app


if __name__ == "__main__":
    uvicorn.run(
        "backend.api:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
