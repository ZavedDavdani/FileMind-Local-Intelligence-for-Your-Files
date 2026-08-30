# Phase 3 Evaluation Dataset & Ground Truth Specification

- **Dataset Version**: `phase3-eval-v1.0`
- **Corpus Version**: `phase3-benchmark-corpus-v1`
- **Total Benchmark Queries**: `28`
- **Corpus Scale**: 20 files, 54 chunks, 219851 bytes

---

## 1. Metric Definitions & Formulas

### Recall@K
$$\text{Recall@K} = \frac{\sum_{q \in Q} \frac{|\text{Retrieved}_K(q) \cap \text{Relevant}(q)|}{|\text{Relevant}(q)|}}{|Q|}$$

### Mean Reciprocal Rank (MRR)
$$\text{MRR} = \frac{1}{|Q|} \sum_{i=1}^{|Q|} \frac{1}{\text{rank}_i}$$
where $\text{rank}_i$ is the 1-indexed position of the first relevant chunk ($rel \ge 1$). If no relevant chunk is in Top-K, reciprocal rank is $0$.

### Normalized Discounted Cumulative Gain (NDCG@K)
$$\text{DCG@K} = \sum_{i=1}^{K} \frac{2^{rel_i} - 1}{\log_2(i + 1)}, \quad \text{NDCG@K} = \frac{\text{DCG@K}}{\text{IDCG@K}}$$
where $rel_i \in \{0, 1, 2\}$ is the graded relevance level.

---

## 2. Benchmark Query Registry

| ID | Query Text | Category | Advantage | Expected Files | Target Chunks |
|---|---|---|---|---|---|
| `Q01_EXACT_FILENAME` | "sample_system_spec.pdf" | `exact_filename` | `lexical` | sample_system_spec.pdf | 5 chunks |
| `Q02_EXACT_PHRASE` | "Cryptographic hashing with streaming SHA-256 validation" | `exact_phrase` | `lexical` | doc1_enterprise_spec.pdf | 1 chunks |
| `Q03_EXACT_PHRASE_STORAGE` | "Write-Ahead Logging (WAL) mode enabled for high-concurrency" | `exact_phrase` | `lexical` | sample_system_spec.pdf, sample_system_spec.docx | 2 chunks |
| `Q04_KEYWORD_IDENTIFIER` | "file_events" | `identifier` | `lexical` | sample_system_spec.docx | 1 chunks |
| `Q05_CODE_SNIPPET` | "def get_config():" | `code` | `lexical` | sample_architecture.md | 1 chunks |
| `Q06_TECHNICAL_ACRONYM` | "mTLS" | `acronym` | `lexical` | doc1_enterprise_spec.pdf | 1 chunks |
| `Q07_TECHNICAL_TERM` | "integrity_mode NORMAL debounce_ms" | `technical_term` | `lexical` | sample_architecture.md | 1 chunks |
| `Q08_CODE_IDENTIFIER` | "EngineCoordinator" | `identifier` | `lexical` | sample_coordinator.py | 4 chunks |
| `Q09_PARTIAL_TERM` | "debounc" | `partial_term` | `lexical` | sample_system_spec.pdf, sample_architecture.md | 2 chunks |
| `Q10_SEMANTIC_CONCEPT_1` | "how does the system guarantee fast crash recovery and restart" | `semantic_concept` | `dense` | sample_system_spec.pdf, sample_architecture.md, sample_metrics.csv | 3 chunks |
| `Q11_SEMANTIC_CONCEPT_2` | "data retention schedule for cold audit records and compliance" | `semantic_concept` | `dense` | doc1_enterprise_spec.pdf | 1 chunks |
| `Q12_SEMANTIC_CONCEPT_3` | "preventing dangling or orphan processes from staying alive" | `semantic_concept` | `dense` | doc5_bullets.docx | 1 chunks |
| `Q13_SEMANTIC_CONCEPT_4` | "quarterly business revenue and financial profit margins" | `semantic_concept` | `dense` | doc11_sheets.xlsx | 1 chunks |
| `Q14_SEMANTIC_CONCEPT_5` | "hardware memory limits for background compute workers" | `semantic_concept` | `dense` | doc4_nested_ops.docx | 1 chunks |
| `Q15_HYBRID_MULTI_TERM_1` | "SQLite WAL persistence and change detection" | `hybrid_multi_term` | `hybrid` | sample_architecture.md, sample_system_spec.pdf, sample_system_spec.docx | 3 chunks |
| `Q16_HYBRID_MULTI_TERM_2` | "discovery rate throughput target 500 files/s" | `hybrid_multi_term` | `hybrid` | sample_metrics.csv, sample_metrics.xlsx | 2 chunks |
| `Q17_HYBRID_MULTI_TERM_3` | "asynchronous worker pool filesystem discovery events" | `hybrid_multi_term` | `hybrid` | doc2_multicolumn.pdf | 1 chunks |
| `Q18_MULTI_CHUNK_RELEVANCE` | "FileMind architecture overview and subsystems" | `multi_chunk` | `hybrid` | sample_presentation.pptx, sample_architecture.md, sample_system_spec.pdf | 3 chunks |
| `Q19_TABLE_CONTENT` | "Quarterly benchmark results discovery and watcher latency" | `table_content` | `hybrid` | sample_metrics.xlsx, sample_metrics.csv | 3 chunks |
| `Q20_NATURAL_LANGUAGE_1` | "What is the key rotation interval for Tier-1 TLS 1.3 protocol?" | `natural_language` | `hybrid` | doc1_enterprise_spec.pdf | 1 chunks |
| `Q21_NATURAL_LANGUAGE_2` | "Which database tables store watcher events and indexing jobs?" | `natural_language` | `hybrid` | sample_system_spec.docx | 1 chunks |
| `Q22_SINGLE_HIGH_RELEVANCE` | "def execute_task(self, task_id: str)" | `single_chunk` | `lexical` | sample_coordinator.py | 1 chunks |
| `Q23_AMBIGUOUS_QUERY` | "performance benchmarks" | `ambiguous` | `hybrid` | sample_architecture.md, sample_metrics.xlsx, doc12_metrics.csv | 4 chunks |
| `Q24_METADATA_FILTER_H1` | "Data Integrity Protocols immutable provenance" | `metadata_heading` | `hybrid` | sample_system_spec.pdf | 1 chunks |
| `Q25_HEADCOUNT_QUERY` | "Engineering department headcount" | `table_content` | `hybrid` | doc11_sheets.xlsx | 1 chunks |
| `Q26_NEGATIVE_NO_MATCH_1` | "quantum entanglement topological superconducting qubit" | `negative` | `none` | None (Negative) | 0 chunks |
| `Q27_NEGATIVE_NO_MATCH_2` | "kubernetes helm chart deployment yaml aws ingress controller" | `negative` | `none` | None (Negative) | 0 chunks |
| `Q28_NEGATIVE_NO_MATCH_3` | "blockchain smart contract solana validator consensus" | `negative` | `none` | None (Negative) | 0 chunks |

