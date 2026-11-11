# Test Flask contracts and dispatch with stubs; browser interaction needs separate checks.
import json
from threading import Event

from breakingpkc.web import server
from breakingpkc.web.server import app
from breakingpkc.rsa.instance import DEFAULT_RSA_CATALOG_ID


def test_home_page_serves_application_shell() -> None:
    response = app.test_client().get("/")

    assert response.status_code == 200
    assert b"Different hard problems. One exploitable algebraic regularity." in response.data
    assert b"CURATED TOY INPUTS" in response.data


def test_home_page_loads_local_styles_and_script() -> None:
    response = app.test_client().get("/")

    assert b"/static/css/app.css" in response.data
    assert b"/static/js/app.js" in response.data


def test_home_page_presents_five_persistent_evidence_sections_without_navigation_rail() -> None:
    response = app.test_client().get("/")
    page = response.get_data(as_text=True)

    assert 'id="rsa-profile-input"' in page
    assert 'id="ecc-profile-input"' in page
    assert 'id="setup-key-button"' in page
    assert 'id="reveal-private-button"' in page
    assert 'id="public-key-fields"' in page
    assert 'id="private-key-fields"' in page
    assert 'id="run-ribbon"' in page
    assert 'id="run-context-detail"' in page
    assert (
        page.index('id="setup-key-button"')
        < page.index('id="run-ribbon"')
        < page.index('id="result-section"')
    )
    for stage in (
        "public_input",
        "quantum_observation",
        "recovered_structure",
        "secret_recovery",
        "validation",
    ):
        assert f'data-flow-section="{stage}"' in page
    assert 'class="step-rail"' not in page
    for modulus in (15, 21, 33, 35, 39, 55):
        assert f'value="rsa-n{modulus}-v1"' in page


def test_local_styles_and_script_are_served() -> None:
    client = app.test_client()

    css_response = client.get("/static/css/app.css")
    js_response = client.get("/static/js/app.js")

    assert css_response.status_code == 200
    assert b"--teal" in css_response.data
    assert js_response.status_code == 200
    assert b"/api/run/stream" in js_response.data


def test_run_route_dispatches_request_and_returns_workflow_result(monkeypatch) -> None:
    expected_result = {"algorithm": "ecc_discrete_log", "outcome": {"status": "recovered"}}
    calls = []

    def fake_workflow(shots: int, seed: int | None):
        calls.append((shots, seed))
        return expected_result

    monkeypatch.setitem(server.WORKFLOWS, "ecc", fake_workflow)
    response = app.test_client().post(
        "/api/run",
        json={"algorithm": "ecc", "shots": 128, "seed": 42},
    )

    assert response.status_code == 200
    assert response.get_json() == expected_result
    assert calls == [(128, 42)]


def test_run_route_uses_shared_default_and_rejects_parameter_overrides(monkeypatch) -> None:
    calls = []

    def fake_workflow(shots: int, seed: int | None, catalog_id: str):
        calls.append((shots, seed, catalog_id))
        return {"outcome": {"status": "failed"}}

    monkeypatch.setitem(server.WORKFLOWS, "rsa", fake_workflow)
    client = app.test_client()
    default_response = client.post("/api/run", json={"algorithm": "rsa"})
    override_response = client.post(
        "/api/run", json={"algorithm": "rsa", "N": 77}
    )

    assert default_response.status_code == 200
    assert calls == [(256, None, DEFAULT_RSA_CATALOG_ID)]
    assert override_response.status_code == 400
    assert override_response.get_json()["outcome"]["status"] == "error"


def test_run_route_dispatches_curated_rsa_catalog_selection(monkeypatch) -> None:
    calls = []

    def fake_workflow(shots: int, seed: int | None, catalog_id: str):
        calls.append((shots, seed, catalog_id))
        return {"instance": {"catalog_id": catalog_id}, "outcome": {"status": "failed"}}

    monkeypatch.setitem(server.WORKFLOWS, "rsa", fake_workflow)
    response = app.test_client().post(
        "/api/run",
        json={"algorithm": "rsa", "shots": 32, "rsa_catalog_id": "rsa-n21-v1"},
    )

    assert response.status_code == 200
    assert response.get_json()["instance"]["catalog_id"] == "rsa-n21-v1"
    assert calls == [(32, None, "rsa-n21-v1")]


