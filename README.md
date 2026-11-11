# Breaking PKC

A local educational application demonstrating how Shor's algorithms approach
RSA integer factoring and elliptic-curve discrete logarithms. It is designed for
presentations and exploration of small, measurable examples, not production-key
attacks.

The browser follows public inputs through circuit measurements, classical
post-processing, candidate recovery, and public validation. Python owns the
mathematics and simulation; the browser presents the resulting evidence.

## Supported Demonstrations

| Family | Profiles | Capability |
| --- | --- | --- |
| Toy RSA | N = 15, 21, 33, 35, 39, 55 | Key setup and bounded factor recovery |
| Toy ECC | Curated groups over F_11 and F_5, both of order 7 | Key setup and scalar recovery from the selected public point |
| Standard RSA | RSA-2048 and RSA-3072 | Key generation and inspection only |
| Standard ECC | NIST P-256 and P-384 | Key generation and inspection only |

Standard profiles use the `cryptography` library. Recovery is disabled for these
profiles; the toy circuits do not scale to production key sizes.

## Requirements

- Windows with 64-bit CPython **3.14**. Other Python minor versions are not supported.
- A browser for the local application.
- Dependencies installed from your approved package source.

Runtime and test dependencies are pinned in [setup/requirements.txt](setup/requirements.txt)
and [pyproject.toml](pyproject.toml). The main libraries are Flask, Qiskit, Qiskit
Aer, and `cryptography`; tests use pytest.

## Installation

Run these commands from the `breakingPKC_Project` directory:

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -r setup/requirements.txt
.venv\Scripts\python.exe -m pip install --no-build-isolation --no-deps -e .
```

The commands use the virtual environment directly; activation is optional.

## Run The Application

```powershell
.venv\Scripts\python.exe -m breakingpkc.web.server
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000). The server binds to localhost.
Press `Ctrl+C` in the server terminal to stop it. Restart the server after Python
code changes.

## User Guide: Execute And Read The Demo

### Execute A Demo

1. Start the server using the command above and open the local application.
	 For a presentation, use a 1920x1080 display and start at 100% browser zoom.
	 Scroll through the evidence rather than shrinking the entire page to fit.
2. Select **RSA** or **ECC**, then choose a toy profile. RSA offers eligible
	 **Public exponent** values; ECC offers a **Private scalar** selection.
	 Leave the exponent at its default for the examples below. For a repeatable
	 ECC example, choose **Toy F11 group (q=7)** and **Choose 3**.
3. Click **GENERATE KEYPAIR**. Read the **Public instance** panel below it:
	 RSA exposes the modulus and public exponent; ECC exposes the curve, generator,
	 subgroup order, and public point. The ECC field prime and subgroup order are
	 different quantities, even when both are small.
4. Open **Settings** beside the run controls. Set **Shots** and optionally
	 **Random seed**. Start with 256 shots; use the examples below when rehearsing
	 a particular outcome. A blank seed chooses a fresh value for each run.
5. Click **RUN SIMULATION**. Follow the five evidence sections as results arrive.
	 Read the final summary and metadata, including the actual total shots and
	 number of attempts or batches, before interpreting the outcome.
6. Optionally click **REVEAL PRIVATE KEY** to compare the setup secret with the
	 recovered result. Reveal is not recovery: it retrieves the setup's private
	 values separately and is not required for the simulation. For a presentation,
	 leave the secret hidden until after public validation.
7. To compare outcomes on the same public instance, change shots or seed and run
	 again. To switch profile or ECC scalar, generate the new keypair before running.

Standard RSA and NIST ECC profiles allow key generation and inspection only.
Their stages say **SETUP ONLY** and recovery is disabled; this is intentional,
not an unfinished run.

### Read The Five Stages

| Stage | RSA: what to inspect | ECC: what to inspect |
| --- | --- | --- |
| 1. Classical Preprocessing / Public Input Checks | The selected base and its gcd with N. A nontrivial gcd can recover factors before any circuit runs. | Curve membership and subgroup checks on the public inputs. Passing these checks does not reveal the private scalar. |
| 2. Quantum Observation | The shared circuit blueprint and each attempt's measured phase histogram. | The shared circuit blueprint and each batch's frequency-pair heatmap. |
| 3. Recovered Structure | Phase fractions, reconstructed candidates, and the minimal order verified by public modular checks. | Measured pairs (u, v) and the relation v = k u modulo q. Informative pairs allow a scalar candidate via modular inversion. |
| 4. Secret Recovery | Factor candidates derived from the order, or the explicitly labeled classical gcd shortcut. The factoring demonstration does not claim that a private exponent was quantum-measured. | A scalar candidate derived from frequency constraints, not read from the generated private key. |
| 5. Validation | Public checks that the proposed nontrivial factors multiply to N. | A public check that multiplying the generator by the candidate reproduces the public point. |

