"""Application configuration and persistent storage path definitions."""

import os
from pathlib import Path


def get_app_data_dir() -> Path:
    """Returns the persistent application data directory for FileMind."""
    if os.name == "nt":
        app_data = os.environ.get("APPDATA")
        if app_data:
            base_dir = Path(app_data) / "FileMind"
        else:
            base_dir = Path.home() / "AppData" / "Roaming" / "FileMind"
    else:
        base_dir = Path.home() / ".filemind"

    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


APP_DATA_DIR = get_app_data_dir()
DEFAULT_DB_PATH = APP_DATA_DIR / "filemind.db"

# Engine configuration defaults
DEFAULT_MAX_WORKERS = 2
DEFAULT_DEBOUNCE_SECONDS = 0.5
MAX_RETRY_ATTEMPTS = 3
INITIAL_BACKOFF_SECONDS = 1.0
HASH_CHUNK_SIZE_BYTES = 64 * 1024  # 64 KB streaming buffer
