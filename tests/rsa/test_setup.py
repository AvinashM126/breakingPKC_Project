# Verify toy/standard key relationships without using setup secrets to drive recovery.
import json
from itertools import combinations
from math import gcd, lcm

import pytest

from breakingpkc.rsa.setup import (
    TOY_PRIMES,
    allowed_exponents,
    create_toy_key,
    generate_standard_key,
    generate_toy_key,
)


def test_all_curated_prime_pairs_and_exponents_have_valid_key_relationships() -> None:
    # Check every supported setup combination instead of assuming the default generalizes.
    for first_prime, second_prime in combinations(TOY_PRIMES, 2):
        for exponent in allowed_exponents(first_prime, second_prime):
            setup = create_toy_key(first_prime, second_prime, exponent)
            carmichael = lcm(first_prime - 1, second_prime - 1)
            assert setup.public.modulus == first_prime * second_prime
            assert gcd(exponent, carmichael) == 1
            assert exponent * setup.private_exponent % carmichael == 1


def test_guided_setup_and_public_projection_exclude_private_components() -> None:
    setup = create_toy_key()
    assert setup.public_attack_input().to_dict() == {
        "catalog_id": "rsa-toy-primes-v1", "N": "15", "e": "3",
    }
    assert set(vars(setup.public_attack_input())) == {
        "modulus", "public_exponent", "catalog_id",
    }
    assert "private_exponent=" not in repr(setup)
    assert "first_prime=" not in repr(setup)
    assert setup.reveal_private() == {
        "p": "3", "q": "5", "d": "3", "phi": "8", "lambda": "4",
    }


@pytest.mark.parametrize("first,second,exponent", [
    (3, 3, None), (2, 5, None), (True, 5, None), (3, 5, 2), (3, 5, True),
])
def test_invalid_or_stale_setup_selections_are_rejected(first, second, exponent) -> None:
    with pytest.raises(ValueError):
        create_toy_key(first, second, exponent)


def test_generated_key_stays_in_the_catalog() -> None:
    setup = generate_toy_key()
    assert setup.first_prime in TOY_PRIMES
    assert setup.second_prime in TOY_PRIMES
    assert setup.first_prime != setup.second_prime


@pytest.mark.parametrize("catalog_id,bits", [("rsa-2048", 2048), ("rsa-3072", 3072)])
def test_standard_setup_has_valid_keys_and_public_only_serialization(catalog_id, bits) -> None:
    setup = generate_standard_key(catalog_id)
    public = setup.public_attack_input()
    assert public.modulus.bit_length() == bits
    assert public.public_exponent == 65537
    assert setup.first_prime != setup.second_prime
    assert setup.first_prime * setup.second_prime == public.modulus
    assert public.public_exponent * setup.private_exponent % lcm(
        setup.first_prime - 1, setup.second_prime - 1
    ) == 1
    serialized = json.loads(json.dumps(public.to_dict()))
    assert set(serialized) == {"catalog_id", "N", "e"}
    assert int(serialized["N"]) == public.modulus
    assert all(isinstance(value, str) for value in serialized.values())
    assert "private_exponent=" not in repr(setup)
    assert int(setup.reveal_private()["d"]) == setup.private_exponent


@pytest.mark.parametrize("catalog_id", ["rsa-1024", "rsa-4096", 2048, ["rsa-2048"]])
def test_standard_setup_rejects_unknown_profiles(catalog_id) -> None:
    with pytest.raises(ValueError, match="profile"):
        generate_standard_key(catalog_id)