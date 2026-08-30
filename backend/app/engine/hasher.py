"""Safe, streaming SHA-256 cryptographic hashing."""

import hashlib
import os
from pathlib import Path
from typing import Optional, Tuple
from app.core.config import HASH_CHUNK_SIZE_BYTES


def compute_file_sha256(file_path: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Computes the SHA-256 hash of a file using streaming 64 KB buffers.
    Returns: (hex_digest, error_message)
    """
    norm_path = os.path.normpath(file_path)

    if not os.path.exists(norm_path):
        return None, f"File does not exist: {norm_path}"

    if not os.path.isfile(norm_path):
        return None, f"Path is not a regular file: {norm_path}"

    hasher = hashlib.sha256()
    try:
        with open(norm_path, "rb") as f:
            while True:
                chunk = f.read(HASH_CHUNK_SIZE_BYTES)
                if not chunk:
                    break
                hasher.update(chunk)
        return hasher.hexdigest(), None
    except PermissionError:
        return None, "Permission denied accessing file"
    except FileNotFoundError:
        return None, "File disappeared during hashing"
    except OSError as exc:
        # Catches Windows sharing violations / locked files (WinError 32)
        return None, f"OS error reading file: {str(exc)}"
    except Exception as exc:
        return None, f"Unexpected error computing SHA-256: {str(exc)}"