---

## 3. Query Details & Relevance Annotations

### `Q01_EXACT_FILENAME`: "sample_system_spec.pdf"
- **Category**: `exact_filename`
- **Expected Advantage**: `lexical`
- **Description**: Exact match for document filename; lexical retrieval should rank all chunks of sample_system_spec.pdf highest.
- **Expected Target Files**: `['sample_system_spec.pdf']`
- **Expected Chunk IDs**: `['chk_a1aeee09a27bab2f', 'chk_17e8d89d65770d17', 'chk_605a72e3901ce2a0', 'chk_6c8f4cc4696197d3', 'chk_f345fe7b5624b925']`
- **Graded Relevance**: `{'chk_a1aeee09a27bab2f': 2, 'chk_17e8d89d65770d17': 2, 'chk_605a72e3901ce2a0': 2, 'chk_6c8f4cc4696197d3': 2, 'chk_f345fe7b5624b925': 2}`

### `Q02_EXACT_PHRASE`: "Cryptographic hashing with streaming SHA-256 validation"
- **Category**: `exact_phrase`
- **Expected Advantage**: `lexical`
- **Description**: Exact phrase from Security Subsystem Hierarchy in doc1_enterprise_spec.pdf.
- **Expected Target Files**: `['doc1_enterprise_spec.pdf']`
- **Expected Chunk IDs**: `['chk_7bf48a114ba7e4ca']`
- **Graded Relevance**: `{'chk_7bf48a114ba7e4ca': 2}`

### `Q03_EXACT_PHRASE_STORAGE`: "Write-Ahead Logging (WAL) mode enabled for high-concurrency"
- **Category**: `exact_phrase`
- **Expected Advantage**: `lexical`
- **Description**: Exact phrase detailing SQLite WAL persistence in system specifications.
- **Expected Target Files**: `['sample_system_spec.pdf', 'sample_system_spec.docx']`
- **Expected Chunk IDs**: `['chk_6c8f4cc4696197d3', 'chk_7f8f007544dfc303']`
- **Graded Relevance**: `{'chk_6c8f4cc4696197d3': 2, 'chk_7f8f007544dfc303': 2, 'chk_2c6e3318d1e28dc2': 1}`

