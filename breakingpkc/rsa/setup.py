"""Curated educational RSA key setup, separate from attack workflows."""

from dataclasses import dataclass, field
from itertools import combinations
from math import gcd, lcm
from secrets import choice

TOY_PRIMES = (3, 5, 7, 11, 13)
TOY_EXPONENTS = (3, 5, 7, 11, 17)


def _validate_primes(first_prime: int, second_prime: int) -> None:
    for value in (first_prime, second_prime):
        if type(value) is not int or value not in TOY_PRIMES:
            raise ValueError("Select primes from the educational RSA catalog.")
    if first_prime == second_prime:
        raise ValueError("RSA setup requires distinct primes.")


def allowed_exponents(first_prime: int, second_prime: int) -> tuple[int, ...]:
    _validate_primes(first_prime, second_prime)
    totient = (first_prime - 1) * (second_prime - 1)
    carmichael = lcm(first_prime - 1, second_prime - 1)
    # Only exponents invertible modulo lambda(N) yield a matching private exponent.
    return tuple(
        exponent for exponent in TOY_EXPONENTS
        if exponent < totient and gcd(exponent, carmichael) == 1
    )


@dataclass(frozen=True)
class RSAPublicSetup:
    modulus: int
    public_exponent: int
    catalog_id: str = "rsa-toy-primes-v1"

    def to_dict(self) -> dict[str, str]:
        # Decimal strings preserve exact integers when JSON reaches JavaScript.
        return {
            "catalog_id": self.catalog_id,
            "N": str(self.modulus),
            "e": str(self.public_exponent),
        }


@dataclass(frozen=True)
class RSAPrivateSetup:
    public: RSAPublicSetup
    # Excluding secrets from repr reduces accidental exposure, not memory access.
    first_prime: int = field(repr=False)
    second_prime: int = field(repr=False)
    private_exponent: int = field(repr=False)

    def public_attack_input(self) -> RSAPublicSetup:
        # Recovery receives only this explicit public projection, never this key object.
        return self.public

    def reveal_private(self) -> dict[str, str]:
        return {
            "p": str(self.first_prime),
            "q": str(self.second_prime),
            "d": str(self.private_exponent),
            "phi": str((self.first_prime - 1) * (self.second_prime - 1)),
            "lambda": str(lcm(self.first_prime - 1, self.second_prime - 1)),
        }


def create_toy_key(
    first_prime: int = 3,
    second_prime: int = 5,
    public_exponent: int | None = None,
) -> RSAPrivateSetup:
    exponents = allowed_exponents(first_prime, second_prime)
    exponent = exponents[0] if public_exponent is None else public_exponent
    if type(exponent) is not int or exponent not in exponents:
        raise ValueError("Select an allowed public exponent for these primes.")
    carmichael = lcm(first_prime - 1, second_prime - 1)
    # The toy convention uses the least positive inverse modulo lambda(N).
    return RSAPrivateSetup(
        public=RSAPublicSetup(first_prime * second_prime, exponent),
        first_prime=first_prime,
        second_prime=second_prime,
        private_exponent=pow(exponent, -1, carmichael),
    )


def generate_toy_key() -> RSAPrivateSetup:
    # Choose without screening whether a later attack or simulator seed succeeds.
    first_prime, second_prime = choice(tuple(combinations(TOY_PRIMES, 2)))
    return create_toy_key(first_prime, second_prime)


def generate_standard_key(catalog_id: str = "rsa-2048") -> RSAPrivateSetup:
    sizes = {"rsa-2048": 2048, "rsa-3072": 3072}
    if not isinstance(catalog_id, str) or catalog_id not in sizes:
        raise ValueError("Select the rsa-2048 or rsa-3072 setup profile.")

    from cryptography.hazmat.primitives.asymmetric import rsa

    # Standard keys use the library's randomness and remain setup-only in this app.
    key = rsa.generate_private_key(public_exponent=65537, key_size=sizes[catalog_id])
    numbers = key.private_numbers()
    return RSAPrivateSetup(
        public=RSAPublicSetup(numbers.public_numbers.n, numbers.public_numbers.e, catalog_id),
        first_prime=numbers.p,
        second_prime=numbers.q,
        private_exponent=numbers.d,
    )