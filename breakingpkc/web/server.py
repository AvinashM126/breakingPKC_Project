"""Local Flask application for the RSA/ECC teaching workflows."""

import json
import logging
from queue import Queue
from secrets import token_urlsafe
from threading import Event, Lock, Thread
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

from flask import Flask, Response, g, jsonify, render_template, request, stream_with_context
from werkzeug.exceptions import HTTPException

from ..common.run_config import DEFAULT_SHOTS, MAX_SEED, MAX_SHOTS
from ..ecc.curve import validate_subgroup
from ..ecc.setup import (
    TOY_GROUPS,
    create_toy_key as create_toy_ecc_key,
    generate_toy_key as generate_toy_ecc_key,
    get_toy_group,
)
from ..ecc.standard_setup import generate_standard_key as generate_standard_ecc_key
from ..ecc.workflow import run_ecc
from ..rsa.instance import (
    DEFAULT_RSA_CATALOG_ID,
    RSA_TOY_CATALOG,
    RSA_TOY_PRIME_PAIRS,
    modulus_from_catalog,
)
from ..rsa.setup import (
    allowed_exponents,
    create_toy_key as create_toy_rsa_key,
    generate_standard_key as generate_standard_rsa_key,
)
from ..rsa.workflow import MAX_RSA_ATTEMPTS, run_rsa

app = Flask(__name__)
app.config.update(
    MAX_CONTENT_LENGTH=16_384,
    TRUSTED_HOSTS=["localhost", "127.0.0.1", "[::1]"],
)
WORKFLOWS = {"rsa": run_rsa, "ecc": run_ecc}
_PRIVATE_SETUP_TTL_SECONDS = 900
_MAX_STORED_PRIVATE_SETUPS = 32
_PRIVATE_SETUP_STORE: dict[str, tuple[float, Any]] = {}
_PRIVATE_SETUP_LOCK = Lock()
_SETUP_LOCK = Lock()
# Both run transports share this lock; separate browser tabs cannot bypass it.
_ACTIVE_RUN_LOCK = Lock()
_MAX_STREAM_EVENTS = MAX_SHOTS * MAX_RSA_ATTEMPTS + 128
LOGGER = logging.getLogger(__name__)


@app.before_request
def check_local_request():
    if request.method == "POST":
        origin = request.headers.get("Origin")
        if origin is not None:
            try:
                parsed = urlsplit(origin)
            except ValueError:
                return _request_error_response("Invalid request origin.", None, None, None, 403)
            if parsed.scheme != request.scheme or parsed.netloc.lower() != request.host.lower():
                return _request_error_response("Cross-origin requests are not allowed.", None, None, None, 403)
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            return _request_error_response("Cross-site requests are not allowed.", None, None, None, 403)
    if request.endpoint == "setup_key":
        if not _SETUP_LOCK.acquire(blocking=False):
            return jsonify({"error": "Another key setup is already active."}), 409
        g.setup_lock_acquired = True


@app.teardown_request
def release_setup_lock(error=None):
    if g.pop("setup_lock_acquired", False):
        _SETUP_LOCK.release()


@app.after_request
def set_response_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.errorhandler(HTTPException)
def handle_http_error(error):
    if request.path.startswith("/api/"):
        return _request_error_response(error.description, None, None, None, error.code or 500)
    return error


@app.errorhandler(500)
def handle_internal_error(error):
    if request.path.startswith("/api/"):
        return _request_error_response("The request failed; see developer logs for details.", None, None, None, 500)
    return error


def _store_private_setup(setup: Any) -> str:
    """Keep private setup in bounded memory and return an expiring reveal handle."""
    now = monotonic()
    with _PRIVATE_SETUP_LOCK:
        expired_handles = [
            handle
            for handle, (expires_at, _) in _PRIVATE_SETUP_STORE.items()
            if expires_at <= now
        ]
        for handle in expired_handles:
            _PRIVATE_SETUP_STORE.pop(handle, None)
        while len(_PRIVATE_SETUP_STORE) >= _MAX_STORED_PRIVATE_SETUPS:
            oldest_handle = min(
                _PRIVATE_SETUP_STORE,
                key=lambda handle: _PRIVATE_SETUP_STORE[handle][0],
            )
            _PRIVATE_SETUP_STORE.pop(oldest_handle, None)
        handle = token_urlsafe(24)
        _PRIVATE_SETUP_STORE[handle] = (now + _PRIVATE_SETUP_TTL_SECONDS, setup)
    return handle