### `Q04_KEYWORD_IDENTIFIER`: "file_events"
- **Category**: `identifier`
- **Expected Advantage**: `lexical`
- **Description**: Specific internal SQLite table identifier for filesystem event audit trail.
- **Expected Target Files**: `['sample_system_spec.docx']`
- **Expected Chunk IDs**: `['chk_0fd53323a9bd011f']`
- **Graded Relevance**: `{'chk_0fd53323a9bd011f': 2}`

### `Q05_CODE_SNIPPET`: "def get_config():"
- **Category**: `code`
- **Expected Advantage**: `lexical`
- **Description**: Code definition in markdown architecture specification.
- **Expected Target Files**: `['sample_architecture.md']`
- **Expected Chunk IDs**: `['chk_072e2e2de283bacf']`
- **Graded Relevance**: `{'chk_072e2e2de283bacf': 2}`

### `Q06_TECHNICAL_ACRONYM`: "mTLS"
- **Category**: `acronym`
- **Expected Advantage**: `lexical`
- **Description**: Technical acronym for mutual TLS protocol in security spec.
- **Expected Target Files**: `['doc1_enterprise_spec.pdf']`
- **Expected Chunk IDs**: `['chk_7bf48a114ba7e4ca']`
- **Graded Relevance**: `{'chk_7bf48a114ba7e4ca': 2}`

### `Q07_TECHNICAL_TERM`: "integrity_mode NORMAL debounce_ms"
- **Category**: `technical_term`
- **Expected Advantage**: `lexical`
- **Description**: Configuration parameter names in architecture specification.
- **Expected Target Files**: `['sample_architecture.md']`
- **Expected Chunk IDs**: `['chk_072e2e2de283bacf']`
- **Graded Relevance**: `{'chk_072e2e2de283bacf': 2}`

### `Q08_CODE_IDENTIFIER`: "EngineCoordinator"
- **Category**: `identifier`
- **Expected Advantage**: `lexical`
- **Description**: Python class name for the background engine coordinator.
- **Expected Target Files**: `['sample_coordinator.py']`
- **Expected Chunk IDs**: `['chk_b34f24984372a069', 'chk_132b6278997535a1', 'chk_2812a646335337b6', 'chk_b28f9ad41ade2729']`
- **Graded Relevance**: `{'chk_b34f24984372a069': 2, 'chk_132b6278997535a1': 2, 'chk_2812a646335337b6': 2, 'chk_b28f9ad41ade2729': 2}`

### `Q09_PARTIAL_TERM`: "debounc"
- **Category**: `partial_term`
- **Expected Advantage**: `lexical`
- **Description**: Stemmed partial term for debounce logic.
- **Expected Target Files**: `['sample_system_spec.pdf', 'sample_architecture.md']`
- **Expected Chunk IDs**: `['chk_605a72e3901ce2a0', 'chk_072e2e2de283bacf']`
- **Graded Relevance**: `{'chk_605a72e3901ce2a0': 2, 'chk_072e2e2de283bacf': 2}`

### `Q10_SEMANTIC_CONCEPT_1`: "how does the system guarantee fast crash recovery and restart"
- **Category**: `semantic_concept`
- **Expected Advantage**: `dense`
- **Description**: Semantic query describing crash resilience and recovery targets.
- **Expected Target Files**: `['sample_system_spec.pdf', 'sample_architecture.md', 'sample_metrics.csv']`
- **Expected Chunk IDs**: `['chk_605a72e3901ce2a0', 'chk_631b00d85a53ecd5', 'chk_6ccc18c68a18a3d0']`
- **Graded Relevance**: `{'chk_605a72e3901ce2a0': 2, 'chk_631b00d85a53ecd5': 2, 'chk_6ccc18c68a18a3d0': 1}`

### `Q11_SEMANTIC_CONCEPT_2`: "data retention schedule for cold audit records and compliance"
- **Category**: `semantic_concept`
- **Expected Advantage**: `dense`
- **Description**: Semantic conceptual query for compliance archival lifecycle.
- **Expected Target Files**: `['doc1_enterprise_spec.pdf']`
- **Expected Chunk IDs**: `['chk_e138fd81d0cc1b59']`
- **Graded Relevance**: `{'chk_e138fd81d0cc1b59': 2}`

