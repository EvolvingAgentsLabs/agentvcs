"""The deterministic part of the agent — its application code / human interface.

In the agentvcs model, an application is just the deterministic skin of an agent.
This module is the frozen logic the fluid LLM layer falls back on once a behavior
has been crystallized.
"""


def handle_refund(request: dict) -> str:
    if request.get("suspicious"):
        return "escalate"
    if request.get("amount", 0) <= 50:
        return "auto_refund"
    return "needs_review"
