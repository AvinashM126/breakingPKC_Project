"""ECC-specific measurement interpretation and discrete-log validation."""

from typing import Any

from .curve import (
    BASE_POINT,
    CURVE,
    PUBLIC_POINT,
    SUBGROUP_ORDER,
    Point,
    ShortWeierstrassCurve,
)


def decode_frequency_counts(
    counts: dict[str, int], exponent_width: int = 3
) -> dict[tuple[int, int], int]:
    """Decode separate a/b classical-register fields into frequencies.

    Qiskit displays classical registers right-to-left. With registers declared
    as point_result, a_result, b_result, the displayed fields are b, a, point.
    Each field is most-significant-bit first and already represents its
    little-endian-register integer value in conventional binary notation.
    """
    expected_width = 8 + 2 * exponent_width
    decoded: dict[tuple[int, int], int] = {}
    for bitstring, count in counts.items():
        compact_bits = bitstring.replace(" ", "")
        if len(compact_bits) != expected_width or set(compact_bits) - {"0", "1"}:
            raise ValueError(f"Unexpected ECC count key: {bitstring!r}")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError("Measurement counts must be nonnegative integers.")

        b_display = compact_bits[:exponent_width]
        a_display = compact_bits[exponent_width : 2 * exponent_width]
        frequency_u = int(a_display, 2)
        frequency_v = int(b_display, 2)
        pair = (frequency_u, frequency_v)
        decoded[pair] = decoded.get(pair, 0) + count
    return decoded


def analyze_frequency_counts(
    frequency_counts: dict[tuple[int, int], int],
    curve: ShortWeierstrassCurve = CURVE,
    base_point: Point = BASE_POINT,
    public_point: Point = PUBLIC_POINT,
    order: int = SUBGROUP_ORDER,
) -> tuple[list[dict[str, Any]], str, str, list[dict[str, Any]]]:
    """Interpret frequencies once for both recovery and presentation evidence."""
    candidates: dict[int, dict[str, Any]] = {}
    observations: list[dict[str, Any]] = []
    # Checks belong to this public instance, never to another key or later run.
    scalar_validation: dict[int, bool] = {}
    inverses: dict[int, int] = {}
    for (frequency_u, frequency_v), count in sorted(frequency_counts.items()):
        if type(count) is not int or count < 0:
            raise ValueError("Measurement counts must be nonnegative integers.")
        if type(frequency_u) is not int or type(frequency_v) is not int:
            raise ValueError("Frequencies must be integers.")
        if count == 0:
            continue
        if not (0 <= frequency_u < order and 0 <= frequency_v < order):
            observations.append(
                {
                    "u": frequency_u,
                    "v": frequency_v,
                    "count": count,
                    "status": "invalid_frequency",
                    "candidate": None,
                }
            )
            continue
        # Zero u cannot be inverted, so this pair cannot determine a scalar candidate.
        if frequency_u == 0:
            observations.append(
                {
                    "u": frequency_u,
                    "v": frequency_v,
                    "count": count,
                    "status": "uninformative",
                    "candidate": None,
                }
            )
            continue

        # For nonzero u, the Fourier constraint gives k = v * u^(-1) mod q.
        if frequency_u not in inverses:
            inverses[frequency_u] = pow(frequency_u, -1, order)
        scalar_candidate = frequency_v * inverses[frequency_u] % order
        if scalar_candidate not in scalar_validation:
            scalar_validation[scalar_candidate] = (
                curve.multiply(scalar_candidate, base_point) == public_point
            )
        is_valid = scalar_validation[scalar_candidate]
        observation_status = "validated" if is_valid else "rejected"
        observations.append(
            {
                "u": frequency_u,
                "v": frequency_v,
                "count": count,
                "status": observation_status,
                "candidate": scalar_candidate,
                "validation": is_valid,
            }
        )
        if is_valid:
            candidate_data = candidates.setdefault(
                scalar_candidate,
                {"kind": "discrete_log_scalar", "value": scalar_candidate, "count": 0},
            )
            candidate_data["count"] += count

    # Supporting shot counts describe observations; public-point checks decide validity.
    candidate_list = [candidates[value] for value in sorted(candidates)]
    if len(candidate_list) == 1:
        status = "recovered"
        summary = (
            f"Recovered scalar {candidate_list[0]['value']} from measured frequencies; "
            "the public point relation passed validation."
        )
    elif len(candidate_list) > 1:
        status = "ambiguous"
        summary = "Multiple distinct measured candidates satisfy the public point relation."
    elif observations and all(item["status"] == "uninformative" for item in observations):
        status = "failed"
        summary = "All measured frequency samples were uninformative."
    else:
        status = "failed"
        summary = "No measured frequency produced a validated scalar candidate."
    return candidate_list, status, summary, observations


def recover_scalar_from_frequencies(
    frequency_counts: dict[tuple[int, int], int],
    curve: ShortWeierstrassCurve = CURVE,
    base_point: Point = BASE_POINT,
    public_point: Point = PUBLIC_POINT,
    order: int = SUBGROUP_ORDER,
) -> tuple[list[dict[str, Any]], str, str]:
    """Recover candidates from measured Fourier frequencies and public Q,G,q."""
    candidates, status, summary, _ = analyze_frequency_counts(
        frequency_counts, curve, base_point, public_point, order
    )
    return candidates, status, summary
