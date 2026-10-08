#!/usr/bin/env bash
# Build the Python SDK into a local venv and (optionally) run its tests.
#
#   crates/agentvcs-py/dev.sh            # venv + maturin develop --release
#   crates/agentvcs-py/dev.sh test       # ... then pytest (SDK + toy pipeline)
#
# macOS arm64 with an x86_64 rustup (Rosetta) — the setup on the dev Mac — builds
# an x86_64 extension that cannot load into an arm64 Python ("symbol(s) not
# found for architecture x86_64"). We detect it and pass the native target
# explicitly. The permanent fix is a native toolchain (README, "Python SDK").
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cd "$here"
py="${PYTHON:-python3.12}"
command -v "$py" >/dev/null || py=python3
venv="${VENV:-$here/.venv}"
[ -x "$venv/bin/python" ] || "$py" -m venv "$venv"
"$venv/bin/python" -m pip install -q --upgrade pip 'maturin>=1.7,<2' 'pytest>=8'

target_args=()
if [ "$(uname -s)" = Darwin ]; then
  py_arch="$("$venv/bin/python" -c 'import platform; print(platform.machine())')"
  rust_host="$(rustc -vV | sed -n 's/^host: //p')"
  if [ "$py_arch" = arm64 ] && [ "${rust_host%%-*}" != aarch64 ]; then
    echo "dev.sh: rustc host is $rust_host but Python is arm64 -> --target aarch64-apple-darwin" >&2
    rustup target add aarch64-apple-darwin >/dev/null 2>&1 || true
    target_args=(--target aarch64-apple-darwin)
  fi
fi

VIRTUAL_ENV="$venv" PATH="$venv/bin:$PATH" \
  "$venv/bin/maturin" develop --release ${target_args[@]+"${target_args[@]}"}

if [ "${1:-}" = test ]; then
  "$venv/bin/python" -m pytest -q tests ../../examples/toy_pipeline/tests ../../examples/lora-kernel/tests
fi
