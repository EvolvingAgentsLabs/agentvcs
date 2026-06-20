# SkillOpt ⇆ AgentVCS Soul bridge

The evolution seam of *Souls of Silicon*: an agent's **signed traces** (AgentVCS)
are distilled into a **validated skill** (SkillOpt), and a passed validation gate
mints a **Soulbound Token** onto the agent's cryptographic **Soul** (DeSoc).

```
AgentVCS  →  signed code+goal+models+trace   (the line of a life, with provenance)
SkillOpt  →  nightly gate: trace → skill      (learning that strictly improves)
DeSoc     →  SBT minted on the Soul           (verified competence = reputation)
```

## Why read the trace from AgentVCS instead of the runtime log?

SkillOpt-Sleep normally harvests a coding agent's *native* session log (Claude
Code / Codex). The trace dimension of an AgentVCS commit is a better training
input for two reasons:

1. **It is already first-class and structured** — no log scraping.
2. **It is signed by the agent's Soul.** The reflection that updates a skill is
   trained on provenance-verified experience, and the credential it ultimately
   mints can point back at an independently-verifiable commit.

## Run the demo

```bash
# from the agentvcs repo (so `agentvcs` is importable)
python examples/skillopt-soul/bridge.py /path/to/your/agent/repo
```

This harvests the trace dimension, runs a self-contained stand-in gate (so it
works without SkillOpt installed), and on accept crystallizes the head commit and
mints a self-attested SBT.

### As an external issuing oracle

```bash
python examples/skillopt-soul/bridge.py /path/to/agent/repo \
    --issuer-seed $(python -c "import secrets; print(secrets.token_bytes(32).hex())")
```

Now the SBT is signed by the **oracle's** key, not the agent's — a third party
vouching for the agent's competence. `agentvcs verify` (and any marketplace) can
check that issuer signature with only its public key.

## Wiring the real SkillOpt gate

The bridge already imports `skillopt_sleep.consolidate`. Inside a configured
SkillOpt environment, map the harvested `records` to SkillOpt `TaskRecord`s, call
`consolidate(...)`, and flip `USE_REAL = True` in `run_gate()` to gate on
`res.accepted` (strict held-out improvement) instead of the stand-in.
