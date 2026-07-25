"""Multi-step video generation pipeline.

Keep this package init empty so submodule imports
(e.g. ``backend.pipeline.renderer`` in the Railway worker) do not pull in
orchestrator + LLM/Supabase dependencies.
"""

__all__: list[str] = []
