# Check the public modulus catalog and reject invalid circuit inputs at its boundary.
import pytest

from breakingpkc.rsa.instance import (
    RSA_TOY_CATALOG,
    RSAInstance,
    modulus_from_catalog,
    validate_instance,
)


def test_default_rsa_instance_is_valid() -> None:
    validate_instance(RSAInstance(modulus=15, base=2))


def test_curated_modulus_catalog_contains_only_supported_small_semiprimes() -> None:
    assert tuple(RSA_TOY_CATALOG.values()) == (15, 21, 33, 35, 39, 55)
    assert [modulus_from_catalog(catalog_id) for catalog_id in RSA_TOY_CATALOG] == [
        15, 21, 33, 35, 39, 55,
    ]


@pytest.mark.parametrize("catalog_id", ["rsa-n77-v1", "rsa-n2048-v1", None, []])
def test_unknown_modulus_catalog_entries_are_rejected(catalog_id) -> None:
    with pytest.raises(ValueError, match="catalog"):
        modulus_from_catalog(catalog_id)


@pytest.mark.parametrize(
    "instance",
    [
        RSAInstance(modulus=3, base=2),
        RSAInstance(modulus=13, base=2),
        RSAInstance(modulus=15, base=5),
        RSAInstance(modulus=15, base=15),
    ],
)
def test_invalid_rsa_instances_are_rejected(instance: RSAInstance) -> None:
    with pytest.raises(ValueError):
        validate_instance(instance)