Stage headings describe the process, not proof that it succeeded. Treat a result
as recovered only when the final outcome and public validation support it.
**NOT REACHED** means no candidate reached validation; it does not mean a
candidate failed its public check. An execution error or interrupted browser
request is also different from a completed, unsuccessful sampling run.

### Read Charts, Samples, And Retries

- **RSA histogram:** each bar is a measured phase outcome; its count is the
	number of shots with that outcome, not a probability that the factors are
	correct. A frequent outcome may still be uninformative or fail reconstruction.
- **ECC heatmap:** each cell counts a measured (u, v) pair. Stronger shading means
	more observations, not greater confidence in a private scalar. The (0, 0) pair
	supplies no scalar constraint and is uninformative, not evidence of k = 0.
- **Stage 3 sample tables:** expand the sample disclosure and use its pagination
	to inspect reconstruction and rejection reasons. Distinct outcomes can have
	counts greater than one; table rows are not individual shots. Graphs stay
	visible even when these dense tables are collapsed.
- **Rejected versus uninformative:** a sample that yields no useful constraint
	differs from a candidate that fails a check. Read the stated reason rather
	than interpreting every non-success as the same failure.
- **Retries:** attempts and batches retain their own observations and outcomes.
	The circuit blueprint is shared, but later measurements are new evidence.
	Both workflows stop on validated recovery or after at most four attempts/batches.
- **Shot accounting:** shots are configured per circuit batch. Total completed
	shots can span multiple attempts; a classical RSA shortcut can use zero shots.
	More shots can help sampling but do not guarantee success within the budget.
- **Technical details:** expand this section for the complete event trace and
	limitations when the summary is insufficient. Use status text and equations,
	not color alone, to interpret the result.

### Rehearsal Examples

Generate the specified toy keypair, then enter these settings. These outcomes
were checked in the project's current environment; exact sampled counts depend
on the installed versions and execution environment.

| Purpose | Public instance / setup | Shots per batch | Seed | Observed outcome |
| --- | --- | --- | --- | --- |
| RSA quantum-derived recovery with retries | Toy RSA N=35 | 256 | 474292336 | Factors 5 and 7 after three base attempts; 768 total shots; validation passed. |
| RSA classical shortcut | Toy RSA N=15 | 256 | 314159 | Factors recovered by classical gcd preprocessing; zero sampled shots. Do not present this as quantum recovery. |
| ECC recovery after an uninformative batch | Toy F11 group, private scalar 3 | 1 | 50 | First batch uninformative; scalar 3 recovered on batch two; two total shots. |
| ECC exhausted sampling budget | Toy F11 group, private scalar 3 | 1 | 17 | Four uninformative batches; four total shots; no candidate and validation not reached. |

For RSA, explain the difference between discovering a period and extracting
useful factors from it. For ECC, explain how a frequency constraint leads to a
candidate scalar. End both routes with public validation and the scale-gap
limitation: a toy simulation illustrates the mechanism, not a production-key
attack or quantum advantage.

### Run Settings

| Setting | Default | Bounds |
| --- | --- | --- |
| Shots per circuit | 256 | 1-4096 |
| Browser seed | Fresh random seed when blank; displayed with the result | 0-4294967295 |
| RSA base attempts | Up to 4 | Stops on validated recovery or budget exhaustion |
| ECC sampling batches | Up to 4 | Stops on validated recovery or budget exhaustion |

The seed controls sampling and RSA base selection, not generated secret keys.
To replay a browser run, use the same public instance, shots, and seed. Selecting
the same ECC group alone is insufficient if a newly generated scalar changes
the public point; choose the same scalar too. CLI/API requests that omit a seed use
the reproducible default 314159. Transpilation is also seeded; exact reproduction
assumes the same dependency versions and execution environment.
RSA shuffles bases from the full interval 2..N-1 without screening for success. A
nontrivial gcd is labeled classical preprocessing, not quantum recovery.
Each retry's seed and observations are retained. Metadata separates configured
shots per batch from total completed shots. One run and one key-generation request
are allowed at a time per server process. Uninformative samples or
unhelpful periods can produce an unsuccessful run; success is not guaranteed.

At 1920x1080, the desktop layout uses fixed presentation typography and places
attempt facts beside the visible graph. Smaller screens stack the same evidence
vertically. The complete five-stage trace scrolls normally; it is not compressed
onto one slide. Neutral stage bands are separate from teal/coral outcome colors.

