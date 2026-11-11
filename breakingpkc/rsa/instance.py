"""Public RSA toy instance and input validation."""

from dataclasses import dataclass
from math import gcd, isqrt


@dataclass(frozen=True)
class RSAInstance:
    modulus: int
    base: int


DEFAULT_INSTANCE = RSAInstance(modulus=15, base=2)
DEFAULT_RSA_CATALOG_ID = "rsa-n15-v1"
# Recovery selects public moduli; the separate prime-pair map is used for key setup.
RSA_TOY_CATALOG = {
    f"rsa-n{modulus}-v1": modulus
    for modulus in (15, 21, 33, 35, 39, 55)
}
RSA_TOY_PRIME_PAIRS = {
    "rsa-n15-v1": (3, 5),
    "rsa-n21-v1": (3, 7),
    "rsa-n33-v1": (3, 11),
    "rsa-n35-v1": (5, 7),
    "rsa-n39-v1": (3, 13),
    "rsa-n55-v1": (5, 11),
}


def modulus_from_catalog(catalog_id: str) -> int:
    if not isinstance(catalog_id, str) or catalog_id not in RSA_TOY_CATALOG:
        raise ValueError("Select a supported RSA toy modulus from the catalog.")
    return RSA_TOY_CATALOG[catalog_id]


def validate_instance(instance: RSAInstance) -> None:
    # Exclude bool explicitly: Python otherwise treats it as an integer parameter.
    if not isinstance(instance.modulus, int) or isinstance(instance.modulus, bool):
        raise ValueError("The RSA modulus must be an integer.")
    if not isinstance(instance.base, int) or isinstance(instance.base, bool):
        raise ValueError("The base must be an integer.")
    if instance.modulus < 4:
        raise ValueError("The RSA modulus must be at least 4.")
    if not any(
        instance.modulus % divisor == 0
        for divisor in range(2, isqrt(instance.modulus) + 1)
    ):
        raise ValueError("The RSA modulus must be composite.")
    if instance.base <= 1 or instance.base >= instance.modulus:
        raise ValueError("The base must be greater than 1 and less than the modulus.")
    # Noncoprime bases belong to the workflow's classical gcd path, not this circuit.
    if gcd(instance.base, instance.modulus) != 1:
        raise ValueError("The base must be coprime to the modulus.")