"""The stages of the scholarly documentary pipeline, one function per stage.

`zyg_workflows.pipeline_scholarly._run_scholarly_pipeline` keeps the prologue
(the job record, the state file, the nested logging/stop closures) and the
`try/except/finally` around the run; the stages themselves live here, in
`stages_01_18`, `stages_19_36`, `stages_37_54` and `stages_55_73`, and share
the single `RunContext` of `context.py`.

Nothing is re-exported on purpose: the monolith imports the stage module it
needs lazily, inside the function, because the stage modules import helpers
back out of `pipeline_scholarly` and a module-level import either way would
close the cycle.
"""
