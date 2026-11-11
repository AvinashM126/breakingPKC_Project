"""Neutral run-control bounds shared by all algorithm workflows."""

DEFAULT_SHOTS = 256
# This seed makes toy experiments reproducible; it is never used for key generation.
DEFAULT_SEED = 314159
# These are local experiment budgets, not cryptographic security parameters.
MAX_SHOTS = 4096
MAX_SEED = (1 << 32) - 1
