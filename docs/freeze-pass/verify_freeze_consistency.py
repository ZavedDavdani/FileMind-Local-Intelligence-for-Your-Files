"""Programmatic consistency verifier for Phase 0-2 Final Quality and Freeze Pass."""

import json
import os
import sys


def verify_freeze_consistency():
    json_path = os.path.join(os.path.dirname(__file__), "freeze-report.json")
    md_path = os.path.join(os.path.dirname(__file__), "freeze-report.md")

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

    pa = data["part_a_packaged_baseline"]
    pb = data["part_b_real_document_structure"]
    pef = data["parts_e_f_scale_and_progressive"]
    pij = data["parts_i_j_concurrent_resources"]
    dec = data["freeze_decision"]

    checks = [
        ("Freeze Decision", dec["status"]),
        ("A-Class Blockers", f"{dec['a_class_blockers_count']}"),
        ("Packaged Backend Size", f"{pa['packaging']['backend_binary_size_mb']}"),
        ("Installer Size", f"{pa['packaging']['installer_size_mb']}"),
        ("Cold-Start Median", f"{pa['cold_start_seconds']['median']}"),
        ("Cold-Start Min", f"{pa['cold_start_seconds']['min']}"),
        ("Cold-Start Max", f"{pa['cold_start_seconds']['max']}"),
        ("Health Roundtrip Median", f"{pa['health_roundtrip']['median_ms']}"),
        ("Documents Parsed", f"{pb['summary']['documents_parsed']}/{pb['summary']['documents_evaluated']}"),
        ("Heading Detection Pct", f"{pb['heading_quality']['heading_detection_pct']}%"),
        ("Table Preservation Pct", f"{pb['table_quality']['table_preservation_pct']}%"),
        ("Scale Total Files", f"{pef['scale_metrics']['total_files_discovered']}"),
        ("Concurrent Throughput", f"{pij['concurrent_throughput_docs_per_sec']}"),
        ("Peak Process RSS", f"{pij['resource_footprint']['peak_process_rss_mb']}"),
    ]

    mismatches = 0
    print("Verifying Phase 0-2 Freeze Pass Measurement Consistency:")
    for label, val in checks:
        if val in md_text:
            print(f"  [MATCH] {label}: {val}")
        else:
            print(f"  [MISMATCH] {label}: '{val}' not found in freeze-report.md")
            mismatches += 1

    if mismatches > 0:
        print(f"\nFAILURE: {mismatches} measurement mismatches found.")
        sys.exit(1)
    else:
        print(f"\nSUCCESS: All {len(checks)} Freeze Pass measurements consistently verified!")


if __name__ == "__main__":
    verify_freeze_consistency()
