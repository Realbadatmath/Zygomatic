# Contributing

1. `python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"`
2. `pre-commit install` — ruff, gitleaks, bandit and reuse run before every commit.
3. `scripts/scan.sh` runs the full gate locally; it is the same gate CI runs.
4. Every Python file carries an SPDX header (`reuse annotate` adds one). Every new
   environment flag is declared in the settings module, never read ad hoc.
5. Tests that need a GPU or a local service carry the `gpu` / `service` marker.
