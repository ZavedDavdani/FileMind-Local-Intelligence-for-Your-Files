"""SQLite connection management with WAL mode and robust concurrency configuration."""

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Generator, Optional, Union
from app.core.config import DEFAULT_DB_PATH


class DatabaseManager:
    """Manages SQLite database connections and configuration with thread-local connection reuse."""

    def __init__(self, db_path: Optional[Union[str, Path]] = None, pooled: Optional[bool] = None):
        self.db_path = Path(db_path) if db_path and str(db_path) != ":memory:" else db_path or DEFAULT_DB_PATH
        if isinstance(self.db_path, Path):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._is_memory = (str(self.db_path) == ":memory:")
        if pooled is not None:
            self._pooled = pooled
        else:
            self._pooled = (not self._is_memory and isinstance(self.db_path, Path) and self.db_path == DEFAULT_DB_PATH)
        self._open_connections: set[sqlite3.Connection] = set()
        self._conns_lock = threading.Lock()

    def _create_new_connection(self) -> sqlite3.Connection:
        """Creates and configures a fresh SQLite connection with WAL mode and foreign keys enabled."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row

        # Configure SQLite pragmas for performance and concurrency
        if not self._is_memory:
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

        if self._pooled:
            with self._conns_lock:
                self._open_connections.add(conn)

        return conn

    def get_connection(self) -> sqlite3.Connection:
        """Returns a configured SQLite connection with thread-local caching when pooled."""
        if self._is_memory or not self._pooled:
            return self._create_new_connection()

        connections: Dict[str, sqlite3.Connection] = getattr(self._local, "connections", None)
        if connections is None:
            connections = {}
            self._local.connections = connections

        key = str(self.db_path)
        conn = connections.get(key)
        if conn is None:
            conn = self._create_new_connection()
            connections[key] = conn
        return conn

    @contextmanager
    def session(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for atomic transactional database operations with connection reuse when pooled."""
        if self._is_memory or not self._pooled:
            conn = self._create_new_connection()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            return

        conn = self.get_connection()
        depth = getattr(self._local, "tx_depth", 0)
        self._local.tx_depth = depth + 1
        try:
            yield conn
            if depth == 0:
                conn.commit()
        except Exception:
            if depth == 0:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise
        finally:
            self._local.tx_depth = max(0, getattr(self._local, "tx_depth", 1) - 1)

    def close_thread_connection(self) -> None:
        """Closes the current thread's cached connection if one exists."""
        connections: Optional[Dict[str, sqlite3.Connection]] = getattr(self._local, "connections", None)
        if connections:
            key = str(self.db_path)
            conn = connections.pop(key, None)
            if conn is not None:
                with self._conns_lock:
                    self._open_connections.discard(conn)
                try:
                    conn.close()
                except Exception:
                    pass

    def close_all(self) -> None:
        """Closes all pooled connections across all threads."""
        self.close_thread_connection()
        with self._conns_lock:
            conns = list(self._open_connections)
            self._open_connections.clear()
        for conn in conns:
            try:
                conn.close()
            except Exception:
                pass


# Global default database manager
db_manager = DatabaseManager()