def test_stream_route_emits_ordered_stage_events_and_final_result(monkeypatch) -> None:
    # A terminal envelope must remain distinct from stage events so readers can finish.
    expected_result = {
        "outcome": {"status": "recovered"},
        "events": [{"stage": "public_input", "category": "public_input"}],
    }

    def fake_workflow(shots: int, seed: int | None, catalog_id: str, progress_callback):
        progress_callback(expected_result["events"][0])
        return expected_result

    monkeypatch.setitem(server.WORKFLOWS, "rsa", fake_workflow)
    response = app.test_client().post(
        "/api/run/stream",
        json={"algorithm": "rsa", "rsa_catalog_id": "rsa-n21-v1"},
        buffered=True,
    )
    messages = [json.loads(line) for line in response.get_data(as_text=True).splitlines()]

    assert response.status_code == 200
    assert response.mimetype == "application/x-ndjson"
    assert [message["type"] for message in messages] == ["run_started", "stage", "complete"]
    assert messages[1]["event"] == expected_result["events"][0]
    assert messages[2]["result"] == expected_result


def test_run_route_dispatches_selected_ecc_public_key(monkeypatch) -> None:
    calls = []

    def fake_workflow(
        shots: int,
        seed: int | None,
        catalog_id: str,
        public_point: tuple[int, int],
    ):
        calls.append((shots, seed, catalog_id, public_point))
        return {"outcome": {"status": "recovered"}}

    monkeypatch.setitem(server.WORKFLOWS, "ecc", fake_workflow)
    response = app.test_client().post(
        "/api/run",
        json={
            "algorithm": "ecc",
            "ecc_catalog_id": "toy-f5-a2-b1-g0-1",
            "ecc_public_point": [1, 3],
        },
    )

    assert response.status_code == 200
    assert calls == [(256, None, "toy-f5-a2-b1-g0-1", (1, 3))]


def test_run_route_rejects_invalid_requests_before_workflow(monkeypatch) -> None:
    # Empty call tracking proves rejected requests never enter circuit construction.
    calls = []

    def fake_workflow(shots: int, seed: int | None):
        calls.append((shots, seed))
        return {}

    monkeypatch.setitem(server.WORKFLOWS, "rsa", fake_workflow)
    client = app.test_client()
    invalid_algorithm = client.post("/api/run", json={"algorithm": "dsa"})
    unhashable_algorithm = client.post("/api/run", json={"algorithm": ["rsa"]})
    invalid_shots = client.post("/api/run", json={"algorithm": "rsa", "shots": True})
    invalid_seed = client.post("/api/run", json={"algorithm": "rsa", "seed": -1})
    invalid_catalog = client.post(
        "/api/run", json={"algorithm": "rsa", "rsa_catalog_id": "rsa-n2048-v1"}
    )
    wrong_algorithm_catalog = client.post(
        "/api/run", json={"algorithm": "ecc", "rsa_catalog_id": "rsa-n15-v1"}
    )
    invalid_ecc_point = client.post(
        "/api/run",
        json={
            "algorithm": "ecc",
            "ecc_catalog_id": "toy-f5-a2-b1-g0-1",
            "ecc_public_point": [1, 1],
        },
    )
    invalid_body = client.post("/api/run", data="[]", content_type="application/json")

    assert [
        invalid_algorithm.status_code,
        unhashable_algorithm.status_code,
        invalid_shots.status_code,
        invalid_seed.status_code,
        invalid_catalog.status_code,
        wrong_algorithm_catalog.status_code,
        invalid_ecc_point.status_code,
        invalid_body.status_code,
    ] == [400, 400, 400, 400, 400, 400, 400, 400]
    assert calls == []


