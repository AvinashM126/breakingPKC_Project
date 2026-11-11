"""Prime-field elliptic-curve and subgroup arithmetic for the ECC toy instance."""

from dataclasses import dataclass
from math import isqrt

Point = tuple[int, int] | None


@dataclass(frozen=True)
class ShortWeierstrassCurve:
    prime: int
    coefficient_a: int
    coefficient_b: int

    def contains(self, point: Point) -> bool:
        if point is None:
            return True
        x_value, y_value = point
        if not (0 <= x_value < self.prime and 0 <= y_value < self.prime):
            return False
        curve_value = x_value**3 + self.coefficient_a * x_value + self.coefficient_b
        return (y_value * y_value - curve_value) % self.prime == 0

    def add(self, first: Point, second: Point) -> Point:
        if not self.contains(first) or not self.contains(second):
            raise ValueError("Both points must lie on this curve.")
        if first is None:
            return second
        if second is None:
            return first

        first_x, first_y = first
        second_x, second_y = second
        # A vertical chord, including a point with y=0 doubled, reaches infinity.
        if first_x == second_x and (first_y + second_y) % self.prime == 0:
            return None

        if first == second:
            if first_y == 0:
                return None
            numerator = (3 * first_x * first_x + self.coefficient_a) % self.prime
            denominator = (2 * first_y) % self.prime
        else:
            numerator = (second_y - first_y) % self.prime
            denominator = (second_x - first_x) % self.prime

        slope = numerator * pow(denominator, -1, self.prime) % self.prime
        result_x = (slope * slope - first_x - second_x) % self.prime
        result_y = (slope * (first_x - result_x) - first_y) % self.prime
        return result_x, result_y

    def multiply(self, scalar: int, point: Point) -> Point:
        """Use double-and-add, reflecting the point for negative scalars."""
        if not self.contains(point):
            raise ValueError("The point must lie on this curve.")
        if scalar < 0:
            if point is None:
                return None
            return self.multiply(-scalar, (point[0], (-point[1]) % self.prime))

        result: Point = None
        addend = point
        remaining = scalar
        # Each scalar bit selects the current multiple before the addend is doubled.
        while remaining:
            if remaining & 1:
                result = self.add(result, addend)
            addend = self.add(addend, addend)
            remaining >>= 1
        return result


def is_prime(value: int) -> bool:
    if value < 2:
        return False
    if value % 2 == 0:
        return value == 2
    return all(value % divisor for divisor in range(3, isqrt(value) + 1, 2))


def validate_curve(curve: ShortWeierstrassCurve) -> None:
    if not is_prime(curve.prime):
        raise ValueError("The field modulus must be prime.")
    if not 0 <= curve.coefficient_a < curve.prime:
        raise ValueError("Curve coefficient a must be a canonical field element.")
    if not 0 <= curve.coefficient_b < curve.prime:
        raise ValueError("Curve coefficient b must be a canonical field element.")
    discriminant = (4 * curve.coefficient_a**3 + 27 * curve.coefficient_b**2) % curve.prime
    if discriminant == 0:
        raise ValueError("The curve is singular over this field.")


def validate_subgroup(
    curve: ShortWeierstrassCurve,
    base_point: Point,
    order: int,
    public_point: Point,
) -> None:
    validate_curve(curve)
    if not curve.contains(base_point) or base_point is None:
        raise ValueError("The base point must be a finite point on the curve.")
    if not is_prime(order):
        raise ValueError("The declared subgroup order must be prime.")
    # A finite generator annihilated by prime q has exactly order q.
    if curve.multiply(order, base_point) is not None:
        raise ValueError("The base point does not have an order dividing q.")
    if public_point is None or not curve.contains(public_point):
        raise ValueError("The public point must be finite and lie on the curve.")
    if curve.multiply(order, public_point) is not None:
        raise ValueError("The public point is not in the declared subgroup.")


CURVE = ShortWeierstrassCurve(prime=11, coefficient_a=1, coefficient_b=1)
BASE_POINT: Point = (0, 1)
SUBGROUP_ORDER = 7
PUBLIC_POINT: Point = (6, 6)


def validate_default_instance() -> None:
    validate_subgroup(CURVE, BASE_POINT, SUBGROUP_ORDER, PUBLIC_POINT)
