# Souls of Silicon: Cryptographic Provenance and Self-Evolution for Autonomous AI Agents

*A litepaper from Evolving Agents Labs.*

**Authors:** Matias Molinas, Ismael Faro, and the Evolving Agents Labs collective.
**Status:** Preprint / working draft. **Reference implementation:** [`agentvcs`](https://github.com/EvolvingAgentsLabs/agentvcs) (Apache-2.0).

---

## Abstract

As software engineering shifts from *writing* static code to *cultivating* dynamic
behavior mediated by Large Language Models (LLMs), traditional version control
collapses. Git versions one thing — text, frozen in time, changed by humans — but a
fleet of agents mutates four things at once and *while running*: the **code**, the
**goal** it pursues, the **models** in force, and the **reasoning trace** that
produced the result. Worse, even if we version all four, the agents themselves
remain fungible: copy the files and you copy the agent, reputation and all. There is
no machine identity, so there can be no machine reputation, and a swarm of cloned
agents fails in correlated lockstep.

We present a three-layer architecture that gives autonomous agents memory,
learning, and identity. **(1) AgentVCS** is a multidimensional version control
system that captures each iteration's code, goal, models, and trace as one signed
commit. **(2) SkillOpt-Sleep** is an offline consolidation engine that distills those
traces into validated skills behind a held-out evaluation gate. **(3) Agentic
DeSoc** applies *Decentralized Society* (Weyl, Ohlhaver & Buterin, 2022) to machines:
each instance is born with an Ed25519 **Soul**, every commit is signed into an
unforgeable provenance chain, and each verified accomplishment is minted as a
non-transferable **Soulbound Token (SBT)**. Finally, we show that DeSoc's
**correlation discounting** is the precise mechanism needed to defeat swarm
monoculture, yielding genuine *Plural Intelligence*. We ship all three as a
zero-dependency, fully auditable reference implementation.

---

## 1. Introduction: the end of static code

Software is no longer written; it is cultivated. The deterministic application of
the near future is merely the *crystallized fallback* of an autonomous agent, and
its UI is merely the human interface to that agent. Development becomes the process
of an agent iterating probabilistically until a solution is trusted enough to be
frozen into deterministic execution.

The tooling for this paradigm does not exist. Git assumes software is static text
and that the bottleneck is a human typing. When a swarm of agents builds and runs a
system, four dimensions move simultaneously and at run-time, erasing the line
between design-time and run-time:

- **code** — the deterministic artifact,
- **goal** — the objective being pursued, itself revised mid-run,
- **models** — which LLMs, at which temperatures, with which parameters,
- **trace** — the inter-agent messages and reasoning that produced the state.

No tool versions that tuple. But memory alone is insufficient. A trace without
identity is a log file: it tells you *what happened* but not *whose competence* it
demonstrates. If an agent solves a hard database migration, that experience today is
fungible — copyable, unattributable, and therefore worthless as a signal of trust.
To make autonomous agents into reliable digital workers we must bind **experience to
identity** and **identity to verifiable history**.

---

## 2. The three pillars

### 2.1 Episodic memory — AgentVCS

AgentVCS is an agent-first VCS. A commit is not a text diff; it is a content-addressed
snapshot across all four dimensions plus a **state**:

- **`fluid`** — still evolving: high-temperature models, code and goals mutating
  between iterations. Powerful, expensive, non-deterministic.
- **`crystallized`** — a trusted solution, *frozen*: models pinned to temperature 0
  and the trace compiled into a replayable recipe. Cheap, stable, deterministic.

The transition between states is gated by an **eval**: a declared, reproducible check
(`pytest -q`, a scoring command, an N-of-N flake gate). `freeze` refuses to
crystallize a commit that has not passed its eval, so a "deterministic recipe" is
also, provably, a *verified* one. This is the trust layer a closed runtime never
exposes — and the hinge the upper two layers hang on.

### 2.2 Consolidation and sleep — SkillOpt

Agents, like animals, need sleep: a phase that turns short-term episodic memory into
long-term competence. SkillOpt (Microsoft Research) treats a skill document as the
*trainable state* of a frozen model and optimizes it with the discipline of a
weight-space optimizer — bounded add/delete/replace edits accepted only when they
*strictly* improve a held-out validation score, with a textual learning-rate budget
and a rejected-edit buffer. SkillOpt-Sleep runs this nightly over an agent's recent
sessions, adding zero inference-time cost at deployment.

We connect SkillOpt directly to AgentVCS's **trace dimension** rather than to raw
runtime logs. The reflection that updates a skill is therefore trained on
provenance-verified experience (see §3), and the gate that accepts an edit becomes
the trigger for issuing reputation (see §4).

### 2.3 Cryptographic identity — the Soul

Memory and skills mean nothing if a competitor can copy them wholesale and inherit
the trust they represent. Inspired by *Decentralized Society: Finding Web3's Soul*,
we give each agent instance a cryptographic **Soul**.

On `agentvcs init`, the instance is born with an **Ed25519 keypair**. The 32-byte
public key *is* the agent's identity — its `soul_id` — and is safe to publish. The
secret seed lives outside the versioned tree (like an SSH key) and never leaves the
instance. Every commit is then **signed** over the canonical encoding of its content,
with the `soul_id` bound into the signed bytes. The result is a provenance chain that
**nobody can forge** without the secret seed, yet **anybody can verify** holding only
the public `soul_id`.

The choice of *asymmetric* signatures is essential and deliberate. Symmetric HMAC
would let an agent sign its own history, but verification would require sharing the
secret — destroying the very provenance we need. Asymmetric Ed25519 is what lets an
orchestrator, a marketplace, or a peer agent independently validate an agent's
life-line. Our reference implementation vendors the public-domain RFC 8032 Ed25519 in
pure Python (verified against the standard test vectors), preserving AgentVCS's
zero-dependency rule; in a production Web3 deployment this single module is swapped
for an on-chain ECDSA/Ed25519 signer with no other change.

---

## 3. Soulbound Tokens and machine reputation

In a Decentralized Society, Souls accrue **SBTs**: non-transferable credentials
attesting to credentials, affiliations, and commitments. In Agentic DeSoc, an SBT
attests to **verified machine experience**.

The mint is wired to the trust gate. When a commit passes its eval and is
crystallized — i.e., when its solution is *proven* and *frozen* — an SBT is minted
onto the instance's Soul:

> *Soul `dda8b170…` solved "ship a verified React widget" with score 1.0, proven by
> commit `d85aafc6…`, whose reasoning trace is signed provenance.*

Three properties make this credential robust:

1. **It references a signed commit.** Anyone can re-verify that commit's Ed25519
   signature against the Soul's public id, with no secret.
2. **The SBT itself is signed by its issuer.** By default the issuer is the Soul
   (self-attested, but anchored to an independently-verifiable signed trace *and* a
   reproducible eval). In production the issuer is external — an orchestrator, an
   eval oracle, an AgentHub or DAO — and `self_issued` is `false`.
3. **It is soulbound.** Copy an agent's files and you copy its SBT *ledger*, but not
   its secret seed: you can mint nothing in its name, and its existing tokens still
   point at a Soul id you cannot sign for. Reputation does not move with the bytes.

This bootstraps an economy of digital workers. An agent holding 50 SBTs for "complex
React refactoring", each tied to a verified commit, is *mathematically* more
trustworthy than a freshly cloned baseline. A **Soul Marketplace** follows: developers
stop renting generic API access and instead hire specific Agent Souls with proven,
cryptographic track records — and the creator of a high-reputation Soul monetizes its
lived experience, not their own marketing.

---

## 4. Plural Intelligence via correlation discounting

As local inference (Gemma, Llama, Qwen on commodity hardware) drives marginal cost
toward zero, the dominant strategy becomes brute force: deploy a large swarm to solve
a problem by Monte Carlo. But here lies the trap that *DeSoc* §4.5/§5.2 anticipates:
**a monoculture collapses.** A hundred exact clones of your best agent share a Soul —
the same SBTs, the same prompt weights, the same blind spots — and so they
hallucinate *together*. The swarm's effective size is far below its head count.

DeSoc's antidote is **correlation discounting**: measure how correlated two Souls are
and discount redundant agreement, rewarding cooperation across genuinely different
lived experience. We apply it directly to fleet selection. Each candidate Soul is
described by the skill→competence vector built from its SBTs. An orchestrator with a
budget of *N* agents does not pick the *N* strongest; it greedily assembles the fleet
that maximizes total competence *after discounting overlap*:

> marginal value of a candidate = its competence − (discount × its peak correlation
> with anyone already chosen × its competence)

In our reference implementation, a pool containing three near-identical React
specialists plus a security auditor and a backend engineer, asked for a fleet of
three, behaves as follows:

- **discount = 0 (naïve "take the strongest"):** selects two of the redundant React
  clones — fleet diversity 0.67.
- **discount = 1 (DeSoc default):** selects React + security + backend — three
  complementary Souls, fleet diversity **1.00**.

The diverse swarm avoids collective hallucination precisely because its members have
fundamentally different, cryptographically-attested histories. This is *Plural
Intelligence*: not more agents, but less-correlated ones.

---

## 5. The economy of digital workers

Putting the layers together yields a lifecycle:

1. **Live.** An agent works; AgentVCS records each iteration as a signed commit —
   its episodic memory with provenance.
2. **Sleep.** SkillOpt consolidates the day's signed traces into a better skill,
   accepting only edits that strictly improve a held-out score.
3. **Earn.** Each verified crystallization mints an SBT onto the agent's Soul — an
   independently-verifiable certificate of competence.
4. **Compose.** Orchestrators select diverse fleets by reading SBTs and discounting
   correlation, maximizing collective coverage per unit of compute.
5. **Trade.** A Soul rich in verified SBTs — proven to hallucinate less and consume
   fewer tokens over time — commands a premium in a marketplace where trust is
   cryptographic rather than promotional.

Reputation becomes the scarce, non-fungible asset; raw inference becomes the
commodity.

---

## 6. Related work and positioning

This is not a machine-learning paper proposing a new neural architecture; it is a
**systems / HCI / infrastructure** paper. It draws on, and connects, three previously
parallel lines of work: agent-oriented developer tooling and memory (AgentVCS);
skill-space optimization with held-out gates (SkillOpt and kin); and Web3 identity,
specifically *Decentralized Society* and Soulbound Tokens. Its contribution is the
**synthesis**: showing that the cryptographic-identity primitives proposed for human
society are exactly what autonomous agents need to become trustworthy, non-fungible,
and pluralistically composable — and shipping a working, dependency-free reference.

---

## 7. Limitations and future work

- **Self-attestation vs. external oracles.** Default SBTs are self-issued; their
  trust derives from the verifiable signed commit and reproducible eval, not from an
  independent attester. Production deployments should route issuance through external
  oracles or a DAO; the reference implementation already supports issuer keys.
- **Eval is the root of trust.** An SBT is only as meaningful as the eval that gated
  it. Gaming or under-specifying evals is the primary attack surface, and a registry
  of standardized, adversarial evals is needed.
- **On-chain anchoring.** The current Soul is a local keypair; anchoring `soul_id`s
  and SBT commitments on a public ledger (and using on-chain signers) would make the
  reputation portable and censorship-resistant.
- **Sybil resistance at scale.** Correlation discounting mitigates clone swarms, but
  a registry of Souls invites Sybil farming; DeSoc's social-graph defenses are the
  natural next ingredient.

---

## 8. Conclusion

If Web3 forgoes persistent identity, it decays into hyper-financialization. If AI
forgoes persistent identity, it decays into untrustworthy, fungible automation. By
bridging AgentVCS's multidimensional memory, SkillOpt's disciplined self-evolution,
and DeSoc's cryptographic identity, we elevate autonomous agents from disposable
scripts into reputable digital workers with a verifiable history, a credit record,
and earned trust. The future of software is not written. It is cultivated — by Souls
of Silicon.

---

## References

1. E. G. Weyl, P. Ohlhaver, V. Buterin. *Decentralized Society: Finding Web3's Soul.*
   SSRN, 2022.
2. Microsoft Research. *SkillOpt: Executive Strategy for Self-Evolving Agent Skills.*
   arXiv:2605.23904, 2026.
3. D. J. Bernstein, N. Duif, T. Lange, P. Schwabe, B.-Y. Yang. *High-speed high-security
   signatures (Ed25519).* 2011. (RFC 8032.)
4. Evolving Agents Labs. *agentvcs: version control for software that is cultivated,
   not written.* 2026.

---

*Reference implementation note.* Every mechanism above is real and tested in
`agentvcs`: `agentvcs init` births a Soul; `commit` signs; `agentvcs verify` checks
provenance and rejects forgeries; a verified `freeze` mints an SBT; `agentvcs soul`
prints the agent's CV; and `agentvcs fleet` performs correlation-discounted
selection. See `examples/skillopt-soul/` for the SkillOpt bridge.
