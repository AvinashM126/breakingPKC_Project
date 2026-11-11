# Verify CLI dispatch/output separately from the combined simulator-backed workflow check.
import json

import pytest

from breakingpkc import cli


def test_cli_dispatches_rsa_to_shared_workflow(monkeypatch, capsys) -> None:
    expected_result = {"outcome": {"status": "failed"}, "events": []}
    calls = []

    def fake_run_rsa(shots: int, seed: int | None, catalog_id: str):
        calls.append((shots, seed, catalog_id))
        return expected_result

    monkeypatch.setattr(cli, "run_rsa", fake_run_rsa)

    exit_code = cli.main(["rsa", "--shots", "64", "--seed", "12"])
    printed_result = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert calls == [(64, 12, "rsa-n15-v1")]
    assert printed_result == expected_result


def test_cli_uses_workflow_validation_for_invalid_shot_count(capsys) -> None:
    exit_code = cli.main(["rsa", "--shots", "0"])
    printed_result = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert printed_result["outcome"]["status"] == "error"
    assert printed_result["run"]["shots"] == 0


def test_cli_dispatches_selected_rsa_catalog(monkeypatch, capsys) -> None:
    calls = []

    def fake_run_rsa(shots: int, seed: int | None, catalog_id: str):
        calls.append((shots, seed, catalog_id))
        return {"outcome": {"status": "failed"}}

    monkeypatch.setattr(cli, "run_rsa", fake_run_rsa)
    exit_code = cli.main(["rsa", "--rsa-catalog", "rsa-n21-v1"])
    json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert calls == [(256, None, "rsa-n21-v1")]


def test_cli_dispatches_ecc_to_shared_workflow(monkeypatch, capsys) -> None:
    expected_result = {"outcome": {"status": "failed"}, "events": []}
    calls = []

    def fake_run_ecc(shots: int, seed: int | None):
        calls.append((shots, seed))
        return expected_result

    monkeypatch.setattr(cli, "run_ecc", fake_run_ecc)

    exit_code = cli.main(["ecc", "--shots", "32", "--seed", "5"])
    printed_result = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert calls == [(32, 5)]
    assert printed_result == expected_result


def test_cli_runs_both_real_workflows_without_cross_algorithm_state(capsys) -> None:
    # Running both algorithms in one process checks that settings and results stay isolated.
    rsa_exit = cli.main(["rsa", "--shots", "64", "--seed", "314159"])
    rsa_result = json.loads(capsys.readouterr().out)
    ecc_exit = cli.main(["ecc", "--shots", "128", "--seed", "314159"])
    ecc_result = json.loads(capsys.readouterr().out)

    assert rsa_exit == 0
    assert ecc_exit == 0
    assert rsa_result["algorithm"] == "rsa_factoring"
    assert ecc_result["algorithm"] == "ecc_discrete_log"
    assert rsa_result["outcome"]["status"] == "recovered"
    assert ecc_result["outcome"]["status"] == "recovered"
    assert rsa_result["instance"]["public_parameters"] == {"N": 15}
    assert rsa_result["instance"]["catalog_id"] == "rsa-n15-v1"
    assert ecc_result["instance"]["public_parameters"]["q"] == 7
    assert ecc_result["instance"]["public_parameters"]["Q"] == [6, 6]
    assert rsa_result["run"]["shots"] == 64
    assert ecc_result["run"]["shots"] == 128
