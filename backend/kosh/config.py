"""Paths and runtime settings."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("KOSH_DATA_DIR", REPO_ROOT / "data"))
DB_PATH = Path(os.environ.get("KOSH_DB", DATA_DIR / "kosh.db"))
CACHE_DIR = DATA_DIR / "cache"
WEB_DIST = Path(__file__).resolve().parent / "web_dist"
SNAPSHOT_DIR = Path(__file__).resolve().parent / "marketdata" / "snapshot"

AUTH_USER = os.environ.get("KOSH_AUTH_USER")
AUTH_PASS = os.environ.get("KOSH_AUTH_PASS")

HTTP_TIMEOUT = 45.0
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