def _take_private_setup(handle: Any) -> Any | None:
    """Consume a reveal handle atomically, including when it has expired."""
    if not isinstance(handle, str):
        return None
    with _PRIVATE_SETUP_LOCK:
        stored = _PRIVATE_SETUP_STORE.pop(handle, None)
    if stored is None or stored[0] <= monotonic():
        return None
    return stored[1]


def _request_error_result(
    message: str, algorithm: str | None, shots: Any, seed: Any
) -> dict[str, Any]:
    algorithm_ids = {"rsa": "rsa_factoring", "ecc": "ecc_discrete_log"}
    algorithm_id = (
        algorithm_ids.get(algorithm, "unknown")
        if isinstance(algorithm, str)
        else "unknown"
    )
    return {
        "schema_version": 1,
        "algorithm": algorithm_id,
        "instance": {"label": "No experiment was run", "public_parameters": {}},
        "run": {
            "shots": shots,
            "seed": seed,
            "simulator": "Qiskit Aer",
            "mode": "ideal_statevector",
            "registers": {},
            "qubits": 0,
            "fixed_instance": True,
            "scalable": False,
        },
        "events": [],
        "candidates": [],
        "outcome": {"status": "error", "summary": message},
        "limitations": ["Request was rejected before circuit construction."],
    }


def _request_error_response(
    message: str,
    algorithm: str | None,
    shots: Any,
    seed: Any,
    status_code: int = 400,
) -> tuple[Response, int]:
    """Use the workflow-shaped error contract for both run endpoints."""
    result = _request_error_result(message, algorithm, shots, seed)
    return jsonify(result), status_code


@app.get("/")
def index() -> str:
    rsa_toy_profiles = [
        {
            "catalog_id": catalog_id,
            "modulus": RSA_TOY_CATALOG[catalog_id],
            "exponents": allowed_exponents(*primes),
        }
        for catalog_id, primes in RSA_TOY_PRIME_PAIRS.items()
    ]
    return render_template(
        "index.html",
        rsa_toy_profiles=rsa_toy_profiles,
        ecc_toy_groups=TOY_GROUPS,
    )


@app.post("/api/setup")
def setup_key():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object."}), 400
    algorithm = payload.get("algorithm")
    profile_id = payload.get("profile_id")
    if not isinstance(profile_id, str):
        return jsonify({"error": "profile_id must be a string."}), 400

    try:
        if algorithm == "rsa":
            if profile_id in RSA_TOY_PRIME_PAIRS:
                allowed = {"algorithm", "profile_id", "public_exponent"}
                if set(payload) - allowed:
                    raise ValueError("Unexpected fields for toy RSA setup.")
                first_prime, second_prime = RSA_TOY_PRIME_PAIRS[profile_id]
                setup = create_toy_rsa_key(
                    first_prime,
                    second_prime,
                    payload.get("public_exponent"),
                )
                recovery_catalog_id = profile_id
                recovery_supported = True
                public = setup.public_attack_input().to_dict()
            elif profile_id in {"rsa-2048", "rsa-3072"}:
                if set(payload) != {"algorithm", "profile_id"}:
                    raise ValueError("Standard RSA setup accepts only its named profile.")
                setup = generate_standard_rsa_key(profile_id)
                recovery_catalog_id = None
                recovery_supported = False
                public = setup.public_attack_input().to_dict()
            else:
                raise ValueError("Select toy RSA, rsa-2048, or rsa-3072.")
        elif algorithm == "ecc":
            if profile_id in {group.catalog_id for group in TOY_GROUPS}:
                allowed = {"algorithm", "profile_id", "private_scalar"}
                if set(payload) - allowed:
                    raise ValueError("Unexpected fields for toy ECC setup.")
                scalar = payload.get("private_scalar")
                setup = (
                    generate_toy_ecc_key(profile_id)
                    if scalar is None
                    else create_toy_ecc_key(profile_id, scalar)
                )
                recovery_catalog_id = profile_id
                recovery_supported = True
                public = setup.public_attack_input().to_dict()
            elif profile_id in {"nist-p256", "nist-p384"}:
                if set(payload) != {"algorithm", "profile_id"}:
                    raise ValueError("Standard ECC setup accepts only its named profile.")
                setup = generate_standard_ecc_key(profile_id)
                recovery_catalog_id = None
                recovery_supported = False
                public = setup.public_attack_input().to_dict()
            else:
                raise ValueError("Select a named toy ECC group or NIST P-256/P-384.")
        else:
            raise ValueError("algorithm must be 'rsa' or 'ecc'.")
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    # Initial responses contain public values plus an opaque handle, not private fields.
    handle = _store_private_setup(setup)
    if algorithm == "rsa":
        key_label = (
            f"Toy RSA keypair, N={setup.public.modulus}"
            if profile_id in RSA_TOY_PRIME_PAIRS
            else profile_id.upper()
        )
    elif profile_id in {group.catalog_id for group in TOY_GROUPS}:
        key_label = f"Toy ECC keypair over F_{setup.public.group.curve.prime}"
    else:
        key_label = f"ECC keypair on {setup.public.curve_name}"
    return jsonify(
        {
            "schema_version": 1,
            "algorithm": algorithm,
            "profile_id": profile_id,
            "key_label": key_label,
            "public_key": public,
            "private_key_handle": handle,
            "recovery": {
                "supported": recovery_supported,
                "catalog_id": recovery_catalog_id,
                "description": (
                    "A matching toy recovery workflow is available."
                    if recovery_supported
                    else "Setup only; Shor recovery is not available for this selected profile."
                ),
            },
        }
    )


