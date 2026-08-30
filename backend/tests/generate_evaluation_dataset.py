"""Deterministic evaluation dataset and ground-truth generator for Phase 3.

Produces:
- docs/phase-3/evaluation-dataset.json
- docs/phase-3/evaluation-dataset.md
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from tests.fixtures.benchmark_corpus import setup_benchmark_corpus, CORPUS_VERSION

DATASET_VERSION = "phase3-eval-v1.0"


def build_evaluation_dataset():
    # Setup temporary benchmark corpus to map deterministic chunk IDs
    td = tempfile.mkdtemp()
    db_path = os.path.join(td, "bm.db")
    meta = setup_benchmark_corpus(td, db_path)

    # Index chunks by source_file and content substring for ground truth mapping
    chunks = meta["chunks"]
    
    def find_chunks(file_name=None, text_contains=None, h1=None, h2=None):
        matched = []
        for c in chunks:
            if file_name and c["source_file"] != file_name:
                continue
            if h1 and c.get("h1_parent") != h1:
                continue
            if h2 and c.get("h2_parent") != h2:
                continue
            if text_contains and text_contains.lower() not in c["content"].lower():
                continue
            matched.append(c["chunk_id"])
        return matched

    # 28 Queries
    benchmark_queries = [
        {
            "query_id": "Q01_EXACT_FILENAME",
            "query_text": "sample_system_spec.pdf",
            "category": "exact_filename",
            "expected_advantage": "lexical",
            "expected_files": ["sample_system_spec.pdf"],
            "expected_chunk_ids": find_chunks(file_name="sample_system_spec.pdf"),
            "graded_relevance": {cid: 2 for cid in find_chunks(file_name="sample_system_spec.pdf")},
            "description": "Exact match for document filename; lexical retrieval should rank all chunks of sample_system_spec.pdf highest.",
        },
        {
            "query_id": "Q02_EXACT_PHRASE",
            "query_text": "Cryptographic hashing with streaming SHA-256 validation",
            "category": "exact_phrase",
            "expected_advantage": "lexical",
            "expected_files": ["doc1_enterprise_spec.pdf"],
            "expected_chunk_ids": find_chunks(file_name="doc1_enterprise_spec.pdf", text_contains="Cryptographic hashing"),
            "graded_relevance": {
                cid: 2 for cid in find_chunks(file_name="doc1_enterprise_spec.pdf", text_contains="Cryptographic hashing")
            },
            "description": "Exact phrase from Security Subsystem Hierarchy in doc1_enterprise_spec.pdf.",
        },
        {
            "query_id": "Q03_EXACT_PHRASE_STORAGE",
            "query_text": "Write-Ahead Logging (WAL) mode enabled for high-concurrency",
            "category": "exact_phrase",
            "expected_advantage": "lexical",
            "expected_files": ["sample_system_spec.pdf", "sample_system_spec.docx"],
            "expected_chunk_ids": (
                find_chunks(file_name="sample_system_spec.pdf", text_contains="Write-Ahead Logging") +
                find_chunks(file_name="sample_system_spec.docx", text_contains="Write-Ahead Logging")
            ),
            "graded_relevance": {
                **{cid: 2 for cid in find_chunks(file_name="sample_system_spec.pdf", text_contains="Write-Ahead Logging")},
                **{cid: 2 for cid in find_chunks(file_name="sample_system_spec.docx", text_contains="Write-Ahead Logging")},
                **{cid: 1 for cid in find_chunks(file_name="doc8_spec.md", text_contains="WAL")},
            },
            "description": "Exact phrase detailing SQLite WAL persistence in system specifications.",
        },
        {
            "query_id": "Q04_KEYWORD_IDENTIFIER",
            "query_text": "file_events",
            "category": "identifier",
            "expected_advantage": "lexical",
            "expected_files": ["sample_system_spec.docx"],
            "expected_chunk_ids": find_chunks(file_name="sample_system_spec.docx", text_contains="file_events"),
            "graded_relevance": {
                cid: 2 for cid in find_chunks(file_name="sample_system_spec.docx", text_contains="file_events")
            },
            "description": "Specific internal SQLite table identifier for filesystem event audit trail.",
        },
        {
            "query_id": "Q05_CODE_SNIPPET",
            "query_text": "def get_config():",
            "category": "code",
            "expected_advantage": "lexical",
            "expected_files": ["sample_architecture.md"],
            "expected_chunk_ids": find_chunks(file_name="sample_architecture.md", text_contains="def get_config():"),
            "graded_relevance": {
                cid: 2 for cid in find_chunks(file_name="sample_architecture.md", text_contains="def get_config():")
            },
            "description": "Code definition in markdown architecture specification.",
        },
        {
            "query_id": "Q06_TECHNICAL_ACRONYM",
            "query_text": "mTLS",
            "category": "acronym",
            "expected_advantage": "lexical",
            "expected_files": ["doc1_enterprise_spec.pdf"],
            "expected_chunk_ids": find_chunks(file_name="doc1_enterprise_spec.pdf", text_contains="mTLS"),
            "graded_relevance": {
                cid: 2 for cid in find_chunks(file_name="doc1_enterprise_spec.pdf", text_contains="mTLS")
            },
            "description": "Technical acronym for mutual TLS protocol in security spec.",
        },
        {
            "query_id": "Q07_TECHNICAL_TERM",
            "query_text": "integrity_mode NORMAL debounce_ms",
            "category": "technical_term",
            "expected_advantage": "lexical",
            "expected_files": ["sample_architecture.md"],
            "expected_chunk_ids": find_chunks(file_name="sample_architecture.md", text_contains="integrity_mode"),
            "graded_relevance": {
                cid: 2 for cid in find_chunks(file_name="sample_architecture.md", text_contains="integrity_mode")
            },
            "description": "Configuration parameter names in architecture specification.",
        },
        {
            "query_id": "Q08_CODE_IDENTIFIER",
            "query_text": "EngineCoordinator",
            "category": "identifier",
            "expected_advantage": "lexical",
            "expected_files": ["sample_coordinator.py"],
            "expected_chunk_ids": find_chunks(file_name="sample_coordinator.py", h1="class EngineCoordinator"),
            "graded_relevance": {
                cid: 2 for cid in find_chunks(file_name="sample_coordinator.py", h1="class EngineCoordinator")
            },
            "description": "Python class name for the background engine coordinator.",
        },
        {
            "query_id": "Q09_PARTIAL_TERM",
            "query_text": "debounc",
            "category": "partial_term",
            "expected_advantage": "lexical",
            "expected_files": ["sample_system_spec.pdf", "sample_architecture.md"],
            "expected_chunk_ids": (
                find_chunks(file_name="sample_system_spec.pdf", text_contains="Debounce") +
                find_chunks(file_name="sample_architecture.md", text_contains="debounce")
            ),
            "graded_relevance": {
                **{cid: 2 for cid in find_chunks(file_name="sample_system_spec.pdf", text_contains="Debounce")},
                **{cid: 2 for cid in find_chunks(file_name="sample_architecture.md", text_contains="debounce")},
            },
            "description": "Stemmed partial term for debounce logic.",
        },
        {
            "query_id": "Q10_SEMANTIC_CONCEPT_1",
            "query_text": "how does the system guarantee fast crash recovery and restart",
            "category": "semantic_concept",
            "expected_advantage": "dense",
            "expected_files": ["sample_system_spec.pdf", "sample_architecture.md", "sample_metrics.csv"],
            "expected_chunk_ids": (
                find_chunks(file_name="sample_system_spec.pdf", text_contains="Crash Recovery") +
                find_chunks(file_name="sample_architecture.md", text_contains="Recovery") +
                find_chunks(file_name="sample_metrics.csv", text_contains="recovery_time")
            ),
            "graded_relevance": {
                **{cid: 2 for cid in find_chunks(file_name="sample_system_spec.pdf", text_contains="Crash Recovery")},
                **{cid: 2 for cid in find_chunks(file_name="sample_architecture.md", text_contains="Recovery")},
                **{cid: 1 for cid in find_chunks(file_name="sample_metrics.csv", text_contains="recovery_time")},
            },
            "description": "Semantic query describing crash resilience and recovery targets.",
        },
        {
            "query_id": "Q11_SEMANTIC_CONCEPT_2",
            "query_text": "data retention schedule for cold audit records and compliance",
            "category": "semantic_concept",
            "expected_advantage": "dense",
            "expected_files": ["doc1_enterprise_spec.pdf"],
            "expected_chunk_ids": find_chunks(file_name="doc1_enterprise_spec.pdf", h1="Archival Schedule"),
            "graded_relevance": {
                cid: 2 for cid in find_chunks(file_name="doc1_enterprise_spec.pdf", h1="Archival Schedule")
            },
            "description": "Semantic conceptual query for compliance archival lifecycle.",
        },
        {
            "query_id": "Q12_SEMANTIC_CONCEPT_3",
            "query_text": "preventing dangling or orphan processes from staying alive",
            "category": "semantic_concept",
            "expected_advantage": "dense",
            "expected_files": ["doc5_bullets.docx"],
            "expected_chunk_ids": find_chunks(file_name="doc5_bullets.docx", text_contains="orphan worker processes"),
            "graded_relevance": {
                cid: 2 for cid in find_chunks(file_name="doc5_bullets.docx", text_contains="orphan worker processes")
            },
            "description": "Semantic query about child-process cleanup.",
        },
        {
            "query_id": "Q13_SEMANTIC_CONCEPT_4",
            "query_text": "quarterly business revenue and financial profit margins",
            "category": "semantic_concept",
            "expected_advantage": "dense",
            "expected_files": ["doc11_sheets.xlsx"],
            "expected_chunk_ids": find_chunks(file_name="doc11_sheets.xlsx", text_contains="Revenue"),
            "graded_relevance": {
                cid: 2 for cid in find_chunks(file_name="doc11_sheets.xlsx", text_contains="Revenue")
            },
            "description": "Semantic retrieval of financial spreadsheet table.",
        },
        {
            "query_id": "Q14_SEMANTIC_CONCEPT_5",
            "query_text": "hardware memory limits for background compute workers",
            "category": "semantic_concept",
            "expected_advantage": "dense",
            "expected_files": ["doc4_nested_ops.docx"],
            "expected_chunk_ids": find_chunks(file_name="doc4_nested_ops.docx", text_contains="Max RAM"),
            "graded_relevance": {
                cid: 2 for cid in find_chunks(file_name="doc4_nested_ops.docx", text_contains="Max RAM")
            },
            "description": "Semantic retrieval of worker RAM capacity limit.",
        },
        {
            "query_id": "Q15_HYBRID_MULTI_TERM_1",
            "query_text": "SQLite WAL persistence and change detection",
            "category": "hybrid_multi_term",
            "expected_advantage": "hybrid",
            "expected_files": ["sample_architecture.md", "sample_system_spec.pdf", "sample_system_spec.docx"],
            "expected_chunk_ids": (
                find_chunks(file_name="sample_architecture.md", text_contains="SQLite WAL persistence") +
                find_chunks(file_name="sample_system_spec.pdf", text_contains="Write-Ahead Logging") +
                find_chunks(file_name="sample_system_spec.docx", text_contains="Write-Ahead Logging")
            ),
            "graded_relevance": {
                **{cid: 2 for cid in find_chunks(file_name="sample_architecture.md", text_contains="SQLite WAL persistence")},
                **{cid: 2 for cid in find_chunks(file_name="sample_system_spec.pdf", text_contains="Write-Ahead Logging")},
                **{cid: 1 for cid in find_chunks(file_name="sample_system_spec.docx", text_contains="Write-Ahead Logging")},
            },
            "description": "Multi-term query benefiting from both lexical precision on WAL/SQLite and dense concept relevance.",
        },
        {
            "query_id": "Q16_HYBRID_MULTI_TERM_2",
            "query_text": "discovery rate throughput target 500 files/s",
            "category": "hybrid_multi_term",
            "expected_advantage": "hybrid",
            "expected_files": ["sample_metrics.csv", "sample_metrics.xlsx"],
            "expected_chunk_ids": (
                find_chunks(file_name="sample_metrics.csv", text_contains="discovery_rate") +
                find_chunks(file_name="sample_metrics.xlsx", text_contains="Discovery Throughput")
            ),
            "graded_relevance": {
                **{cid: 2 for cid in find_chunks(file_name="sample_metrics.csv", text_contains="discovery_rate")},
                **{cid: 2 for cid in find_chunks(file_name="sample_metrics.xlsx", text_contains="Discovery Throughput")},
            },
            "description": "Multi-term benchmark target matching across CSV and XLSX tables.",
        },
        {
            "query_id": "Q17_HYBRID_MULTI_TERM_3",
            "query_text": "asynchronous worker pool filesystem discovery events",
            "category": "hybrid_multi_term",
            "expected_advantage": "hybrid",
            "expected_files": ["doc2_multicolumn.pdf"],
            "expected_chunk_ids": find_chunks(file_name="doc2_multicolumn.pdf", text_contains="Asynchronous worker pools"),
            "graded_relevance": {
                cid: 2 for cid in find_chunks(file_name="doc2_multicolumn.pdf", text_contains="Asynchronous worker pools")
            },
            "description": "Multi-term whitepaper section retrieval.",
        },
        {
            "query_id": "Q18_MULTI_CHUNK_RELEVANCE",
            "query_text": "FileMind architecture overview and subsystems",
            "category": "multi_chunk",
            "expected_advantage": "hybrid",
            "expected_files": ["sample_presentation.pptx", "sample_architecture.md", "sample_system_spec.pdf"],
            "expected_chunk_ids": (
                find_chunks(file_name="sample_presentation.pptx", text_contains="Architecture Overview") +
                find_chunks(file_name="sample_architecture.md", text_contains="Subsystems") +
                find_chunks(file_name="sample_system_spec.pdf", text_contains="Component Overview")
            ),
            "graded_relevance": {
                **{cid: 2 for cid in find_chunks(file_name="sample_presentation.pptx", text_contains="Architecture Overview")},
                **{cid: 2 for cid in find_chunks(file_name="sample_architecture.md", text_contains="Subsystems")},
                **{cid: 2 for cid in find_chunks(file_name="sample_system_spec.pdf", text_contains="Component Overview")},
            },
            "description": "Broad architectural topic with multiple highly relevant chunks across presentation, markdown, and PDF.",
        },
        {
            "query_id": "Q19_TABLE_CONTENT",
            "query_text": "Quarterly benchmark results discovery and watcher latency",
            "category": "table_content",
            "expected_advantage": "hybrid",
            "expected_files": ["sample_metrics.xlsx", "sample_metrics.csv"],
            "expected_chunk_ids": (
                find_chunks(file_name="sample_metrics.xlsx", text_contains="PerformanceBenchmarks") +
                find_chunks(file_name="sample_metrics.csv", text_contains="watcher_latency")
            ),
            "graded_relevance": {
                **{cid: 2 for cid in find_chunks(file_name="sample_metrics.xlsx", text_contains="PerformanceBenchmarks")},
                **{cid: 1 for cid in find_chunks(file_name="sample_metrics.csv", text_contains="watcher_latency")},
            },
            "description": "Retrieval of tabular benchmark performance data.",
        },
        {
            "query_id": "Q20_NATURAL_LANGUAGE_1",
            "query_text": "What is the key rotation interval for Tier-1 TLS 1.3 protocol?",
            "category": "natural_language",
            "expected_advantage": "hybrid",
            "expected_files": ["doc1_enterprise_spec.pdf"],
            "expected_chunk_ids": find_chunks(file_name="doc1_enterprise_spec.pdf", text_contains="TLS 1.3"),
            "graded_relevance": {
                cid: 2 for cid in find_chunks(file_name="doc1_enterprise_spec.pdf", text_contains="TLS 1.3")
            },
            "description": "Natural language question seeking a specific table value (90 Days) in security spec.",
        },
        {
            "query_id": "Q21_NATURAL_LANGUAGE_2",
            "query_text": "Which database tables store watcher events and indexing jobs?",
            "category": "natural_language",
            "expected_advantage": "hybrid",
            "expected_files": ["sample_system_spec.docx"],
            "expected_chunk_ids": find_chunks(file_name="sample_system_spec.docx", text_contains="indexing_jobs"),
            "graded_relevance": {
                cid: 2 for cid in find_chunks(file_name="sample_system_spec.docx", text_contains="indexing_jobs")
            },
            "description": "Natural language inquiry mapping to component layer table in DOCX.",
        },
        {
            "query_id": "Q22_SINGLE_HIGH_RELEVANCE",
            "query_text": "def execute_task(self, task_id: str)",
            "category": "single_chunk",
            "expected_advantage": "lexical",
            "expected_files": ["sample_coordinator.py"],
            "expected_chunk_ids": find_chunks(file_name="sample_coordinator.py", text_contains="def execute_task"),
            "graded_relevance": {
                cid: 2 for cid in find_chunks(file_name="sample_coordinator.py", text_contains="def execute_task")
            },
            "description": "Exact method signature lookup with exactly one matching chunk.",
        },
        {
            "query_id": "Q23_AMBIGUOUS_QUERY",
            "query_text": "performance benchmarks",
            "category": "ambiguous",
            "expected_advantage": "hybrid",
            "expected_files": ["sample_architecture.md", "sample_metrics.xlsx", "doc12_metrics.csv"],
            "expected_chunk_ids": (
                find_chunks(file_name="sample_architecture.md", text_contains="Performance Targets") +
                find_chunks(file_name="sample_metrics.xlsx", text_contains="PerformanceBenchmarks") +
                find_chunks(file_name="doc12_metrics.csv", text_contains="latency")
            ),
            "graded_relevance": {
                **{cid: 2 for cid in find_chunks(file_name="sample_architecture.md", text_contains="Performance Targets")},
                **{cid: 2 for cid in find_chunks(file_name="sample_metrics.xlsx", text_contains="PerformanceBenchmarks")},
                **{cid: 1 for cid in find_chunks(file_name="doc12_metrics.csv", text_contains="latency")},
            },
            "description": "Short ambiguous query matching across multiple document formats.",
        },
        {
            "query_id": "Q24_METADATA_FILTER_H1",
            "query_text": "Data Integrity Protocols immutable provenance",
            "category": "metadata_heading",
            "expected_advantage": "hybrid",
            "expected_files": ["sample_system_spec.pdf"],
            "expected_chunk_ids": find_chunks(file_name="sample_system_spec.pdf", h1="Data Integrity Protocols"),
            "graded_relevance": {
                cid: 2 for cid in find_chunks(file_name="sample_system_spec.pdf", h1="Data Integrity Protocols")
            },
            "description": "Heading and section provenance query in PDF.",
        },
        {
            "query_id": "Q25_HEADCOUNT_QUERY",
            "query_text": "Engineering department headcount",
            "category": "table_content",
            "expected_advantage": "hybrid",
            "expected_files": ["doc11_sheets.xlsx"],
            "expected_chunk_ids": find_chunks(file_name="doc11_sheets.xlsx", text_contains="Engineering"),
            "graded_relevance": {
                cid: 2 for cid in find_chunks(file_name="doc11_sheets.xlsx", text_contains="Engineering")
            },
            "description": "Specific department headcount query matching table row in Excel workbook.",
        },
        {
            "query_id": "Q26_NEGATIVE_NO_MATCH_1",
            "query_text": "quantum entanglement topological superconducting qubit",
            "category": "negative",
            "expected_advantage": "none",
            "expected_files": [],
            "expected_chunk_ids": [],
            "graded_relevance": {},
            "description": "Negative query: No quantum computing documents exist in the corpus.",
        },
        {
            "query_id": "Q27_NEGATIVE_NO_MATCH_2",
            "query_text": "kubernetes helm chart deployment yaml aws ingress controller",
            "category": "negative",
            "expected_advantage": "none",
            "expected_files": [],
            "expected_chunk_ids": [],
            "graded_relevance": {},
            "description": "Negative query: No cloud/Kubernetes deployment artifacts exist in the corpus.",
        },
        {
            "query_id": "Q28_NEGATIVE_NO_MATCH_3",
            "query_text": "blockchain smart contract solana validator consensus",
            "category": "negative",
            "expected_advantage": "none",
            "expected_files": [],
            "expected_chunk_ids": [],
            "graded_relevance": {},
            "description": "Negative query: No crypto/blockchain materials exist in the corpus.",
        },
    ]

    # Validate each query has correct structure
    for q in benchmark_queries:
        assert q["query_id"]
        assert q["query_text"]
        if q["category"] != "negative":
            assert len(q["expected_files"]) > 0, f"Query {q['query_id']} has no expected files"
            assert len(q["expected_chunk_ids"]) > 0, f"Query {q['query_id']} has no expected chunks"
            assert len(q["graded_relevance"]) > 0, f"Query {q['query_id']} has no graded relevance"

    dataset_obj = {
        "dataset_version": DATASET_VERSION,
        "corpus_version": CORPUS_VERSION,
        "total_queries": len(benchmark_queries),
        "corpus_summary": {
            "total_files": meta["total_files"],
            "total_chunks": meta["total_chunks"],
            "total_bytes": meta["total_bytes"],
        },
        "queries": benchmark_queries,
    }

    # Write JSON artifact
    json_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "docs", "phase-3", "evaluation-dataset.json"))
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(dataset_obj, f, indent=2)

    # Write Markdown documentation artifact
    md_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "docs", "phase-3", "evaluation-dataset.md"))
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# Phase 3 Evaluation Dataset & Ground Truth Specification\n\n")
        f.write(f"- **Dataset Version**: `{DATASET_VERSION}`\n")
        f.write(f"- **Corpus Version**: `{CORPUS_VERSION}`\n")
        f.write(f"- **Total Benchmark Queries**: `{len(benchmark_queries)}`\n")
        f.write(f"- **Corpus Scale**: {meta['total_files']} files, {meta['total_chunks']} chunks, {meta['total_bytes']} bytes\n\n")
        f.write(f"---\n\n")
        f.write(f"## 1. Metric Definitions & Formulas\n\n")
        f.write(f"### Recall@K\n")
        f.write(f"$$\\text{{Recall@K}} = \\frac{{\\sum_{{q \\in Q}} \\frac{{|\\text{{Retrieved}}_K(q) \\cap \\text{{Relevant}}(q)|}}{{|\\text{{Relevant}}(q)|}}}}{{|Q|}}$$\n\n")
        f.write(f"### Mean Reciprocal Rank (MRR)\n")
        f.write(f"$$\\text{{MRR}} = \\frac{{1}}{{|Q|}} \\sum_{{i=1}}^{{|Q|}} \\frac{{1}}{{\\text{{rank}}_i}}$$\n")
        f.write(f"where $\\text{{rank}}_i$ is the 1-indexed position of the first relevant chunk ($rel \\ge 1$). If no relevant chunk is in Top-K, reciprocal rank is $0$.\n\n")
        f.write(f"### Normalized Discounted Cumulative Gain (NDCG@K)\n")
        f.write(f"$$\\text{{DCG@K}} = \\sum_{{i=1}}^{{K}} \\frac{{2^{{rel_i}} - 1}}{{\\log_2(i + 1)}}, \\quad \\text{{NDCG@K}} = \\frac{{\\text{{DCG@K}}}}{{\\text{{IDCG@K}}}}$$\n")
        f.write(f"where $rel_i \\in \\{{0, 1, 2\\}}$ is the graded relevance level.\n\n")
        f.write(f"---\n\n")
        f.write(f"## 2. Benchmark Query Registry\n\n")
        f.write(f"| ID | Query Text | Category | Advantage | Expected Files | Target Chunks |\n")
        f.write(f"|---|---|---|---|---|---|\n")
        for q in benchmark_queries:
            exp_f = ", ".join(q["expected_files"]) if q["expected_files"] else "None (Negative)"
            chk_cnt = len(q["expected_chunk_ids"])
            f.write(f"| `{q['query_id']}` | \"{q['query_text']}\" | `{q['category']}` | `{q['expected_advantage']}` | {exp_f} | {chk_cnt} chunks |\n")
        f.write(f"\n---\n\n")
        f.write(f"## 3. Query Details & Relevance Annotations\n\n")
        for q in benchmark_queries:
            f.write(f"### `{q['query_id']}`: \"{q['query_text']}\"\n")
            f.write(f"- **Category**: `{q['category']}`\n")
            f.write(f"- **Expected Advantage**: `{q['expected_advantage']}`\n")
            f.write(f"- **Description**: {q['description']}\n")
            f.write(f"- **Expected Target Files**: `{q['expected_files']}`\n")
            f.write(f"- **Expected Chunk IDs**: `{q['expected_chunk_ids']}`\n")
            f.write(f"- **Graded Relevance**: `{q['graded_relevance']}`\n\n")

    print(f"Generated {len(benchmark_queries)} queries in {json_path} and {md_path}")
    return dataset_obj


if __name__ == "__main__":
    build_evaluation_dataset()
