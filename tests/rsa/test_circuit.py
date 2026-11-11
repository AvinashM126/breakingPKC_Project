# Exercise basis-state action, phase support, register widths, and local gate reuse.
from unittest.mock import patch

import pytest
from qiskit.circuit import Gate
from qiskit.quantum_info import Statevector

from breakingpkc.rsa.arithmetic import modular_multiplication_map
from breakingpkc.rsa import circuit as rsa_circuit
from breakingpkc.rsa.circuit import (
    build_order_finding_circuit,
    controlled_modular_multiplier_gate,
    modular_multiplier_gate,
)
from breakingpkc.rsa.instance import RSAInstance


def basis_output(operation, source_state: int, dimensions: int) -> int:
    # A permutation gate must concentrate all probability on exactly one basis state.
    state = Statevector.from_int(source_state, dims=dimensions).evolve(operation)
    output_state = max(range(dimensions), key=lambda index: abs(state.data[index]) ** 2)
    assert abs(state.data[output_state]) ** 2 == pytest.approx(1.0)
    return output_state


def test_modular_multiplier_gate_matches_every_work_basis_state() -> None:
    mapping = modular_multiplication_map(multiplier=2, modulus=15, width=4)
    gate = modular_multiplier_gate(multiplier=2, modulus=15, width=4)

    for source_state, expected_state in enumerate(mapping):
        assert basis_output(gate, source_state, dimensions=16) == expected_state


def test_controlled_multiplier_preserves_inactive_branch_and_maps_active_branch() -> None:
    mapping = modular_multiplication_map(multiplier=2, modulus=15, width=4)
    gate = controlled_modular_multiplier_gate(multiplier=2, modulus=15, width=4)

    for work_state, expected_work_state in enumerate(mapping):
        inactive_input = work_state << 1
        active_input = (work_state << 1) | 1
        assert basis_output(gate, inactive_input, dimensions=32) == inactive_input
        assert basis_output(gate, active_input, dimensions=32) == (expected_work_state << 1) | 1


def test_phase_estimation_ideal_support_matches_order_four() -> None:
    circuit = build_order_finding_circuit(phase_qubits=8, measure=False)
    final_state = Statevector.from_instruction(circuit)
    phase_qubits = [circuit.find_bit(qubit).index for qubit in circuit.qregs[0]]
    phase_probabilities = final_state.probabilities(qargs=phase_qubits)
    support = {
        phase_value
        for phase_value, probability in enumerate(phase_probabilities)
        if probability > 1e-9
    }

    assert support == {0, 64, 128, 192}
    for phase_value in support:
        assert phase_probabilities[phase_value] == pytest.approx(0.25, abs=1e-9)


def test_circuit_has_expected_registers_and_measurements() -> None:
    circuit = build_order_finding_circuit()

    assert circuit.num_qubits == 12
    assert circuit.num_clbits == 8
    assert circuit.qregs[0].name == "phase"
    assert circuit.qregs[1].name == "work"


def test_selected_modulus_uses_derived_phase_and_work_register_widths() -> None:
    instance = RSAInstance(modulus=21, base=2)
    circuit = build_order_finding_circuit(instance, phase_qubits=9, measure=True)

    assert circuit.num_qubits == 14
    assert circuit.num_clbits == 9
    assert circuit.qregs[0].size == 9
    assert circuit.qregs[1].size == 5


def test_repeated_multipliers_are_built_once_per_circuit() -> None:
    # Placeholder gates count construction/placement without expensive gate synthesis.
    instance = RSAInstance(modulus=21, base=2)
    with patch.object(
        rsa_circuit,
        "controlled_modular_multiplier_gate",
        side_effect=lambda multiplier, modulus, width: Gate(f"mul_{multiplier}", width + 1, []),
    ) as factory:
        circuit = build_order_finding_circuit(instance, phase_qubits=9)
        assert factory.call_count == 3
        assert [call.kwargs["multiplier"] for call in factory.call_args_list] == [2, 4, 16]
        assert sum(
            instruction.operation.name.startswith("mul_")
            for instruction in circuit.data
        ) == 9
        build_order_finding_circuit(instance, phase_qubits=9)
        assert factory.call_count == 6
