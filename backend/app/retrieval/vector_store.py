"""Vector store abstractions and implementations for Phase 3 dense retrieval.

Provides:
- SqliteVecStore (native SQLite vector extension via sqlite-vec vec0)
- LanceDBVectorStore (embedded LanceDB table)
- MemoryCosineStore (in-memory NumPy cosine similarity baseline)
"""

import json
import logging
import os
import shutil
import sqlite3
import struct
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import numpy as np

logger = logging.getLogger("FileMind.Retrieval.VectorStore")


class BaseVectorStore(ABC):
    """Abstract interface for local vector store backends."""

    @abstractmethod
    def initialize(self):
        """Initializes tables or storage directories."""
        pass

    @abstractmethod
    def upsert_vectors(self, records: List[Dict[str, Any]]) -> int:
        """
        Upserts a batch of vector records.
        Each record must contain:
        - chunk_id (str)
        - embedding (List[float])
        - file_id (str)
        """
        pass

    @abstractmethod
    def search(
        self,
        query_vector: List[float],
        top_k: int = 50,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Searches for top_k nearest neighbors by cosine similarity."""
        pass

    @abstractmethod
    def delete_by_chunk_ids(self, chunk_ids: List[str]) -> int:
        """Deletes vectors by chunk_id."""
        pass

    @abstractmethod
    def delete_by_file_id(self, file_id: str) -> int:
        """Deletes all vectors associated with a file_id."""
        pass

    @abstractmethod
    def count(self) -> int:
        """Returns the total number of indexed vectors."""
        pass


class SqliteVecStore(BaseVectorStore):
    """Native SQLite vector store using sqlite-vec vec0 virtual tables."""

    def __init__(self, db_conn: sqlite3.Connection, dimension: int = 384):
        self.conn = db_conn
        self.dimension = dimension
        self.initialize()

    def initialize(self):
        """Creates vec0 virtual table for chunk vectors."""
        try:
            self.conn.execute(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors USING vec0(
                    chunk_id TEXT PRIMARY KEY,
                    embedding FLOAT[{self.dimension}] DISTANCE_METRIC=cosine
                );
                """
            )
        except Exception as exc:
            logger.error("Failed to initialize sqlite-vec table: %s", str(exc))

    def _pack_vector(self, vec: List[float]) -> bytes:
        return struct.pack(f"{len(vec)}f", *vec)

    def upsert_vectors(self, records: List[Dict[str, Any]]) -> int:
        if not records:
            return 0
        
        # In vec0, replace existing chunk_ids
        chunk_ids = [r["chunk_id"] for r in records]
        self.delete_by_chunk_ids(chunk_ids)

        insert_sql = "INSERT INTO chunk_vectors (chunk_id, embedding) VALUES (?, ?);"
        rows = []
        for r in records:
            packed = self._pack_vector(r["embedding"])
            rows.append((r["chunk_id"], packed))

        self.conn.executemany(insert_sql, rows)
        return len(rows)

    def delete_by_chunk_ids(self, chunk_ids: List[str]) -> int:
        if not chunk_ids:
            return 0
        placeholders = ",".join(["?"] * len(chunk_ids))
        cursor = self.conn.execute(
            f"DELETE FROM chunk_vectors WHERE chunk_id IN ({placeholders});",
            chunk_ids,
        )
        return cursor.rowcount

    def delete_by_file_id(self, file_id: str) -> int:
        cursor = self.conn.execute(
            """
            DELETE FROM chunk_vectors 
            WHERE chunk_id IN (SELECT chunk_id FROM chunks WHERE file_id = ?);
            """,
            (file_id,),
        )
        return cursor.rowcount

    def count(self) -> int:
        cursor = self.conn.execute("SELECT COUNT(*) FROM chunk_vectors;")
        row = cursor.fetchone()
        return row[0] if row else 0

    def search(
        self,
        query_vector: List[float],
        top_k: int = 50,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        if not query_vector:
            raise ValueError("query_vector cannot be empty")
        if len(query_vector) != self.dimension:
            raise ValueError(f"query_vector dimension mismatch: expected {self.dimension}, got {len(query_vector)}")

        packed_q = self._pack_vector(query_vector)
        filters = filters or {}

        # Fetch extra candidate matches from vec0 to allow for metadata filtering
        fetch_k = top_k * 5 if filters else top_k

        # 1. Retrieve candidates from vec0
        vec_sql = """
        SELECT chunk_id, distance
        FROM chunk_vectors
        WHERE embedding MATCH ?
          AND k = ?
        ORDER BY distance ASC;
        """
        cursor = self.conn.execute(vec_sql, (packed_q, fetch_k))
        vec_rows = cursor.fetchall()

        if not vec_rows:
            return []

        # 2. Join with chunks and files table for provenance and metadata filtering
        chunk_distances = {r[0]: float(r[1]) for r in vec_rows}
        chunk_ids = list(chunk_distances.keys())
        placeholders = ",".join(["?"] * len(chunk_ids))

        where_clauses = [f"c.chunk_id IN ({placeholders})"]
        params: List[Any] = list(chunk_ids)

        if filters.get("folder_id"):
            where_clauses.append("f.folder_id = ?")
            params.append(filters["folder_id"])

        if filters.get("extension"):
            ext = filters["extension"].lower()
            if not ext.startswith("."):
                ext = f".{ext}"
            where_clauses.append("LOWER(f.extension) = ?")
            params.append(ext)

        if filters.get("file_id"):
            where_clauses.append("c.file_id = ?")
            params.append(filters["file_id"])

        if filters.get("source_path"):
            where_clauses.append("c.source_path = ?")
            params.append(filters["source_path"])

        where_clauses.append("f.index_status != 'MISSING'")

        where_sql = " AND ".join(where_clauses)
        sql = f"""
        SELECT 
            c.chunk_id,
            c.file_id,
            c.source_file,
            c.source_path,
            c.page,
            c.section,
            c.h1_parent,
            c.h2_parent,
            c.line_start,
            c.line_end,
            c.char_start,
            c.char_end,
            c.content_hash,
            c.chunk_index,
            c.content,
            c.metadata_json
        FROM chunks c
        JOIN files f ON f.file_id = c.file_id
        WHERE {where_sql};
        """

        cur = self.conn.execute(sql, params)
        matched_chunks = {}
        for r in cur.fetchall():
            d = dict(r) if isinstance(r, sqlite3.Row) else {col[0]: r[i] for i, col in enumerate(cur.description)}
            matched_chunks[d["chunk_id"]] = d

        # 3. Sort by vector distance ASC, then chunk_id ASC
        sorted_ids = sorted(
            [cid for cid in chunk_ids if cid in matched_chunks],
            key=lambda cid: (chunk_distances[cid], cid),
        )[:top_k]

        results = []
        for rank, cid in enumerate(sorted_ids, start=1):
            d = matched_chunks[cid]
            dist = chunk_distances[cid]
            # Convert cosine distance (0..2) to cosine similarity (1 - dist) bounded to [-1, 1]
            sim = round(max(-1.0, min(1.0, 1.0 - dist)), 4)
            try:
                meta = json.loads(d.get("metadata_json") or "{}")
            except Exception:
                meta = {}

            results.append({
                "rank": rank,
                "chunk_id": d["chunk_id"],
                "file_id": d["file_id"],
                "score": sim,
                "distance": dist,
                "retrieval_method": "dense",
                "source_file": d["source_file"],
                "source_path": d["source_path"],
                "page": d.get("page"),
                "section": d.get("section"),
                "h1_parent": d.get("h1_parent"),
                "h2_parent": d.get("h2_parent"),
                "line_start": d.get("line_start"),
                "line_end": d.get("line_end"),
                "char_start": d.get("char_start"),
                "char_end": d.get("char_end"),
                "content": d["content"],
                "content_hash": d["content_hash"],
                "metadata": meta,
            })

        return results


class LanceDBVectorStore(BaseVectorStore):
    """LanceDB embedded columnar vector store implementation."""

    def __init__(self, db_path: str, table_name: str = "chunk_vectors", dimension: int = 384):
        self.db_path = db_path
        self.table_name = table_name
        self.dimension = dimension
        self._db = None
        self._table = None
        self.initialize()

    def initialize(self):
        import lancedb
        import pyarrow as pa
        self._db = lancedb.connect(self.db_path)
        schema = pa.schema([
            pa.field("chunk_id", pa.string()),
            pa.field("file_id", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), self.dimension)),
        ])
        if self.table_name not in self._db.table_names():
            self._table = self._db.create_table(self.table_name, schema=schema)
        else:
            self._table = self._db.open_table(self.table_name)

    def upsert_vectors(self, records: List[Dict[str, Any]]) -> int:
        if not records:
            return 0
        data = []
        for r in records:
            data.append({
                "chunk_id": r["chunk_id"],
                "file_id": r.get("file_id", ""),
                "vector": [float(x) for x in r["embedding"]],
            })
        self._table.add(data)
        return len(data)

    def search(
        self,
        query_vector: List[float],
        top_k: int = 50,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        if not query_vector:
            return []
        query_res = self._table.search(query_vector).limit(top_k).to_list()
        results = []
        for rank, r in enumerate(query_res, start=1):
            dist = r.get("_distance", 0.0)
            sim = round(max(-1.0, min(1.0, 1.0 - dist)), 4)
            results.append({
                "rank": rank,
                "chunk_id": r["chunk_id"],
                "file_id": r.get("file_id", ""),
                "score": sim,
                "distance": dist,
                "retrieval_method": "dense",
            })
        return results

    def delete_by_chunk_ids(self, chunk_ids: List[str]) -> int:
        if not chunk_ids:
            return 0
        expr = "chunk_id IN (" + ",".join([f"'{cid}'" for cid in chunk_ids]) + ")"
        self._table.delete(expr)
        return len(chunk_ids)

    def delete_by_file_id(self, file_id: str) -> int:
        self._table.delete(f"file_id = '{file_id}'")
        return 1

    def count(self) -> int:
        return self._table.count_rows()


class MemoryCosineStore(BaseVectorStore):
    """In-memory NumPy cosine similarity vector store baseline."""

    def __init__(self, dimension: int = 384):
        self.dimension = dimension
        self.chunk_ids = []
        self.file_ids = []
        self.vectors = np.empty((0, dimension), dtype=np.float32)

    def initialize(self):
        self.chunk_ids = []
        self.file_ids = []
        self.vectors = np.empty((0, self.dimension), dtype=np.float32)

    def upsert_vectors(self, records: List[Dict[str, Any]]) -> int:
        if not records:
            return 0
        new_cids = [r["chunk_id"] for r in records]
        new_fids = [r.get("file_id", "") for r in records]
        new_vecs = np.array([r["embedding"] for r in records], dtype=np.float32)

        # Remove existing IDs if present
        existing_indices = {cid: idx for idx, cid in enumerate(self.chunk_ids)}
        keep_mask = [cid not in set(new_cids) for cid in self.chunk_ids]
        if not all(keep_mask):
            self.chunk_ids = [cid for cid, keep in zip(self.chunk_ids, keep_mask) if keep]
            self.file_ids = [fid for fid, keep in zip(self.file_ids, keep_mask) if keep]
            self.vectors = self.vectors[keep_mask]

        self.chunk_ids.extend(new_cids)
        self.file_ids.extend(new_fids)
        if len(self.vectors) == 0:
            self.vectors = new_vecs
        else:
            self.vectors = np.vstack([self.vectors, new_vecs])
        return len(records)

    def search(
        self,
        query_vector: List[float],
        top_k: int = 50,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        if len(self.vectors) == 0 or not query_vector:
            return []
        q_vec = np.array(query_vector, dtype=np.float32)
        q_norm = np.linalg.norm(q_vec)
        if q_norm > 0:
            q_vec = q_vec / q_norm

        # Cosine similarities = dot product of normalized vectors
        sims = np.dot(self.vectors, q_vec)
        top_indices = np.argsort(-sims)[:top_k]

        results = []
        for rank, idx in enumerate(top_indices, start=1):
            results.append({
                "rank": rank,
                "chunk_id": self.chunk_ids[idx],
                "file_id": self.file_ids[idx],
                "score": float(round(sims[idx], 4)),
                "retrieval_method": "dense",
            })
        return results

    def delete_by_chunk_ids(self, chunk_ids: List[str]) -> int:
        if not chunk_ids or len(self.chunk_ids) == 0:
            return 0
        del_set = set(chunk_ids)
        keep_mask = [cid not in del_set for cid in self.chunk_ids]
        deleted_count = len(self.chunk_ids) - sum(keep_mask)
        self.chunk_ids = [cid for cid, keep in zip(self.chunk_ids, keep_mask) if keep]
        self.file_ids = [fid for fid, keep in zip(self.file_ids, keep_mask) if keep]
        self.vectors = self.vectors[keep_mask]
        return deleted_count

    def delete_by_file_id(self, file_id: str) -> int:
        if not file_id or len(self.file_ids) == 0:
            return 0
        keep_mask = [fid != file_id for fid in self.file_ids]
        deleted_count = len(self.file_ids) - sum(keep_mask)
        self.chunk_ids = [cid for cid, keep in zip(self.chunk_ids, keep_mask) if keep]
        self.file_ids = [fid for fid, keep in zip(self.file_ids, keep_mask) if keep]
        self.vectors = self.vectors[keep_mask]
        return deleted_count

    def count(self) -> int:
        return len(self.chunk_ids)
