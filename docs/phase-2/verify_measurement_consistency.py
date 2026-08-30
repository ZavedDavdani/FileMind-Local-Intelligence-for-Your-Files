"""Programmatic measurement consistency verifier for Phase 2."""

import json
import os
import re
import sys


def verify_phase2_consistency():
    json_path = os.path.join(os.path.dirname(__file__), "measurements.json")
    md_path = os.path.join(os.path.dirname(__file__), "validation-report.md")

    if not os.path.exists(json_path):
        print(f"ERROR: {json_path} not found.")
        sys.exit(1)

    if not os.path.exists(md_path):
        print(f"ERROR: {md_path} not found.")
        sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    m = data["metrics"]
    meta = data["metadata"]

    checks = [
        ("PDF Parse Median", f"{m['pdf_parse_latency_ms']['median']}"),
        ("PDF Parse Min", f"{m['pdf_parse_latency_ms']['min']}"),
        ("PDF Parse Max", f"{m['pdf_parse_latency_ms']['max']}"),
        ("DOCX Parse Median", f"{m['docx_parse_latency_ms']['median']}"),
        ("PPTX Parse Median", f"{m['pptx_parse_latency_ms']['median']}"),
        ("Markdown Parse Median", f"{m['markdown_parse_latency_ms']['median']}"),
        ("XLSX Parse Median", f"{m['xlsx_parse_latency_ms']['median']}"),
        ("Hierarchical Chunking Median", f"{m['hierarchical_chunking_latency_ms']['median']}"),
        ("Hierarchical Chunking Min", f"{m['hierarchical_chunking_latency_ms']['min']}"),
        ("Hierarchical Chunking Max", f"{m['hierarchical_chunking_latency_ms']['max']}"),
        ("E2E Throughput Median", f"{m['end_to_end_document_processing_throughput_docs_per_sec']['median']}"),
        ("Peak RSS", f"{meta['peak_rss_mb']}"),
        ("Tests Passed", f"{meta['tests_passed']}/{meta['total_test_count']}"),
    ]

    mismatches = 0
    print("Verifying Phase 2 Measurement Consistency:")
    for label, val in checks:
        if val in md_text:
            print(f"  [MATCH] {label}: {val}")
        else:
            print(f"  [MISMATCH] {label}: '{val}' not found in validation-report.md")
            mismatches += 1

    if mismatches > 0:
        print(f"\nFAILURE: {mismatches} measurement mismatches found.")
        sys.exit(1)
    else:
        print(f"\nSUCCESS: All {len(checks)} Phase 2 measurements consistently verified!")


if __name__ == "__main__":
    verify_phase2_consistency()