### `Q12_SEMANTIC_CONCEPT_3`: "preventing dangling or orphan processes from staying alive"
- **Category**: `semantic_concept`
- **Expected Advantage**: `dense`
- **Description**: Semantic query about child-process cleanup.
- **Expected Target Files**: `['doc5_bullets.docx']`
- **Expected Chunk IDs**: `['chk_86ac22b7c079cf1c']`
- **Graded Relevance**: `{'chk_86ac22b7c079cf1c': 2}`

### `Q13_SEMANTIC_CONCEPT_4`: "quarterly business revenue and financial profit margins"
- **Category**: `semantic_concept`
- **Expected Advantage**: `dense`
- **Description**: Semantic retrieval of financial spreadsheet table.
- **Expected Target Files**: `['doc11_sheets.xlsx']`
- **Expected Chunk IDs**: `['chk_11d95f31b9155dac']`
- **Graded Relevance**: `{'chk_11d95f31b9155dac': 2}`

### `Q14_SEMANTIC_CONCEPT_5`: "hardware memory limits for background compute workers"
- **Category**: `semantic_concept`
- **Expected Advantage**: `dense`
- **Description**: Semantic retrieval of worker RAM capacity limit.
- **Expected Target Files**: `['doc4_nested_ops.docx']`
- **Expected Chunk IDs**: `['chk_ac10fe9dbc1e49db']`
- **Graded Relevance**: `{'chk_ac10fe9dbc1e49db': 2}`

### `Q15_HYBRID_MULTI_TERM_1`: "SQLite WAL persistence and change detection"
- **Category**: `hybrid_multi_term`
- **Expected Advantage**: `hybrid`
- **Description**: Multi-term query benefiting from both lexical precision on WAL/SQLite and dense concept relevance.
- **Expected Target Files**: `['sample_architecture.md', 'sample_system_spec.pdf', 'sample_system_spec.docx']`
- **Expected Chunk IDs**: `['chk_75ba49ac19ff5b1d', 'chk_6c8f4cc4696197d3', 'chk_7f8f007544dfc303']`
- **Graded Relevance**: `{'chk_75ba49ac19ff5b1d': 2, 'chk_6c8f4cc4696197d3': 2, 'chk_7f8f007544dfc303': 1}`

### `Q16_HYBRID_MULTI_TERM_2`: "discovery rate throughput target 500 files/s"
- **Category**: `hybrid_multi_term`
- **Expected Advantage**: `hybrid`
- **Description**: Multi-term benchmark target matching across CSV and XLSX tables.
- **Expected Target Files**: `['sample_metrics.csv', 'sample_metrics.xlsx']`
- **Expected Chunk IDs**: `['chk_6ccc18c68a18a3d0', 'chk_489448ae4328db31']`
- **Graded Relevance**: `{'chk_6ccc18c68a18a3d0': 2, 'chk_489448ae4328db31': 2}`

### `Q17_HYBRID_MULTI_TERM_3`: "asynchronous worker pool filesystem discovery events"
- **Category**: `hybrid_multi_term`
- **Expected Advantage**: `hybrid`
- **Description**: Multi-term whitepaper section retrieval.
- **Expected Target Files**: `['doc2_multicolumn.pdf']`
- **Expected Chunk IDs**: `['chk_7f4c75db248aa141']`
- **Graded Relevance**: `{'chk_7f4c75db248aa141': 2}`

### `Q18_MULTI_CHUNK_RELEVANCE`: "FileMind architecture overview and subsystems"
- **Category**: `multi_chunk`
- **Expected Advantage**: `hybrid`
- **Description**: Broad architectural topic with multiple highly relevant chunks across presentation, markdown, and PDF.
- **Expected Target Files**: `['sample_presentation.pptx', 'sample_architecture.md', 'sample_system_spec.pdf']`
- **Expected Chunk IDs**: `['chk_7fd49b2bdbf4c628', 'chk_75ba49ac19ff5b1d', 'chk_17e8d89d65770d17']`
- **Graded Relevance**: `{'chk_7fd49b2bdbf4c628': 2, 'chk_75ba49ac19ff5b1d': 2, 'chk_17e8d89d65770d17': 2}`

### `Q19_TABLE_CONTENT`: "Quarterly benchmark results discovery and watcher latency"
- **Category**: `table_content`
- **Expected Advantage**: `hybrid`
- **Description**: Retrieval of tabular benchmark performance data.
- **Expected Target Files**: `['sample_metrics.xlsx', 'sample_metrics.csv']`
- **Expected Chunk IDs**: `['chk_a942b79d5ffb353f', 'chk_489448ae4328db31', 'chk_6ccc18c68a18a3d0']`
- **Graded Relevance**: `{'chk_a942b79d5ffb353f': 2, 'chk_489448ae4328db31': 2, 'chk_6ccc18c68a18a3d0': 1}`