def test_toy_rsa_setup_returns_public_key_and_explicit_one_time_private_reveal() -> None:
    client = app.test_client()
    setup_response = client.post(
        "/api/setup",
        json={
            "algorithm": "rsa",
            "profile_id": "rsa-n15-v1",
            "public_exponent": 3,
        },
    )

    assert setup_response.status_code == 200
    setup = setup_response.get_json()
    assert set(setup) == {
        "schema_version", "algorithm", "profile_id", "key_label",
        "public_key", "private_key_handle", "recovery",
    }
    assert setup["public_key"] == {
        "catalog_id": "rsa-toy-primes-v1", "N": "15", "e": "3",
    }
    assert set(setup["public_key"]) == {"catalog_id", "N", "e"}
    assert setup["recovery"] == {
        "supported": True,
        "catalog_id": "rsa-n15-v1",
        "description": "A matching toy recovery workflow is available.",
    }
    factor_override = client.post(
        "/api/setup",
        json={
            "algorithm": "rsa",
            "profile_id": "rsa-n15-v1",
            "public_exponent": 3,
            "first_prime": 3,
            "second_prime": 5,
        },
    )
    assert factor_override.status_code == 400

    reveal_response = client.post(
        "/api/setup/reveal", json={"private_key_handle": setup["private_key_handle"]}
    )
    assert reveal_response.get_json()["private_key"] == {
        "p": "3", "q": "5", "d": "3", "phi": "8", "lambda": "4",
    }
    assert client.post(
        "/api/setup/reveal", json={"private_key_handle": setup["private_key_handle"]}
    ).status_code == 410


def test_toy_ecc_setup_derives_public_point_and_reveals_scalar_on_request() -> None:
    client = app.test_client()
    setup_response = client.post(
        "/api/setup",
        json={
            "algorithm": "ecc",
            "profile_id": "toy-f11-a1-b1-g0-1",
            "private_scalar": 3,
        },
    )

    assert setup_response.status_code == 200
    setup = setup_response.get_json()
    assert set(setup) == {
        "schema_version", "algorithm", "profile_id", "key_label",
        "public_key", "private_key_handle", "recovery",
    }
    assert setup["public_key"]["Q"] == ["6", "6"]
    assert "k" not in setup["public_key"]
    assert setup["recovery"]["supported"] is True
    reveal_response = client.post(
        "/api/setup/reveal", json={"private_key_handle": setup["private_key_handle"]}
    )
    assert reveal_response.get_json() == {"private_key": {"k": "3"}}


def test_toy_f5_key_setup_supports_recovery_from_its_derived_public_point() -> None:
    response = app.test_client().post(
        "/api/setup",
        json={"algorithm": "ecc", "profile_id": "toy-f5-a2-b1-g0-1", "private_scalar": 2},
    )

    assert response.status_code == 200
    result = response.get_json()
    assert result["public_key"]["Q"] == ["1", "3"]
    assert result["recovery"]["supported"] is True


def test_standard_key_setup_profiles_are_explicitly_setup_only() -> None:
    client = app.test_client()
    response = client.post(
        "/api/setup", json={"algorithm": "ecc", "profile_id": "nist-p256"}
    )
    rsa_response = client.post(
        "/api/setup", json={"algorithm": "rsa", "profile_id": "rsa-2048"}
    )

    assert response.status_code == 200
    result = response.get_json()
    assert result["public_key"]["curve_name"] == "secp256r1"
    assert result["recovery"]["supported"] is False
    assert "setup only" in result["recovery"]["description"].lower()
    rsa_result = rsa_response.get_json()
    assert rsa_response.status_code == 200
    assert rsa_result["public_key"]["e"] == "65537"
    assert rsa_result["recovery"]["supported"] is False


def test_setup_rejects_invalid_profiles_and_private_reveal_handles() -> None:
    client = app.test_client()
    invalid_profile = client.post(
        "/api/setup", json={"algorithm": "rsa", "profile_id": "rsa-1024"}
    )
    no_reveal_handle = client.post("/api/setup/reveal", json={})

    assert invalid_profile.status_code == 400
    assert no_reveal_handle.status_code == 400


