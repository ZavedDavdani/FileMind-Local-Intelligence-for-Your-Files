"""SQLite connection management with WAL mode and robust concurrency configuration."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional, Union
from app.core.config import DEFAULT_DB_PATH


class DatabaseManager:
    """Manages SQLite database connections and configuration."""

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        self.db_path = Path(db_path) if db_path and str(db_path) != ":memory:" else db_path or DEFAULT_DB_PATH
        if isinstance(self.db_path, Path):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def get_connection(self) -> sqlite3.Connection:
        """Creates and configures a SQLite connection with WAL mode and foreign keys enabled."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        
        # Configure SQLite pragmas for performance and concurrency
        if str(self.db_path) != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 10000;")
        conn.execute("PRAGMA foreign_keys = ON;")

        # Load sqlite-vec extension (mandatory for vector storage and search)
        try:
            import sqlite_vec
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
        except Exception as exc:
            try:
                conn.close()
            except Exception:
                pass
            raise RuntimeError(f"Failed to load sqlite-vec extension: {exc}") from exc

        return conn


    @contextmanager
    def session(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for atomic transactional database operations."""
        conn = self.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


# Global default database manager
db_manager = DatabaseManager()
