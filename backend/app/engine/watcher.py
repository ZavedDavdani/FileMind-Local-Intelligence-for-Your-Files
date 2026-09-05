"""Filesystem watcher with event normalization, debouncing, and deduplication."""

import logging
import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from watchdog.events import (
    FileSystemEvent,
    FileSystemEventHandler,
    FileCreatedEvent,
    FileModifiedEvent,
    FileDeletedEvent,
    FileMovedEvent,
    DirCreatedEvent,
    DirModifiedEvent,
    DirDeletedEvent,
    DirMovedEvent,
)
from watchdog.observers import Observer

from app.core.exclusions import ExclusionMatcher
from app.core.security import is_path_within_root, is_symlink_or_junction, normalize_path
from app.db.connection import DatabaseManager
from app.db.repositories.files import escape_like_wildcards
from app.db.repository import Repository

logger = logging.getLogger("FileMind.Watcher")


def is_subpath(child_path: str, parent_path: str) -> bool:
    """Returns True if child_path is equal to or strictly inside parent_path (case-insensitive)."""
    try:
        return is_path_within_root(child_path, parent_path)
    except Exception:
        return False


class DebouncedEventManager:
    """Coalesces rapid duplicate filesystem notifications and directory cascades within a sliding window."""

    def __init__(
        self,
        debounce_window_sec: float = 0.5,
        on_flush: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_flush_batch: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
    ):
        self.debounce_window_sec = debounce_window_sec
        self.on_flush = on_flush
        self.on_flush_batch = on_flush_batch
        self._pending_events: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._stopped: bool = False

    def push_event(self, event_data: Dict[str, Any]):
        path = event_data["path"]
        event_type = event_data["event_type"]
        is_directory = event_data.get("is_directory", False)

        with self._lock:
            if self._stopped:
                return

            if is_directory and event_type == "DELETE":
                # 1. Prune all existing pending child events under this deleted directory subtree
                keys_to_purge = [
                    k for k in self._pending_events
                    if is_subpath(k, path)
                ]
                for k in keys_to_purge:
                    del self._pending_events[k]

                # 2. Check if an existing pending directory delete already covers this path
                already_covered = any(
                    ev.get("is_directory") and ev["event_type"] == "DELETE" and is_subpath(path, ev["path"])
                    for ev in self._pending_events.values()
                )
                if not already_covered:
                    self._pending_events[path] = event_data

            elif is_directory and event_type in ("MOVE", "RENAME"):
                old_path = event_data.get("old_path")
                if old_path:
                    keys_to_purge = [
                        k for k in self._pending_events
                        if is_subpath(k, old_path)
                    ]
                    for k in keys_to_purge:
                        del self._pending_events[k]
                self._pending_events[path] = event_data

            elif not is_directory and event_type in ("MOVE", "RENAME"):
                old_p = event_data.get("old_path", "")
                if old_p and old_p in self._pending_events and self._pending_events[old_p]["event_type"] == "CREATE":
                    del self._pending_events[old_p]
                    event_data["event_type"] = "CREATE"
                    event_data["old_path"] = None

                # If a pending directory move covers this child file, suppress redundant child move!
                already_covered = any(
                    ev.get("is_directory") and ev["event_type"] in ("MOVE", "RENAME")
                    and ev.get("old_path") and is_subpath(old_p, ev["old_path"])
                    for ev in self._pending_events.values()
                )
                if not already_covered:
                    self._pending_events[path] = event_data

            elif not is_directory and event_type == "DELETE":
                # Check if a pending directory delete already covers this child file
                already_covered = any(
                    ev.get("is_directory") and ev["event_type"] == "DELETE" and is_subpath(path, ev["path"])
                    for ev in self._pending_events.values()
                )
                if not already_covered:
                    self._pending_events[path] = event_data

            else:
                # Standard file-level debouncing
                if path in self._pending_events:
                    existing = self._pending_events[path]
                    prev_type = existing["event_type"]

                    if prev_type == "CREATE" and event_type == "MODIFY":
                        existing["observed_at"] = event_data["observed_at"]
                    else:
                        self._pending_events[path] = event_data
                else:
                    self._pending_events[path] = event_data

            self._reset_timer()

    def _reset_timer(self):
        if self._stopped:
            return
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(self.debounce_window_sec, self._flush)
        self._timer.daemon = True
        self._timer.start()

    def flush(self):
        """Immediately flushes all pending debounced events synchronously."""
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None
        self._flush()

    def stop(self):
        """Stops the debouncer, cancels pending timers, and flushes remaining events."""
        with self._lock:
            self._stopped = True
            if self._timer:
                self._timer.cancel()
                self._timer = None
        self._flush()

    def _flush(self):
        with self._lock:
            if self._timer:
                self._timer.cancel()
                self._timer = None
            events_to_process = list(self._pending_events.values())
            self._pending_events.clear()

        if not events_to_process:
            return

        if self.on_flush_batch:
            try:
                self.on_flush_batch(events_to_process)
            except Exception as exc:
                logger.error("Error flushing debounced event batch: %s", str(exc))
        elif self.on_flush:
            for ev in events_to_process:
                try:
                    self.on_flush(ev)
                except Exception as exc:
                    logger.error("Error flushing debounced event: %s", str(exc))


