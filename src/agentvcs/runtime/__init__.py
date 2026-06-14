"""The runtime-visibility layer — agentvcs's second operating mode.

In **vcs mode** (the original proposal) agentvcs versions code + goal + models +
trace. In **runtime mode** it *additionally* captures the operational frame the
closed runtime hides — budget, context pressure, model routing, tool usage,
subagent fan-out — and exposes it to the agent itself (``agentvcs budget`` /
``context`` / ``runtime``) and to a human (the dashboard, ``avcs diff``).

See ``frame.py`` for the pure reconstruction logic.
"""
from .frame import build_frame, DEFAULT_PRICING, DEFAULT_WINDOWS

__all__ = ["build_frame", "DEFAULT_PRICING", "DEFAULT_WINDOWS"]
