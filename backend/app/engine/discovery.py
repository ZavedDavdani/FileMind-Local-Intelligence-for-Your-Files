import logging
import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.exclusions import ExclusionMatcher
from app.core.security import is_symlink_or_junction, normalize_path, validate_subpath_safety
from app.db.repository import Repository

logger = logging.getLogger("FileMind.Discovery")


class DiscoveryResult:
    def __init__(self):
        self.total_scanned: int = 0
        self.new_files: int = 0
        self.modified_files: int = 0
        self.unchanged_files: int = 0
        self.skipped_exclusions: int = 0
        self.stale_files: int = 0  # Files deleted while offline, now marked missing
        self.errors: List[Dict[str, str]] = []
        self.enqueued_job_ids: List[str] = []



class FilesystemScanner:
    """Discovers files in registered folders, applies exclusions, and performs change detection."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def scan_folder(self, folder_id: str, force_strict_rehash: bool = False) -> DiscoveryResult:
        folder = self.repo.get_folder(folder_id)
        if not folder:
            raise ValueError(f"Folder with ID {folder_id} not found")

        folder_path = normalize_path(folder["path"])
        if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
            raise FileNotFoundError(f"Folder root does not exist or is not a directory: {folder_path}")

        result = DiscoveryResult()
        matcher = ExclusionMatcher(folder.get("exclude_patterns", []))
        is_recursive = folder.get("recursive", True)
        is_strict = (folder.get("integrity_mode") == "STRICT") or force_strict_rehash

        seen_file_paths = set()

        if is_recursive:
            walker = os.walk(folder_path, topdown=True)
        else:
            # Single-level traversal
            try:
                entries = os.scandir(folder_path)
                dirs = [e.name for e in entries if e.is_dir()]
                files = [e.name for e in os.scandir(folder_path) if e.is_file()]
                walker = [(folder_path, dirs, files)]
            except Exception as exc:
                result.errors.append({"path": folder_path, "error": str(exc)})
                return result

        for root, dirs, files in walker:
            # Skip symlink / junction directories to prevent circular loops and escapes
            rel_dir = os.path.relpath(root, folder_path)
            if rel_dir == ".":
                rel_dir = ""

            # Filter out excluded directories in-place (prevents traversing their children)
            filtered_dirs = []
            for d in list(dirs):
                dir_abs = os.path.join(root, d)
                dir_rel = os.path.relpath(dir_abs, folder_path)
                
                # Check symlink or junction
                if is_symlink_or_junction(dir_abs):
                    result.skipped_exclusions += 1
                    continue

                if matcher.is_directory_excluded(d, dir_rel):
                    result.skipped_exclusions += 1
                else:
                    filtered_dirs.append(d)
            dirs[:] = filtered_dirs

            for f in files:
                result.total_scanned += 1
                file_abs = os.path.normpath(os.path.join(root, f))
                file_rel = os.path.relpath(file_abs, folder_path)

                # Check symlink
                if is_symlink_or_junction(file_abs):
                    result.skipped_exclusions += 1
                    continue

                # Check exclusion pattern
                if matcher.is_file_excluded(f, file_rel):
                    result.skipped_exclusions += 1
                    continue

                seen_file_paths.add(file_abs)

                try:
                    # Validate subpath security
                    validate_subpath_safety(file_abs, folder_path)
                    
                    st = os.stat(file_abs)
                    size_bytes = st.st_size
                    mod_dt = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
                    mod_iso = mod_dt.isoformat()
                    create_iso = None
                    if hasattr(st, "st_ctime"):
                        create_iso = datetime.fromtimestamp(st.st_ctime, tz=timezone.utc).isoformat()

                    _, ext = os.path.splitext(f)
                    mime, _ = mimetypes.guess_type(file_abs)

                    # Ingestion Guard: Check MAX_FILE_SIZE_BYTES limit early
                    from app.core.config import MAX_FILE_SIZE_BYTES
                    is_oversized = (size_bytes > MAX_FILE_SIZE_BYTES)
                    oversized_error = f"File size ({size_bytes} bytes) exceeds limit ({MAX_FILE_SIZE_BYTES} bytes)" if is_oversized else None

                    # Change detection check against existing database record
                    existing = self.repo.get_file_by_path(file_abs)

                    if not existing:
                        # New file discovered
                        result.new_files += 1
                        file_record = self.repo.upsert_file(
                            folder_id=folder_id,
                            path=file_abs,
                            relative_path=file_rel,
                            filename=f,
                            extension=ext.lower(),
                            size_bytes=size_bytes,
                            modified_at=mod_iso,
                            created_at=create_iso,
                            mime_type=mime,
                            index_status="SKIPPED" if is_oversized else "QUEUED",
                            indexing_error=oversized_error,
                        )
                        if not is_oversized:
                            job = self.repo.enqueue_job(
                                file_id=file_record["file_id"],
                                folder_id=folder_id,
                                job_type="HASH_VERIFICATION" if is_strict else "METADATA_DISCOVERY",
                                priority=1,
                            )
                            result.enqueued_job_ids.append(job["job_id"])

                    else:
                        # Existing file: compare mtime, size, strict hash, and parser/chunker versions
                        mtime_changed = (existing["modified_at"] != mod_iso)
                        size_changed = (existing["size_bytes"] != size_bytes)
                        needs_rehash = is_strict or (existing["sha256"] is None)

                        # Version Invalidation Check: Check if active parser/chunker version has evolved
                        version_changed = False
                        if not is_oversized and existing.get("index_status") == "INDEXED":
                            try:
                                from app.intelligence.parsers.registry import default_parser_registry
                                from app.intelligence.chunker.hierarchical import CHUNKER_VERSION
                                active_parser = default_parser_registry.get_parser_for_file(file_abs, mime)
                                if active_parser:
                                    chunk_vers = self.repo.get_file_chunk_versions(existing["file_id"])
                                    if chunk_vers:
                                        if (chunk_vers["parser_version"] != active_parser.parser_version or
                                            chunk_vers["chunker_version"] != CHUNKER_VERSION):
                                            version_changed = True
                            except Exception as exc:
                                logger.warning(
                                    "Failed to evaluate parser/chunker version invalidation for %s: %s",
                                    file_abs,
                                    exc,
                                )

                        if is_oversized:
                            if existing.get("index_status") != "SKIPPED":
                                result.modified_files += 1
                                self.repo.purge_file_index(existing["file_id"])
                                self.repo.upsert_file(
                                    folder_id=folder_id,
                                    path=file_abs,
                                    relative_path=file_rel,
                                    filename=f,
                                    extension=ext.lower(),
                                    size_bytes=size_bytes,
                                    modified_at=mod_iso,
                                    created_at=create_iso,
                                    mime_type=mime,
                                    index_status="SKIPPED",
                                    indexing_error=oversized_error,
                                    file_id=existing["file_id"],
                                )
                            else:
                                result.unchanged_files += 1
                        elif mtime_changed or size_changed or needs_rehash or version_changed:
                            result.modified_files += 1
                            file_record = self.repo.upsert_file(
                                folder_id=folder_id,
                                path=file_abs,
                                relative_path=file_rel,
                                filename=f,
                                extension=ext.lower(),
                                size_bytes=size_bytes,
                                modified_at=mod_iso,
                                created_at=create_iso,
                                mime_type=mime,
                                index_status="QUEUED",
                                file_id=existing["file_id"],
                            )
                            job = self.repo.enqueue_job(
                                file_id=existing["file_id"],
                                folder_id=folder_id,
                                job_type="HASH_VERIFICATION",
                                priority=2,
                            )
                            result.enqueued_job_ids.append(job["job_id"])
                        else:
                            result.unchanged_files += 1


                except (PermissionError, OSError) as exc:
                    result.errors.append({"path": file_abs, "error": str(exc)})
                    # Record failure in database if file exists
                    existing = self.repo.get_file_by_path(file_abs)
                    if existing:
                        self.repo.record_scan_error(
                            file_id=existing["file_id"],
                            error_message=f"Access error during scan: {str(exc)}",
                        )
                    continue

        # Offline deletion reconciliation: find indexed files that are no longer present on disk.
        # These are files that were deleted while FileMind was closed, which the watcher could not
        # observe. We reuse the existing deletion lifecycle: mark missing + cancel jobs +
        # enqueue DELETE_CLEANUP so the worker removes chunks and vectors.
        indexed_records = self.repo.list_indexed_paths_for_folder(folder_id)
        for rec in indexed_records:
            db_path = rec["path"]
            if db_path not in seen_file_paths:
                # File is in DB but was not found on disk during this scan.
                self.repo.mark_file_missing(db_path)
                self.repo.cancel_pending_jobs_for_file(rec["file_id"])
                cleanup_job = self.repo.enqueue_job(
                    file_id=rec["file_id"],
                    folder_id=folder_id,
                    job_type="DELETE_CLEANUP",
                    priority=0,
                )
                result.enqueued_job_ids.append(cleanup_job["job_id"])
                result.stale_files += 1

        return result
