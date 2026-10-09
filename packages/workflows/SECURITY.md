# Security policy

Report a vulnerability by opening a private security advisory on this repository
(GitHub → Security → Advisories → "Report a vulnerability"). Do not open a public issue.

Secrets never live in this repository. Runtime credentials are read from environment
variables or from files outside the checkout (see `docs/configuration.md`). Every push runs
gitleaks, bandit, ruff, reuse and import-linter in CI; a finding fails the build.

Bandit policy: medium and high severity findings fail CI. Low severity findings are
reviewed and either fixed or listed with a reason in `pyproject.toml` under `[tool.bandit]`.
