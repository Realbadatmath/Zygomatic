<!-- SPDX-FileCopyrightText: 2026 Zygomatic -->
<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Security policy

Report a vulnerability by opening a private security advisory on this repository
(GitHub: Security, Advisories, "Report a vulnerability"). Do not open a public issue.

Secrets never live in this repository. Runtime credentials are read from environment variables
or from files outside the checkout (each package's `docs/configuration.md` lists them). Every
push runs gitleaks over the working tree and the full history, bandit, ruff, reuse and
import-linter in CI; a finding fails the build.

Bandit policy: medium and high severity findings fail CI. Low severity findings are reviewed
and either fixed or listed with a reason in the package's `pyproject.toml` under `[tool.bandit]`.

Signing keys: deliverables carry a C2PA content credential, and the signing key material is
operator material, not repository material. The private signer key (`ZYG_C2PA_KEY`) and the root
CA key live under `~/.config/zygomatic/c2pa` at mode `0600`, outside every checkout; the test suite
builds its own throwaway CA in a temporary directory and never reads them. Only the root
certificate is public — it is published so that strangers can verify. The root CA key belongs on
offline media and is brought out only to issue a new signer; the signer certificate is rotated
every two years from the same root, which keeps already-signed files valid. See
`packages/workflows/docs/content_credentials.md` for the runbook.

Network posture: every service binds to loopback by default. Publishing a service on a LAN or
the internet is an explicit configuration step (`BIND_HOST`, `ZYG_LAN_HOST`, `ZYG_CORS_ORIGINS`)
and the public site is the only component designed to face strangers.
