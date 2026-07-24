# Contributing

Thank you for helping make Python automations safer.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
python -m pip install -e ".[dev]"
```

## Checks

```bash
ruff check .
pytest --cov=kiwai --cov-report=term-missing
python -m build
```

## Pull requests

- Keep changes focused.
- Add tests for behavior changes.
- Update the README when the public API changes.
- Explain the failure scenario the change protects against.

Security-sensitive behavior should include a crash, concurrency, or replay test whenever possible.
