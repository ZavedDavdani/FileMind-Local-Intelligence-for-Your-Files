# Security Policy

## Privacy & Security Architecture

FileMind is designed from the ground up as a **100% local-first desktop application**:

- **Local-Only Processing**: Document parsing, text extraction, lexical indexing, vector embeddings, reranking, and local LLM queries execute strictly on `127.0.0.1`.
- **Zero Telemetry**: FileMind collects no usage analytics, tracking cookies, or document metrics.
- **Process Supervision**: The Python backend is managed via Windows Job Objects (`KILL_ON_JOB_CLOSE`) to prevent orphaned processes or unmanaged ports.
- **Path Containment**: All file operations and search requests enforce strict registered-folder boundaries, preventing path traversal attacks.
- **Prompt Injection Defense**: Retrieved document text is treated as untrusted data and wrapped in boundary delimiters during local LLM prompt construction.

---

## Reporting a Vulnerability

If you discover a potential security vulnerability in FileMind, please report it responsibly.

### How to Report
Please send an email to **zaved.davdani@gmail.com** or open a private GitHub Security Advisory with:
- A description of the vulnerability.
- Steps to reproduce or proof-of-concept.
- Potential impact.

We will acknowledge receipt within 48 hours and work on a prompt remediation.