@app.post("/api/setup/reveal")
def reveal_private_setup():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {"private_key_handle"}:
        return jsonify({"error": "A private_key_handle is required."}), 400
    setup = _take_private_setup(payload["private_key_handle"])
    if setup is None:
        message = "This private-key reveal handle is invalid, expired, or already used."
        return jsonify({"error": message}), 410
    return jsonify({"private_key": setup.reveal_private()})


@app.post("/api/run")
def run_experiment():
    parameters, error_response = _validated_run_parameters(request.get_json(silent=True))
    if error_response is not None:
        return error_response
    if not _ACTIVE_RUN_LOCK.acquire(blocking=False):
        return _request_error_response(
            "Another local run is already active.",
            parameters["algorithm"],
            parameters["shots"],
            parameters["seed"],
            status_code=409,
        )
    try:
        result = _execute_workflow(parameters)
    except Exception:
        LOGGER.exception("Synchronous workflow failed")
        return _request_error_response(
            "The run failed; see developer logs for details.",
            parameters["algorithm"], parameters["shots"], parameters["seed"], 500,
        )
    finally:
        _ACTIVE_RUN_LOCK.release()
    return jsonify(result)


def _validated_run_parameters(payload: Any) -> tuple[dict[str, Any] | None, Any | None]:
    """Reject invalid or private inputs before invoking an algorithm workflow."""
    if not isinstance(payload, dict):
        return None, _request_error_response(
            "Request body must be a JSON object.", None, None, None
        )

    algorithm = payload.get("algorithm")
    shots = payload.get("shots", DEFAULT_SHOTS)
    seed = payload.get("seed")
    allowed_keys = {
        "algorithm",
        "shots",
        "seed",
        "rsa_catalog_id",
        "ecc_catalog_id",
        "ecc_public_point",
    }
    if set(payload) - allowed_keys:
        message = "Unsupported fields supplied for this run request."
        return None, _request_error_response(message, algorithm, shots, seed)
    if not isinstance(algorithm, str) or algorithm not in WORKFLOWS:
        return None, _request_error_response(
            "algorithm must be 'rsa' or 'ecc'.", None, shots, seed
        )

    parameters: dict[str, Any] = {"algorithm": algorithm, "shots": shots, "seed": seed}
    if algorithm == "rsa":
        if "ecc_catalog_id" in payload or "ecc_public_point" in payload:
            message = "ECC key fields are only valid for the ECC workflow."
            return None, _request_error_response(message, algorithm, shots, seed)
        catalog_id = payload.get("rsa_catalog_id", DEFAULT_RSA_CATALOG_ID)
        try:
            modulus_from_catalog(catalog_id)
        except ValueError as error:
            return None, _request_error_response(str(error), algorithm, shots, seed)
        parameters["catalog_id"] = catalog_id
    else:
        if "rsa_catalog_id" in payload:
            message = "rsa_catalog_id is only valid for the RSA workflow."
            return None, _request_error_response(message, algorithm, shots, seed)
        if "ecc_catalog_id" in payload or "ecc_public_point" in payload:
            catalog_id = payload.get("ecc_catalog_id")
            public_value = payload.get("ecc_public_point")
            if (
                not isinstance(catalog_id, str)
                or not isinstance(public_value, list)
                or len(public_value) != 2
            ):
                message = "A named ECC toy group and two-coordinate public point are required."
                return None, _request_error_response(message, algorithm, shots, seed)
            try:
                group = get_toy_group(catalog_id)
                if any(type(coordinate) is not int for coordinate in public_value):
                    raise ValueError("ECC public point coordinates must be integers.")
                public_point = (public_value[0], public_value[1])
                validate_subgroup(group.curve, group.generator, group.order, public_point)
            except ValueError as error:
                return None, _request_error_response(str(error), algorithm, shots, seed)
            parameters["catalog_id"] = catalog_id
            parameters["public_point"] = public_point

    if not isinstance(shots, int) or isinstance(shots, bool) or not 1 <= shots <= MAX_SHOTS:
        message = f"shots must be an integer from 1 through {MAX_SHOTS}."
        return None, _request_error_response(message, algorithm, shots, seed)
    if seed is not None and (
        not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed <= MAX_SEED
    ):
        message = f"seed must be an integer from 0 through {MAX_SEED}."
        return None, _request_error_response(message, algorithm, shots, None)
    return parameters, None


