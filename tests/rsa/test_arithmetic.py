# Verify full-space permutations and measurement-derived periods before workflow integration.
import builtins
from math import gcd
from unittest.mock import patch

import pytest

from breakingpkc.rsa.arithmetic import (
    decode_phase_counts,
    infer_order,
    modular_multiplication_map,
    phase_denominator,
    recover_factors,
)
from breakingpkc.rsa.instance import DEFAULT_INSTANCE, RSAInstance


def test_modular_multiplier_is_a_permutation_over_all_work_states() -> None:
    mapping = modular_multiplication_map(multiplier=2, modulus=15, width=4)

    assert mapping == tuple((2 * state) % 15 if state < 15 else state for state in range(16))
    assert len(set(mapping)) == 16
    assert mapping[15] == 15


def test_multiplier_rejects_noninvertible_values() -> None:
    with pytest.raises(ValueError, match="invertible"):
        modular_multiplication_map(multiplier=3, modulus=15, width=4)


def test_count_strings_decode_to_phase_integers() -> None:
    counts = decode_phase_counts({"01000000": 4, "11000000": 2}, phase_qubits=8)

    assert counts == {64: 4, 192: 2}


def test_phase_denominators_and_order_candidate_follow_observations() -> None:
    assert phase_denominator(64, 8) == 4
    assert phase_denominator(128, 8) == 2
    assert phase_denominator(0, 8) == 1

    order_candidate, observations = infer_order({64: 3, 192: 2}, DEFAULT_INSTANCE, 8)

    assert order_candidate == 4
    assert [item["denominator"] for item in observations] == [4, 4]


def test_uninformative_or_invalid_order_samples_do_not_supply_fixture_order() -> None:
    no_information, _ = infer_order({0: 8}, DEFAULT_INSTANCE, 8)
    rounded_to_integer, observations = infer_order({1: 1}, DEFAULT_INSTANCE, 8)

    assert no_information is None
    assert rounded_to_integer is None
    assert observations[0]["informative"] is False


def test_continued_fraction_reconstructs_non_power_of_two_order() -> None:
    instance = RSAInstance(modulus=21, base=2)
    order_candidate, observations = infer_order({85: 1}, instance, phase_qubits=9)

    assert order_candidate == 6
    assert observations[0]["fraction_denominator"] == 6
    assert observations[0]["verified_period"] == 6


def test_order_to_factor_reduction_validates_public_modulus() -> None:
    assert recover_factors(DEFAULT_INSTANCE, order_candidate=4) == (3, 5)
    assert recover_factors(DEFAULT_INSTANCE, order_candidate=None) is None
    assert recover_factors(DEFAULT_INSTANCE, order_candidate=2) is None
    assert recover_factors(DEFAULT_INSTANCE, order_candidate=6) is None


@pytest.mark.parametrize("counts", [{84: 1}, {171: 100, 84: 1}])
def test_nonminimal_measured_period_is_reduced_using_public_checks(counts) -> None:
    instance = RSAInstance(modulus=35, base=2)
    order, observations = infer_order(counts, instance, 11)

    assert order == 12
    assert all(sample["verified_period"] in (None, 12) for sample in observations)
    assert recover_factors(instance, order) == (5, 7)


@pytest.mark.parametrize("count", [True, -1, 1.5])
def test_rsa_rejects_noncanonical_measurement_counts(count) -> None:
    with pytest.raises(ValueError, match="nonnegative integers"):
        decode_phase_counts({"01000000": count}, 8)
    with pytest.raises(ValueError, match="nonnegative integers"):
        infer_order({64: count}, DEFAULT_INSTANCE, 8)


@pytest.mark.parametrize("modulus", [15, 21, 33, 35, 39, 55])
def test_returned_orders_are_minimal_for_all_supported_public_bases(modulus) -> None:
    width = (modulus * modulus - 1).bit_length()
    limit = 1 << width
    for base in range(2, modulus):
        if gcd(base, modulus) != 1:
            continue
        expected = next(exponent for exponent in range(1, modulus) if pow(base, exponent, modulus) == 1)
        instance = RSAInstance(modulus, base)
        counts = {phase: 1 for phase in range(1, limit, max(1, limit // 31))}
        order, observations = infer_order(counts, instance, width)
        assert order in (None, expected)
        assert all(sample["verified_period"] in (None, expected) for sample in observations)


def test_order_inference_reuses_modular_checks_within_each_call() -> None:
    # Compare complete observations while counting repeated modular-exponent arguments.
    counts = {phase: 1 for phase in range(512)}
    instance = RSAInstance(modulus=21, base=2)
    expected = infer_order(counts, instance, 9)
    with patch("breakingpkc.rsa.arithmetic.pow", wraps=builtins.pow, create=True) as modular_power:
        assert infer_order(counts, instance, 9) == expected

    arguments = [call.args for call in modular_power.call_args_list]
    assert len(arguments) == len(set(arguments))
