#!/usr/bin/env bash
# Headless Newman run of the ONE folder that is safe to run live:
# "Health (open, no login)" — GET-only, login-gate-exempt endpoints on 127.0.0.1,
# no body, no side effects. Every other folder needs credentials in ZYG_USER /
# ZYG_PASS, and the EXCLUDED folder additionally refuses to run unless
# ALLOW_DANGEROUS=1 (do not set that against production data).
#
# Regenerate the collection first with (ZYG_PY overrides the interpreter):
#   "${ZYG_PY:-python}" apitests/make_postman.py
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p apitests/reports

exec apitests/node_modules/.bin/newman run \
  apitests/zygomatic.postman_collection.json \
  -e apitests/zygomatic.postman_environment.json \
  --folder "Health (open, no login)" \
  --timeout-request 15000 \
  --reporters cli,json \
  --reporter-json-export apitests/reports/newman_health.json
