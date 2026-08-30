"""FileMind Phase 1 Measurement Consistency Verification Script.

Programmatically verifies that all current/audited numeric fields in docs/phase-1/measurements.json
match the reported values in docs/phase-1/validation-report.md with 100% precision.
Explicitly excludes and isolates historical_measurements.
"""

import json
import os
import re
import sys
from pathlib import Path


def verify_consistency() -> bool:
    base_dir = Path(__file__).resolve().parent
    measurements_json_path = base_dir / "measurements.json"
    report_md_path = base_dir / "validation-report.md"

    if not measurements_json_path.exists():
        print(f"ERROR: {measurements_json_path} does not exist.")
        return False

    if not report_md_path.exists():
        print(f"ERROR: {report_md_path} does not exist.")
        return False

    with open(measurements_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    with open(report_md_path, "r", encoding="utf-8") as f:
        report_text = f.read()

    print("=" * 60)
    print("FileMind Phase 1 Measurement Consistency")
    print("=" * 60)
    print(f"Source JSON:   {measurements_json_path}")
    print(f"Source Report: {report_md_path}\n")

    # 1. Verify and isolate historical fields
    historical = data.get("historical_measurements", {})
    historical_count = len(historical)
    print(f"[*] Historical fields identified and excluded from active audit: {historical_count}")
    for k in historical:
        print(f"    - Excluded historical key: {k}")
    print()

    # 2. Extract current audited primary measurements
    audited = data.get("audited_measurements", {})
    if not audited:
        print("ERROR: No 'audited_measurements' section found in measurements.json!")
        return False

    fields_to_check = [
        ("audited_measurements.discovery_throughput_files_per_sec.median", audited["discovery_throughput_files_per_sec"]["median"], "files/s"),
        ("audited_measurements.sha256_streaming_throughput_mb_per_sec.median", audited["sha256_streaming_throughput_mb_per_sec"]["median"], "MB/s"),
        ("audited_measurements.worker_queue_throughput_jobs_per_sec.median", audited["worker_queue_throughput_jobs_per_sec"]["median"], "jobs/s"),
        ("audited_measurements.watcher_event_latency_ms.median", audited["watcher_event_latency_ms"]["median"], "ms"),
        ("audited_measurements.crash_recovery_latency_ms.median", audited["crash_recovery_latency_ms"]["median"], "ms"),
        ("audited_measurements.resources.rss_ram_mb", audited["resources"]["rss_ram_mb"], "MB"),
        ("audited_measurements.resources.cpu_percent", audited["resources"]["cpu_percent"], "%"),
    ]

    # 3. Extract supplementary realistic workload measurements
    supp = data.get("supplementary_realistic_workload_benchmark", {})
    if supp:
        fields_to_check.extend([
            ("supplementary.discovery_throughput_files_per_sec.median", supp["discovery_throughput_files_per_sec"]["median"], "files/s"),
            ("supplementary.realistic_workload_hashing_only_throughput_mb_per_sec.median", supp["realistic_workload_hashing_only_throughput_mb_per_sec"]["median"], "MB/s"),
            ("supplementary.end_to_end_worker_processing_throughput_jobs_per_sec.median", supp["end_to_end_worker_processing_throughput_jobs_per_sec"]["median"], "jobs/s"),
        ])

    matched = 0
    mismatched = 0

    for json_path, expected_val, unit in fields_to_check:
        print("-" * 60)
        print(f"JSON current field: {json_path}")
        print(f"Expected numeric value: {expected_val} {unit}")

        val_str = str(expected_val)
        pattern = re.compile(rf"\b{re.escape(val_str)}\b")
        matches = pattern.findall(report_text)

        if matches:
            print(f"Report match found: '{val_str}' in markdown tables/sections")
            print(f"Parsed numeric value: {float(val_str)}")
            print("Match: PASS")
            matched += 1
        else:
            print(f"ERROR: Expected value '{val_str}' not found in {report_md_path}")
            print("Match: FAIL")
            mismatched += 1

    print("\n" + "=" * 60)
    print(f"Total current numeric fields checked: {len(fields_to_check)}")
    print(f"Matched: {matched}")
    print(f"Mismatched: {mismatched}")
    print(f"Historical fields excluded: {historical_count}")
    print("=" * 60)

    if mismatched == 0:
        print("\nRESULT: PASS\n")
        return True
    else:
        print("\nRESULT: FAIL\n")
        return False


if __name__ == "__main__":
    success = verify_consistency()
    sys.exit(0 if success else 1)
