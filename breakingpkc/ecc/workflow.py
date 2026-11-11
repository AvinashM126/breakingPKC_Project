"""ECC discrete-log simulation and measurement-derived recovery workflow."""

import logging
from collections.abc import Callable
from typing import Any

from qiskit import transpile
from qiskit_aer import AerSimulator

from ..common.run_config import DEFAULT_SEED, DEFAULT_SHOTS, MAX_SEED, MAX_SHOTS
from .arithmetic import analyze_frequency_counts, decode_frequency_counts
from .circuit import build_discrete_log_circuit
from .curve import (
    PUBLIC_POINT,
    Point,
    ShortWeierstrassCurve,
    validate_default_instance,
    validate_subgroup,
)
from .setup import get_toy_group

LOGGER = logging.getLogger(__name__)
MAX_ECC_ATTEMPTS = 4
MAX_TOTAL_QUBITS = 18
MAX_COMPILED_OPERATIONS = 250_000


def _curve_equation(curve: ShortWeierstrassCurve) -> str:
    a_term = "x" if curve.coefficient_a == 1 else f"{curve.coefficient_a}x"
    return f"y^2 = x^3 + {a_term} + {curve.coefficient_b}"


def _error_result(
    message: str,
    shots: int,
    seed: int | None,
    catalog_id: str = "toy-f11-a1-b1-g0-1",
    events: list[dict[str, Any]] | None = None,
    qubits: int = 0,
    total_shots: int = 0,
    attempts_completed: int = 0,
) -> dict[str, Any]:
    try:
        group = get_toy_group(catalog_id)
        public_parameters = {
            "catalog_id": catalog_id,
            "field_prime": group.curve.prime,
            "curve": _curve_equation(group.curve),
            "G": list(group.generator),
            "q": group.order,
        }
    except ValueError:
        public_parameters = {}
    return {
        "schema_version": 1,
        "algorithm": "ecc_discrete_log",
        "instance": {
            "label": f"ECC setup for {catalog_id}",
            "public_parameters": public_parameters,
        },
        "run": {
            "shots": shots,
            "total_shots": total_shots,
            "seed": seed,
            "simulator": "Qiskit Aer",
            "mode": "ideal_statevector",
            "registers": {},
            "qubits": qubits,
            "attempts_completed": attempts_completed,
            "attempt_budget": MAX_ECC_ATTEMPTS,
            "fixed_instance": True,
            "scalable": False,
        },
        "events": events or [],
        "candidates": [],
        "outcome": {"status": "error", "summary": message},
        "limitations": ["The run stopped before recovery completed."],
    }


