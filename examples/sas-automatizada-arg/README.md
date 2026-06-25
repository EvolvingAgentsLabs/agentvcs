# SAS Automatizada (Argentina) — agentvcs as the *libro de actas técnico*

A reference example for running an autonomous agent as a **legal entity** under the
kind of legislation now being drafted (Argentina's *Sociedades Automatizadas* / DAO
framework, which gives software agents legal personhood within declared limits and
named human representatives).

agentvcs is the **technical book of minutes** ("libro de actas técnico"): every
decision the agent commits is a cryptographically signed **acta**, and the audit
proves the agent operated within its statute.

## Run it (offline, ~90s, no account)

```bash
bash examples/sas-automatizada-arg/demo.sh
```

It spins up a throwaway repo and walks the full lifecycle:

1. `agentvcs init --corporate` — the instance is born as a *SAS Automatizada*: it
   gets an Ed25519 **Soul**, runs in runtime mode, and a digital **statute** is
   written to `LEGAL.md` (human-readable) + the `corporate` block in `agent.json`
   (machine-binding, versioned and signed by the tree hash on every commit).
2. The statute declares **reserved matters** (`transfer`, `wire`, `pay_supplier`),
   an inference **spend ceiling**, and a **legal representative** (Ana Gómez, by her
   Ed25519 public key).
3. **Acta 1** — a routine KYC check → *within mandate*.
4. **Acta 2** — the agent wires USD 5000 to a supplier → **OUT OF MANDATE**: a
   reserved matter with no human authorization.
5. The representative signs a **board resolution** authorizing the transfer
   (`agentvcs approve <acta> --seed <her-seed>`) — clearing the acta.
6. `agentvcs audit` re-runs → **COMPLIANT**, and the **Libro de Actas Digital** is
   itself signed by the entity's Soul. `agentvcs verify --all` confirms every acta
   is cryptographically the entity's own.

## How it maps to the law

| Legal concept | agentvcs mechanism |
|---|---|
| Estatuto / objeto social | `corporate` block in `agent.json` + `LEGAL.md` (versioned, signed) |
| Personería / identidad de la entidad | the Soul (Ed25519 `soul_id`) |
| Acta de directorio | a signed commit |
| Límites del mandato / facultades | `liability_limits` (`max_inference_usd`, `requires_human_for`) |
| Representante legal | `legal_representatives[].soul` (Ed25519 pubkey) |
| Autorización de acto reservado | `agentvcs approve` (representative's signed resolution) |
| Libro de actas / prueba ante UIF/AFIP/IGJ | `agentvcs audit --json` (Soul-signed report) |

## The model (honest about scope)

The gate is a **policy gate**, not a claim to see real-world money it cannot. It
enforces two things from evidence agentvcs actually holds:

- **Spend ceiling** — inference cost per acta vs `max_inference_usd` (from the
  runtime frame; needs runtime mode + a real provider to be non-null).
- **Reserved matters** — tool calls in the trace matching `requires_human_for`
  must carry a *valid signed* authorization from a listed representative, or the
  acta is a breach. Unsigned attestations are advisory only.

Each acta is judged against the statute **in force at that commit** — tightening the
statute later never retroactively breaches past actas.

## Files

`demo.sh` is fully self-contained (generates the agent.json, statute and traces in a
temp dir). Use it as the template for wiring a real autonomous-company agent: keep
`agent.json`'s `corporate` block as your source of truth, commit each decision, and
ship `agentvcs audit --json` to your compliance/legal pipeline.
