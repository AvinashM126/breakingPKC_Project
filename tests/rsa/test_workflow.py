# Check measured recovery/provenance and distinguish classical gcd recovery from simulation.
from fractions import Fraction
from unittest.mock import MagicMock, patch

from breakingpkc.rsa.workflow import MAX_RSA_ATTEMPTS, _select_bases, run_rsa


def test_seeded_aer_run_recovers_and_validates_factors() -> None:
    # Repetition checks histogram reproducibility as well as the final validated factors.
    progress_events = []
    result = run_rsa(shots=64, seed=2, progress_callback=progress_events.append)
    repeated_result = run_rsa(shots=64, seed=2)

    assert result["outcome"]["status"] == "recovered"
    assert result["candidates"] == [
        {
            "kind": "factor_pair",
            "value": [3, 5],
            "validation": {
                "status": "passed",
                "explanation": "Both factors are nontrivial and 3 * 5 = 15.",
            },
        }
    ]
    assert result["run"]["shots"] == 64
    assert result["run"]["seed"] == 2
    assert progress_events == result["events"]
    assert [event["stage"] for event in progress_events[:3]] == [
        "public_input", "public_input", "quantum_observation",
    ]
    assert any(event["category"] == "simulator_observation" for event in result["events"])
    for event in result["events"]:
        for sample in event.get("evidence", {}).get("phase_samples", []):
            assert Fraction(sample["fraction"]) == Fraction(sample["phase"], 1 << 8)
    first_histogram = next(
        event["evidence"]["counts"]
        for event in result["events"]
        if event["category"] == "simulator_observation"
    )
    repeated_histogram = next(
        event["evidence"]["counts"]
        for event in repeated_result["events"]
        if event["category"] == "simulator_observation"
    )
    assert repeated_histogram == first_histogram


def test_invalid_run_settings_return_error_without_simulation() -> None:
    result = run_rsa(shots=0, seed=1)
    invalid_seed_result = run_rsa(shots=1, seed=-1)

    assert result["outcome"]["status"] == "error"
    assert result["candidates"] == []
    assert invalid_seed_result["outcome"]["status"] == "error"


def test_guided_default_run_is_seeded_and_recovers() -> None:
    result = run_rsa()

    assert result["run"]["seed"] == 314159
    assert result["run"]["shots"] == 256
    assert result["outcome"]["status"] == "recovered"


def test_selected_n21_uses_dynamic_precision_and_recovers_from_measured_phases() -> None:
    result = run_rsa(shots=128, seed=314159, catalog_id="rsa-n21-v1")

    assert result["instance"]["public_parameters"] == {"N": 21}
    assert result["run"]["registers"] == {"phase": 9, "work": 5}
    assert result["run"]["attempts_completed"] <= MAX_RSA_ATTEMPTS
    assert result["outcome"]["status"] == "recovered"
    assert result["candidates"][0]["value"] == [3, 7]


def test_automatic_base_sequence_is_reproducible_and_bounded() -> None:
    bases = _select_bases(55, seed=42)

    assert bases == _select_bases(55, seed=42)
    assert bases != _select_bases(55, seed=43)
    assert bases[0] != _select_bases(55, seed=43)[0]
    assert len(bases) == MAX_RSA_ATTEMPTS
    assert len(set(bases)) == MAX_RSA_ATTEMPTS
    assert 2 <= bases[0] < 55


def test_classical_gcd_path_recovers_without_circuit_submission() -> None:
    simulator = MagicMock()
    with patch("breakingpkc.rsa.workflow._select_bases", return_value=(3,)), patch(
        "breakingpkc.rsa.workflow.AerSimulator", return_value=simulator
    ), patch("breakingpkc.rsa.workflow.build_order_finding_circuit") as builder:
        result = run_rsa(shots=1)

    assert result["outcome"]["status"] == "recovered"
    assert result["outcome"]["recovery_source"] == "classical_preprocessing"
    assert result["candidates"][0]["value"] == [3, 5]
    assert result["run"]["circuits_submitted"] == 0
    base_event = next(
        event
        for event in result["events"]
        if event["category"] == "attempt_started"
    )
    assert base_event["stage"] == "quantum_observation"
    assert base_event["evidence"]["base"] == 3
    assert base_event["evidence"]["gcd"] == 3
    assert result["events"].index(base_event) < next(
        index
        for index, event in enumerate(result["events"])
        if event["category"] == "classical_preprocessing"
    )
    shortcut_event = next(
        event for event in result["events"] if event["category"] == "attempt_outcome"
    )
    assert shortcut_event["evidence"]["status"] == "classical_shortcut"
    builder.assert_not_called()
    simulator.run.assert_not_called()


def test_postprocessing_rejection_is_visible_before_next_attempt() -> None:
    result = run_rsa(shots=256, seed=34)

    assert result["run"]["attempts_completed"] == 2
    assert result["attempts"][0]["base"] == 14
    assert result["attempts"][0]["status"] == "rejected"
    assert "trivial square root of one" in result["attempts"][0]["rejection_reason"]
    rejection = next(
        event
        for event in result["events"]
        if event["category"] == "classical_postprocessing"
    )
    assert "Retrying with the next sampled base." in rejection["description"]
    assert result["attempts"][1]["base"] == 5
    assert result["outcome"]["recovery_source"] == "classical_preprocessing"


def test_partial_run_error_preserves_completed_observations_and_counts() -> None:
    compiled = MagicMock(num_qubits=12)
    compiled.count_ops.return_value = {"cx": 100}
    compiled.depth.return_value = 10
    first_job = MagicMock()
    first_job.result.return_value.get_counts.return_value = {"10000000": 1}
    simulator = MagicMock()
    simulator.run.side_effect = [first_job, RuntimeError("Second attempt failed")]
    with patch("breakingpkc.rsa.workflow._select_bases", return_value=(14, 2)), patch(
        "breakingpkc.rsa.workflow.AerSimulator", return_value=simulator
    ), patch("breakingpkc.rsa.workflow.build_order_finding_circuit", return_value=compiled), patch(
        "breakingpkc.rsa.workflow.transpile", return_value=compiled
    ):
        result = run_rsa(shots=1, seed=1)

    assert result["outcome"]["status"] == "error"
    assert result["run"]["attempts_started"] == 2
    assert result["run"]["attempts_completed"] == 1
    assert result["run"]["circuits_submitted"] == 2
    assert result["run"]["total_shots"] == 1
    assert result["events"][-1]["evidence"]["attempt"] == 2
    assert "earlier observations are preserved" in result["limitations"][0]
