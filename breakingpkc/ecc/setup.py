"""Named educational ECC group and key setup, independent of recovery."""

from dataclasses import dataclass, field
from secrets import randbelow

from .curve import ShortWeierstrassCurve, validate_subgroup


@dataclass(frozen=True)
class ToyGroup:
    catalog_id: str
    curve: ShortWeierstrassCurve
    generator: tuple[int, int]
    order: int
    cofactor: int


# Named, checked groups fix the arithmetic and encoding supported by the toy circuit.
TOY_GROUPS = (
    ToyGroup("toy-f11-a1-b1-g0-1", ShortWeierstrassCurve(11, 1, 1), (0, 1), 7, 2),
    ToyGroup("toy-f5-a2-b1-g0-1", ShortWeierstrassCurve(5, 2, 1), (0, 1), 7, 1),
)


def get_toy_group(catalog_id: str) -> ToyGroup:
    for group in TOY_GROUPS:
        if group.catalog_id == catalog_id:
            return group
    raise ValueError("Select a named educational ECC group from the catalog.")


@dataclass(frozen=True)
class ECCPublicSetup:
    group: ToyGroup
    public_point: tuple[int, int]

    def to_dict(self) -> dict[str, str | list[str]]:
        # p is the field modulus; q is subgroup order; h relates q to curve cardinality.
        return {
            "catalog_id": self.group.catalog_id,
            "p": str(self.group.curve.prime),
            "a": str(self.group.curve.coefficient_a),
            "b": str(self.group.curve.coefficient_b),
            "G": [str(coordinate) for coordinate in self.group.generator],
            "q": str(self.group.order),
            "h": str(self.group.cofactor),
            "Q": [str(coordinate) for coordinate in self.public_point],
        }


@dataclass(frozen=True)
class ECCPrivateSetup:
    public: ECCPublicSetup
    scalar: int = field(repr=False)

    def public_attack_input(self) -> ECCPublicSetup:
        # The scalar is intentionally absent from the object supplied to recovery.
        return self.public

    def reveal_private(self) -> dict[str, str]:
        return {"k": str(self.scalar)}


def create_toy_key(
    catalog_id: str = "toy-f11-a1-b1-g0-1", scalar: int = 3
) -> ECCPrivateSetup:
    group = get_toy_group(catalog_id)
    if type(scalar) is not int or not 1 <= scalar < group.order:
        raise ValueError("The private scalar must be an integer in 1..q-1.")
    public_point = group.curve.multiply(scalar, group.generator)
    if public_point is None:
        raise ValueError("The public point must be finite.")
    validate_subgroup(group.curve, group.generator, group.order, public_point)
    # Enumerating these tiny groups makes membership explicit, beyond q*Q = infinity.
    subgroup_points = {
        group.curve.multiply(multiplier, group.generator)
        for multiplier in range(group.order)
    }
    if public_point not in subgroup_points:
        raise ValueError("The public point must belong to the selected subgroup.")
    return ECCPrivateSetup(ECCPublicSetup(group, public_point), scalar)


def generate_toy_key(catalog_id: str = "toy-f11-a1-b1-g0-1") -> ECCPrivateSetup:
    group = get_toy_group(catalog_id)
    # Sample a nonzero scalar without searching for favorable attack outcomes.
    return create_toy_key(catalog_id, randbelow(group.order - 1) + 1)