You maintain a payments **refund queue**. When asked to add or change behavior,
edit the files under `agent/tools/` and keep the build green.

Rules:
- Only import packages that exist in `package.json`. Never invent module names.
- Refund operations must be idempotent: the same `requestId` must never refund twice.
- Prefer small, reviewable changes — one tool per file.