def test_local_request_boundary_and_private_cache_policy() -> None:
    client = app.test_client()
    assert client.get("/", headers={"Host": "untrusted.example"}).status_code == 400
    assert client.post(
        "/api/setup", json={"algorithm": "rsa", "profile_id": "rsa-n15-v1"},
        headers={"Origin": "https://untrusted.example"},
    ).status_code == 403
    oversized = client.post("/api/setup", data=b"x" * 16_385, content_type="application/json")
    assert oversized.status_code == 413
    assert oversized.is_json
    setup = client.post("/api/setup", json={"algorithm": "rsa", "profile_id": "rsa-n15-v1"})
    assert setup.headers["Cache-Control"] == "no-store"
    reveal = client.post("/api/setup/reveal", json={
        "private_key_handle": setup.get_json()["private_key_handle"],
    })
    assert reveal.headers["Cache-Control"] == "no-store"


def test_worker_start_failure_releases_run_lock(monkeypatch) -> None:
    def fail_start(*args, **kwargs):
        raise RuntimeError("Cannot start worker")

    monkeypatch.setattr(server.Thread, "start", fail_start)
    response = app.test_client().post("/api/run/stream", json={"algorithm": "rsa"})
    assert response.status_code == 500
    assert response.is_json
    assert not server._ACTIVE_RUN_LOCK.locked()


def test_run_transport_errors_preserve_provenance(monkeypatch) -> None:
    observation = {
        "stage": "quantum_observation", "category": "simulator_observation",
        "label": "Measured", "evidence": {"attempt": 1, "counts": {"0": 1}},
    }

    def fail_workflow(parameters, progress_callback=None):
        if progress_callback is not None:
            progress_callback(observation)
        raise RuntimeError("Unexpected execution error")

    monkeypatch.setattr(server, "_execute_workflow", fail_workflow)
    client = app.test_client()
    synchronous = client.post("/api/run", json={"algorithm": "rsa"})
    assert synchronous.status_code == 500
    assert synchronous.is_json
    streamed = client.post("/api/run/stream", json={"algorithm": "rsa"}, buffered=True)
    messages = [json.loads(line) for line in streamed.get_data(as_text=True).splitlines()]
    result = messages[-1]["result"]
    assert result["events"][0] == observation
    assert result["events"][-1]["category"] == "run_error"
    assert result["run"]["total_shots"] == 1
    assert not server._ACTIVE_RUN_LOCK.locked()


def test_run_and_setup_contention_reject_without_releasing_owner_lock() -> None:
    client = app.test_client()
    for lock, route, payload in (
        (server._ACTIVE_RUN_LOCK, "/api/run", {"algorithm": "rsa"}),
        (server._ACTIVE_RUN_LOCK, "/api/run/stream", {"algorithm": "rsa"}),
        (server._SETUP_LOCK, "/api/setup", {"algorithm": "rsa", "profile_id": "rsa-n15-v1"}),
    ):
        lock.acquire()
        try:
            assert client.post(route, json=payload).status_code == 409
            assert lock.locked()
        finally:
            lock.release()


def test_expired_reveal_is_removed_and_returns_gone(monkeypatch) -> None:
    client = app.test_client()
    setup = client.post("/api/setup", json={"algorithm": "rsa", "profile_id": "rsa-n15-v1"})
    handle = setup.get_json()["private_key_handle"]
    expires, _ = server._PRIVATE_SETUP_STORE[handle]
    monkeypatch.setattr(server, "monotonic", lambda: expires + 1)
    assert client.post("/api/setup/reveal", json={"private_key_handle": handle}).status_code == 410
    assert handle not in server._PRIVATE_SETUP_STORE


def test_disconnect_does_not_release_execution_lock_before_worker_finishes(monkeypatch) -> None:
    resume = Event()
    entered = Event()

    def blocked_workflow(parameters, progress_callback):
        entered.set()
        assert resume.wait(timeout=5)
        progress_callback({"stage": "public_input", "category": "public_input"})
        return {"outcome": {"status": "failed"}, "events": []}

    monkeypatch.setattr(server, "_execute_workflow", blocked_workflow)
    response = app.test_client().post("/api/run/stream", json={"algorithm": "rsa"}, buffered=False)
    try:
        assert entered.wait(timeout=5)
        response.close()
        assert server._ACTIVE_RUN_LOCK.locked()
    finally:
        resume.set()
    assert server._ACTIVE_RUN_LOCK.acquire(timeout=5)
    server._ACTIVE_RUN_LOCK.release()
