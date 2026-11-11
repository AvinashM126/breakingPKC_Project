# Verify key derivation, exact public serialization, and private-scalar separation.
import json

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from breakingpkc.ecc.setup import TOY_GROUPS, create_toy_key, generate_toy_key
from breakingpkc.ecc.standard_setup import create_standard_key, generate_standard_key


def test_all_curated_scalars_derive_valid_distinct_public_points() -> None:
    # Exhaust the tiny allowed scalar range rather than sampling only the guided key.
    for group in TOY_GROUPS:
        public_points = set()
        for scalar in range(1, group.order):
            setup = create_toy_key(group.catalog_id, scalar)
            assert setup.public.public_point == group.curve.multiply(scalar, group.generator)
            assert group.curve.multiply(group.order, setup.public.public_point) is None
            public_points.add(setup.public.public_point)
        assert len(public_points) == group.order - 1
        point_count = 1 + sum(
            group.curve.contains((first, second))
            for first in range(group.curve.prime)
            for second in range(group.curve.prime)
        )
        assert point_count == group.order * group.cofactor


def test_guided_public_projection_and_explicit_private_reveal() -> None:
    setup = create_toy_key()
    public = setup.public_attack_input()
    assert set(vars(public)) == {"group", "public_point"}
    assert public.to_dict() == {
        "catalog_id": "toy-f11-a1-b1-g0-1",
        "p": "11", "a": "1", "b": "1", "G": ["0", "1"],
        "q": "7", "h": "2", "Q": ["6", "6"],
    }
    assert "scalar=" not in repr(setup)
    assert setup.reveal_private() == {"k": "3"}


@pytest.mark.parametrize("scalar", [0, 7, -1, True, 3.0, "3"])
def test_invalid_scalars_are_rejected_without_normalization(scalar) -> None:
    with pytest.raises(ValueError):
        create_toy_key(scalar=scalar)


def test_unknown_group_is_rejected() -> None:
    with pytest.raises(ValueError, match="catalog"):
        create_toy_key("arbitrary-curve", 3)


def test_generated_keys_stay_in_the_selected_group() -> None:
    for group in TOY_GROUPS:
        setup = generate_toy_key(group.catalog_id)
        assert 1 <= setup.scalar < group.order
        assert setup.public.group is group


@pytest.mark.parametrize(
    "catalog_id,curve_type", [("nist-p256", ec.SECP256R1), ("nist-p384", ec.SECP384R1)]
)
def test_standard_setup_scalar_boundaries_and_public_projection(catalog_id, curve_type) -> None:
    curve = curve_type()
    for scalar in (1, curve.group_order - 1):
        setup = create_standard_key(catalog_id, scalar)
        public = setup.public_attack_input()
        expected = ec.derive_private_key(scalar, curve).public_key().public_numbers()
        assert public.public_point == (expected.x, expected.y)
        assert public.curve_name == curve.name
        assert public.key_size == curve.key_size
        assert public.order == curve.group_order
        if scalar == 1:
            assert public.public_point == public.generator
        serialized = json.loads(json.dumps(public.to_dict()))
        assert set(serialized) == {"catalog_id", "curve_name", "key_size", "q", "h", "G", "Q"}
        assert serialized["Q"] == [str(expected.x), str(expected.y)]
        assert isinstance(serialized["q"], str)
        assert "scalar=" not in repr(setup)
        assert setup.reveal_private() == {"k": str(scalar)}
    for invalid in (0, -1, curve.group_order, curve.group_order + 1, True, 1.0, "1"):
        with pytest.raises(ValueError, match="scalar"):
            create_standard_key(catalog_id, invalid)


@pytest.mark.parametrize("catalog_id", ["nist-p256", "nist-p384"])
def test_generated_standard_setup_matches_private_scalar(catalog_id) -> None:
    setup = generate_standard_key(catalog_id)
    assert 1 <= setup.scalar < setup.public.order
    assert create_standard_key(catalog_id, setup.scalar).public == setup.public


@pytest.mark.parametrize("catalog_id", ["secp256k1", "toy-f11-a1-b1-g0-1", None, []])
def test_standard_setup_rejects_unknown_profiles(catalog_id) -> None:
    with pytest.raises(ValueError, match="profile"):
        generate_standard_key(catalog_id)