### Troubleshooting A Demo

| Symptom | Action |
| --- | --- |
| The launch command cannot find the virtual environment or package | Run it from `breakingPKC_Project`, using the installation steps above. Launching from the workspace parent is not equivalent. |
| Run is disabled | Generate a keypair and check its capability. Standard profiles are setup-only; select a toy profile for recovery. |
| A run finishes without recovery | Read the rejection reasons and attempt budget. Try another seed or more shots; keep unsuccessful runs visible as legitimate probabilistic outcomes. |
| A seeded ECC run differs from rehearsal | Check the group, chosen scalar/public point, shots, seed, and dependency versions. The run seed does not reproduce random key generation. |
| The server reports another run or setup is active | Let the active request finish before retrying. Only one of each is admitted per server process. |
| The browser times out or disconnects | The simulator may still be active. Wait for it to finish; if it is genuinely hung, stop and restart the server. A browser timeout does not cancel native simulator work. |
| Private-key reveal expires or was already used | Reveal handles are one-use and expire after 15 minutes. Generate a new demo keypair if a fresh reveal is needed; setup changes require a new run for that instance. |

## Limitations And Key Handling

- Simulations use ideal local Qiskit Aer, not quantum hardware or a noise model.
- Gates and oracles are compiled for tiny public instances. They are not scalable
	reversible arithmetic and do not demonstrate quantum advantage.
- Local circuit limits are 18 compiled qubits and 250,000 compiled operations.
	These application limits are not production-attack resource estimates.
- Encryption, decryption, signing, key exchange, and importing deployed keys
	are outside the application's scope.
- Private setup objects are held in bounded process memory, not saved to disk.
	Reveal handles are one-use and expire after 15 minutes. Expired objects are
	removed lazily on storage/reveal activity, not by timed memory erasure. API
	responses use no-store. Revealed values remain
	visible in the current page until its setup is cleared or replaced.
- Requests are limited to 16 KiB, local Host values, and same-origin browser POSTs.
  These are local-app safeguards, not authorization for shared-network deployment.
- The browser stops waiting for a run after 120 seconds (setup/reveal: 30 seconds).
  Disconnecting or timing out does not cancel an in-process Aer operation. The
  server keeps the execution lock until that operation returns; restart the server
  to recover from a genuinely hung simulator.
- This is an educational inspection boundary, not secure secret storage or
	production key management. Use generated demonstration keys only.

## Testing

Run the complete suite from the project directory:

```powershell
.venv\Scripts\python.exe -m pytest
```

Tests cover RSA/ECC arithmetic, circuit behavior, key setup, recovery workflows,
the developer CLI, and Flask routes. The suite includes simulator-backed tests.
Browser interaction and visual checks are separate from the Python suite.
The reusable browser regressions are in `tests/web/renderer_checks.js`. On a fresh
local app page, load that file with Playwright's `page.addScriptTag({path: ...})`
and evaluate `runRendererRegressionChecks()`. Run at 1920x1080 and 390x844.
The script resets its synthetic fixtures afterward and requires no new package.

## Developer CLI

The CLI is a JSON-output validation harness over the same Python workflows,
not a separate implementation or a replacement for the browser interface.

```powershell
.venv\Scripts\python.exe -m breakingpkc rsa --shots 256 --seed 314159
.venv\Scripts\python.exe -m breakingpkc rsa --rsa-catalog rsa-n21-v1 --shots 256
.venv\Scripts\python.exe -m breakingpkc ecc --shots 256 --seed 314159
```

RSA catalog IDs use `rsa-n<N>-v1`, where N is one of the supported toy moduli
listed above. The ECC CLI runs the default F_11 public instance; use the browser
to select a different ECC group or generated public point.

## Project Structure

```text
breakingPKC_Project/
		breakingpkc/
				common/          Shared run defaults and limits
				ecc/             ECC setup, curve arithmetic, circuits, and recovery
				rsa/             RSA setup, arithmetic, circuits, and recovery
				web/             Flask routes, templates, CSS, and browser JavaScript
				cli.py           Developer workflow dispatcher
				__main__.py      Python module entry point
		setup/
				requirements.txt
		tests/               Tests grouped by algorithm and interface
		pyproject.toml       Package metadata and test configuration
		README.md
```

RSA and ECC remain independent packages. Shared configuration and the web/CLI
interfaces coordinate them without duplicating recovery mathematics.
Legacy source, presentation material, and planning documents elsewhere in the
workspace are reference material outside this application package.
