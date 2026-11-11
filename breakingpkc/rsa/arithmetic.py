"""RSA-specific modular arithmetic and classical order-to-factor reduction."""

from fractions import Fraction
from math import gcd

from .instance import RSAInstance


def modular_multiplication_map(multiplier: int, modulus: int, width: int) -> tuple[int, ...]:
    """Return the reversible basis-state map for multiplication modulo N.

    Encoded states below N are multiplied modulo N. Unused states at or above N
    are fixed points, giving a permutation over the complete 2**width space.
    """
    if modulus < 2 or width < 1 or (1 << width) < modulus:
        raise ValueError("The register width must encode every residue modulo N.")
    if not 0 <= multiplier < modulus or gcd(multiplier, modulus) != 1:
        raise ValueError("The multiplier must be invertible modulo N.")

    state_count = 1 << width
    mapping = tuple(
        (multiplier * state) % modulus if state < modulus else state
        for state in range(state_count)
    )
    if len(set(mapping)) != state_count:
        raise ValueError("The modular multiplication extension is not reversible.")
    return mapping


def decode_phase_counts(
    counts: dict[str, int], phase_qubits: int
) -> dict[int, int]:
    """Decode Qiskit count strings into little-endian phase integers."""
    if type(phase_qubits) is not int or phase_qubits < 1:
        raise ValueError("At least one phase qubit is required.")

    decoded: dict[int, int] = {}
    for bitstring, count in counts.items():
        compact_bits = bitstring.replace(" ", "")
        if len(compact_bits) != phase_qubits or set(compact_bits) - {"0", "1"}:
            raise ValueError(f"Unexpected phase-register count key: {bitstring!r}")
        if type(count) is not int or count < 0:
            raise ValueError("Measurement counts must be nonnegative integers.")
        # Qiskit's displayed bitstring is MSB-first even for a little-endian register.
        phase_value = int(compact_bits, 2)
        decoded[phase_value] = decoded.get(phase_value, 0) + count
    return decoded


def phase_denominator(phase_value: int, phase_qubits: int) -> int:
    """Reduce the observed phase y/2**m to its exact rational denominator."""
    phase_limit = 1 << phase_qubits
    if phase_qubits < 1 or not 0 <= phase_value < phase_limit:
        raise ValueError("The phase value is outside the measured register range.")
    return Fraction(phase_value, phase_limit).denominator


def infer_order(
    phase_counts: dict[int, int], instance: RSAInstance, phase_qubits: int
) -> tuple[int | None, list[dict[str, int | bool | None]]]:
    """Reconstruct and verify periods from measured phases using bounded fractions."""
    if type(phase_qubits) is not int or phase_qubits < 1:
        raise ValueError("At least one phase qubit is required.")
    observations: list[dict[str, int | bool | None]] = []
    verified_periods: list[int] = []
    phase_limit = 1 << phase_qubits
    # Different measured fractions can propose the same modular exponent.
    period_checks: dict[int, bool] = {}

    def is_period(exponent: int) -> bool:
        if exponent not in period_checks:
            period_checks[exponent] = pow(instance.base, exponent, instance.modulus) == 1
        return period_checks[exponent]

    def minimal_order(period: int) -> int:
        remaining = period
        divisor = 2
        prime_divisors: list[int] = []
        while divisor * divisor <= remaining:
            if remaining % divisor == 0:
                prime_divisors.append(divisor)
                while remaining % divisor == 0:
                    remaining //= divisor
            divisor += 1
        if remaining > 1:
            prime_divisors.append(remaining)
        for prime_divisor in prime_divisors:
            while period % prime_divisor == 0 and is_period(period // prime_divisor):
                period //= prime_divisor
        return period

    for phase_value, count in sorted(phase_counts.items()):
        if type(count) is not int or count < 0:
            raise ValueError("Measurement counts must be nonnegative integers.")
        if type(phase_value) is not int or not 0 <= phase_value < phase_limit:
            raise ValueError("A measured phase is outside the register range.")
        if count == 0:
            continue
        measured_fraction = Fraction(phase_value, phase_limit)
        denominator = measured_fraction.denominator
        informative = phase_value != 0
        fraction_denominator: int | None = None
        period_candidate: int | None = None
        if informative:
            # Approximate the measured phase without using a known order or factors.
            fraction_denominator = measured_fraction.limit_denominator(
                instance.modulus - 1
            ).denominator
            informative = fraction_denominator > 1
            if informative:
                for candidate in range(
                    fraction_denominator,
                    instance.modulus,
                    fraction_denominator,
                ):
                    if is_period(candidate):
                        period_candidate = minimal_order(candidate)
                        break
        observations.append(
            {
                "phase": phase_value,
                "count": count,
                "numerator": measured_fraction.numerator,
                "denominator": denominator,
                "informative": informative,
                "fraction_denominator": fraction_denominator,
                "verified_period": period_candidate,
            }
        )
        if period_candidate is not None:
            verified_periods.append(period_candidate)

    if not verified_periods:
        return None, observations

    order_candidate = gcd(*verified_periods)
    if order_candidate >= instance.modulus:
        return None, observations
    if not is_period(order_candidate):
        return None, observations
    return order_candidate, observations


def recover_factors(
    instance: RSAInstance, order_candidate: int | None
) -> tuple[int, int] | None:
    """Apply Shor's classical order-to-factors reduction and validate the pair."""
    if order_candidate is None or order_candidate % 2 != 0:
        return None
    if pow(instance.base, order_candidate, instance.modulus) != 1:
        return None

    # Only a nontrivial square root of one can supply useful gcd(x-1,N), gcd(x+1,N).
    square_root_of_one = pow(instance.base, order_candidate // 2, instance.modulus)
    if square_root_of_one in (1, instance.modulus - 1):
        return None

    first_factor = gcd(square_root_of_one - 1, instance.modulus)
    second_factor = gcd(square_root_of_one + 1, instance.modulus)
    if first_factor <= 1 or second_factor <= 1:
        return None
    if first_factor >= instance.modulus or second_factor >= instance.modulus:
        return None
    if first_factor == second_factor or first_factor * second_factor != instance.modulus:
        return None
    return tuple(sorted((first_factor, second_factor)))
