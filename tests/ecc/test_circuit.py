# Check reversible oracle/Fourier behavior directly, not merely successful final recovery.
from math import sqrt
from unittest.mock import MagicMock, patch

import pytest
from qiskit import QuantumCircuit, QuantumRegister
from qiskit.quantum_info import Operator, Statevector

from breakingpkc.ecc.circuit import (
    EXPONENT_WIDTH,
    OUTPUT_WIDTH,
    _append_point_oracle,
    build_discrete_log_circuit,
    encode_point,
    fourier_7_embedded_matrix,
)
from breakingpkc.ecc.curve import (
    BASE_POINT,
    CURVE,
    PUBLIC_POINT,
    SUBGROUP_ORDER,
    ShortWeierstrassCurve,
)
from breakingpkc.ecc.setup import get_toy_group


def test_point_encoding_handles_finite_points_and_infinity() -> None:
    assert encode_point((6, 6)) == 0x66
    assert encode_point(None) == 0xFF


def test_oracle_precomputes_each_public_multiple_once() -> None:
    original_multiply = ShortWeierstrassCurve.multiply
    with patch.object(
        ShortWeierstrassCurve, "multiply", autospec=True, side_effect=original_multiply
    ) as multiply:
        _append_point_oracle(MagicMock(), list(range(3)), list(range(3, 6)), list(range(6, 14)))

    assert multiply.call_count == 2 * SUBGROUP_ORDER


def test_embedded_fourier_matrix_is_unitary_and_leaves_unused_state_unchanged() -> None:
    matrix = fourier_7_embedded_matrix()
    operator = Operator(matrix)

    assert operator.is_unitary()
    assert matrix[7][7] == 1
    assert all(matrix[7][index] == 0 for index in range(7))
    assert all(matrix[index][7] == 0 for index in range(7))


def test_public_point_oracle_maps_all_valid_exponent_pairs_from_public_group_math() -> None:
    # Expected outputs come from public curve operations over every valid exponent pair.
    exponent_a = QuantumRegister(EXPONENT_WIDTH, "a")
    exponent_b = QuantumRegister(EXPONENT_WIDTH, "b")
    point_output = QuantumRegister(OUTPUT_WIDTH, "point")
    oracle_circuit = QuantumCircuit(exponent_a, exponent_b, point_output)
    valid_state = [1 / sqrt(SUBGROUP_ORDER)] * SUBGROUP_ORDER + [0.0]
    oracle_circuit.initialize(valid_state, exponent_a)
    oracle_circuit.initialize(valid_state, exponent_b)
    _append_point_oracle(oracle_circuit, exponent_a, exponent_b, point_output)
    final_state = Statevector.from_instruction(oracle_circuit)

    observed_pairs = set()
    for a_value in range(SUBGROUP_ORDER):
        for b_value in range(SUBGROUP_ORDER):
            point = CURVE.add(
                CURVE.multiply(a_value, BASE_POINT),
                CURVE.multiply(b_value, PUBLIC_POINT),
            )
            encoded_point = encode_point(point)
            basis_index = (
                (encoded_point << (2 * EXPONENT_WIDTH))
                | (b_value << EXPONENT_WIDTH)
                | a_value
            )
            assert final_state.data[basis_index] == pytest.approx(complex(1 / SUBGROUP_ORDER, 0))
            observed_pairs.add((a_value, b_value))

    assert len(observed_pairs) == SUBGROUP_ORDER**2
    assert sum(abs(amplitude) ** 2 for amplitude in final_state.data) == pytest.approx(1.0)


def test_qft_sampling_support_is_the_expected_public_frequency_relation() -> None:
    # The known fixture relation is an assertion here, never an input to the sampler.
    circuit = build_discrete_log_circuit(measure=False)
    final_state = Statevector.from_instruction(circuit)
    exponent_qubits = [
        circuit.find_bit(qubit).index
        for qubit in [*circuit.qregs[0], *circuit.qregs[1]]
    ]
    probabilities = final_state.probabilities(qargs=exponent_qubits)
    observed_support = {
        (frequency_a, frequency_b)
        for frequency_b in range(8)
        for frequency_a in range(8)
        if probabilities[frequency_a | (frequency_b << EXPONENT_WIDTH)] > 1e-9
    }
    expected_support = {(u, (3 * u) % SUBGROUP_ORDER) for u in range(SUBGROUP_ORDER)}

    assert observed_support == expected_support
    for frequency_a, frequency_b in expected_support:
        probability = probabilities[frequency_a | (frequency_b << EXPONENT_WIDTH)]
        assert probability == pytest.approx(1 / SUBGROUP_ORDER, abs=1e-10)


def test_f5_key_uses_the_same_order_seven_frequency_relation() -> None:
    group = get_toy_group("toy-f5-a2-b1-g0-1")
    public_point = group.curve.multiply(2, group.generator)
    circuit = build_discrete_log_circuit(
        measure=False,
        curve=group.curve,
        base_point=group.generator,
        public_point=public_point,
        order=group.order,
    )
    final_state = Statevector.from_instruction(circuit)
    exponent_qubits = [
        circuit.find_bit(qubit).index
        for qubit in [*circuit.qregs[0], *circuit.qregs[1]]
    ]
    probabilities = final_state.probabilities(qargs=exponent_qubits)
    expected_support = {(u, (2 * u) % group.order) for u in range(group.order)}
    observed_support = {
        (frequency_a, frequency_b)
        for frequency_b in range(8)
        for frequency_a in range(8)
        if probabilities[frequency_a | (frequency_b << EXPONENT_WIDTH)] > 1e-9
    }

    assert public_point == (1, 3)
    assert observed_support == expected_support
