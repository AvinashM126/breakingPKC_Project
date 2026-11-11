# Establish toy group-law and validation properties independently of quantum circuits.
import pytest

from breakingpkc.ecc.curve import (
    BASE_POINT,
    CURVE,
    PUBLIC_POINT,
    SUBGROUP_ORDER,
    ShortWeierstrassCurve,
    validate_default_instance,
    validate_subgroup,
)


def test_default_curve_and_subgroup_validate() -> None:
    validate_default_instance()
    assert CURVE.multiply(SUBGROUP_ORDER, BASE_POINT) is None
    assert CURVE.multiply(3, BASE_POINT) == PUBLIC_POINT


def test_point_addition_has_identity_inverse_and_associativity_on_fixture() -> None:
    identity = None
    points = [CURVE.multiply(scalar, BASE_POINT) for scalar in range(SUBGROUP_ORDER)]

    for point in points:
        assert CURVE.add(point, identity) == point
        if point is None:
            continue
        inverse = (point[0], (-point[1]) % CURVE.prime)
        assert CURVE.add(point, inverse) is None

    for first in points:
        for second in points:
            for third in points:
                assert CURVE.add(CURVE.add(first, second), third) == CURVE.add(
                    first, CURVE.add(second, third)
                )


def test_curve_rejects_composite_field_and_singular_curve() -> None:
    with pytest.raises(ValueError, match="prime"):
        validate_subgroup(
            ShortWeierstrassCurve(prime=9, coefficient_a=1, coefficient_b=1),
            (0, 1),
            7,
            (6, 6),
        )
    with pytest.raises(ValueError, match="singular"):
        validate_subgroup(
            ShortWeierstrassCurve(prime=11, coefficient_a=0, coefficient_b=0),
            (0, 0),
            7,
            (0, 0),
        )


def test_subgroup_validation_rejects_invalid_points_and_order() -> None:
    with pytest.raises(ValueError, match="prime"):
        validate_subgroup(CURVE, BASE_POINT, 6, PUBLIC_POINT)
    with pytest.raises(ValueError, match="curve"):
        validate_subgroup(CURVE, (1, 1), SUBGROUP_ORDER, PUBLIC_POINT)
