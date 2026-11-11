"""Library-backed NIST key inspection, separate from toy quantum recovery."""

from dataclasses import dataclass, field

from cryptography.hazmat.primitives.asymmetric import ec


def _curve_for_profile(catalog_id: str) -> ec.EllipticCurve:
    curves = {"nist-p256": ec.SECP256R1, "nist-p384": ec.SECP384R1}
    if not isinstance(catalog_id, str) or catalog_id not in curves:
        raise ValueError("Select the nist-p256 or nist-p384 setup profile.")
    return curves[catalog_id]()


@dataclass(frozen=True)
class StandardECCPublicSetup:
    catalog_id: str
    curve_name: str
    key_size: int
    order: int
    generator: tuple[int, int]
    public_point: tuple[int, int]

    def to_dict(self) -> dict[str, str | list[str]]:
        # Standard coordinates and subgroup orders exceed JavaScript's safe integers.
        return {
            "catalog_id": self.catalog_id,
            "curve_name": self.curve_name,
            "key_size": str(self.key_size),
            "q": str(self.order),
            "h": "1",
            "G": [str(coordinate) for coordinate in self.generator],
            "Q": [str(coordinate) for coordinate in self.public_point],
        }


@dataclass(frozen=True)
class StandardECCPrivateSetup:
    public: StandardECCPublicSetup
    scalar: int = field(repr=False)

    def public_attack_input(self) -> StandardECCPublicSetup:
        # This public-only object is separate from the scalar kept for optional reveal.
        return self.public

    def reveal_private(self) -> dict[str, str]:
        return {"k": str(self.scalar)}


def _setup_from_key(catalog_id: str, key: ec.EllipticCurvePrivateKey) -> StandardECCPrivateSetup:
    curve = key.curve
    public = key.public_key().public_numbers()
    # Multiplication by one obtains the library's canonical generator for this curve.
    generator = ec.derive_private_key(1, curve).public_key().public_numbers()
    return StandardECCPrivateSetup(
        StandardECCPublicSetup(
            catalog_id, curve.name, curve.key_size, curve.group_order,
            (generator.x, generator.y), (public.x, public.y),
        ),
        key.private_numbers().private_value,
    )


def create_standard_key(catalog_id: str, scalar: int) -> StandardECCPrivateSetup:
    curve = _curve_for_profile(catalog_id)
    # Reject noncanonical scalars rather than silently reducing them modulo q.
    if type(scalar) is not int or not 1 <= scalar < curve.group_order:
        raise ValueError("The private scalar must be an integer in 1..q-1.")
    return _setup_from_key(catalog_id, ec.derive_private_key(scalar, curve))


def generate_standard_key(catalog_id: str = "nist-p256") -> StandardECCPrivateSetup:
    curve = _curve_for_profile(catalog_id)
    return _setup_from_key(catalog_id, ec.generate_private_key(curve))