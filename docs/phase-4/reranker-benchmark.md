# Phase 4 Fast vs Quality Retrieval Benchmark Report

## Execution Environment
- **Dataset Version**: phase4-eval-v1.0
- **Corpus Version**: phase3-benchmark-corpus-v1
- **Embedding Model**: `sentence-transformers/all-MiniLM-L6-v2`
- **Reranker Model**: `BAAI/bge-reranker-base`
- **OS / Platform**: Windows-10-10.0.26200-SP0
- **Python**: 3.11.0
- **RAM Footprint**: 2160.67 MB (Delta: +2066.28 MB)

## Retrieval Quality and Latency Summary Table

| Configuration | Recall@1 | Recall@5 | Recall@10 | MRR | NDCG@10 | p50 Latency | p95 Latency | Mean Latency | Rerank Latency |
|---|---|---|---|---|---|---|---|---|---|
| **BM25 Fast** | 0.4113 | 0.4933 | 0.4933 | 0.5600 | 0.5090 | 0.22 ms | 0.42 ms | 0.25 ms | 0.00 ms |
| **Dense Fast** | 0.6267 | 0.8613 | 0.9113 | 0.8393 | 0.8263 | 18.15 ms | 21.91 ms | 18.36 ms | 0.00 ms |
| **Hybrid Fast (RRF)** | 0.7147 | 0.9233 | 0.9733 | 0.9433 | 0.9367 | 19.67 ms | 22.04 ms | 19.90 ms | 0.00 ms |
| **Hybrid Quality (RRF + bge-reranker-base)** | 0.6667 | 0.8747 | 0.9347 | 0.9200 | 0.8868 | 4817.67 ms | 5890.36 ms | 5176.00 ms | 5062.31 ms |

## Semantic Reordering Analysis

Reranking produced reordered top-3 candidates across **23** queries:

### `Q01_EXACT_FILENAME`: "sample_system_spec.pdf"
- **Category**: exact_filename
- **Fast Top-1 (RRF)**: `sample_system_spec.pdf` (RRF Score: 0.051778)
- **Quality Top-1 (Cross-Encoder)**: `sample_system_spec.docx` (Rerank Score: 0.077249)
- **NDCG@10**: Fast = 1.0000 -> Quality = 0.2140 (Delta: -0.7860)

### `Q02_EXACT_PHRASE`: "Cryptographic hashing with streaming SHA-256 validation"
- **Category**: exact_phrase
- **Fast Top-1 (RRF)**: `doc1_enterprise_spec.pdf` (RRF Score: 0.032787)
- **Quality Top-1 (Cross-Encoder)**: `doc1_enterprise_spec.pdf` (Rerank Score: 0.989848)
- **NDCG@10**: Fast = 1.0000 -> Quality = 1.0000 (Delta: +0.0000)

### `Q04_KEYWORD_IDENTIFIER`: "file_events"
- **Category**: identifier
- **Fast Top-1 (RRF)**: `sample_system_spec.docx` (RRF Score: 0.031778)
- **Quality Top-1 (Cross-Encoder)**: `sample_system_spec.docx` (Rerank Score: 0.862675)
- **NDCG@10**: Fast = 1.0000 -> Quality = 1.0000 (Delta: +0.0000)

### `Q05_CODE_SNIPPET`: "def get_config():"
- **Category**: code
- **Fast Top-1 (RRF)**: `sample_architecture.md` (RRF Score: 0.032787)
- **Quality Top-1 (Cross-Encoder)**: `sample_architecture.md` (Rerank Score: 0.984362)
- **NDCG@10**: Fast = 1.0000 -> Quality = 1.0000 (Delta: +0.0000)

### `Q06_TECHNICAL_ACRONYM`: "mTLS"
- **Category**: acronym
- **Fast Top-1 (RRF)**: `doc1_enterprise_spec.pdf` (RRF Score: 0.032787)
- **Quality Top-1 (Cross-Encoder)**: `doc1_enterprise_spec.pdf` (Rerank Score: 0.642145)
- **NDCG@10**: Fast = 1.0000 -> Quality = 1.0000 (Delta: +0.0000)

