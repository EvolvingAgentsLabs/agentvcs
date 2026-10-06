"""The zero-dependency claim, enforced instead of asserted.

`pyproject.toml` says `dependencies = []  # stdlib only, auditable by anyone`.
That comment is the same kind of promise as EAT's firmware string: it asks
politely and nothing checks it. One `import httpx` in a helper and the claim is
quietly false — which is exactly how this organisation lost the property twice
before (see legacy/eat, pinned to beeai-framework 0.1.4 and MongoDB Atlas).

This walks the AST rather than the import machinery, so it fails on a module
that is never imported at runtime and on one guarded by TYPE_CHECKING.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "agentvcs"

# Python's own module list, plus the package itself. Nothing else may appear.
ALLOWED = set(sys.stdlib_module_names) | {"agentvcs"}


def _top_level_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import — always internal.
            if node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return found


def test_the_package_imports_nothing_outside_the_standard_library() -> None:
    offenders: dict[str, set[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        third_party = _top_level_imports(path) - ALLOWED
        if third_party:
            offenders[str(path.relative_to(SRC))] = third_party

    assert not offenders, (
        "agentvcs claims zero runtime dependencies. These modules import "
        f"outside the standard library: {offenders}. Either drop the import or "
        "move the code into a package that declares the dependency."
    )


def test_every_module_parses() -> None:
    """Guards the test above: a file that fails to parse must not pass silently."""
    modules = list(SRC.rglob("*.py"))
    assert len(modules) > 20, f"expected the full package, walked only {len(modules)} files"
    for path in modules:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