class FolderWatchHandler(FileSystemEventHandler):
    """Translates raw watchdog events into normalized FileMind logical events."""

    def __init__(
        self,
        folder_id: str,
        folder_path: str,
        exclude_patterns: list,
        debouncer: DebouncedEventManager,
    ):
        super().__init__()
        self.folder_id = folder_id
        self.folder_path = folder_path
        self.matcher = ExclusionMatcher(exclude_patterns)
        self.debouncer = debouncer

    def _should_ignore(self, path: str, is_dir: bool = False) -> bool:
        try:
            # Reject symlinks and Windows junctions/reparse points immediately —
            # consistent with the scanner's is_symlink_or_junction policy.
            if is_symlink_or_junction(path):
                return True
            rel = os.path.relpath(path, self.folder_path)
            if is_dir:
                name = os.path.basename(path)
                return self.matcher.is_directory_excluded(name, rel)
            else:
                name = os.path.basename(path)
                return self.matcher.is_file_excluded(name, rel)
        except Exception:
            return True

    def on_created(self, event: FileSystemEvent):
        if event.is_directory:
            if self._should_ignore(event.src_path, is_dir=True):
                return
            self.debouncer.push_event({
                "folder_id": self.folder_id,
                "event_type": "CREATE",
                "path": normalize_path(event.src_path),
                "old_path": None,
                "is_directory": True,
                "observed_at": time.time(),
            })
            return
        if self._should_ignore(event.src_path, is_dir=False):
            return
        self.debouncer.push_event({
            "folder_id": self.folder_id,
            "event_type": "CREATE",
            "path": normalize_path(event.src_path),
            "old_path": None,
            "is_directory": False,
            "observed_at": time.time(),
        })

    def on_modified(self, event: FileSystemEvent):
        if event.is_directory or self._should_ignore(event.src_path, is_dir=event.is_directory):
            return
        self.debouncer.push_event({
            "folder_id": self.folder_id,
            "event_type": "MODIFY",
            "path": normalize_path(event.src_path),
            "old_path": None,
            "is_directory": False,
            "observed_at": time.time(),
        })

    def on_deleted(self, event: FileSystemEvent):
        if event.is_directory:
            if self._should_ignore(event.src_path, is_dir=True):
                return
            self.debouncer.push_event({
                "folder_id": self.folder_id,
                "event_type": "DELETE",
                "path": normalize_path(event.src_path),
                "old_path": None,
                "is_directory": True,
                "observed_at": time.time(),
            })
        else:
            if self._should_ignore(event.src_path, is_dir=False):
                return
            self.debouncer.push_event({
                "folder_id": self.folder_id,
                "event_type": "DELETE",
                "path": normalize_path(event.src_path),
                "old_path": None,
                "is_directory": False,
                "observed_at": time.time(),
            })

    def on_moved(self, event: FileMovedEvent):
        if event.is_directory:
            src_ignored = self._should_ignore(event.src_path, is_dir=True)
            dest_ignored = self._should_ignore(event.dest_path, is_dir=True)

            if src_ignored and dest_ignored:
                return
            elif not src_ignored and dest_ignored:
                # Moved to ignored location -> DELETE directory
                self.debouncer.push_event({
                    "folder_id": self.folder_id,
                    "event_type": "DELETE",
                    "path": normalize_path(event.src_path),
                    "old_path": None,
                    "is_directory": True,
                    "observed_at": time.time(),
                })
            else:
                # Valid directory move / rename
                old_p = normalize_path(event.src_path)
                new_p = normalize_path(event.dest_path)
                is_same_dir = os.path.dirname(old_p) == os.path.dirname(new_p)
                self.debouncer.push_event({
                    "folder_id": self.folder_id,
                    "event_type": "RENAME" if is_same_dir else "MOVE",
                    "path": new_p,
                    "old_path": old_p,
                    "is_directory": True,
                    "observed_at": time.time(),
                })
            return

        src_ignored = self._should_ignore(event.src_path, is_dir=False)
        dest_ignored = self._should_ignore(event.dest_path, is_dir=False)

        if src_ignored and dest_ignored:
            return
        elif src_ignored and not dest_ignored:
            # Appeared from ignored location -> CREATE
            self.debouncer.push_event({
                "folder_id": self.folder_id,
                "event_type": "CREATE",
                "path": normalize_path(event.dest_path),
                "old_path": None,
                "is_directory": False,
                "observed_at": time.time(),
            })
        elif not src_ignored and dest_ignored:
            # Moved to ignored location -> DELETE
            self.debouncer.push_event({
                "folder_id": self.folder_id,
                "event_type": "DELETE",
                "path": normalize_path(event.src_path),
                "old_path": None,
                "is_directory": False,
                "observed_at": time.time(),
            })
        else:
            # True RENAME / MOVE
            old_p = normalize_path(event.src_path)
            new_p = normalize_path(event.dest_path)
            is_same_dir = os.path.dirname(old_p) == os.path.dirname(new_p)
            self.debouncer.push_event({
                "folder_id": self.folder_id,
                "event_type": "RENAME" if is_same_dir else "MOVE",
                "path": new_p,
                "old_path": old_p,
                "is_directory": False,
                "observed_at": time.time(),
            })


