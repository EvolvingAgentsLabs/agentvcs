"""``python -m agentvcs`` (and the ``agentvcs`` console script): the Rust CLI,
in-process — the same code path as the release binary (``agentvcs_cli::main_with``)."""

import sys

from . import _native


def main() -> None:
    sys.stdout.flush()
    sys.exit(_native.main(sys.argv[1:]))


if __name__ == "__main__":
    main()
