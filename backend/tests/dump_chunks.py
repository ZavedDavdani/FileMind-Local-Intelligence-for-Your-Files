import os
import sys
import tempfile
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from tests.fixtures.benchmark_corpus import setup_benchmark_corpus

td = tempfile.mkdtemp()
db_path = os.path.join(td, "bm.db")
meta = setup_benchmark_corpus(td, db_path)

output_rows = []
for c in meta["chunks"]:
    output_rows.append({
        "chunk_id": c["chunk_id"],
        "source_file": c["source_file"],
        "h1": c.get("h1_parent"),
        "h2": c.get("h2_parent"),
        "section": c.get("section"),
        "page": c.get("page"),
        "content": c["content"],
    })

with open("corpus_chunks_dump.json", "w", encoding="utf-8") as f:
    json.dump(output_rows, f, indent=2)

print(f"Dumped {len(output_rows)} chunks across {meta['total_files']} files to corpus_chunks_dump.json")
