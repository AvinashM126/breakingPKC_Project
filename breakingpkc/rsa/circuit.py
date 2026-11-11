"""Instance-compiled RSA order-finding circuit for curated toy moduli."""

from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister
from qiskit.circuit.library import QFTGate, UnitaryGate

from .arithmetic import modular_multiplication_map
from .instance import DEFAULT_INSTANCE, RSAInstance, validate_instance


def modular_multiplier_gate(multiplier: int, modulus: int, width: int) -> UnitaryGate:
    """Create the instance-compiled reversible gate for modular multiplication."""
    basis_mapping = modular_multiplication_map(multiplier, modulus, width)
    unitary_matrix = [[0j] * len(basis_mapping) for _ in basis_mapping]
    # Each matrix column maps one input basis state to its permutation destination.
    for source_state, destination_state in enumerate(basis_mapping):
        unitary_matrix[destination_state][source_state] = 1.0 + 0.0j
    return UnitaryGate(unitary_matrix, label=f"mul_{multiplier}_mod_{modulus}")


def controlled_modular_multiplier_gate(
    multiplier: int, modulus: int, width: int
) -> UnitaryGate:
    """Return the one-control version of the reversible modular multiplier."""
    return modular_multiplier_gate(multiplier, modulus, width).control(1)


def build_order_finding_circuit(
    instance: RSAInstance = DEFAULT_INSTANCE,
    phase_qubits: int = 8,
    measure: bool = True,
) -> QuantumCircuit:
    """Build phase estimation of controlled modular multiplication.

    Phase qubit j controls multiplication by a**(2**j) mod N. The work
    register is little-endian and begins in |1>. Unused work states are fixed
    by the reversible permutation extension.
    """
    validate_instance(instance)
    minimum_phase_qubits = (instance.modulus * instance.modulus - 1).bit_length()
    if phase_qubits < minimum_phase_qubits:
        raise ValueError(
            f"At least {minimum_phase_qubits} phase qubits are required for this instance."
        )

    work_qubits = (instance.modulus - 1).bit_length()
    phase_register = QuantumRegister(phase_qubits, "phase")
    work_register = QuantumRegister(work_qubits, "work")
    if measure:
        classical_register = ClassicalRegister(phase_qubits, "phase_result")
        circuit = QuantumCircuit(phase_register, work_register, classical_register)
    else:
        circuit = QuantumCircuit(phase_register, work_register)
        classical_register = None

    circuit.h(phase_register)
    circuit.x(work_register[0])

    # Reuse gates only within this circuit's public instance and register width.
    controlled_multipliers = {}
    for phase_index in range(phase_qubits):
        multiplier = pow(instance.base, 1 << phase_index, instance.modulus)
        # Controlled identity operations have no effect, including on unused states.
        if multiplier == 1:
            continue

        if multiplier not in controlled_multipliers:
            controlled_multipliers[multiplier] = controlled_modular_multiplier_gate(
                multiplier=multiplier,
                modulus=instance.modulus,
                width=work_qubits,
            )
        circuit.append(
            controlled_multipliers[multiplier],
            [phase_register[phase_index], *work_register],
        )

    circuit.append(QFTGate(phase_qubits).inverse(), list(phase_register))

    if classical_register is not None:
        circuit.measure(phase_register, classical_register)
    return circuit
