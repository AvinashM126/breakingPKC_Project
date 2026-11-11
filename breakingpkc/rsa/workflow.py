"""RSA order-finding simulation and measurement-derived recovery workflow."""

import logging
from collections.abc import Callable
from math import gcd
from random import Random
from typing import Any

from qiskit import transpile
from qiskit_aer import AerSimulator

from ..common.run_config import DEFAULT_SEED, DEFAULT_SHOTS, MAX_SEED, MAX_SHOTS
from .arithmetic import decode_phase_counts, infer_order, recover_factors
from .circuit import build_order_finding_circuit
from .instance import (
    DEFAULT_RSA_CATALOG_ID,
    RSAInstance,
    modulus_from_catalog,
)

MAX_RSA_ATTEMPTS = 4
MAX_TOTAL_QUBITS = 18
MAX_COMPILED_OPERATIONS = 250_000
_BASE_SELECTION_SALT = 0xA57E11
LOGGER = logging.getLogger(__name__)


def _error_result(
    message: str,
    shots: int,
    seed: int | None,
    catalog_id: str,
    events: list[dict[str, Any]] | None = None,
    attempts: list[dict[str, Any]] | None = None,
    total_shots: int = 0,
    circuits_submitted: int = 0,
    qubits: int = 0,
    registers: dict[str, int] | None = None,
) -> dict[str, Any]:
    try:
        modulus = modulus_from_catalog(catalog_id)
    except ValueError:
        modulus = None
    return {
        "schema_version": 1,
        "algorithm": "rsa_factoring",
        "instance": {
            "catalog_id": catalog_id if modulus is not None else None,
            "label": (
                f"RSA toy modulus N={modulus}"
                if modulus is not None
                else "No RSA toy instance"
            ),
            "public_parameters": {"N": modulus} if modulus is not None else {},
        },
        "run": {
            "shots": shots,
            "total_shots": total_shots,
            "seed": seed,
            "simulator": "Qiskit Aer",
            "mode": "ideal_statevector",
            "registers": registers or {},
            "qubits": qubits,
            "fixed_instance": False,
            "scalable": False,
            "attempt_budget": MAX_RSA_ATTEMPTS,
            "attempts_started": len(attempts or []),
            "attempts_completed": sum(
                attempt["status"] in {"recovered", "rejected", "classically_recovered"}
                for attempt in attempts or []
            ),
            "circuits_submitted": circuits_submitted,
            "bases_attempted": [attempt["base"] for attempt in attempts or []],
        },
        "events": events or [],
        "attempts": attempts or [],
        "candidates": [],
        "outcome": {"status": "error", "summary": message, "recovery_source": None},
        "limitations": [
            "The run stopped before recovery completed; earlier observations are preserved."
            if total_shots
            else "No complete measurement result was produced."
        ],
    }


def _select_bases(modulus: int, seed: int) -> tuple[int, ...]:
    """Shuffle all public bases reproducibly for bounded RSA attempts."""
    candidates = list(range(2, modulus))
    Random(seed ^ _BASE_SELECTION_SALT).shuffle(candidates)
    return tuple(candidates[:MAX_RSA_ATTEMPTS])


def _phase_qubits_for(modulus: int) -> int:
    return (modulus * modulus - 1).bit_length()


def _factor_candidate(factors: tuple[int, int], modulus: int) -> dict[str, Any]:
    return {
        "kind": "factor_pair",
        "value": list(factors),
        "validation": {
            "status": "passed",
            "explanation": (
                f"Both factors are nontrivial and {factors[0]} * {factors[1]} "
                f"= {modulus}."
            ),
        },
    }