class WatcherService:
    """Manages active filesystem observers across all registered folders."""

    def __init__(self, db_manager: DatabaseManager, on_normalized_event: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.db = db_manager
        self.on_normalized_event = on_normalized_event
        self.debouncer = DebouncedEventManager(debounce_window_sec=0.5, on_flush_batch=self._handle_flushed_batch)
        self.observer: Optional[Observer] = None
        self.watches: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def start(self):
        with self._lock:
            self.debouncer._stopped = False
            if self.observer and self.observer.is_alive():
                return
            self.observer = Observer()
            self.observer.daemon = True
            self.observer.start()
            self._sync_watches()
        logger.info("WatcherService started")

    def stop(self):
        with self._lock:
            if self.observer:
                self.observer.stop()
                self.observer.join(timeout=2.0)
                self.observer = None
            self.watches.clear()
        self.debouncer.stop()
        logger.info("WatcherService stopped")

    def sync_watches(self):
        """Synchronizes watchdog monitors with folders table in SQLite."""
        with self._lock:
            self._sync_watches()

    def _sync_watches(self):
        if not self.observer or not self.observer.is_alive():
            return

        with self.db.session() as conn:
            repo = Repository(conn)
            folders = repo.list_folders()

        active_folder_ids = set()
        for f in folders:
            fid = f["folder_id"]
            fpath = f["path"]
            is_enabled = f["indexing_enabled"]
            is_rec = f["recursive"]
            patterns = f["exclude_patterns"]

            if is_enabled and os.path.exists(fpath) and os.path.isdir(fpath):
                active_folder_ids.add(fid)
                if fid not in self.watches:
                    handler = FolderWatchHandler(fid, fpath, patterns, self.debouncer)
                    watch = self.observer.schedule(handler, fpath, recursive=is_rec)
                    self.watches[fid] = {
                        "watch": watch,
                        "recursive": is_rec,
                        "patterns": patterns,
                        "path": fpath,
                    }
                    logger.info("Watching folder: %s (recursive=%s)", fpath, is_rec)
                else:
                    # Check if recursive or exclude_patterns changed on existing active watch
                    curr = self.watches[fid]
                    curr_rec = curr.get("recursive") if isinstance(curr, dict) else None
                    curr_pats = curr.get("patterns") if isinstance(curr, dict) else None
                    if curr_rec != is_rec or curr_pats != patterns:
                        old_watch = curr.get("watch") if isinstance(curr, dict) else curr
                        try:
                            self.observer.unschedule(old_watch)
                        except Exception:
                            pass
                        handler = FolderWatchHandler(fid, fpath, patterns, self.debouncer)
                        watch = self.observer.schedule(handler, fpath, recursive=is_rec)
                        self.watches[fid] = {
                            "watch": watch,
                            "recursive": is_rec,
                            "patterns": patterns,
                            "path": fpath,
                        }
                        logger.info("Updated watch for folder: %s (recursive=%s)", fpath, is_rec)

        # Remove watches for removed/disabled folders
        for fid in list(self.watches.keys()):
            if fid not in active_folder_ids:
                curr = self.watches.pop(fid)
                old_watch = curr.get("watch") if isinstance(curr, dict) else curr
                try:
                    self.observer.unschedule(old_watch)
                    logger.info("Unscheduled watch for folder %s", fid)
                except Exception:
                    pass

    def _handle_flushed_batch(self, events: List[Dict[str, Any]]):
        """Processes a batch of normalized events in bounded sub-batches.

        Large event bursts (e.g. 50,000 events) are split into sub-batches of at most
        WATCHER_BATCH_SIZE items. This prevents a single oversized SQLite transaction from
        blocking reads and writes. Sub-batches are processed sequentially, preserving ordering
        and deduplication guarantees established by the debouncer.

        Batch size is justified by SQLite WAL mode: 200 events per transaction keeps single
        write transactions comfortably within the WAL checkpoint window.
        """
        WATCHER_BATCH_SIZE = 200

        if not events:
            return

        for i in range(0, len(events), WATCHER_BATCH_SIZE):
            sub_batch = events[i:i + WATCHER_BATCH_SIZE]
            self._process_event_sub_batch(sub_batch)

        if self.on_normalized_event:
            for ev in events:
                try:
                    self.on_normalized_event(ev)
                except Exception:
                    pass

    def _process_event_sub_batch(self, events: List[Dict[str, Any]]):
        """Processes a single bounded sub-batch of events inside one atomic SQLite transaction."""
        with self.db.session() as conn:
            repo = Repository(conn)

            for event_data in events:
                folder_id = event_data["folder_id"]
                event_type = event_data["event_type"]
                path = event_data["path"]
                old_path = event_data.get("old_path")
                is_directory = event_data.get("is_directory", False)

                # Log event in audit table
                repo.log_event(
                    folder_id=folder_id,
                    event_type=event_type,
                    path=path,
                    old_path=old_path,
                    status="PROCESSED",
                )

                folder = repo.get_folder(folder_id)
                if not folder or not folder["indexing_enabled"]:
                    continue

                destination_inside_root = is_subpath(path, folder["path"])
                origin_inside_root = bool(old_path and is_subpath(old_path, folder["path"]))

                # A move out of this registered root (including a cross-drive
                # move) is a deletion from this corpus. Never inspect or queue
                # the external destination, but converge the old tracked state.
                if event_type in ("MOVE", "RENAME") and origin_inside_root and not destination_inside_root:
                    if is_directory:
                        cur = conn.execute(
                            """
                            SELECT file_id FROM files
                            WHERE folder_id = ? AND index_status = 'INDEXED' AND (
                                path = ? OR path = ?
                                OR path LIKE ? ESCAPE '\\' OR path LIKE ? ESCAPE '\\'
                            );
                            """,
                            (
                                folder_id,
                                old_path.replace('\\', '/'),
                                old_path.replace('/', '\\'),
                                escape_like_wildcards(old_path.replace('\\', '/').rstrip('/') + '/') + '%',
                                escape_like_wildcards(old_path.replace('/', '\\').rstrip('\\') + '\\') + '%',
                            ),
                        )
                        affected_fids = [r[0] for r in cur.fetchall()]
                        repo.mark_directory_missing(folder_id=folder_id, dir_path=old_path)
                        for fid in affected_fids:
                            repo.enqueue_job(
                                file_id=fid,
                                folder_id=folder_id,
                                job_type="DELETE_CLEANUP",
                                priority=1,
                            )
                    else:
                        file_rec = repo.get_file_by_path(old_path)
                        if file_rec:
                            repo.mark_file_missing(old_path)
                            repo.cancel_pending_jobs_for_file(file_rec["file_id"])
                            if file_rec.get("index_status") == "INDEXED":
                                repo.enqueue_job(
                                    file_id=file_rec["file_id"],
                                    folder_id=folder_id,
                                    job_type="DELETE_CLEANUP",
                                    priority=1,
                                )
                    continue

                if not destination_inside_root:
                    logger.warning("Event path %s is outside root %s — skipping", path, folder["path"])
                    continue

                if is_directory:
                    if event_type == "DELETE":
                        # Atomic subtree deletion: mark all files under directory missing and cancel pending jobs
                        # Handle recreate race: only proceed if directory no longer exists on disk
                        if not os.path.exists(path):
                            cur = conn.execute(
                                """
                                SELECT file_id FROM files
                                WHERE folder_id = ? AND index_status = 'INDEXED' AND (
                                    path = ? OR path = ?
                                    OR path LIKE ? ESCAPE '\\' OR path LIKE ? ESCAPE '\\'
                                );
                                """,
                                (
                                    folder_id,
                                    path.replace('\\', '/'),
                                    path.replace('/', '\\'),
                                    escape_like_wildcards(path.replace('\\', '/').rstrip('/') + '/') + '%',
                                    escape_like_wildcards(path.replace('/', '\\').rstrip('\\') + '\\') + '%',
                                ),
                            )
                            affected_fids = [r[0] for r in cur.fetchall()]
                            repo.mark_directory_missing(folder_id=folder_id, dir_path=path)
                            for fid in affected_fids:
                                repo.enqueue_job(
                                    file_id=fid,
                                    folder_id=folder_id,
                                    job_type="DELETE_CLEANUP",
                                    priority=1,
                                )

                    elif event_type in ("MOVE", "RENAME"):
                        if old_path and os.path.exists(path):
                            repo.rename_directory_path(
                                folder_id=folder_id,
                                old_dir_path=old_path,
                                new_dir_path=path,
                                root_folder_path=folder["path"]
                            )
                    continue

                if event_type in ("CREATE", "MODIFY"):
                    if os.path.exists(path) and os.path.isfile(path) and not is_symlink_or_junction(path):
                        st = os.stat(path)
                        filename = os.path.basename(path)
                        _, ext = os.path.splitext(filename)
                        rel = os.path.relpath(path, folder["path"]).replace("\\", "/")
                        from datetime import datetime, timezone
                        mod_iso = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
                        
                        from app.core.config import MAX_FILE_SIZE_BYTES
                        is_oversized = (st.st_size > MAX_FILE_SIZE_BYTES)
                        oversized_err = f"File size ({st.st_size} bytes) exceeds limit ({MAX_FILE_SIZE_BYTES} bytes)" if is_oversized else None

                        file_rec = repo.upsert_file(
                            folder_id=folder_id,
                            path=path,
                            relative_path=rel,
                            filename=filename,
                            extension=ext.lower(),
                            size_bytes=st.st_size,
                            modified_at=mod_iso,
                            index_status="SKIPPED" if is_oversized else "QUEUED",
                            indexing_error=oversized_err,
                        )
                        if not is_oversized:
                            repo.enqueue_job(
                                file_id=file_rec["file_id"],
                                folder_id=folder_id,
                                job_type="HASH_VERIFICATION",
                                priority=3,
                            )


                elif event_type == "DELETE":
                    file_rec = repo.get_file_by_path(path)
                    if file_rec:
                        repo.mark_file_missing(path)
                        repo.cancel_pending_jobs_for_file(file_rec["file_id"])
                        if file_rec.get("index_status") == "INDEXED":
                            repo.enqueue_job(
                                file_id=file_rec["file_id"],
                                folder_id=folder_id,
                                job_type="DELETE_CLEANUP",
                                priority=1,
                            )

                elif event_type in ("RENAME", "MOVE"):
                    if old_path and os.path.exists(path):
                        file_rec = repo.get_file_by_path(old_path)
                        if file_rec:
                            filename = os.path.basename(path)
                            _, ext = os.path.splitext(filename)
                            rel = os.path.relpath(path, folder["path"]).replace("\\", "/")
                            repo.rename_file_path(old_path, path, rel, filename, ext.lower())
                            repo.enqueue_job(
                                file_id=file_rec["file_id"],
                                folder_id=folder_id,
                                job_type="HASH_VERIFICATION",
                                priority=2,
                            )
