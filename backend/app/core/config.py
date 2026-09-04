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
MAX_BACKOFF_SECONDS = float(os.environ.get("FILEMIND_MAX_BACKOFF_SECONDS", "60.0"))
HASH_CHUNK_SIZE_BYTES = 64 * 1024  # 64 KB streaming buffer

# Ingestion guards & limits
# 50 MB default file size guard before hashing/parsing/embedding
MAX_FILE_SIZE_BYTES = int(os.environ.get("FILEMIND_MAX_FILE_SIZE_BYTES", 50 * 1024 * 1024))

# Persistent rotating logging configuration
LOG_DIR = APP_DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_LOG_FILE = LOG_DIR / "filemind.log"
MAX_LOG_BYTES = 5 * 1024 * 1024  # 5 MB per log file
LOG_BACKUP_COUNT = 5  # Retain up to 5 rotated backup files
DEFAULT_LOG_LEVEL = os.environ.get("FILEMIND_LOG_LEVEL", "INFO").upper()

# Phase 3 Embedding configuration defaults
EMBEDDING_RETRY_COOLDOWN_SECONDS = float(
    os.environ.get("FILEMIND_EMBED_RETRY_COOLDOWN_SEC", "30.0")
)

# Phase 4 Reranker configuration defaults
DEFAULT_RERANK_MODEL_NAME = "BAAI/bge-reranker-base"
DEFAULT_RERANK_POOL = 25
RERANKER_LOAD_TIMEOUT_SECONDS = 15.0
RERANKER_RETRY_COOLDOWN_SECONDS = float(
    os.environ.get("FILEMIND_RERANK_RETRY_COOLDOWN_SEC", "30.0")
)

OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = "qwen3:4b"
OLLAMA_CONNECT_TIMEOUT_SECONDS = 2.0
OLLAMA_READ_TIMEOUT_SECONDS = 120.0
