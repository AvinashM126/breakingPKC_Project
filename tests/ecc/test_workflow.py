# Combine seeded Aer checks with stubbed resource-limit and unsuccessful-evidence cases.
from unittest.mock import MagicMock

import pytest

from breakingpkc.ecc import workflow
from breakingpkc.ecc.workflow import run_ecc
from breakingpkc.ecc.setup import create_toy_key


def _frequency_histogram(result: dict) -> list[dict]:
    observation = next(
        event for event in result["events"] if event["category"] == "simulator_observation"
    )
    return observation["evidence"]["frequencies"]


def test_seeded_aer_run_recovers_scalar_from_measured_frequencies() -> None:
    progress_events = []
    result = run_ecc(shots=128, seed=314159, progress_callback=progress_events.append)
    repeated_result = run_ecc(shots=128, seed=314159)

    assert result["outcome"]["status"] == "recovered"
    assert result["candidates"][0]["value"] == 3
    assert result["candidates"][0]["validation"]["status"] == "passed"
    assert result["run"]["shots"] == 128
    assert result["run"]["seed"] == 314159
    assert progress_events == result["events"]
    assert [event["stage"] for event in progress_events[:3]] == [
        "public_input", "public_input", "quantum_observation",
    ]
    assert _frequency_histogram(repeated_result) == _frequency_histogram(result)


def test_invalid_run_settings_return_error_without_candidate() -> None:
    invalid_shots = run_ecc(shots=0, seed=1)
    invalid_seed = run_ecc(shots=1, seed=-1)

    assert invalid_shots["outcome"]["status"] == "error"
    assert invalid_seed["outcome"]["status"] == "error"
    assert invalid_shots["candidates"] == []


def test_guided_default_run_is_seeded_and_recovers() -> None:
    result = run_ecc()

    assert result["run"]["seed"] == 314159
    assert result["run"]["shots"] == 256
    assert result["outcome"]["status"] == "recovered"


def test_f5_selected_key_recovers_from_setup_derived_public_point() -> None:
    public_setup = create_toy_key("toy-f5-a2-b1-g0-1", scalar=2).public_attack_input()
    result = run_ecc(
        shots=128,
        seed=314159,
        catalog_id=public_setup.group.catalog_id,
        public_point=public_setup.public_point,
    )

    assert result["instance"]["public_parameters"]["catalog_id"] == "toy-f5-a2-b1-g0-1"
    assert result["instance"]["public_parameters"]["Q"] == [1, 3]
    assert result["outcome"]["status"] == "recovered"
    assert result["candidates"][0]["value"] == 2


def _stub_sampler(monkeypatch, counts, qubits=14, operations=100):
    # Inject boundary measurements and compiled sizes without building or simulating gates.
    compiled = MagicMock()
    compiled.num_qubits = qubits
    compiled.count_ops.return_value = {"cx": operations}
    compiled.depth.return_value = 10
    simulator = MagicMock()
    simulator.run.return_value.result.return_value.get_counts.return_value = counts
    monkeypatch.setattr(workflow, "build_discrete_log_circuit", lambda **kwargs: compiled)
    monkeypatch.setattr(workflow, "transpile", lambda circuit, backend, **options: compiled)
    monkeypatch.setattr(workflow, "AerSimulator", lambda **kwargs: simulator)
    return simulator


def _counts_result(counts):
    result = MagicMock()
    result.result.return_value.get_counts.return_value = counts
    return result


def test_ecc_retries_uninformative_batch_then_recovers(monkeypatch):
    simulator = _stub_sampler(monkeypatch, {})
    simulator.run.side_effect = [
        _counts_result({"00000000000000": 1}),
        _counts_result({"01100100000000": 1}),
    ]
    progress_events = []

    result = run_ecc(shots=1, seed=17, progress_callback=progress_events.append)

    assert result["outcome"]["status"] == "recovered"
    assert result["candidates"][0]["value"] == 3
    assert result["run"]["attempts_completed"] == 2
    assert result["run"]["total_shots"] == 2
    assert simulator.run.call_count == 2
    assert [
        event["evidence"]["seed"]
        for event in result["events"]
        if event["category"] == "simulator_observation"
    ] == [17, 104746]
    structure_events = [
        event for event in result["events"] if event["category"] == "classical_postprocessing"
    ]
    assert "retrying with a new seed" in structure_events[0]["description"]
    assert "validated scalar was recovered" in structure_events[1]["description"]
    assert progress_events == result["events"]


@pytest.mark.parametrize("qubits,operations", [(19, 100), (14, 250_001)])
def test_compiled_resource_limits_reject_before_submission(monkeypatch, qubits, operations):
    simulator = _stub_sampler(monkeypatch, {"01100100000000": 1}, qubits, operations)

    result = run_ecc(shots=1)

    assert result["outcome"]["status"] == "error"
    assert result["candidates"] == []
    simulator.run.assert_not_called()


def test_compiled_resource_limits_allow_boundary(monkeypatch):
    simulator = _stub_sampler(monkeypatch, {"01100100000000": 1}, 18, 250_000)

    result = run_ecc(shots=1)

    assert result["outcome"]["status"] == "recovered"
    simulator.run.assert_called_once()


@pytest.mark.parametrize(
    "bits,status",
    [
        ("00111100000000", "invalid_frequency"),
        ("11100100000000", "invalid_frequency"),
        ("00100100000000", "rejected"),
        ("00000000000000", "uninformative"),
    ],
)
def test_unsuccessful_frequency_evidence_is_preserved(monkeypatch, bits, status):
    _stub_sampler(monkeypatch, {bits: 1})
    progress_events = []

    result = run_ecc(shots=1, progress_callback=progress_events.append)

    assert result["outcome"]["status"] == "failed"
    assert result["candidates"] == []
    assert result["run"]["attempts_completed"] == workflow.MAX_ECC_ATTEMPTS
    assert result["run"]["total_shots"] == workflow.MAX_ECC_ATTEMPTS
    assert progress_events == result["events"]
    structure_events = [
        event for event in result["events"] if event["stage"] == "recovered_structure"
    ]
    assert len(structure_events) == workflow.MAX_ECC_ATTEMPTS
    assert "budget is exhausted" in structure_events[-1]["description"]
    structure = structure_events[0]
    assert structure["evidence"]["frequencies"][0]["status"] == status
