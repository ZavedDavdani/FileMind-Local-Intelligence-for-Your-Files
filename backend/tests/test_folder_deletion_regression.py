import os
import tempfile
import pytest
from app.db.connection import DatabaseManager
from app.db.migrations import apply_migrations
from app.db.repository import Repository
from app.retrieval.vector_store import SqliteVecStore
from app.intelligence.models import Document, DocumentElement, ElementType
from app.intelligence.chunker.hierarchical import HierarchicalChunker

def test_folder_deletion_cascade_and_vector_cleanup():
    """Regression test: Deleting a folder cleanly removes all files, chunks, FTS5 entries, and vector embeddings."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_folder_del.db")
        db = DatabaseManager(db_path)

        with db.session() as conn:
            apply_migrations(conn)
            vec_store = SqliteVecStore(conn, dimension=384)
            repo = Repository(conn)

            folder = repo.create_folder(r"C:\test\del_folder", folder_id="fol-del-1")
            fid1 = "file-del-1"
            fid2 = "file-del-2"

            repo.upsert_file(
                folder_id="fol-del-1",
                path=r"C:\test\del_folder\doc1.txt",
                relative_path="doc1.txt",
                filename="doc1.txt",
                extension=".txt",
                size_bytes=100,
                modified_at="2026-08-30T10:00:00Z",
                file_id=fid1,
            )
            repo.upsert_file(
                folder_id="fol-del-1",
                path=r"C:\test\del_folder\doc2.txt",
                relative_path="doc2.txt",
                filename="doc2.txt",
                extension=".txt",
                size_bytes=200,
                modified_at="2026-08-30T10:00:00Z",
                file_id=fid2,
            )

            # Insert chunks for both files
            chunker = HierarchicalChunker()
            doc1 = Document(
                file_id=fid1,
                filename="doc1.txt",
                source_path=r"C:\test\del_folder\doc1.txt",
                mime_type="text/plain",
                parser_name="text_parser",
                parser_version="1.0.0",
                elements=[
                    DocumentElement(
                        element_id="el-1",
                        element_type=ElementType.PARAGRAPH,
                        text="First document content for deletion test.",
                        line_start=1,
                        line_end=1,
                        char_start=0,
                        char_end=42,
                    )
                ],
            )
            doc2 = Document(
                file_id=fid2,
                filename="doc2.txt",
                source_path=r"C:\test\del_folder\doc2.txt",
                mime_type="text/plain",
                parser_name="text_parser",
                parser_version="1.0.0",
                elements=[
                    DocumentElement(
                        element_id="el-2",
                        element_type=ElementType.PARAGRAPH,
                        text="Second document content for deletion test.",
                        line_start=1,
                        line_end=1,
                        char_start=0,
                        char_end=43,
                    )
                ],
            )
            chunks1 = chunker.chunk_document(doc1)
            chunks2 = chunker.chunk_document(doc2)
            repo.replace_file_chunks(fid1, chunks1)
            repo.replace_file_chunks(fid2, chunks2)

            # Insert vectors in chunk_vectors
            vec_store.upsert_vectors([
                {"chunk_id": chunks1[0].chunk_id, "file_id": fid1, "embedding": [0.1] * 384},
                {"chunk_id": chunks2[0].chunk_id, "file_id": fid2, "embedding": [0.2] * 384},
            ])

            # Enqueue jobs
            repo.enqueue_job(fid1, "fol-del-1", "DOCUMENT_PARSE")
            repo.enqueue_job(fid2, "fol-del-1", "DOCUMENT_PARSE")

            # Verify initial populated state
            assert len(repo.list_files("fol-del-1")) == 2
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM chunks WHERE file_id IN (?, ?)", (fid1, fid2))
            assert cur.fetchone()[0] == 2
            cur.execute("SELECT count(*) FROM chunks_fts WHERE file_id IN (?, ?)", (fid1, fid2))
            assert cur.fetchone()[0] == 2
            cur.execute("SELECT count(*) FROM chunk_vectors")
            assert cur.fetchone()[0] == 2

            # Perform folder deletion
            deleted = repo.delete_folder("fol-del-1")
            assert deleted is True

            # Verify 100% complete cascade and vector cleanup
            assert repo.get_folder("fol-del-1") is None
            assert len(repo.list_files("fol-del-1")) == 0
            cur.execute("SELECT count(*) FROM chunks WHERE file_id IN (?, ?)", (fid1, fid2))
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT count(*) FROM chunks_fts WHERE file_id IN (?, ?)", (fid1, fid2))
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT count(*) FROM chunk_vectors")
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT count(*) FROM indexing_jobs WHERE folder_id = ?", ("fol-del-1",))
            assert cur.fetchone()[0] == 0
