# Phase 3 Retrieval Benchmark Report

## 1. Executive Summary & Comparison

| Retrieval Mode | Recall@5 | Recall@10 | MRR | NDCG@10 | Median Latency (ms) | Latency Range (ms) |
|---|---|---|---|---|---|---|
| **BM25** | 0.4933 | 0.4933 | 0.5600 | 0.5090 | 0.18 ms | 0.05 – 2.71 ms |
| **DENSE** | 0.8613 | 0.9113 | 0.8393 | 0.8263 | 19.02 ms | 16.71 – 25.59 ms |
| **HYBRID** | 0.9153 | 0.9733 | 0.9433 | 0.9356 | 20.34 ms | 17.98 – 47.12 ms |

---

## 2. Stage Latency Breakdown (Hybrid Mode)

| Stage | Description | Median Latency (ms) |
|---|---|---|
| `normalization` | Stage execution | 0.051 ms |
| `lexical_search` | Stage execution | 0.303 ms |
| `query_embedding` | Stage execution | 17.104 ms |
| `dense_search` | Stage execution | 2.580 ms |
| `rrf_fusion` | Stage execution | 0.157 ms |
| `total_request` | Stage execution | 20.315 ms |

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
| `Q01_EXACT_FILENAME` | `exact_filename` | 0.8 | 1.0 | 1.0 | 0.9709 | 20.16 | `sample_system_spec.pdf` |
| `Q02_EXACT_PHRASE` | `exact_phrase` | 1.0 | 1.0 | 1.0 | 1.0 | 21.19 | `doc1_enterprise_spec.pdf` |
| `Q03_EXACT_PHRASE_STORAGE` | `exact_phrase` | 1.0 | 1.0 | 1.0 | 0.9514 | 20.40 | `sample_system_spec.pdf` |
| `Q04_KEYWORD_IDENTIFIER` | `identifier` | 1.0 | 1.0 | 1.0 | 1.0 | 19.47 | `sample_system_spec.docx` |
| `Q05_CODE_SNIPPET` | `code` | 1.0 | 1.0 | 1.0 | 1.0 | 19.52 | `sample_architecture.md` |
| `Q06_TECHNICAL_ACRONYM` | `acronym` | 1.0 | 1.0 | 1.0 | 1.0 | 20.55 | `doc1_enterprise_spec.pdf` |
| `Q07_TECHNICAL_TERM` | `technical_term` | 1.0 | 1.0 | 1.0 | 1.0 | 21.56 | `sample_architecture.md` |
| `Q08_CODE_IDENTIFIER` | `identifier` | 1.0 | 1.0 | 1.0 | 1.0 | 19.13 | `sample_coordinator.py` |
| `Q09_PARTIAL_TERM` | `partial_term` | 1.0 | 1.0 | 1.0 | 1.0 | 20.20 | `sample_architecture.md` |
| `Q10_SEMANTIC_CONCEPT_1` | `semantic_concept` | 0.6667 | 0.6667 | 1.0 | 0.7959 | 19.90 | `sample_system_spec.pdf` |
| `Q11_SEMANTIC_CONCEPT_2` | `semantic_concept` | 1.0 | 1.0 | 1.0 | 1.0 | 21.88 | `doc1_enterprise_spec.pdf` |
| `Q12_SEMANTIC_CONCEPT_3` | `semantic_concept` | 1.0 | 1.0 | 1.0 | 1.0 | 20.82 | `doc5_bullets.docx` |
| `Q13_SEMANTIC_CONCEPT_4` | `semantic_concept` | 1.0 | 1.0 | 1.0 | 1.0 | 20.32 | `doc11_sheets.xlsx` |
| `Q14_SEMANTIC_CONCEPT_5` | `semantic_concept` | 1.0 | 1.0 | 1.0 | 1.0 | 20.21 | `doc4_nested_ops.docx` |
| `Q15_HYBRID_MULTI_TERM_1` | `hybrid_multi_term` | 1.0 | 1.0 | 1.0 | 0.9514 | 20.68 | `sample_architecture.md` |
| `Q16_HYBRID_MULTI_TERM_2` | `hybrid_multi_term` | 1.0 | 1.0 | 1.0 | 0.9197 | 19.74 | `sample_metrics.csv` |
| `Q17_HYBRID_MULTI_TERM_3` | `hybrid_multi_term` | 1.0 | 1.0 | 1.0 | 1.0 | 20.94 | `doc2_multicolumn.pdf` |
| `Q18_MULTI_CHUNK_RELEVANCE` | `multi_chunk` | 0.3333 | 1.0 | 0.25 | 0.5173 | 19.29 | `sample_architecture.md` |
| `Q19_TABLE_CONTENT` | `table_content` | 0.3333 | 0.6667 | 0.3333 | 0.3318 | 20.11 | `doc7_table_deck.pptx` |
| `Q20_NATURAL_LANGUAGE_1` | `natural_language` | 1.0 | 1.0 | 1.0 | 1.0 | 20.42 | `doc1_enterprise_spec.pdf` |
| `Q21_NATURAL_LANGUAGE_2` | `natural_language` | 1.0 | 1.0 | 1.0 | 1.0 | 18.90 | `sample_system_spec.docx` |
| `Q22_SINGLE_HIGH_RELEVANCE` | `single_chunk` | 1.0 | 1.0 | 1.0 | 1.0 | 20.40 | `sample_coordinator.py` |
| `Q23_AMBIGUOUS_QUERY` | `ambiguous` | 0.75 | 1.0 | 1.0 | 0.9505 | 20.63 | `sample_architecture.md` |
| `Q24_METADATA_FILTER_H1` | `metadata_heading` | 1.0 | 1.0 | 1.0 | 1.0 | 21.01 | `sample_system_spec.pdf` |
| `Q25_HEADCOUNT_QUERY` | `table_content` | 1.0 | 1.0 | 1.0 | 1.0 | 20.00 | `doc11_sheets.xlsx` |
