"""Developer validation CLI over the Python algorithm workflows."""

import argparse
import json
from collections.abc import Sequence

from .common.run_config import DEFAULT_SHOTS
from .ecc.workflow import run_ecc
from .rsa.instance import DEFAULT_RSA_CATALOG_ID, RSA_TOY_CATALOG
from .rsa.workflow import run_rsa


def build_parser() -> argparse.ArgumentParser:
    # Only run controls and named public instances are accepted, never setup secrets.
    parser = argparse.ArgumentParser(prog="breakingpkc")
    parser.add_argument("algorithm", choices=("rsa", "ecc"))
    parser.add_argument("--shots", type=int, default=DEFAULT_SHOTS)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument(
        "--rsa-catalog",
        choices=tuple(RSA_TOY_CATALOG),
        default=DEFAULT_RSA_CATALOG_ID,
        help="Select a curated RSA toy modulus (RSA only).",
    )
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parsed = parser.parse_args(arguments)

    # Algorithm packages own recovery and validation; the CLI only dispatches them.
    if parsed.algorithm == "rsa":
        result = run_rsa(
            shots=parsed.shots,
            seed=parsed.seed,
            catalog_id=parsed.rsa_catalog,
        )
    else:
        result = run_ecc(shots=parsed.shots, seed=parsed.seed)
    print(json.dumps(result, indent=2))
    # An unsuccessful recovery is a completed experiment, not an execution error.
    return 1 if result["outcome"]["status"] == "error" else 0
