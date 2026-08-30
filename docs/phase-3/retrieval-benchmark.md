# Phase 3 Retrieval Benchmark Report

## 1. Executive Summary & Comparison

| Retrieval Mode | Recall@5 | Recall@10 | MRR | NDCG@10 | Median Latency (ms) | Latency Range (ms) |
|---|---|---|---|---|---|---|
| **BM25** | 0.4933 | 0.4933 | 0.5600 | 0.5090 | 0.13 ms | 0.04 – 0.81 ms |
| **DENSE** | 0.8613 | 0.9113 | 0.8393 | 0.8263 | 15.65 ms | 14.24 – 19.17 ms |
| **HYBRID** | 0.9153 | 0.9733 | 0.9433 | 0.9356 | 17.04 ms | 15.09 – 23.04 ms |

---

## 2. Stage Latency Breakdown (Hybrid Mode)

| Stage | Description | Median Latency (ms) |
|---|---|---|
| `normalization` | Stage execution | 0.046 ms |
| `lexical_search` | Stage execution | 0.267 ms |
| `query_embedding` | Stage execution | 14.347 ms |
| `dense_search` | Stage execution | 2.159 ms |
| `rrf_fusion` | Stage execution | 0.135 ms |
| `total_request` | Stage execution | 17.101 ms |

---

## 3. RRF Tuning ($k \in \{20, 40, 60, 100\}$)

| $k$ Constant | Recall@5 | Recall@10 | MRR | NDCG@10 |
|---|---|---|---|---|
| $k=20$ | 0.9153 | 0.9733 | 0.9433 | 0.9356 |
| $k=40$ | 0.9153 | 0.9733 | 0.9433 | 0.9356 |
| $k=60$ | 0.9153 | 0.9733 | 0.9433 | 0.9356 |
| $k=100$ | 0.9153 | 0.9733 | 0.9433 | 0.9356 |

---

## 4. Query-by-Query Retrieval Results (Hybrid Mode)

| Query ID | Category | Recall@5 | Recall@10 | MRR | NDCG@10 | Median Lat (ms) | Top-1 File |
|---|---|---|---|---|---|---|---|
| `Q01_EXACT_FILENAME` | `exact_filename` | 0.8 | 1.0 | 1.0 | 0.9709 | 17.53 | `sample_system_spec.pdf` |
| `Q02_EXACT_PHRASE` | `exact_phrase` | 1.0 | 1.0 | 1.0 | 1.0 | 20.19 | `doc1_enterprise_spec.pdf` |
| `Q03_EXACT_PHRASE_STORAGE` | `exact_phrase` | 1.0 | 1.0 | 1.0 | 0.9514 | 18.43 | `sample_system_spec.pdf` |
| `Q04_KEYWORD_IDENTIFIER` | `identifier` | 1.0 | 1.0 | 1.0 | 1.0 | 18.75 | `sample_system_spec.docx` |
| `Q05_CODE_SNIPPET` | `code` | 1.0 | 1.0 | 1.0 | 1.0 | 17.10 | `sample_architecture.md` |
| `Q06_TECHNICAL_ACRONYM` | `acronym` | 1.0 | 1.0 | 1.0 | 1.0 | 16.27 | `doc1_enterprise_spec.pdf` |
| `Q07_TECHNICAL_TERM` | `technical_term` | 1.0 | 1.0 | 1.0 | 1.0 | 17.69 | `sample_architecture.md` |
| `Q08_CODE_IDENTIFIER` | `identifier` | 1.0 | 1.0 | 1.0 | 1.0 | 16.03 | `sample_coordinator.py` |
| `Q09_PARTIAL_TERM` | `partial_term` | 1.0 | 1.0 | 1.0 | 1.0 | 18.32 | `sample_architecture.md` |
| `Q10_SEMANTIC_CONCEPT_1` | `semantic_concept` | 0.6667 | 0.6667 | 1.0 | 0.7959 | 17.40 | `sample_system_spec.pdf` |
| `Q11_SEMANTIC_CONCEPT_2` | `semantic_concept` | 1.0 | 1.0 | 1.0 | 1.0 | 16.06 | `doc1_enterprise_spec.pdf` |
| `Q12_SEMANTIC_CONCEPT_3` | `semantic_concept` | 1.0 | 1.0 | 1.0 | 1.0 | 16.85 | `doc5_bullets.docx` |
| `Q13_SEMANTIC_CONCEPT_4` | `semantic_concept` | 1.0 | 1.0 | 1.0 | 1.0 | 16.75 | `doc11_sheets.xlsx` |
| `Q14_SEMANTIC_CONCEPT_5` | `semantic_concept` | 1.0 | 1.0 | 1.0 | 1.0 | 15.82 | `doc4_nested_ops.docx` |
| `Q15_HYBRID_MULTI_TERM_1` | `hybrid_multi_term` | 1.0 | 1.0 | 1.0 | 0.9514 | 17.51 | `sample_architecture.md` |
| `Q16_HYBRID_MULTI_TERM_2` | `hybrid_multi_term` | 1.0 | 1.0 | 1.0 | 0.9197 | 17.46 | `sample_metrics.csv` |
| `Q17_HYBRID_MULTI_TERM_3` | `hybrid_multi_term` | 1.0 | 1.0 | 1.0 | 1.0 | 16.05 | `doc2_multicolumn.pdf` |
| `Q18_MULTI_CHUNK_RELEVANCE` | `multi_chunk` | 0.3333 | 1.0 | 0.25 | 0.5173 | 18.89 | `sample_architecture.md` |
| `Q19_TABLE_CONTENT` | `table_content` | 0.3333 | 0.6667 | 0.3333 | 0.3318 | 16.59 | `doc7_table_deck.pptx` |
| `Q20_NATURAL_LANGUAGE_1` | `natural_language` | 1.0 | 1.0 | 1.0 | 1.0 | 16.82 | `doc1_enterprise_spec.pdf` |
| `Q21_NATURAL_LANGUAGE_2` | `natural_language` | 1.0 | 1.0 | 1.0 | 1.0 | 17.27 | `sample_system_spec.docx` |
| `Q22_SINGLE_HIGH_RELEVANCE` | `single_chunk` | 1.0 | 1.0 | 1.0 | 1.0 | 16.21 | `sample_coordinator.py` |
| `Q23_AMBIGUOUS_QUERY` | `ambiguous` | 0.75 | 1.0 | 1.0 | 0.9505 | 15.53 | `sample_architecture.md` |
| `Q24_METADATA_FILTER_H1` | `metadata_heading` | 1.0 | 1.0 | 1.0 | 1.0 | 17.54 | `sample_system_spec.pdf` |
| `Q25_HEADCOUNT_QUERY` | `table_content` | 1.0 | 1.0 | 1.0 | 1.0 | 15.58 | `doc11_sheets.xlsx` |