def _execute_workflow(
    parameters: dict[str, Any],
    progress_callback=None,
) -> dict[str, Any]:
    workflow = WORKFLOWS[parameters["algorithm"]]
    options = {key: value for key, value in parameters.items() if key != "algorithm"}
    if progress_callback is not None:
        options["progress_callback"] = progress_callback
    return workflow(**options)


@app.post("/api/run/stream")
def stream_experiment():
    parameters, error_response = _validated_run_parameters(request.get_json(silent=True))
    if error_response is not None:
        return error_response
    if not _ACTIVE_RUN_LOCK.acquire(blocking=False):
        return _request_error_response(
            "Another local run is already active.",
            parameters["algorithm"],
            parameters["shots"],
            parameters["seed"],
            status_code=409,
        )

    event_queue: Queue[dict[str, Any]] = Queue(maxsize=_MAX_STREAM_EVENTS)
    client_disconnected = Event()
    run_id = token_urlsafe(12)
    published_events: list[dict[str, Any]] = []

    def send_stage_event(event: dict[str, Any]) -> None:
        # Transport envelopes must not be mistaken for workflow stage events.
        published_events.append(event)
        if not client_disconnected.is_set():
            event_queue.put({"type": "stage", "event": event})

    def execute() -> None:
        terminal_message: dict[str, Any]
        try:
            result = _execute_workflow(parameters, send_stage_event)
            terminal_message = {"type": "complete", "result": result}
        except Exception:
            LOGGER.exception("Streamed workflow failed")
            result = _request_error_result(
                "The run failed; see developer logs for details.",
                parameters["algorithm"],
                parameters["shots"],
                parameters["seed"],
            )
            failure_event = {
                "stage": "quantum_observation",
                "category": "run_error",
                "label": "Execution error",
                "description": "Execution stopped; previous observations are preserved.",
                "evidence": {},
            }
            send_stage_event(failure_event)
            result["events"] = list(published_events)
            observations = [
                event["evidence"] for event in published_events
                if event["category"] == "simulator_observation"
            ]
            result["run"]["total_shots"] = sum(
                sum(evidence.get("counts", {}).values())
                + sum(pair["count"] for pair in evidence.get("frequencies", []))
                for evidence in observations
            )
            result["run"]["attempts_completed"] = len(observations)
            terminal_message = {"type": "complete", "result": result}
        finally:
            # The worker, not the browser connection, owns execution lifetime.
            _ACTIVE_RUN_LOCK.release()
        if not client_disconnected.is_set():
            event_queue.put(terminal_message)

    try:
        Thread(target=execute, daemon=True, name=f"breakingpkc-{run_id}").start()
    except Exception:
        _ACTIVE_RUN_LOCK.release()
        LOGGER.exception("Unable to start run worker")
        return _request_error_response(
            "Unable to start the run worker.",
            parameters["algorithm"], parameters["shots"], parameters["seed"], 500,
        )

    @stream_with_context
    def stream_events():
        # NDJSON frames follow semantic workflow events, not simulated shot progress.
        try:
            yield json.dumps({"type": "run_started", "run_id": run_id}) + "\n"
            while True:
                event = event_queue.get()
                yield json.dumps(event, separators=(",", ":")) + "\n"
                if event.get("type") == "complete":
                    break
        finally:
            # Stop publishing output without claiming to cancel an in-flight Aer call.
            client_disconnected.set()

    return Response(stream_events(), mimetype="application/x-ndjson")


def main() -> None:
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()