### `Q07_TECHNICAL_TERM`: "integrity_mode NORMAL debounce_ms"
- **Category**: technical_term
- **Fast Top-1 (RRF)**: `sample_architecture.md` (RRF Score: 0.032787)
- **Quality Top-1 (Cross-Encoder)**: `sample_architecture.md` (Rerank Score: 0.96919)
- **NDCG@10**: Fast = 1.0000 -> Quality = 1.0000 (Delta: +0.0000)

### `Q08_CODE_IDENTIFIER`: "EngineCoordinator"
- **Category**: identifier
- **Fast Top-1 (RRF)**: `sample_coordinator.py` (RRF Score: 0.032787)
- **Quality Top-1 (Cross-Encoder)**: `sample_coordinator.py` (Rerank Score: 0.959948)
- **NDCG@10**: Fast = 1.0000 -> Quality = 0.5032 (Delta: -0.4968)

### `Q09_PARTIAL_TERM`: "debounc"
- **Category**: partial_term
- **Fast Top-1 (RRF)**: `sample_architecture.md` (RRF Score: 0.032522)
- **Quality Top-1 (Cross-Encoder)**: `sample_architecture.md` (Rerank Score: 0.003239)
- **NDCG@10**: Fast = 1.0000 -> Quality = 1.0000 (Delta: +0.0000)

### `Q10_SEMANTIC_CONCEPT_1`: "how does the system guarantee fast crash recovery and restart"
- **Category**: semantic_concept
- **Fast Top-1 (RRF)**: `sample_system_spec.pdf` (RRF Score: 0.016393)
- **Quality Top-1 (Cross-Encoder)**: `doc8_spec.md` (Rerank Score: 0.083316)
- **NDCG@10**: Fast = 0.7959 -> Quality = 0.5364 (Delta: -0.2595)

### `Q11_SEMANTIC_CONCEPT_2`: "data retention schedule for cold audit records and compliance"
- **Category**: semantic_concept
- **Fast Top-1 (RRF)**: `doc1_enterprise_spec.pdf` (RRF Score: 0.016393)
- **Quality Top-1 (Cross-Encoder)**: `doc1_enterprise_spec.pdf` (Rerank Score: 0.392989)
- **NDCG@10**: Fast = 1.0000 -> Quality = 1.0000 (Delta: +0.0000)

### `Q12_SEMANTIC_CONCEPT_3`: "preventing dangling or orphan processes from staying alive"
- **Category**: semantic_concept
- **Fast Top-1 (RRF)**: `doc5_bullets.docx` (RRF Score: 0.016393)
- **Quality Top-1 (Cross-Encoder)**: `doc5_bullets.docx` (Rerank Score: 0.019719)
- **NDCG@10**: Fast = 1.0000 -> Quality = 1.0000 (Delta: +0.0000)

### `Q13_SEMANTIC_CONCEPT_4`: "quarterly business revenue and financial profit margins"
- **Category**: semantic_concept
- **Fast Top-1 (RRF)**: `doc11_sheets.xlsx` (RRF Score: 0.016393)
- **Quality Top-1 (Cross-Encoder)**: `doc11_sheets.xlsx` (Rerank Score: 0.916362)
- **NDCG@10**: Fast = 1.0000 -> Quality = 1.0000 (Delta: +0.0000)

### `Q14_SEMANTIC_CONCEPT_5`: "hardware memory limits for background compute workers"
- **Category**: semantic_concept
- **Fast Top-1 (RRF)**: `doc4_nested_ops.docx` (RRF Score: 0.016393)
- **Quality Top-1 (Cross-Encoder)**: `doc4_nested_ops.docx` (Rerank Score: 0.269253)
- **NDCG@10**: Fast = 1.0000 -> Quality = 1.0000 (Delta: +0.0000)

### `Q15_HYBRID_MULTI_TERM_1`: "SQLite WAL persistence and change detection"
- **Category**: hybrid_multi_term
- **Fast Top-1 (RRF)**: `sample_architecture.md` (RRF Score: 0.032266)
- **Quality Top-1 (Cross-Encoder)**: `sample_architecture.md` (Rerank Score: 0.982472)
- **NDCG@10**: Fast = 0.9514 -> Quality = 1.0000 (Delta: +0.0486)