def _factor_rejection_reason(
    instance: RSAInstance, order_candidate: int | None
) -> str:
    if order_candidate is None:
        return "No measured phase produced a verified order."
    if order_candidate % 2:
        return f"The verified order r={order_candidate} is odd; factor recovery requires even r."
    square_root_of_one = pow(instance.base, order_candidate // 2, instance.modulus)
    if square_root_of_one in (1, instance.modulus - 1):
        return (
            f"a^(r/2) mod N = {square_root_of_one}, a trivial square root of one; "
            "this base yields no nontrivial factors."
        )
    return "The resulting GCDs did not produce two nontrivial factors."


def run_rsa(
    shots: int = DEFAULT_SHOTS,
    seed: int | None = None,
    catalog_id: str = DEFAULT_RSA_CATALOG_ID,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run bounded order-finding attempts for one curated public modulus."""
    seed = DEFAULT_SEED if seed is None else seed
    if not isinstance(shots, int) or isinstance(shots, bool) or not 1 <= shots <= MAX_SHOTS:
        return _error_result(
            f"shots must be an integer from 1 through {MAX_SHOTS}.", shots, seed, catalog_id
        )
    if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed <= MAX_SEED:
        return _error_result(
            f"seed must be an integer from 0 through {MAX_SEED}.", shots, None, catalog_id
        )
    try:
        modulus = modulus_from_catalog(catalog_id)
    except ValueError as error:
        return _error_result(str(error), shots, seed, catalog_id)

    phase_qubits = _phase_qubits_for(modulus)
    work_qubits = (modulus - 1).bit_length()
    if phase_qubits + work_qubits > MAX_TOTAL_QUBITS:
        return _error_result(
            "The selected instance exceeds the local circuit qubit limit.",
            shots,
            seed,
            catalog_id,
        )

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
            "label": "Curated RSA toy modulus",
            "description": (
                f"Use public N={modulus}; bases are selected reproducibly without "
                "consulting its factors or order."
            ),
            "evidence": {"catalog_id": catalog_id, "N": modulus},
        }
    )
    attempts: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    factors: tuple[int, int] | None = None
    recovery_source: str | None = None
    last_order_candidate: int | None = None
    circuit_count = 0
    total_shots = 0
    compiled_qubits = 0
    registers: dict[str, int] = {}
    simulator = AerSimulator(method="statevector")
    bases = _select_bases(modulus, seed)

    try:
        for attempt_number, base in enumerate(bases, start=1):
            # Record classical factor discoveries separately from quantum evidence.
            common_factor = gcd(base, modulus)
            record_event(
                {
                    "stage": "public_input",
                    "category": "base_selection",
                    "label": f"Attempt {attempt_number} of {MAX_RSA_ATTEMPTS} · a={base}",
                    "description": (
                        f"gcd({base}, {modulus})={common_factor}; "
                        "this check determines whether order finding is submitted."
                    ),
                    "evidence": {
                        "attempt": attempt_number,
                        "attempt_budget": MAX_RSA_ATTEMPTS,
                        "base": base,
                        "gcd": common_factor,
                    },
                }
            )
            record_event(
                {
                    "stage": "quantum_observation",
                    "category": "attempt_started",
                    "label": f"Attempt {attempt_number} of {MAX_RSA_ATTEMPTS}",
                    "description": (
                        "The GCD check found a classical shortcut; no circuit will run."
                        if common_factor > 1
                        else "The coprime base proceeds to order finding."
                    ),
                    "evidence": {
                        "attempt": attempt_number,
                        "attempt_budget": MAX_RSA_ATTEMPTS,
                        "base": base,
                        "gcd": common_factor,
                    },
                }
            )
            attempt: dict[str, Any] = {
                "attempt": attempt_number,
                "base": base,
                "gcd": common_factor,
                "status": "gcd_only" if common_factor > 1 else "circuit_pending",
            }
            attempts.append(attempt)
            if common_factor > 1:
                record_event(
                    {
                        "stage": "quantum_observation",
                        "category": "attempt_outcome",
                        "label": f"Attempt {attempt_number}: classical GCD shortcut",
                        "description": (
                            f"gcd({base}, {modulus})={common_factor}; a factor is available "
                            "without submitting a quantum circuit."
                        ),
                        "evidence": {
                            "attempt": attempt_number,
                            "attempt_budget": MAX_RSA_ATTEMPTS,
                            "base": base,
                            "gcd": common_factor,
                            "status": "classical_shortcut",
                        },
                    }
                )
                record_event(
                    {
                        "stage": "secret_recovery",
                        "category": "classical_preprocessing",
                        "label": f"Attempt {attempt_number}: gcd check for a={base}",
                        "description": (
                            f"gcd({base}, {modulus})={common_factor}; this is a classical "
                            "factor discovery, not a quantum recovery."
                        ),
                        "evidence": {
                            "attempt": attempt_number,
                            "base": base,
                            "gcd": common_factor,
                            "circuit_submitted": False,
                        },
                    }
                )
                factors = tuple(sorted((common_factor, modulus // common_factor)))
                recovery_source = "classical_preprocessing"
                attempt["status"] = "classically_recovered"
                candidates.append(_factor_candidate(factors, modulus))
                record_event(
                    {
                        "stage": "secret_recovery",
                        "category": "candidate",
                        "label": "Factor candidate from classical gcd",
                        "description": (
                            "The nontrivial gcd produced a candidate "
                            "without submitting a quantum circuit."
                        ),
                        "evidence": {"factors": list(factors), "source": recovery_source},
                    }
                )
                record_event(
                    {
                        "stage": "validation",
                        "category": "validation",
                        "label": "Classical gcd factor check",
                        "description": (
                            "The nontrivial gcd and its cofactor "
                            "multiply to the public modulus."
                        ),
                        "evidence": {"factors": list(factors), "product": modulus, "status": "passed"},
                    }
                )
                break

            instance = RSAInstance(modulus=modulus, base=base)
            circuit = build_order_finding_circuit(instance, phase_qubits, measure=True)
            compiled_circuit = transpile(circuit, simulator, seed_transpiler=seed)
            if compiled_circuit.num_qubits > MAX_TOTAL_QUBITS:
                raise RuntimeError("The compiled circuit exceeds the local qubit limit.")
            circuit_operations = dict(compiled_circuit.count_ops())
            if sum(circuit_operations.values()) > MAX_COMPILED_OPERATIONS:
                raise RuntimeError("The compiled circuit exceeds the local operation limit.")

            # Each bounded attempt gets a reproducible seed without changing the key.
            attempt_seed = (seed + (attempt_number - 1) * 104_729) % (MAX_SEED + 1)
            record_event(
                {
                    "stage": "quantum_observation",
                    "category": "circuit_operation",
                    "label": f"Order-finding circuit for a={base}",
                    "description": (
                        f"Prepare {phase_qubits} phase qubits and "
                        f"{work_qubits} work qubits in |1>; "
                        "apply controlled modular multiplications and the inverse QFT."
                    ),
                    "evidence": {
                        "attempt": attempt_number,
                        "base": base,
                        "phase_qubits": phase_qubits,
                        "work_qubits": work_qubits,
                        "attempt_budget": MAX_RSA_ATTEMPTS,
                        "circuit_depth": compiled_circuit.depth(),
                        "circuit_operations": circuit_operations,
                    },
                }
            )
            record_event(
                {
                    "stage": "quantum_observation",
                    "category": "run_state",
                    "label": f"Sampling base a={base}",
                    "description": (
                        "The simulator is processing this circuit; "
                        "measurement values are not available yet."
                    ),
                    "evidence": {
                        "attempt": attempt_number,
                        "attempt_budget": MAX_RSA_ATTEMPTS,
                        "base": base,
                        "shots": shots,
                        "seed": attempt_seed,
                    },
                }
            )
            circuit_count += 1
            compiled_qubits = compiled_circuit.num_qubits
            registers = {"phase": phase_qubits, "work": work_qubits}
            result_counts = simulator.run(
                compiled_circuit,
                shots=shots,
                seed_simulator=attempt_seed,
            ).result().get_counts()
            if sum(result_counts.values()) != shots:
                raise RuntimeError("The simulator returned an unexpected shot count.")

            total_shots += shots
            phase_counts = decode_phase_counts(result_counts, phase_qubits)
            order_candidate, observations = infer_order(phase_counts, instance, phase_qubits)
            last_order_candidate = order_candidate
            factors = recover_factors(instance, order_candidate)
            rejection_reason = (
                _factor_rejection_reason(instance, order_candidate)
                if factors is None
                else None
            )
            attempt.update(
                {
                    "status": "recovered" if factors is not None else "rejected",
                    "simulator_seed": attempt_seed,
                    "order_candidate": order_candidate,
                    "circuit_depth": compiled_circuit.depth(),
                    "circuit_operations": circuit_operations,
                }
            )
            if rejection_reason is not None:
                attempt["rejection_reason"] = rejection_reason
            record_event(
                {
                    "stage": "quantum_observation",
                    "category": "simulator_observation",
                    "label": f"Measured phases for a={base}",
                    "description": (
                        "Counts are simulator observations; "
                        "they are not orders by themselves."
                    ),
                    "evidence": {
                        "attempt": attempt_number,
                        "attempt_budget": MAX_RSA_ATTEMPTS,
                        "base": base,
                        "seed": attempt_seed,
                        "shots": shots,
                        "counts": {
                            str(phase): count
                            for phase, count in sorted(phase_counts.items())
                        },
                        "phase_bits": phase_qubits,
                    },
                }
            )

            # Preserve the measured phase numerator; reduced fractions are different data.
            period_samples = [
                {
                    "phase": int(observation["phase"]),
                    "count": int(observation["count"]),
                    "fraction": f"{observation['phase']}/{1 << phase_qubits}",
                    "denominator": observation["fraction_denominator"],
                    "verified_period": observation["verified_period"],
                    "informative": observation["informative"],
                }
                for observation in observations
            ]
            retry_note = (
                "Retrying with the next sampled base."
                if attempt_number < len(bases)
                else "The attempt budget is exhausted."
            )
            if order_candidate is None:
                postprocessing_description = f"{rejection_reason} {retry_note}"
            elif rejection_reason is not None:
                postprocessing_description = (
                    f"Verified order r={order_candidate}. {rejection_reason} {retry_note}"
                )
            else:
                postprocessing_description = (
                    f"Measured fractions were reconstructed and modularly checked; "
                    f"verified period candidate r={order_candidate}."
                )
            record_event(
                {
                    "stage": "recovered_structure",
                    "category": "classical_postprocessing",
                    "label": f"Measured phase structure for a={base}",
                    "description": postprocessing_description,
                    "evidence": {
                        "attempt": attempt_number,
                        "attempt_budget": MAX_RSA_ATTEMPTS,
                        "base": base,
                        "phase_samples": period_samples,
                        "order_candidate": order_candidate,
                        "modular_check": order_candidate is not None,
                        "factor_rejection": rejection_reason,
                    },
                }
            )

            if factors is not None:
                recovery_source = "quantum_order_finding"
                candidates.append(_factor_candidate(factors, modulus))
                record_event(
                    {
                        "stage": "secret_recovery",
                        "category": "candidate",
                        "label": "Factor candidate",
                        "description": (
                            "The measured order supplied the candidate factors; "
                            "validate them against public N."
                        ),
                        "evidence": {"factors": list(factors), "source": recovery_source},
                    }
                )
                record_event(
                    {
                        "stage": "validation",
                        "category": "validation",
                        "label": "Public modulus check",
                        "description": "The recovered factors are nontrivial and multiply to N.",
                        "evidence": {"factors": list(factors), "product": modulus, "status": "passed"},
                    }
                )
                break
    except Exception:
        LOGGER.exception("RSA simulation failed")
        if attempts:
            attempts[-1]["status"] = "error"
        record_event(
            {
                "stage": "quantum_observation",
                "category": "run_error",
                "label": "Simulation error",
                "description": (
                    "This attempt ended with an execution error; earlier measurements remain available."
                ),
                "evidence": {
                    "attempt": len(attempts),
                    "base": attempts[-1]["base"] if attempts else None,
                },
            }
        )
        return _error_result(
            "RSA simulation failed; see developer logs for details.",
            shots,
            seed,
            catalog_id,
            events,
            attempts,
            total_shots,
            circuit_count,
            compiled_qubits,
            registers,
        )

    if factors is not None and recovery_source == "classical_preprocessing":
        outcome = {
            "status": "recovered",
            "recovery_source": recovery_source,
            "summary": (
                f"A classical gcd check recovered factors {factors[0]} and {factors[1]}; "
                "no quantum recovery is claimed for this result."
            ),
        }
    elif factors is not None:
        outcome = {
            "status": "recovered",
            "recovery_source": recovery_source,
            "summary": (
                f"Recovered factors {factors[0]} and {factors[1]} from measured order-finding "
                f"evidence for N={modulus}."
            ),
        }
    else:
        record_event(
            {
                "stage": "secret_recovery",
                "category": "limitation",
                "label": "No validated factor pair",
                "description": "The bounded base attempts did not produce a validated factor pair.",
                "evidence": {
                    "last_order_candidate": last_order_candidate,
                    "attempts_completed": len(attempts),
                    "attempt_budget": MAX_RSA_ATTEMPTS,
                },
            }
        )
        outcome = {
            "status": "failed",
            "recovery_source": None,
            "summary": f"This run did not recover a validated factor pair for N={modulus}.",
        }

    return {
        "schema_version": 1,
        "algorithm": "rsa_factoring",
        "instance": {
            "catalog_id": catalog_id,
            "label": f"RSA toy modulus N={modulus}",
            "public_parameters": {"N": modulus},
        },
        "run": {
            "shots": shots,
            "total_shots": total_shots,
            "seed": seed,
            "simulator": "Qiskit Aer",
            "mode": "ideal_statevector",
            "registers": registers,
            "qubits": compiled_qubits,
            "fixed_instance": False,
            "scalable": False,
            "attempt_budget": MAX_RSA_ATTEMPTS,
            "attempts_started": len(attempts),
            "attempts_completed": len(attempts),
            "circuits_submitted": circuit_count,
            "bases_attempted": [attempt["base"] for attempt in attempts],
        },
        "events": events,
        "attempts": attempts,
        "candidates": candidates,
        "outcome": outcome,
        "limitations": [
            "Curated toy inputs and instance-compiled reversible gates; not scalable arithmetic.",
            "Ideal local simulation; not quantum hardware or a production-key attack.",
            "A nontrivial gcd is classical preprocessing "
            "and is reported separately from quantum recovery.",
            "Toy factors are classically trivial; this is not evidence of quantum advantage.",
        ],
    }
