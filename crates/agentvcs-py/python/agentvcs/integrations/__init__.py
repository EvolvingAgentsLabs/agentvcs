"""Model-call wrappers that read model/sampling/prompt from the active manifest and
record tokens and latency into the current step (or into a step of their own).

Convention: an agent ``a`` is configured by the dimensions ``a.prompt`` (``template``,
optional ``system``, ``variables``), ``a.model`` (``id`` is sent as the model name)
and optionally ``a.sampling``. A patch that changes any of them changes the next call.
"""

from ._common import Completion, render_prompt

__all__ = ["Completion", "render_prompt"]
