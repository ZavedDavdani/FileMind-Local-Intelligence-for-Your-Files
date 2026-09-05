# Contributing to FileMind

Thank you for your interest in contributing to **FileMind (Local Intelligence for Your Files)**!

FileMind is dedicated to building high-performance, 100% private, local-first knowledge extraction and search software for desktop users.

---

## Development Workflow

### Prerequisites
- **Operating System**: Windows 10 or Windows 11 (x64)
- **Python**: 3.11+
- **Node.js**: 18+ & npm
- **Rust**: Latest stable `rustc` and `cargo`

### Setup Instructions

1. **Fork and Clone the Repository**:
   ```powershell
   git clone https://github.com/ZavedDavdani/FileMind-Local-Intelligence-for-Your-Files.git
   cd FileMind-Local-Intelligence-for-Your-Files
   ```

2. **Backend Setup**:
   ```powershell
   cd backend
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. **Frontend Setup**:
   ```powershell
   cd ..\frontend
   npm install
   ```

4. **Running Locally in Dev Mode**:
   ```powershell
   cd ..
   npm run tauri dev
   ```

---

## Testing Guidelines

Before opening a pull request, ensure all test suites pass:

```powershell
# Backend automated tests (Pytest)
pytest backend/tests -v

# Frontend TypeScript build
cd frontend
npm run build

# Tauri Rust compilation check
cd ..\src-tauri
cargo check
```

---

## Architectural Principles

1. **Local-First Privacy**: Never introduce network calls or telemetry to external cloud servers for core file processing or AI retrieval.
2. **Grounded Provenance**: AI answers must always be traceable to verified source chunks and citation coordinates.
3. **Filesystem Primacy**: Treat the user's files on disk as the immutable source of truth.

---

## Pull Request Process

1. Create a feature branch (`git checkout -b feature/my-feature`).
2. Write clean code with appropriate unit tests.
3. Verify all tests and builds pass cleanly.
4. Commit your changes with clear, descriptive commit messages.
5. Push to your fork and submit a Pull Request.