### `Q16_HYBRID_MULTI_TERM_2`: "discovery rate throughput target 500 files/s"
- **Category**: hybrid_multi_term
- **Fast Top-1 (RRF)**: `sample_metrics.csv` (RRF Score: 0.032522)
- **Quality Top-1 (Cross-Encoder)**: `sample_metrics.csv` (Rerank Score: 0.937731)
- **NDCG@10**: Fast = 0.9197 -> Quality = 0.8772 (Delta: -0.0425)

### `Q17_HYBRID_MULTI_TERM_3`: "asynchronous worker pool filesystem discovery events"
- **Category**: hybrid_multi_term
- **Fast Top-1 (RRF)**: `doc2_multicolumn.pdf` (RRF Score: 0.032787)
- **Quality Top-1 (Cross-Encoder)**: `doc2_multicolumn.pdf` (Rerank Score: 0.998766)
- **NDCG@10**: Fast = 1.0000 -> Quality = 1.0000 (Delta: +0.0000)

### `Q18_MULTI_CHUNK_RELEVANCE`: "FileMind architecture overview and subsystems"
- **Category**: multi_chunk
- **Fast Top-1 (RRF)**: `sample_architecture.md` (RRF Score: 0.016393)
- **Quality Top-1 (Cross-Encoder)**: `sample_architecture.md` (Rerank Score: 0.991772)
- **NDCG@10**: Fast = 0.5173 -> Quality = 0.6338 (Delta: +0.1165)

### `Q19_TABLE_CONTENT`: "Quarterly benchmark results discovery and watcher latency"
- **Category**: table_content
- **Fast Top-1 (RRF)**: `doc7_table_deck.pptx` (RRF Score: 0.016393)
- **Quality Top-1 (Cross-Encoder)**: `sample_metrics.xlsx` (Rerank Score: 0.87031)
- **NDCG@10**: Fast = 0.3318 -> Quality = 0.8408 (Delta: +0.5090)

### `Q20_NATURAL_LANGUAGE_1`: "What is the key rotation interval for Tier-1 TLS 1.3 protocol?"
- **Category**: natural_language
- **Fast Top-1 (RRF)**: `doc1_enterprise_spec.pdf` (RRF Score: 0.016393)
- **Quality Top-1 (Cross-Encoder)**: `doc1_enterprise_spec.pdf` (Rerank Score: 0.995879)
- **NDCG@10**: Fast = 1.0000 -> Quality = 1.0000 (Delta: +0.0000)

### `Q21_NATURAL_LANGUAGE_2`: "Which database tables store watcher events and indexing jobs?"
- **Category**: natural_language
- **Fast Top-1 (RRF)**: `sample_system_spec.docx` (RRF Score: 0.016393)
- **Quality Top-1 (Cross-Encoder)**: `sample_system_spec.docx` (Rerank Score: 0.918972)
- **NDCG@10**: Fast = 1.0000 -> Quality = 1.0000 (Delta: +0.0000)

### `Q23_AMBIGUOUS_QUERY`: "performance benchmarks"
- **Category**: ambiguous
- **Fast Top-1 (RRF)**: `sample_architecture.md` (RRF Score: 0.016393)
- **Quality Top-1 (Cross-Encoder)**: `sample_architecture.md` (Rerank Score: 0.993889)
- **NDCG@10**: Fast = 0.9505 -> Quality = 0.9831 (Delta: +0.0326)

### `Q24_METADATA_FILTER_H1`: "Data Integrity Protocols immutable provenance"
- **Category**: metadata_heading
- **Fast Top-1 (RRF)**: `sample_system_spec.pdf` (RRF Score: 0.032787)
- **Quality Top-1 (Cross-Encoder)**: `sample_system_spec.pdf` (Rerank Score: 0.996997)
- **NDCG@10**: Fast = 1.0000 -> Quality = 1.0000 (Delta: +0.0000)

### `Q25_HEADCOUNT_QUERY`: "Engineering department headcount"
- **Category**: table_content
- **Fast Top-1 (RRF)**: `doc11_sheets.xlsx` (RRF Score: 0.016393)
- **Quality Top-1 (Cross-Encoder)**: `doc11_sheets.xlsx` (Rerank Score: 0.937216)
- **NDCG@10**: Fast = 1.0000 -> Quality = 0.6309 (Delta: -0.3691)

