# Synthetic frequency counts exercise decoding, scalar validation, and cache behavior.
from unittest.mock import patch

import pytest

from breakingpkc.ecc.arithmetic import (
    analyze_frequency_counts,
    decode_frequency_counts,
    recover_scalar_from_frequencies,
)
from breakingpkc.ecc.curve import ShortWeierstrassCurve


def test_frequency_count_decoder_maps_little_endian_register_bits() -> None:
    # Register display is b_result, a_result, point_result; 3 is 011 and 1 is 001.
    counts = decode_frequency_counts({"01100100000000": 5})

    assert counts == {(1, 3): 5}


def test_frequency_recovery_skips_zero_u_and_validates_public_relation() -> None:
    candidates, status, summary = recover_scalar_from_frequencies(
        {
            (0, 0): 4,
            (1, 3): 8,
            (2, 6): 5,
        }
    )

    assert status == "recovered"
    assert candidates == [{"kind": "discrete_log_scalar", "value": 3, "count": 13}]
    assert "public point relation passed" in summary


def test_uninformative_or_invalid_frequencies_do_not_recover() -> None:
    candidates, status, _ = recover_scalar_from_frequencies({(0, 0): 8})
    assert candidates == []
    assert status == "failed"

    candidates, status, _ = recover_scalar_from_frequencies({(8, 1): 2})
    assert candidates == []
    assert status == "failed"


def test_frequency_analysis_reuses_validation_for_equal_scalar_candidates() -> None:
    # Distinct measured pairs can imply the same scalar and should share its point check.
    counts = {(frequency, 3 * frequency % 7): 2 for frequency in range(1, 7)}
    original_multiply = ShortWeierstrassCurve.multiply
    with patch.object(
        ShortWeierstrassCurve, "multiply", autospec=True, side_effect=original_multiply
    ) as multiply:
        candidates, status, summary, observations = analyze_frequency_counts(counts)

    assert multiply.call_count == 1
    assert candidates == [{"kind": "discrete_log_scalar", "value": 3, "count": 12}]
    assert all(observation["status"] == "validated" for observation in observations)
    assert recover_scalar_from_frequencies(counts) == (candidates, status, summary)


def test_inconsistent_frequency_is_rejected_by_public_point_check() -> None:
    candidates, status, _ = recover_scalar_from_frequencies({(1, 2): 3})

    assert candidates == []
    assert status == "failed"


@pytest.mark.parametrize("count", [True, -1, 1.5])
def test_frequency_analyzer_rejects_noncanonical_counts(count) -> None:
    with pytest.raises(ValueError, match="nonnegative integers"):
        analyze_frequency_counts({(1, 3): count})
    with pytest.raises(ValueError, match="nonnegative integers"):
        decode_frequency_counts({"01100100000000": count})