### `Q20_NATURAL_LANGUAGE_1`: "What is the key rotation interval for Tier-1 TLS 1.3 protocol?"
- **Category**: `natural_language`
- **Expected Advantage**: `hybrid`
- **Description**: Natural language question seeking a specific table value (90 Days) in security spec.
- **Expected Target Files**: `['doc1_enterprise_spec.pdf']`
- **Expected Chunk IDs**: `['chk_7bf48a114ba7e4ca']`
- **Graded Relevance**: `{'chk_7bf48a114ba7e4ca': 2}`

### `Q21_NATURAL_LANGUAGE_2`: "Which database tables store watcher events and indexing jobs?"
- **Category**: `natural_language`
- **Expected Advantage**: `hybrid`
- **Description**: Natural language inquiry mapping to component layer table in DOCX.
- **Expected Target Files**: `['sample_system_spec.docx']`
- **Expected Chunk IDs**: `['chk_0fd53323a9bd011f']`
- **Graded Relevance**: `{'chk_0fd53323a9bd011f': 2}`

### `Q22_SINGLE_HIGH_RELEVANCE`: "def execute_task(self, task_id: str)"
- **Category**: `single_chunk`
- **Expected Advantage**: `lexical`
- **Description**: Exact method signature lookup with exactly one matching chunk.
- **Expected Target Files**: `['sample_coordinator.py']`
- **Expected Chunk IDs**: `['chk_b28f9ad41ade2729']`
- **Graded Relevance**: `{'chk_b28f9ad41ade2729': 2}`

### `Q23_AMBIGUOUS_QUERY`: "performance benchmarks"
- **Category**: `ambiguous`
- **Expected Advantage**: `hybrid`
- **Description**: Short ambiguous query matching across multiple document formats.
- **Expected Target Files**: `['sample_architecture.md', 'sample_metrics.xlsx', 'doc12_metrics.csv']`
- **Expected Chunk IDs**: `['chk_b187539fc8bcb4ac', 'chk_a942b79d5ffb353f', 'chk_489448ae4328db31', 'chk_1fb728b134565854']`
- **Graded Relevance**: `{'chk_b187539fc8bcb4ac': 2, 'chk_a942b79d5ffb353f': 2, 'chk_489448ae4328db31': 2, 'chk_1fb728b134565854': 1}`

### `Q24_METADATA_FILTER_H1`: "Data Integrity Protocols immutable provenance"
- **Category**: `metadata_heading`
- **Expected Advantage**: `hybrid`
- **Description**: Heading and section provenance query in PDF.
- **Expected Target Files**: `['sample_system_spec.pdf']`
- **Expected Chunk IDs**: `['chk_f345fe7b5624b925']`
- **Graded Relevance**: `{'chk_f345fe7b5624b925': 2}`

### `Q25_HEADCOUNT_QUERY`: "Engineering department headcount"
- **Category**: `table_content`
- **Expected Advantage**: `hybrid`
- **Description**: Specific department headcount query matching table row in Excel workbook.
- **Expected Target Files**: `['doc11_sheets.xlsx']`
- **Expected Chunk IDs**: `['chk_03ebc371aed08760']`
- **Graded Relevance**: `{'chk_03ebc371aed08760': 2}`

### `Q26_NEGATIVE_NO_MATCH_1`: "quantum entanglement topological superconducting qubit"
- **Category**: `negative`
- **Expected Advantage**: `none`
- **Description**: Negative query: No quantum computing documents exist in the corpus.
- **Expected Target Files**: `[]`
- **Expected Chunk IDs**: `[]`
- **Graded Relevance**: `{}`

### `Q27_NEGATIVE_NO_MATCH_2`: "kubernetes helm chart deployment yaml aws ingress controller"
- **Category**: `negative`
- **Expected Advantage**: `none`
- **Description**: Negative query: No cloud/Kubernetes deployment artifacts exist in the corpus.
- **Expected Target Files**: `[]`
- **Expected Chunk IDs**: `[]`
- **Graded Relevance**: `{}`

### `Q28_NEGATIVE_NO_MATCH_3`: "blockchain smart contract solana validator consensus"
- **Category**: `negative`
- **Expected Advantage**: `none`
- **Description**: Negative query: No crypto/blockchain materials exist in the corpus.
- **Expected Target Files**: `[]`
- **Expected Chunk IDs**: `[]`
- **Graded Relevance**: `{}`

