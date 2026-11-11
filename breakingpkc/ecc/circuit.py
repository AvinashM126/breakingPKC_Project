"""Fixed-instance reversible ECC oracle and seven-dimensional Fourier circuit."""

from math import cos, pi, sin, sqrt

from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister
from qiskit.circuit.library import UnitaryGate

from .curve import (
    BASE_POINT,
    CURVE,
    PUBLIC_POINT,
    SUBGROUP_ORDER,
    Point,
    ShortWeierstrassCurve,
    validate_default_instance,
    validate_subgroup,
)

EXPONENT_WIDTH = 3
# Two four-bit coordinates share this register; 0xFF is reserved for infinity.
OUTPUT_WIDTH = 8


def encode_point(point: Point, prime: int = 11) -> int:
    """Encode toy-curve points in two nibbles and infinity as 0xFF."""
    if point is None:
        return 0xFF
    x_value, y_value = point
    if not (0 <= x_value < prime and 0 <= y_value < prime and prime <= 16):
        raise ValueError("Point coordinates must fit the toy two-nibble encoding.")
    return (x_value << 4) | y_value


def fourier_7_embedded_matrix() -> list[list[complex]]:
    """Return the exact F_7 block embedded in an 8-state register as diag(F_7, 1)."""
    matrix = [[0j] * 8 for _ in range(8)]
    for frequency in range(7):
        for value in range(7):
            angle = 2 * pi * frequency * value / 7
            matrix[frequency][value] = complex(cos(angle), sin(angle)) / sqrt(7)
    # The unused encoded state |7> stays fixed outside the order-7 transform.
    matrix[7][7] = 1.0 + 0.0j
    return matrix


def _append_point_oracle(
    circuit: QuantumCircuit,
    exponent_a: QuantumRegister,
    exponent_b: QuantumRegister,
    output: QuantumRegister,
    curve: ShortWeierstrassCurve = CURVE,
    base_point: Point = BASE_POINT,
    public_point: Point = PUBLIC_POINT,
    order: int = SUBGROUP_ORDER,
) -> None:
    """Append a reversible XOR oracle compiled from public group operations."""
    controls = [*exponent_a, *exponent_b]
    # Oracle inputs are public points; the hidden scalar is never consulted.
    base_multiples = [curve.multiply(value, base_point) for value in range(order)]
    public_multiples = [curve.multiply(value, public_point) for value in range(order)]
    for a_value, point_a in enumerate(base_multiples):
        for b_value, point_b in enumerate(public_multiples):
            encoded_point = encode_point(curve.add(point_a, point_b), curve.prime)
            control_values = [
                (a_value >> bit_index) & 1 for bit_index in range(EXPONENT_WIDTH)
            ] + [
                (b_value >> bit_index) & 1 for bit_index in range(EXPONENT_WIDTH)
            ]
            negative_controls = [
                control
                for control, bit_value in zip(controls, control_values)
                if bit_value == 0
            ]
            # X-conjugation implements the zero-valued controls for this table row.
            circuit.x(negative_controls)
            for output_bit in range(OUTPUT_WIDTH):
                if (encoded_point >> output_bit) & 1:
                    circuit.mcx(controls, output[output_bit])
            circuit.x(negative_controls)


def build_discrete_log_circuit(
    measure: bool = True,
    *,
    curve: ShortWeierstrassCurve = CURVE,
    base_point: Point = BASE_POINT,
    public_point: Point = PUBLIC_POINT,
    order: int = SUBGROUP_ORDER,
) -> QuantumCircuit:
    """Build the order-7 ECDLP sampler for a named toy group and public key."""
    if (
        curve == CURVE
        and base_point == BASE_POINT
        and public_point == PUBLIC_POINT
        and order == SUBGROUP_ORDER
    ):
        validate_default_instance()
    else:
        if order != 7:
            raise ValueError("The current ECC circuit supports toy subgroups of order 7 only.")
        validate_subgroup(curve, base_point, order, public_point)
    exponent_a = QuantumRegister(EXPONENT_WIDTH, "a")
    exponent_b = QuantumRegister(EXPONENT_WIDTH, "b")
    point_output = QuantumRegister(OUTPUT_WIDTH, "point")
    if measure:
        point_classical = ClassicalRegister(OUTPUT_WIDTH, "point_result")
        a_classical = ClassicalRegister(EXPONENT_WIDTH, "a_result")
        b_classical = ClassicalRegister(EXPONENT_WIDTH, "b_result")
        circuit = QuantumCircuit(
            exponent_a,
            exponent_b,
            point_output,
            point_classical,
            a_classical,
            b_classical,
        )
    else:
        circuit = QuantumCircuit(exponent_a, exponent_b, point_output)

    # Populate q=7 valid exponents, leaving the eighth encoded state unoccupied.
    seven_state = [1 / sqrt(7)] * 7 + [0.0]
    circuit.initialize(seven_state, exponent_a)
    circuit.initialize(seven_state, exponent_b)
    _append_point_oracle(
        circuit,
        exponent_a,
        exponent_b,
        point_output,
        curve,
        base_point,
        public_point,
        order,
    )

    if measure:
        circuit.measure(point_output, point_classical)

    fourier_gate = UnitaryGate(fourier_7_embedded_matrix(), label="F7_embedded_8")
    circuit.append(fourier_gate, exponent_a)
    circuit.append(fourier_gate, exponent_b)

    if measure:
        circuit.measure(exponent_a, a_classical)
        circuit.measure(exponent_b, b_classical)
    return circuit
