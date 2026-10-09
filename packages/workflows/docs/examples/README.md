# Workflow examples

Runnable, documentation-only examples. Nothing in `src/` imports them.

- `dsl_integration_example.py` — demonstrates the SCENE DSL end to end: generating DSL from
  research findings, validating it, transforming it into tool configs, and wiring it
  non-invasively into the research / scripting / generation / QA / assembly pipeline stages.
  It runs with stub callables (no LLM, no GPU) and prints each stage:
  `cd packages/workflows && uv run --no-sync python docs/examples/dsl_integration_example.py`.
  Moved here from `src/zyg_workflows/DSL_INTEGRATION_EXAMPLE.py` — it is a print-driven
  walkthrough, not a library module.