def run_ecc(
    shots: int = DEFAULT_SHOTS,
    seed: int | None = None,
    catalog_id: str = "toy-f11-a1-b1-g0-1",
    public_point: Point | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Simulate the selected order-7 toy public key and recover from measured frequencies."""
    seed = DEFAULT_SEED if seed is None else seed
    if not isinstance(shots, int) or isinstance(shots, bool) or not 1 <= shots <= MAX_SHOTS:
        return _error_result(
            f"shots must be an integer from 1 through {MAX_SHOTS}.",
            shots,
            seed,
            catalog_id,
        )
    if seed is not None and (
        not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed <= MAX_SEED
    ):
        return _error_result(
            f"seed must be an integer from 0 through {MAX_SEED}.",
            shots,
            None,
            catalog_id,
        )

    try:
        group = get_toy_group(catalog_id)
    except ValueError as error:
        return _error_result(str(error), shots, seed, catalog_id)
    if public_point is None:
        # Only the guided fixture has a default Q; other groups need an explicit key.
        if catalog_id != "toy-f11-a1-b1-g0-1":
            return _error_result(
                "A public point Q is required for this selected toy group.",
                shots,
                seed,
                catalog_id,
            )
        public_point = PUBLIC_POINT
    curve = group.curve
    base_point = group.generator
    order = group.order
    events: list[dict[str, Any]] = []

    def record_event(event: dict[str, Any]) -> None:
        """Store and stream the same event at an actual workflow boundary."""
        events.append(event)
        if progress_callback is not None:
            progress_callback(event)

    record_event(
        {
            "stage": "public_input",
            "category": "public_input",
            "label": "ECC toy instance",
            "description": (
                "Use the public curve, base point, subgroup order, and generated public point."
            ),
            "evidence": {
                "catalog_id": catalog_id,
                "p": curve.prime,
                "curve": _curve_equation(curve),
                "G": list(base_point),
                "q": order,
                "Q": list(public_point),
            },
        }
    )

    compiled_qubits = 0
    total_shots = 0
    attempts_completed = 0
    candidates: list[dict[str, Any]] = []
    outcome_status = "failed"
    outcome_summary = "No measured frequency produced a validated scalar candidate."
    attempt_number = 0
    attempt_seed = seed
    try:
        if catalog_id == "toy-f11-a1-b1-g0-1" and public_point == PUBLIC_POINT:
            validate_default_instance()
        else:
            validate_subgroup(curve, base_point, order, public_point)
        record_event(
            {
                "stage": "public_input",
                "category": "classical_preflight",
                "label": "Public point subgroup check passed",
                "description": (
                    f"The public point Q is valid in the subgroup generated by G "
                    f"with order q={order}."
                ),
                "evidence": {"subgroup_validated": True, "q": order},
            }
        )
        circuit = build_discrete_log_circuit(
            measure=True,
            curve=curve,
            base_point=base_point,
            public_point=public_point,
            order=order,
        )
        simulator = AerSimulator(method="statevector")
        compiled_circuit = transpile(circuit, simulator, seed_transpiler=seed)
        # Enforce limits on compiled output before allocating simulator work.
        compiled_qubits = compiled_circuit.num_qubits
        if compiled_qubits > MAX_TOTAL_QUBITS:
            raise RuntimeError("The compiled circuit exceeds the local qubit limit.")
        circuit_operations = dict(compiled_circuit.count_ops())
        if sum(circuit_operations.values()) > MAX_COMPILED_OPERATIONS:
            raise RuntimeError("The compiled circuit exceeds the local operation limit.")
        record_event(
            {
                "stage": "quantum_observation",
                "category": "circuit_operation",
                "label": "Instance-compiled public-point oracle and Fourier transform",
                "description": (
                    "Prepare valid exponent states, compute aG+bQ using public group operations, "
                    "measure the point output, then apply the exact seven-dimensional Fourier "
                    "transform embedded in each three-qubit exponent register."
                ),
                "evidence": {
                    "exponent_registers": {"a": 3, "b": 3},
                    "point_output_register": 8,
                    "fourier_transform": "diag(F_7, 1) on each exponent register",
                    "circuit_depth": compiled_circuit.depth(),
                    "circuit_operations": circuit_operations,
                },
            }
        )

        for attempt_number in range(1, MAX_ECC_ATTEMPTS + 1):
            attempt_seed = (seed + (attempt_number - 1) * 104_729) % (MAX_SEED + 1)
            record_event(
                {
                    "stage": "quantum_observation",
                    "category": "run_state",
                    "label": f"Sampling ECC frequencies · attempt {attempt_number}/{MAX_ECC_ATTEMPTS}",
                    "description": (
                        f"Sample {shots} shots using seed {attempt_seed}; "
                        "frequency values are not available yet."
                    ),
                    "evidence": {
                        "attempt": attempt_number,
                        "attempt_budget": MAX_ECC_ATTEMPTS,
                        "shots": shots,
                        "seed": attempt_seed,
                    },
                }
            )
            raw_counts = simulator.run(
                compiled_circuit,
                shots=shots,
                seed_simulator=attempt_seed,
            ).result().get_counts()
            if sum(raw_counts.values()) != shots:
                raise RuntimeError("The simulator returned an unexpected shot count.")

            total_shots += shots
            attempts_completed = attempt_number
            frequency_counts = decode_frequency_counts(raw_counts)
            (
                candidates,
                outcome_status,
                outcome_summary,
                frequency_observations,
            ) = analyze_frequency_counts(
                frequency_counts, curve, base_point, public_point, order
            )
            ordered_histogram = [
                {"u": frequency_u, "v": frequency_v, "count": count}
                for (frequency_u, frequency_v), count in sorted(frequency_counts.items())
            ]
            record_event(
                {
                    "stage": "quantum_observation",
                    "category": "simulator_observation",
                    "label": f"Attempt {attempt_number}: measured frequency histogram",
                    "description": (
                        f"Batch {attempt_number} used seed {attempt_seed}. "
                        "The exponent registers are interpreted as Fourier frequencies (u,v)."
                    ),
                    "evidence": {
                        "attempt": attempt_number,
                        "seed": attempt_seed,
                        "frequencies": ordered_histogram,
                    },
                }
            )

            # Stage 3 exposes classifications, not scalar candidates derived for Stage 4.
            interpreted_frequencies = [
                {field: observation[field] for field in ("u", "v", "count", "status")}
                for observation in frequency_observations
            ]
            informative_count = sum(
                item["status"] in {"validated", "rejected"}
                for item in interpreted_frequencies
            )
            validated_count = sum(
                item["status"] == "validated" for item in interpreted_frequencies
            )
            validated_pairs_label = (
                "distinct pair" if validated_count == 1 else "distinct pairs"
            )
            if outcome_status == "recovered":
                retry_note = "A validated scalar was recovered; sampling stops."
            elif outcome_status == "ambiguous":
                retry_note = "Multiple candidates remain; the result is ambiguous."
            elif attempt_number < MAX_ECC_ATTEMPTS:
                retry_note = "No validated scalar in this batch; retrying with a new seed."
            else:
                retry_note = "No candidate recovered; the sampling budget is exhausted."
            record_event(
                {
                    "stage": "recovered_structure",
                    "category": "classical_postprocessing",
                    "label": f"Attempt {attempt_number}: measured frequency constraint",
                    "description": (
                        f"Test v = k*u mod {order}; {validated_count} {validated_pairs_label} "
                        f"passed the public point check. Informative pairs: "
                        f"{informative_count}/{len(interpreted_frequencies)}. "
                        f"{retry_note}"
                    ),
                    "evidence": {
                        "attempt": attempt_number,
                        "attempt_budget": MAX_ECC_ATTEMPTS,
                        "relation": f"v = k*u mod {order}",
                        "frequencies": interpreted_frequencies,
                    },
                }
            )
            if candidates:
                break
    except Exception:
        LOGGER.exception("ECC simulation failed")
        record_event(
            {
                "stage": "quantum_observation",
                "category": "run_error",
                "label": "Simulation error",
                "description": (
                    f"Attempt {attempt_number or 1} stopped before it produced a complete measured result."
                ),
                "evidence": {
                    "attempt": attempt_number or 1,
                    "attempts_completed": attempts_completed,
                    "attempt_budget": MAX_ECC_ATTEMPTS,
                    "shots_requested": shots,
                    "seed": attempt_seed,
                },
            }
        )
        return _error_result(
            "ECC simulation failed; see developer logs for details.",
            shots,
            seed,
            catalog_id,
            events,
            compiled_qubits,
            total_shots,
            attempts_completed,
        )

    if candidates:
        for candidate in candidates:
            candidate_value = candidate["value"]
            # The shared analysis has already verified every accepted scalar via kG=Q.
            candidate["validation"] = {
                "status": "passed",
                "explanation": "The candidate satisfies the public relation kG=Q.",
            }
            record_event(
                {
                    "stage": "secret_recovery",
                    "category": "candidate",
                    "label": "Scalar candidate",
                    "description": f"Derived from measured frequency attempt {attempts_completed}.",
                    "evidence": {
                        "candidate": candidate_value,
                        "supporting_shots": candidate["count"],
                        "attempt": attempts_completed,
                    },
                }
            )
            record_event(
                {
                    "stage": "validation",
                    "category": "candidate_validation",
                    "label": "Public point check",
                    "description": "Check kG=Q: passed.",
                    "evidence": {
                        "candidate": candidate_value,
                        "G": list(base_point),
                        "Q": list(public_point),
                        "status": "passed",
                    },
                }
            )
    else:
        outcome_summary = (
            f"{outcome_summary} No candidate was recovered after "
            f"{attempts_completed} of {MAX_ECC_ATTEMPTS} sampling attempts."
        )
        record_event(
            {
                "stage": "secret_recovery",
                "category": "limitation",
                "label": "No validated scalar candidate",
                "description": outcome_summary,
                "evidence": {
                    "validated_candidate_count": 0,
                    "attempts_completed": attempts_completed,
                    "attempt_budget": MAX_ECC_ATTEMPTS,
                },
            }
        )
        record_event(
            {
                "stage": "validation",
                "category": "limitation",
                "label": "Public point check not reached",
                "description": "No candidate was available to check against the public point.",
                "evidence": {
                    "status": "not_reached",
                    "G": list(base_point),
                    "Q": list(public_point),
                },
            }
        )

    return {
        "schema_version": 1,
        "algorithm": "ecc_discrete_log",
        "instance": {
            "catalog_id": catalog_id,
            "label": f"ECC toy instance over F_{curve.prime}",
            "public_parameters": {
                "catalog_id": catalog_id,
                "field_prime": curve.prime,
                "curve": _curve_equation(curve),
                "G": list(base_point),
                "q": order,
                "Q": list(public_point),
            },
        },
        "run": {
            "shots": shots,
            "total_shots": total_shots,
            "seed": seed,
            "simulator": "Qiskit Aer",
            "mode": "ideal_statevector",
            "registers": {"a": 3, "b": 3, "point_output": 8},
            "qubits": compiled_circuit.num_qubits,
            "attempts_completed": attempts_completed,
            "attempt_budget": MAX_ECC_ATTEMPTS,
            "fixed_instance": catalog_id == "toy-f11-a1-b1-g0-1" and public_point == PUBLIC_POINT,
            "scalable": False,
        },
        "events": events,
        "candidates": candidates,
        "outcome": {"status": outcome_status, "summary": outcome_summary},
        "limitations": [
            "Fixed-instance oracle and exact F_7 embedding; not scalable reversible arithmetic.",
            "Ideal local simulation; not quantum hardware or a production-key attack.",
            "The toy discrete logarithm is classically trivial; "
            "this is not evidence of quantum advantage.",
            f"At most {MAX_ECC_ATTEMPTS} independently seeded sampling batches run per request.",
        ],
    }
