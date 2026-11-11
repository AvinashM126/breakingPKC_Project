// This layer submits public inputs and renders Python evidence; it performs no recovery math.
const algorithmContent = {
  rsa: {
    kicker: "SHOR'S FACTORING ROUTE",
    title: "Find the hidden factors.",
    description: "Order finding reveals periodic structure in modular multiplication. Classical post-processing turns measured phase information into factor candidates.",
    quantum: "Controlled modular multiplication\nand inverse Fourier transform",
    classical: "Phase fractions, order checks,\nthen gcd factor recovery"
  },
  ecc: {
    kicker: "SHOR'S DISCRETE-LOG ROUTE",
    title: "Recover the hidden scalar.",
    description: "A coherent public-point oracle combines curve points. Fourier-sampled frequencies reveal a relation that classical modular arithmetic can test against the public key.",
    quantum: "Public-point group oracle\nand exact seven-state Fourier transform",
    classical: "Measured frequency pairs, modular\ninversion, then public point check"
  }
};

// Keep stable control references together so run locking covers every selection field.
const tabs = [...document.querySelectorAll(".algorithm-tab")];
const algorithmInput = document.querySelector("#algorithm-input");
const rsaProfileInput = document.querySelector("#rsa-profile-input");
const rsaExponentInput = document.querySelector("#rsa-exponent-input");
const rsaExponentField = document.querySelector("#rsa-exponent-field");
const eccProfileInput = document.querySelector("#ecc-profile-input");
const eccScalarInput = document.querySelector("#ecc-scalar-input");
const eccScalarField = document.querySelector("#ecc-scalar-field");
const rsaSetupControls = document.querySelector("#rsa-setup-controls");
const eccSetupControls = document.querySelector("#ecc-setup-controls");
const setupKeyButton = document.querySelector("#setup-key-button");
const setupResult = document.querySelector("#key-setup-result");
const revealPrivateButton = document.querySelector("#reveal-private-button");
const publicKeyFields = document.querySelector("#public-key-fields");
const privateKeyFields = document.querySelector("#private-key-fields");
const runForm = document.querySelector("#run-form");
const runButton = document.querySelector("#run-button");
const shotsInput = document.querySelector("#shots-input");
const seedInput = document.querySelector("#seed-input");
const runControls = [
  setupKeyButton,
  ...tabs,
  rsaProfileInput,
  rsaExponentInput,
  eccProfileInput,
  eccScalarInput,
  shotsInput,
  seedInput
];
const runRibbon = document.querySelector("#run-ribbon");
const runRibbonSlot = document.querySelector("#run-ribbon-slot");
const runSettings = document.querySelector(".advanced-settings");
const resultSection = document.querySelector("#result-section");
const toast = document.querySelector("#toast");
let activeKeySetup = null;
let privateKeyHandle = null;
// A selection change invalidates pending setup and private-key reveal responses.
let keySetupRevision = 0;
let setupRequestSequence = 0;
// A returning stream may update only the run that still owns the visible evidence.
let runSequence = 0;
let activeRunId = null;
const structurePageSize = 50;
const renderedTraceEvents = [];
const flowContentIds = {
  public_input: "#flow-public-content",
  quantum_observation: "#flow-observation-content",
  recovered_structure: "#flow-structure-content",
  secret_recovery: "#flow-secret-content",
  validation: "#flow-validation-content"
};

function flowContent(stage) {
  return document.querySelector(flowContentIds[stage]);
}

function setButtonLabel(button, text) {
  button.textContent = text;
}

function setRunControlsDisabled(disabled) {
  for (const control of runControls) control.disabled = disabled;
}

function updateRunAvailability() {
  // Capability comes from setup; a standard-sized key must never enable toy recovery.
  const title = document.querySelector("#run-title");
  const detail = document.querySelector("#run-context-detail");
  if (!activeKeySetup) {
    runRibbon.dataset.state = "waiting";
    title.textContent = "Generate a keypair first";
    detail.textContent = "No public key selected";
    runButton.disabled = true;
    runButton.querySelector("span:first-child").textContent = "RUN SIMULATION";
  } else if (!activeKeySetup.recovery?.supported) {
    runRibbon.dataset.state = "setup_only";
    title.textContent = "Setup only";
    detail.textContent = activeKeySetup.key_label;
    runButton.disabled = true;
    runButton.querySelector("span:first-child").textContent = "SETUP ONLY";
  } else {
    const running = resultSection.getAttribute("aria-busy") === "true";
    runRibbon.dataset.state = running ? "running" : "ready";
    title.textContent = running
      ? "Simulation running"
      : `${activeKeySetup.algorithm.toUpperCase()} keypair ready`;
    detail.textContent = activeKeySetup.algorithm === "rsa"
      ? `N = ${activeKeySetup.public_key.N} / e = ${activeKeySetup.public_key.e}`
      : `F_${activeKeySetup.public_key.p} / Q = (${activeKeySetup.public_key.Q.join(", ")})`;
    runButton.disabled = running;
    runButton.querySelector("span:first-child").textContent = running ? "RUNNING..." : "RUN SIMULATION";
  }
  updateRibbonPosition();
}

function updateRibbonPosition() {
  const docked = Boolean(activeKeySetup?.recovery?.supported)
    && runRibbonSlot.getBoundingClientRect().top < 0;
  runRibbon.classList.toggle("is-docked", docked);
  document.body.classList.toggle("has-docked-ribbon", docked);
}

new ResizeObserver(() => {
  // Preserve document space when the same ribbon becomes a fixed-position element.
  const height = runRibbon.getBoundingClientRect().height;
  runRibbonSlot.style.height = `${height}px`;
  document.body.style.setProperty("--run-ribbon-height", `${height}px`);
}).observe(runRibbon);
window.addEventListener("scroll", updateRibbonPosition, { passive: true });
shotsInput.addEventListener("input", (event) => {
  document.querySelector("#shot-count-display").textContent = event.target.value || "-";
});
document.addEventListener("click", (event) => {
  if (!runSettings.contains(event.target)) runSettings.open = false;
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && runSettings.open) {
    runSettings.open = false;
    runSettings.querySelector("summary").focus();
  }
});

function clearKeySetup() {
  // Invalidate in-flight responses before clearing either public or revealed fields.
  keySetupRevision += 1;
  activeKeySetup = null;
  privateKeyHandle = null;
  setupResult.hidden = true;
  publicKeyFields.replaceChildren();
  privateKeyFields.replaceChildren();
  privateKeyFields.hidden = true;
  revealPrivateButton.hidden = false;
  revealPrivateButton.disabled = false;
  setButtonLabel(revealPrivateButton, "REVEAL PRIVATE KEY");
  resetFlow();
  updateRunAvailability();
}

function updateRSAProfile() {
  const selectedProfile = rsaProfileInput.selectedOptions[0];
  const toyProfile = selectedProfile.dataset.kind === "toy";
  rsaExponentField.hidden = !toyProfile;
  rsaExponentInput.replaceChildren();
  if (toyProfile) {
    for (const exponent of selectedProfile.dataset.exponents.split(",")) {
      const option = document.createElement("option");
      option.value = exponent;
      option.textContent = exponent;
      rsaExponentInput.append(option);
    }
  }
}

function updateECCProfile() {
  const selectedProfile = eccProfileInput.selectedOptions[0];
  const toyProfile = selectedProfile.dataset.kind === "toy";
  eccScalarField.hidden = !toyProfile;
}

function configurePublicInputStage(algorithm) {
  const rsa = algorithm === "rsa";
  document.querySelector("#flow-public-title").textContent = rsa
    ? "1. Classical Preprocessing"
    : "1. Public Input Checks";
  flowPlaceholders.public_input = rsa
    ? "Selected RSA bases and GCD outcomes appear here."
    : "ECC public-point and subgroup checks appear here.";
  const placeholder = flowContent("public_input").querySelector(".flow-placeholder");
  if (placeholder) placeholder.textContent = flowPlaceholders.public_input;
}

function renderKeyFields(container, fields) {
  container.replaceChildren();
  for (const [name, value] of Object.entries(fields)) {
    if (value === undefined || value === null) continue;
    const term = document.createElement("dt");
    term.textContent = name;
    const detail = document.createElement("dd");
    detail.textContent = Array.isArray(value) ? `(${value.join(", ")})` : String(value);
    container.append(term, detail);
  }
}

function publicSetupFields(setup) {
  const key = setup.public_key;
  if (setup.algorithm === "rsa") return { N: key.N, e: key.e };
  return {
    group: key.curve_name ?? `Toy F_${key.p} group`,
    p: key.p,
    a: key.a,
    b: key.b,
    G: key.G,
    q: key.q,
    h: key.h,
    Q: key.Q
  };
}

function selectAlgorithm(algorithm) {
  if (activeRunId !== null) return;
  const content = algorithmContent[algorithm];
  algorithmInput.value = algorithm;
  document.querySelector("#problem-content").setAttribute("aria-labelledby", `tab-${algorithm}`);
  document.querySelector("#problem-kicker").textContent = content.kicker;
  document.querySelector("#problem-title").textContent = content.title;
  document.querySelector("#problem-description").textContent = content.description;
  rsaSetupControls.hidden = algorithm !== "rsa";
  eccSetupControls.hidden = algorithm !== "ecc";
  if (algorithm === "rsa") updateRSAProfile();
  else updateECCProfile();
  const pathDetails = document.querySelectorAll(".concept-path small");
  pathDetails[0].textContent = content.quantum;
  pathDetails[1].textContent = content.classical;
  clearKeySetup();
  configurePublicInputStage(algorithm);
  tabs.forEach((tab) => {
    const active = tab.dataset.algorithm === algorithm;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
  });
}

tabs.forEach((tab, index) => {
  tab.addEventListener("click", () => selectAlgorithm(tab.dataset.algorithm));
  tab.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const nextIndex = (index + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length;
    tabs[nextIndex].focus();
    selectAlgorithm(tabs[nextIndex].dataset.algorithm);
  });
});

rsaProfileInput.addEventListener("change", () => { clearKeySetup(); updateRSAProfile(); });
rsaExponentInput.addEventListener("change", clearKeySetup);
eccProfileInput.addEventListener("change", () => { clearKeySetup(); updateECCProfile(); });
eccScalarInput.addEventListener("change", clearKeySetup);

async function generateKeyPair() {
  // Profile changes may happen while generation is pending; identity checks gate its result.
  if (activeRunId !== null) return;
  clearKeySetup();
  const revision = keySetupRevision;
  const requestId = ++setupRequestSequence;
  setupKeyButton.disabled = true;
  setButtonLabel(setupKeyButton, "GENERATING…");
  let payload;
  if (algorithmInput.value === "rsa") {
    const profile = rsaProfileInput.selectedOptions[0];
    if (profile.dataset.kind === "toy") {
      payload = {
        algorithm: "rsa",
        profile_id: profile.value,
        public_exponent: Number(rsaExponentInput.value)
      };
    } else {
      payload = { algorithm: "rsa", profile_id: profile.value };
    }
  } else {
    payload = { algorithm: "ecc", profile_id: eccProfileInput.value };
    if (
      eccProfileInput.selectedOptions[0].dataset.kind === "toy"
      && eccScalarInput.value !== ""
    ) {
      payload.private_scalar = Number(eccScalarInput.value);
    }
  }

  try {
    const response = await fetch("/api/setup", {
      method: "POST",
      signal: AbortSignal.timeout(30_000),
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(payload)
    });
    const result = await response.json();
    if (revision !== keySetupRevision || requestId !== setupRequestSequence) return;
    if (!response.ok) throw new Error(result.error ?? "Key setup was rejected.");
    activeKeySetup = result;
    privateKeyHandle = result.private_key_handle;
    document.querySelector("#key-setup-title-result").textContent = result.algorithm === "rsa"
      ? "RSA keypair generated"
      : "ECC keypair generated";
    const capability = document.querySelector("#key-capability-status");
    capability.textContent = result.recovery.supported ? "RECOVERY AVAILABLE" : "SETUP ONLY";
    capability.dataset.supported = String(result.recovery.supported);
    document.querySelector("#setup-capability-copy").textContent = result.recovery.description;
    renderKeyFields(publicKeyFields, publicSetupFields(result));
    setupResult.hidden = false;
    initializePreparationStage(result);
  } catch (error) {
    if (revision === keySetupRevision && requestId === setupRequestSequence) {
      showToast(error.message ?? "Key setup failed.");
    }
  } finally {
    if (requestId === setupRequestSequence) {
      setupKeyButton.disabled = activeRunId !== null;
      setButtonLabel(setupKeyButton, "GENERATE KEYPAIR");
      updateRunAvailability();
    }
  }
}

setupKeyButton.addEventListener("click", generateKeyPair);

revealPrivateButton.addEventListener("click", async () => {
  // Capture the original key and handle so a delayed reveal cannot attach to a new key.
  if (!privateKeyHandle || !activeKeySetup || revealPrivateButton.disabled) return;
  const setup = activeKeySetup;
  const handle = privateKeyHandle;
  const revision = keySetupRevision;
  const isCurrentSetup = () => setup === activeKeySetup
    && handle === privateKeyHandle && revision === keySetupRevision;
  revealPrivateButton.disabled = true;
  try {
    const response = await fetch("/api/setup/reveal", {
      method: "POST",
      signal: AbortSignal.timeout(30_000),
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify({ private_key_handle: handle })
    });
    const result = await response.json();
    if (!isCurrentSetup()) return;
    if (!response.ok) throw new Error(result.error ?? "Private-key reveal expired.");
    const privateFields = setup.algorithm === "rsa"
      ? { p: result.private_key.p, q: result.private_key.q, d: result.private_key.d }
      : { k: result.private_key.k };
    renderKeyFields(privateKeyFields, privateFields);
    privateKeyFields.hidden = false;
    privateKeyHandle = null;
    activeKeySetup.private_key_handle = null;
    revealPrivateButton.hidden = true;
  } catch (error) {
    if (isCurrentSetup()) {
      revealPrivateButton.disabled = false;
      showToast(error.message ?? "Private-key reveal failed.");
    }
  }
});

updateRSAProfile();
updateRunAvailability();

function showToast(message) {
  toast.textContent = message;
  toast.hidden = false;
  window.setTimeout(() => { toast.hidden = true; }, 5000);
}

function addTextElement(parent, tagName, className, text) {
  const element = document.createElement(tagName);
  if (className) element.className = className;
  element.textContent = text;
  parent.append(element);
  return element;
}

function formatCount(count, singular, plural = `${singular}s`) {
  return `${count} ${count === 1 ? singular : plural}`;
}

// All five sections remain mounted; stage events replace their waiting placeholders.
const flowPlaceholders = {
  public_input: "Selected RSA bases and GCD outcomes appear here.",
  quantum_observation: "Circuit details and actual measurements appear after the run.",
  recovered_structure: "Order or frequency constraints are derived from observed samples.",
  secret_recovery: "A candidate appears only when the measured structure supports one.",
  validation: "The candidate is checked using public key data."
};

function setFlowState(stage, state, label) {
  const stateElement = document.querySelector(`[data-flow-state="${stage}"]`);
  if (!stateElement) return;
  stateElement.dataset.state = state;
  stateElement.textContent = label;
}

function resetFlowSection(stage) {
  flowContent(stage).replaceChildren();
  addTextElement(
    flowContent(stage),
    "p",
    "flow-placeholder",
    flowPlaceholders[stage]
  );
  setFlowState(stage, "waiting", stage === "public_input" ? "WAITING FOR KEY SETUP" : "WAITING");
}

function resetFlow() {
  for (const stage of Object.keys(flowPlaceholders)) resetFlowSection(stage);
  document.querySelector("#result-title").textContent = "Build a keypair to begin";
  document.querySelector("#result-summary").textContent = "The public input and each measured recovery step will appear here.";
  document.querySelector("#result-status").hidden = true;
  resetEventTrace();
  document.querySelector("#run-metadata").textContent = "";
  document.querySelector("#limitations").replaceChildren();
  resultSection.setAttribute("aria-busy", "false");
}

function replacePlaceholder(stage) {
  const content = flowContent(stage);
  if (content.querySelector(".flow-placeholder")) content.replaceChildren();
  return content;
}

function appendFlowValues(parent, values) {
  const populated = Object.entries(values).filter(([, value]) => value !== undefined && value !== null);
  if (!populated.length) return;
  const labels = {
    profile: "Profile",
    N: "N",
    e: "e",
    p: "p",
    q: "q",
    Q: "Q",
    G: "G",
    base: "base a",
    attempt: "Attempt",
    order_candidate: "verified order r",
    modular_check: "order check",
    relation: "measured relation",
    candidate: "candidate k",
    factors: "factors (p, q)",
    product: "product",
    source: "recovery source"
  };
  const row = document.createElement("div");
  row.className = "flow-value-row";
  for (const [name, value] of populated) {
    const item = document.createElement("span");
    item.className = "flow-value";
    const label = document.createElement("b");
    label.textContent = `${labels[name] ?? name} `;
    let formatted;
    if (name === "source") {
      formatted = value === "classical_preprocessing" ? "classical gcd" : "quantum-derived";
    } else if (Array.isArray(value)) {
      formatted = `(${value.join(", ")})`;
    } else if (typeof value === "object") {
      formatted = Object.entries(value).map(([key, size]) => `${key}=${size}`).join(", ");
    } else {
      formatted = String(value);
    }
    item.append(label, document.createTextNode(formatted));
    row.append(item);
  }
  parent.append(row);
}

function appendObservationHistogram(parent, event, visualParent = parent) {
  // Summarize the visible RSA bars only; the technical trace retains full counts.
  const evidence = event.evidence ?? {};
  if (evidence.counts) {
    const outcomes = Object.entries(evidence.counts)
      .map(([phase, count]) => ({ label: phase, count }))
      .sort((first, second) => second.count - first.count || Number(first.label) - Number(second.label));
    const visibleOutcomes = outcomes.slice(0, 8);
    const otherCount = outcomes.slice(8).reduce((total, item) => total + item.count, 0);
    const totalShots = outcomes.reduce((total, item) => total + item.count, 0);
    const values = otherCount > 0
      ? [...visibleOutcomes, { label: `Other (${outcomes.length - 8})`, count: otherCount }]
      : visibleOutcomes;
    addTextElement(
      parent,
      "p",
      "flow-entry-description",
      `Showing ${visibleOutcomes.length} of ${formatCount(outcomes.length, "distinct outcome")}; the full distribution is in Technical details.`
    );
    addTextElement(
      parent,
      "p",
      "flow-measurement-summary",
      `${formatCount(totalShots, "shot")} across ${formatCount(outcomes.length, "distinct measured phase")}.`
    );
    const maximum = Math.max(...values.map((value) => value.count), 1);
    const histogram = document.createElement("div");
    histogram.className = "histogram flow-histogram";
    for (const value of values) {
      const column = document.createElement("div");
      column.className = "bar-item";
      column.setAttribute("role", "img");
      column.setAttribute("aria-label", `${value.label}: ${formatCount(value.count, "shot")}`);
      addTextElement(column, "span", "bar-count", String(value.count));
      const track = document.createElement("span");
      track.className = "bar-track";
      const fill = document.createElement("span");
      fill.className = "bar-fill";
      fill.style.height = `${Math.max(3, (value.count / maximum) * 100)}%`;
      track.append(fill);
      column.append(track);
      addTextElement(column, "span", "bar-label", value.label);
      histogram.append(column);
    }
    visualParent.append(histogram);
  } else if (evidence.frequencies) {
    const totalShots = evidence.frequencies.reduce((total, item) => total + item.count, 0);
    addTextElement(
      parent,
      "p",
      "flow-measurement-summary",
      `${formatCount(totalShots, "shot")} across ${formatCount(evidence.frequencies.length, "distinct measured pair")}.`
    );
    appendFrequencyHeatmap(visualParent, evidence.frequencies);
  }
}

function getAttemptGroup(parent, evidence) {
  if (evidence.attempt === undefined) return null;
  const attempt = String(evidence.attempt);
  const existing = [...parent.querySelectorAll(".flow-attempt-group")]
    .find((group) => group.dataset.attempt === attempt);
  if (existing) return existing;

  const group = document.createElement("div");
  group.className = "flow-attempt-group";
  group.dataset.attempt = attempt;
  const heading = document.createElement("div");
  heading.className = "flow-attempt-heading";
  const hasBase = evidence.base !== undefined;
  const attemptType = hasBase ? "Attempt" : "Sampling batch";
  const attemptLabel = evidence.attempt_budget === undefined
    ? `${attemptType} ${attempt}`
    : `${attemptType} ${attempt} of ${evidence.attempt_budget}`;
  addTextElement(
    heading,
    "span",
    "flow-attempt-label",
    attemptLabel
  );
  addTextElement(heading, "span", "flow-attempt-state", "READY");
  const facts = document.createElement("div");
  facts.className = "attempt-facts";
  const visual = document.createElement("div");
  visual.className = "attempt-visual";
  group.append(heading, facts, visual);
  parent.append(group);
  return group;
}

function setAttemptState(group, state) {
  const stateElement = group?.querySelector(".flow-attempt-state");
  if (!stateElement) return;
  stateElement.textContent = state;
  stateElement.dataset.state = state.toLowerCase().replaceAll(" ", "_");
}

function appendCircuitFootprint(parent, evidence) {
  if (evidence.circuit_depth === undefined || !evidence.circuit_operations) return;
  const operationCount = Object.values(evidence.circuit_operations)
    .reduce((total, count) => total + count, 0);
  addTextElement(
    parent,
    "p",
    "circuit-footprint",
    `Compiled circuit: ${evidence.circuit_depth} depth · ${operationCount} operations.`
  );
}

function appendFrequencyHeatmap(parent, frequencies) {
  const order = Number(activeKeySetup?.public_key?.q ?? 7);
  const counts = new Map(
    frequencies.map(({ u, v, count }) => [`${u},${v}`, count])
  );
  const maxCount = Math.max(...frequencies.map(({ count }) => count), 1);
  const table = document.createElement("table");
  table.className = "frequency-heatmap";
  addTextElement(table, "caption", "", `Measured frequency counts (u, v), q = ${order}`);

  const head = document.createElement("thead");
  const headingRow = document.createElement("tr");
  addTextElement(headingRow, "th", "", "u \\ v").scope = "col";
  for (let v = 0; v < order; v += 1) {
    addTextElement(headingRow, "th", "", String(v)).scope = "col";
  }
  head.append(headingRow);

  const body = document.createElement("tbody");
  for (let u = 0; u < order; u += 1) {
    const row = document.createElement("tr");
    addTextElement(row, "th", "", String(u)).scope = "row";
    for (let v = 0; v < order; v += 1) {
      const count = counts.get(`${u},${v}`) ?? 0;
      const cell = addTextElement(row, "td", "", count ? String(count) : "-");
      cell.dataset.count = String(count);
      cell.setAttribute("aria-label", `u ${u}, v ${v}: ${formatCount(count, "shot")}`);
      cell.dataset.intense = String(count / maxCount >= 0.6);
      cell.style.setProperty("--frequency-strength", String(count / maxCount));
    }
    body.append(row);
  }
  table.append(head, body);
  parent.append(table);

  const invalidPairs = frequencies.filter(
    ({ u, v }) => u < 0 || v < 0 || u >= order || v >= order
  );
  if (invalidPairs.length) {
    addTextElement(
      parent,
      "p",
      "flow-entry-description frequency-invalid-note",
      `Out-of-domain measured pairs: ${invalidPairs.map(({ u, v, count }) => `(${u}, ${v}) ${formatCount(count, "shot")}`).join("; ")}`
    );
  }
}

function appendCircuitSummary(parent, evidence) {
  const isRsa = evidence.phase_qubits !== undefined;
  const publicKey = activeKeySetup?.public_key ?? {};
  const labels = isRsa
    ? [
        "Prepare phase and work registers",
        "Controlled modular multiplication",
        "Apply inverse QFT",
        "Measure phase register"
      ]
    : [
        "Prepare valid exponent states",
        "Apply public-point oracle aG + bQ",
        "Measure point output",
        "Apply Fourier transform to exponent registers",
        "Measure (u, v) frequencies"
      ];
  const details = isRsa
    ? [
        `Phase: ${evidence.phase_qubits} qubits; work: ${evidence.work_qubits} qubits, initialized to |1>.`,
        `Uses the attempt's public base a; modulus N=${publicKey.N ?? "not reported"}.`,
        `Inverse QFT on the ${evidence.phase_qubits}-qubit phase register.`,
        "Measured phase counts are shown below."
      ]
    : [
        `Exponent registers a and b: ${evidence.exponent_registers?.a} qubits each.`,
        `Public-point output register: ${evidence.point_output_register} qubits.`,
        "The point output is measured before the Fourier transform.",
        `${evidence.fourier_transform ?? "Fourier transform details not reported"}.`,
        "Measured (u, v) counts are shown below."
      ];

  const steps = document.createElement("ol");
  steps.className = "circuit-steps";
  labels.forEach((label, index) => {
    const item = document.createElement("li");
    addTextElement(item, "span", "circuit-step-label", label);
    addTextElement(item, "span", "circuit-step-detail", details[index]);
    steps.append(item);
  });
  parent.append(steps);
}

function appendRecoveredStructure(parent, event) {
  // Classifications are supplied by Python; counts here describe rows, not confidence.
  const evidence = event.evidence ?? {};
  const rsa = Array.isArray(evidence.phase_samples);
  const samples = rsa ? evidence.phase_samples : evidence.frequencies;
  if (!Array.isArray(samples)) return false;

  const informative = samples.filter((sample) => rsa
    ? sample.informative
    : ["validated", "rejected"].includes(sample.status));
  const rejectedPhases = rsa
    ? samples.filter((sample) => sample.informative && sample.verified_period == null)
    : [];
  const validated = samples.filter((sample) => sample.status === "validated");
  const rejected = samples.filter((sample) => sample.status === "rejected");
  const invalid = samples.filter((sample) => sample.status === "invalid_frequency");
  if (evidence.attempt !== undefined) {
    const attemptType = rsa ? "Attempt" : "Sampling batch";
    const attemptLabel = evidence.attempt_budget === undefined
      ? `${attemptType} ${evidence.attempt}`
      : `${attemptType} ${evidence.attempt} of ${evidence.attempt_budget}`;
    addTextElement(
      parent,
      "p",
      "flow-attempt-label structure-attempt-label",
      attemptLabel
    );
  }
  const summary = document.createElement("dl");
  summary.className = "structure-summary";
  const metrics = rsa
    ? [
        [
          "Verified order",
          evidence.order_candidate == null ? "Not recovered" : `r = ${evidence.order_candidate}`
        ],
        ["Modular check", evidence.modular_check ? "a^r mod N = 1" : "Not verified"],
        ["Informative phases", `${informative.length} / ${samples.length}`],
        ["Informative fractions rejected", String(rejectedPhases.length)]
      ]
    : [
        ["Frequency relation", evidence.relation ?? "Not available"],
        ["Informative pairs", `${informative.length} / ${samples.length}`],
        ["Validated pairs", String(validated.length)],
        ["Rejected pairs", String(rejected.length)],
        ["Invalid pairs", String(invalid.length)]
      ];
  for (const [label, value] of metrics) {
    const metric = document.createElement("div");
    metric.dataset.state = "neutral";
    if (["Informative fractions rejected", "Rejected pairs", "Invalid pairs"].includes(label)) {
      metric.dataset.state = Number(value) > 0 ? "failed" : "neutral";
    } else if (value === "Not recovered" || value === "Not verified") {
      metric.dataset.state = "neutral";
    } else if (["Verified order", "Modular check"].includes(label)
      || (label === "Validated pairs" && Number(value) > 0)) {
      metric.dataset.state = "complete";
    }
    addTextElement(metric, "dt", "", label);
    addTextElement(metric, "dd", "", value);
    summary.append(metric);
  }
  parent.append(summary);

  const sampleDetails = document.createElement("details");
  sampleDetails.className = "attempt-evidence-details structure-samples-details";
  sampleDetails.open = evidence.attempt === undefined;
  addTextElement(
    sampleDetails,
    "summary",
    "",
    `View ${formatCount(samples.length, rsa ? "phase sample" : "frequency pair")}`
  );
  const scrollArea = document.createElement("div");
  scrollArea.className = "structure-table-scroll";
  scrollArea.tabIndex = 0;
  scrollArea.setAttribute("role", "region");
  scrollArea.setAttribute(
    "aria-label",
    rsa ? "Phase reconstruction evidence" : "Frequency constraint evidence"
  );
  const table = document.createElement("table");
  table.className = "structure-table";
  addTextElement(table, "caption", "", rsa ? "Phase reconstruction" : "Frequency constraints");
  const head = document.createElement("thead");
  const headings = document.createElement("tr");
  const columns = rsa
    ? ["Phase fraction", "Shots", "Denominator", "Period r", "Sample"]
    : ["u", "v", "Shots", "Sample"];
  for (const column of columns) {
    const cell = addTextElement(headings, "th", "", column);
    cell.scope = "col";
  }
  head.append(headings);
  const body = document.createElement("tbody");
  const sampleLabels = {
    validated: "Validated",
    rejected: "Rejected",
    invalid_frequency: "Invalid frequency",
    uninformative: "Uninformative"
  };
  table.append(head, body);
  scrollArea.append(table);
  sampleDetails.append(scrollArea);
  parent.append(sampleDetails);
  if (event.description) {
    const hasRejection = rsa && (
      evidence.factor_rejection != null || evidence.order_candidate == null
    );
    const descriptionClass = hasRejection
      ? "flow-entry-description structure-rejection"
      : "flow-entry-description";
    addTextElement(parent, "p", descriptionClass, event.description);
  }
  const pagination = document.createElement("div");
  pagination.className = "structure-pagination";
  pagination.hidden = samples.length <= structurePageSize;
  const pageStatus = addTextElement(pagination, "span", "structure-page-status", "");
  pageStatus.setAttribute("role", "status");
  const previousButton = addTextElement(pagination, "button", "structure-page-button", "←");
  const nextButton = addTextElement(pagination, "button", "structure-page-button", "→");
  const paginationButtons = [
    [previousButton, "Previous samples"],
    [nextButton, "Next samples"]
  ];
  for (const [button, label] of paginationButtons) {
    button.type = "button";
    button.title = label;
    button.setAttribute("aria-label", label);
  }
  sampleDetails.append(pagination);
  let pageIndex = 0;
  const pageCount = Math.max(1, Math.ceil(samples.length / structurePageSize));

  // Preserve the complete evidence while mounting only the current page's rows.
  function renderPage() {
    const first = pageIndex * structurePageSize;
    const fragment = document.createDocumentFragment();
    for (const sample of samples.slice(first, first + structurePageSize)) {
      const useful = rsa
        ? sample.informative
        : ["validated", "rejected"].includes(sample.status);
      const values = rsa
        ? [
            sample.fraction,
            sample.count,
            sample.denominator,
            sample.verified_period ?? "-",
            sample.verified_period != null
              ? `Verified order r=${sample.verified_period}`
              : sample.informative
                ? "Rejected: no verified order"
                : "Uninformative"
          ]
        : [sample.u, sample.v, sample.count, sampleLabels[sample.status] ?? "Unknown"];
      const row = document.createElement("tr");
      row.dataset.informative = String(Boolean(useful));
      row.dataset.status = rsa
        ? sample.verified_period != null
          ? "validated"
          : sample.informative
            ? "rejected"
            : "uninformative"
        : sample.status;
      for (const value of values) addTextElement(row, "td", "", String(value ?? "-"));
      fragment.append(row);
    }
    body.replaceChildren(fragment);
    scrollArea.scrollTop = 0;
    pageStatus.textContent = samples.length
      ? `${first + 1}-${Math.min(first + structurePageSize, samples.length)} / ${samples.length} samples`
      : "0 samples";
    previousButton.disabled = pageIndex === 0;
    nextButton.disabled = pageIndex === pageCount - 1;
  }
  function changePage(delta) {
    pageIndex = Math.max(0, Math.min(pageCount - 1, pageIndex + delta));
    renderPage();
  }
  previousButton.addEventListener("click", () => changePage(-1));
  nextButton.addEventListener("click", () => changePage(1));
  renderPage();

  if (rsa) {
    const hasVerifiedOrder = evidence.order_candidate != null;
    setFlowState(
      "recovered_structure",
      hasVerifiedOrder ? "complete" : "failed",
      hasVerifiedOrder ? "ORDER VERIFIED" : "NO VERIFIED ORDER"
    );
  } else if (validated.length > 0) {
    setFlowState("recovered_structure", "complete", "CONSTRAINTS OBSERVED");
  } else {
    const label = informative.length > 0
      ? "NO VALIDATED CONSTRAINTS"
      : samples.length === 0
        ? "NO SAMPLES"
        : invalid.length === samples.length
          ? "INVALID FREQUENCIES"
          : invalid.length > 0
            ? "NO USABLE FREQUENCIES"
            : "NO INFORMATIVE SAMPLES";
    setFlowState("recovered_structure", "failed", label);
  }
  return true;
}

function appendCandidateEvidence(parent, event) {
  const evidence = event.evidence ?? {};
  if (evidence.factors === undefined && evidence.candidate === undefined) return false;

  const result = document.createElement("div");
  result.className = "candidate-evidence";
  const kind = evidence.factors !== undefined ? "Factor pair" : "Scalar candidate";
  addTextElement(result, "span", "candidate-kind", kind);
  if (evidence.factors !== undefined) {
    const [first, second] = evidence.factors;
    addTextElement(result, "p", "candidate-primary", `(${first}, ${second})`);
    const details = document.createElement("dl");
    details.className = "candidate-details";
    addTextElement(details, "dt", "", "p");
    addTextElement(details, "dd", "", String(first));
    addTextElement(details, "dt", "", "q");
    addTextElement(details, "dd", "", String(second));
    result.append(details);
  } else {
    addTextElement(result, "p", "candidate-primary", `k = ${evidence.candidate}`);
  }

  const source = evidence.source;
  const sourceLabel = source === "classical_preprocessing"
    ? "Classical GCD"
    : source === "quantum_order_finding"
      ? "Measured order-finding candidate"
      : "Measured-frequency candidate";
  addTextElement(result, "span", "candidate-source", sourceLabel);
  if (evidence.supporting_shots !== undefined) {
    result.append(document.createTextNode(" · "));
    addTextElement(
      result,
      "span",
      "candidate-support",
      formatCount(evidence.supporting_shots, "supporting shot")
    );
  }
  parent.append(result);
  setFlowState("secret_recovery", "candidate", "CANDIDATE");
  return true;
}

function appendCandidateAbsence(parent, event) {
  const result = document.createElement("div");
  result.className = "candidate-absence";
  addTextElement(result, "span", "candidate-kind", "No candidate recovered");
  if (event.description) {
    addTextElement(result, "p", "candidate-absence-description", event.description);
  }
  appendFlowValues(result, event.evidence ?? {});
  parent.append(result);
  setFlowState("secret_recovery", "failed", "NOT RECOVERED");
}

function appendValidationEvidence(parent, event) {
  const evidence = event.evidence ?? {};
  const result = document.createElement("div");
  const reached = event.category !== "limitation" && evidence.status !== "not_reached";
  const passed = ["passed", "validated"].includes(evidence.status);
  result.className = "validation-evidence";
  result.dataset.status = !reached ? "not_reached" : passed ? "passed" : "failed";

  if (Array.isArray(evidence.factors) && evidence.product !== undefined) {
    addTextElement(
      result,
      "p",
      "validation-equation",
      passed
        ? `${evidence.factors[0]} × ${evidence.factors[1]} = ${evidence.product}`
        : `${evidence.factors[0]} × ${evidence.factors[1]}; expected N = ${evidence.product}`
    );
  } else if (evidence.candidate !== undefined) {
    addTextElement(result, "p", "validation-equation", passed
      ? `k = ${evidence.candidate}: kG = Q`
      : `Candidate k = ${evidence.candidate}; check kG against Q`);
    const publicInputs = document.createElement("div");
    publicInputs.className = "validation-public-inputs";
    appendFlowValues(publicInputs, { G: evidence.G, Q: evidence.Q });
    result.append(publicInputs);
  }

  if (event.description) {
    addTextElement(result, "p", "validation-description", event.description);
  }
  parent.append(result);
  setFlowState(
    "validation",
    !reached ? "not_reached" : passed ? "complete" : "failed",
    !reached ? "NOT REACHED" : passed ? "PASSED" : "FAILED"
  );
}

function renderFlowEvent(event) {
  // Route semantic events without upgrading workflow candidates into recovered results.
  const stage = event.stage;
  if (!flowPlaceholders[stage]) return;
  if (stage === "public_input" && event.category === "public_input") {
    setFlowState(stage, "complete", "READY");
    return;
  }
  if (stage === "public_input" && event.category === "base_selection") {
    const content = replacePlaceholder(stage);
    const entry = document.createElement("div");
    entry.className = "flow-entry";
    entry.dataset.stage = stage;
    addTextElement(entry, "p", "flow-entry-title", event.label);
    if (event.description) {
      addTextElement(entry, "p", "flow-entry-description", event.description);
    }
    content.append(entry);
    setFlowState(stage, "running", "CHECKING BASES");
    return;
  }
  const content = replacePlaceholder(stage);
  const entry = document.createElement("div");
  entry.className = "flow-entry";
  entry.dataset.stage = stage;
  if (event.category === "run_state") {
    setFlowState(stage, "running", "SAMPLING");
    const runEvidence = event.evidence ?? {};
    const attemptGroup = stage === "quantum_observation"
      ? getAttemptGroup(content, runEvidence)
      : null;
    if (attemptGroup) {
      setAttemptState(attemptGroup, "SAMPLING");
      const facts = attemptGroup.querySelector(".attempt-facts");
      const samplingMetadata = [
        runEvidence.shots === undefined ? "" : formatCount(runEvidence.shots, "shot"),
        runEvidence.seed === undefined ? "" : `seed ${runEvidence.seed}`
      ].filter(Boolean).join(" · ");
      if (samplingMetadata) {
        addTextElement(facts, "p", "flow-attempt-metadata", samplingMetadata);
      }
      addTextElement(facts, "p", "flow-attempt-description flow-sampling-message", event.description);
      return;
    }
    entry.classList.add("flow-running-entry");
    addTextElement(entry, "p", "flow-entry-description", event.description);
    content.append(entry);
    return;
  }
  if (event.category === "run_error") {
    const attemptGroups = content.querySelectorAll(".flow-attempt-group");
    const lastAttempt = attemptGroups[attemptGroups.length - 1];
    if (stage === "quantum_observation" && lastAttempt) {
      setAttemptState(lastAttempt, "ERROR");
      lastAttempt.querySelectorAll(".flow-sampling-message").forEach(element => element.remove());
      addTextElement(lastAttempt.querySelector(".attempt-facts"), "p", "flow-entry-description", event.description);
    } else {
      addTextElement(entry, "p", "flow-entry-description", event.description);
      content.append(entry);
    }
    setFlowState(stage, "failed", "ERROR");
    return;
  }
  const evidence = event.evidence ?? {};
  if (stage === "quantum_observation" && event.category === "circuit_operation") {
    let blueprint = content.querySelector(".circuit-blueprint");
    if (!blueprint) {
      blueprint = document.createElement("div");
      blueprint.className = "flow-entry circuit-blueprint";
      addTextElement(blueprint, "p", "flow-entry-title", "Circuit sequence");
      appendCircuitSummary(blueprint, evidence);
      content.prepend(blueprint);
    }
    const attemptGroup = getAttemptGroup(content, evidence);
    appendCircuitFootprint(attemptGroup?.querySelector(".attempt-facts") ?? blueprint, evidence);
    setAttemptState(attemptGroup, "CIRCUIT READY");
    setFlowState(stage, "complete", "CIRCUIT READY");
    return;
  }
  if (stage === "quantum_observation" && event.category === "attempt_started") {
    const attemptGroup = getAttemptGroup(content, evidence);
    if (attemptGroup) {
      const state = evidence.gcd > 1 ? "CLASSICAL SHORTCUT" : "BASE SELECTED";
      setAttemptState(attemptGroup, state);
      addTextElement(attemptGroup.querySelector(".attempt-facts"), "p", "flow-attempt-description", event.description);
    }
    const hasObservation = Boolean(content.querySelector(".flow-histogram, .frequency-heatmap"));
    const classicalShortcut = evidence.gcd > 1;
    setFlowState(
      stage,
      classicalShortcut ? (hasObservation ? "complete" : "not_reached") : "running",
      classicalShortcut ? (hasObservation ? "MIXED PATH" : "CLASSICAL PATH") : "ATTEMPTING"
    );
    return;
  }
  if (stage === "quantum_observation" && event.category === "attempt_outcome") {
    const attemptGroup = getAttemptGroup(content, evidence);
    if (attemptGroup && event.description) {
      setAttemptState(attemptGroup, "CLASSICAL SHORTCUT");
      addTextElement(attemptGroup.querySelector(".attempt-facts"), "p", "flow-attempt-outcome", event.description);
    }
    const hasObservation = Boolean(content.querySelector(".flow-histogram, .frequency-heatmap"));
    setFlowState(
      stage,
      hasObservation ? "complete" : "not_reached",
      hasObservation ? "MIXED PATH" : "CLASSICAL PATH"
    );
    return;
  }
  if (stage === "recovered_structure" && appendRecoveredStructure(entry, event)) {
    content.append(entry);
    return;
  }
  if (stage === "secret_recovery" && event.category === "candidate") {
    if (appendCandidateEvidence(entry, event)) {
      content.append(entry);
      return;
    }
  }
  if (stage === "secret_recovery" && event.category === "limitation") {
    appendCandidateAbsence(entry, event);
    content.append(entry);
    return;
  }
  if (stage === "validation") {
    appendValidationEvidence(entry, event);
    content.append(entry);
    return;
  }
  if (stage === "quantum_observation" && event.category === "simulator_observation") {
    const attemptGroup = getAttemptGroup(content, evidence);
    if (attemptGroup) {
      setAttemptState(attemptGroup, "OBSERVED");
      attemptGroup.querySelectorAll(".flow-sampling-message").forEach(element => element.remove());
      const facts = attemptGroup.querySelector(".attempt-facts");
      addTextElement(facts, "p", "flow-entry-title", event.label);
      if (event.description) {
        addTextElement(facts, "p", "flow-entry-description", event.description);
      }
      appendObservationHistogram(facts, event, attemptGroup.querySelector(".attempt-visual"));
      setFlowState(stage, "complete", "OBSERVED");
      return;
    }
  }
  addTextElement(entry, "p", "flow-entry-title", event.label);
  if (event.description) addTextElement(entry, "p", "flow-entry-description", event.description);

  if (event.category === "simulator_observation") {
    content.querySelectorAll(".flow-running-entry").forEach((item) => item.remove());
    appendObservationHistogram(entry, event);
    setFlowState(stage, "complete", "OBSERVED");
  } else {
    const visibleFields = {
      public_input: ["N", "e", "p", "curve", "G", "q", "Q", "base", "gcd", "attempt"],
      quantum_observation: [
        "attempt", "base", "shots", "phase_qubits", "work_qubits",
        "exponent_registers", "point_output_register"
      ],
      recovered_structure: [
        "phase", "numerator", "denominator", "fraction_denominator",
        "verified_period", "order_candidate", "modular_check",
        "u", "v", "relation", "status"
      ],
      secret_recovery: ["factors", "candidate", "source", "supporting_shots", "gcd", "attempt"],
      validation: ["factors", "product", "candidate", "G", "Q", "status"]
    }[stage] ?? [];
    appendFlowValues(entry, Object.fromEntries(
      visibleFields.filter((field) => field in evidence).map((field) => [field, evidence[field]])
    ));
    const rejectedCandidate = stage === "secret_recovery" && evidence.status === "rejected";
    const failed = event.category === "limitation" || rejectedCandidate;
    let state = failed ? "failed" : "complete";
    let label = failed ? "NOT RECOVERED" : "UPDATED";
    if (rejectedCandidate) label = "REJECTED";
    if (stage === "public_input") label = "READY";
    if (stage === "secret_recovery" && event.category === "candidate") label = "CANDIDATE";
    if (stage === "recovered_structure" && "order_candidate" in evidence) {
      state = evidence.order_candidate === null ? "failed" : "complete";
      label = evidence.order_candidate === null ? "NO VERIFIED ORDER" : "ORDER VERIFIED";
    }
    setFlowState(stage, state, label);
  }
  content.append(entry);
}

function initializePreparationStage(setup) {
  const content = flowContent("public_input");
  configurePublicInputStage(setup.algorithm);
  content.replaceChildren();
  if (!setup.recovery?.supported) {
    addTextElement(content, "p", "flow-placeholder", "Key setup is complete. This profile has no supported quantum recovery workflow.");
    for (const stage of Object.keys(flowPlaceholders)) {
      setFlowState(stage, "not_reached", "SETUP ONLY");
      if (stage !== "public_input") {
        flowContent(stage).replaceChildren();
        addTextElement(flowContent(stage), "p", "flow-placeholder", "Not applicable: this profile supports key inspection only.");
      }
    }
    document.querySelector("#result-title").textContent = `${setup.algorithm.toUpperCase()} setup only`;
    document.querySelector("#result-summary").textContent = "Key generation and inspection are available; quantum recovery is not supported for this profile.";
    return;
  }
  addTextElement(content, "p", "flow-placeholder", flowPlaceholders.public_input);
  document.querySelector("#result-title").textContent = setup.algorithm === "rsa"
    ? "RSA factoring ready"
    : "ECC discrete-log ready";
  document.querySelector("#result-summary").textContent = (
    "The public instance is shown in Key Setup. Run the selected recovery to follow its evidence."
  );
  setFlowState("public_input", "complete", "READY");
}

function resetRunSections() {
  for (const stage of ["quantum_observation", "recovered_structure", "secret_recovery", "validation"]) {
    resetFlowSection(stage);
  }
  initializePreparationStage(activeKeySetup);
}

function resetEventTrace() {
  document.querySelector("#event-trace").replaceChildren();
  renderedTraceEvents.length = 0;
}

function appendRawEvent(event, serializedEvent = JSON.stringify(event)) {
  const item = document.createElement("li");
  addTextElement(item, "span", "event-category", event.category.replaceAll("_", " "));
  addTextElement(item, "span", "event-label", event.label);
  addTextElement(item, "span", "event-description", event.description);
  if (event.evidence && Object.keys(event.evidence).length) {
    addTextElement(item, "code", "evidence-code", JSON.stringify(event.evidence));
  }
  document.querySelector("#event-trace").append(item);
  renderedTraceEvents.push(serializedEvent);
}

function reconcileEventTrace(events) {
  const serializedEvents = events.map((event) => JSON.stringify(event));
  // Keep the shared prefix so completion preserves already-rendered stream rows.
  let prefix = 0;
  while (
    prefix < renderedTraceEvents.length
    && prefix < serializedEvents.length
    && renderedTraceEvents[prefix] === serializedEvents[prefix]
  ) {
    prefix += 1;
  }
  const trace = document.querySelector("#event-trace");
  while (trace.children.length > prefix) trace.lastElementChild.remove();
  renderedTraceEvents.length = prefix;
  for (let index = prefix; index < events.length; index += 1) {
    appendRawEvent(events[index], serializedEvents[index]);
  }
}

function finalizeFlow(result) {
  // Final outcomes distinguish missing stages, classical recovery, and failed attempts.
  const events = result.events ?? [];
  const hasStageEvent = (stage) => events.some((event) => event.stage === stage);
  const recovered = result.outcome?.status === "recovered";
  const classical = result.outcome?.recovery_source === "classical_preprocessing";
  const classicalEvent = events.find((event) => event.category === "classical_preprocessing");
  if (result.outcome?.status === "error") {
    for (const group of document.querySelectorAll(".flow-attempt-group")) {
      group.querySelectorAll(".flow-sampling-message").forEach(element => element.remove());
      const state = group.querySelector(".flow-attempt-state")?.dataset.state;
      if (["sampling", "circuit_ready", "base_selected", "ready"].includes(state)) {
        setAttemptState(group, "ERROR");
      }
    }
    if (flowContent("quantum_observation").querySelector(".flow-attempt-group, .flow-entry")) {
      setFlowState("quantum_observation", "failed", "ERROR");
    }
  }
  if (events.some((event) => event.category === "base_selection")) {
    setFlowState("public_input", "complete", "BASES CHECKED");
  } else if (events.some((event) => event.category === "classical_preflight")) {
    setFlowState("public_input", "complete", "INPUT CHECKED");
  }
  if (!hasStageEvent("quantum_observation") && !flowContent("quantum_observation").querySelector(".flow-attempt-group, .flow-entry")) {
    setFlowState("quantum_observation", classical ? "not_reached" : "failed", "NOT REACHED");
    if (classicalEvent) {
      const placeholder = flowContent("quantum_observation").querySelector(".flow-placeholder");
      if (placeholder) placeholder.textContent = `No circuit submitted: ${classicalEvent.description}`;
    }
  }
  if (!hasStageEvent("recovered_structure")) {
    setFlowState("recovered_structure", "not_reached", "NOT REACHED");
    if (classicalEvent) {
      const placeholder = flowContent("recovered_structure").querySelector(".flow-placeholder");
      if (placeholder) {
        placeholder.textContent = "No quantum samples were produced for period reconstruction.";
      }
    }
  }
  if (!hasStageEvent("secret_recovery")) {
    setFlowState("secret_recovery", recovered ? "complete" : "failed", recovered ? "RECOVERED" : "NO CANDIDATE");
  }
  if (!hasStageEvent("validation")) {
      setFlowState("validation", "not_reached", "NOT REACHED");
      const placeholder = flowContent("validation").querySelector(".flow-placeholder");
      if (placeholder) {
        placeholder.textContent = result.outcome?.status === "error"
          ? "Validation was not reached because the run ended with an error."
          : "No candidate was produced; validation was not reached.";
      }
  }
  if (recovered) {
    setFlowState(
      "secret_recovery",
      "complete",
      result.outcome?.recovery_source === "classical_preprocessing" ? "CLASSICAL FACTOR" : "RECOVERED"
    );
  } else if (result.outcome?.status === "ambiguous") {
    setFlowState("secret_recovery", "failed", "AMBIGUOUS");
  } else if (result.outcome?.status === "failed") {
    setFlowState("secret_recovery", "failed", "NOT RECOVERED");
  }
}

function renderCompletedResult(result) {
  const status = result.outcome?.status ?? "error";
  const resultTitles = {
    rsa_factoring: "RSA factoring result",
    ecc_discrete_log: "ECC discrete-log result"
  };
  document.querySelector("#result-title").textContent = resultTitles[result.algorithm]
    ?? "Run result";
  const statusElement = document.querySelector("#result-status");
  statusElement.hidden = false;
  statusElement.textContent = status.replaceAll("_", " ");
  statusElement.dataset.status = status;
  document.querySelector("#result-summary").textContent = result.outcome?.summary ?? "No result summary was returned.";
  if (status !== "error" || result.events?.length) reconcileEventTrace(result.events ?? []);
  document.querySelector("#limitations").replaceChildren();
  for (const limitation of result.limitations ?? []) {
    addTextElement(document.querySelector("#limitations"), "li", "", limitation);
  }
  const run = result.run ?? {};
  const registers = Object.entries(run.registers ?? {}).map(([name, size]) => `${name}: ${size}`).join(" · ");
  const shotsSummary = run.total_shots === undefined
    ? formatCount(run.shots ?? 0, "shot")
    : `${formatCount(run.shots ?? 0, "shot")} per batch · ${formatCount(run.total_shots, "shot")} total`;
  const attemptUnit = result.algorithm === "rsa_factoring" ? "base attempt" : "sampling attempt";
  const attemptSummary = `${run.attempts_completed ?? 0} of ${formatCount(run.attempt_budget ?? 1, attemptUnit)}`;
  document.querySelector("#run-metadata").textContent = [
    shotsSummary,
    `seed ${run.seed ?? "auto"}`,
    `${run.qubits ?? "?"} qubits`,
    attemptSummary,
    registers
  ].filter(Boolean).join(" · ");
  finalizeFlow(result);
  resultSection.setAttribute("aria-busy", "false");
}

async function consumeRunStream(response, isCurrentRun = () => true) {
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.outcome?.summary ?? "The run request was rejected.");
  }
  const reader = response.body.getReader();
  // Network chunks can split UTF-8 characters and NDJSON lines at arbitrary boundaries.
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult = null;
  const processLine = (line) => {
    if (!line.trim() || !isCurrentRun()) return;
    const message = JSON.parse(line);
    if (message.type === "stage") {
      renderFlowEvent(message.event);
      appendRawEvent(message.event);
    }
    if (message.type === "complete") finalResult = message.result;
  };
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) processLine(line);
      if (done) break;
    }
    processLine(buffer);
    if (!finalResult) throw new Error("The run stream ended before returning a result.");
    return finalResult;
  } finally {
    if (!finalResult) await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

runForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (activeRunId !== null) return;
  if (!activeKeySetup?.recovery?.supported) {
    showToast("Generate a recovery-supported toy keypair before running.");
    return;
  }
  // Acquire client-side ownership before rendering or sending a request.
  const runId = ++runSequence;
  activeRunId = runId;
  const isCurrentRun = () => activeRunId === runId;
  resetRunSections();
  document.querySelector("#result-title").textContent = "Run in progress";
  document.querySelector("#result-summary").textContent = "Public input is ready. The simulator is sampling the selected operation.";
  const statusElement = document.querySelector("#result-status");
  statusElement.hidden = false;
  statusElement.textContent = "running";
  statusElement.dataset.status = "running";
  setFlowState("quantum_observation", "running", "SAMPLING");
  resultSection.scrollIntoView({ block: "start", behavior: "smooth" });
  resultSection.setAttribute("aria-busy", "true");
  resetEventTrace();
  document.querySelector("#limitations").replaceChildren();
  document.querySelector("#run-metadata").textContent = "";
  runSettings.open = false;
  updateRunAvailability();
  setRunControlsDisabled(true);
  const controller = new AbortController();
  const deadline = window.setTimeout(() => controller.abort(), 120_000);
  try {
    const seedValue = seedInput.value;
    const payload = {
      algorithm: algorithmInput.value,
      shots: Number(shotsInput.value)
    };
    payload.seed = seedValue === ""
      ? window.crypto.getRandomValues(new Uint32Array(1))[0]
      : Number(seedValue);
    if (algorithmInput.value === "rsa") {
      payload.rsa_catalog_id = activeKeySetup.recovery.catalog_id;
    } else {
      payload.ecc_catalog_id = activeKeySetup.profile_id;
      payload.ecc_public_point = activeKeySetup.public_key.Q.map(Number);
    }
    document.querySelector("#run-metadata").textContent = `Run seed ${payload.seed}`;

    const response = await fetch("/api/run/stream", {
      method: "POST",
      signal: controller.signal,
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(payload)
    });
    const result = await consumeRunStream(response, isCurrentRun);
    if (isCurrentRun()) renderCompletedResult(result);
  } catch (error) {
    if (!isCurrentRun()) return;
    resultSection.setAttribute("aria-busy", "false");
    document.querySelector("#result-title").textContent = "Run error";
    statusElement.textContent = "error";
    statusElement.dataset.status = "error";
    const message = error.name === "AbortError"
      ? "Browser waiting limit reached. Server execution may still be active; this did not cancel the simulator."
      : error.message ?? "The local run failed.";
    document.querySelector("#result-summary").textContent = message;
    for (const group of document.querySelectorAll(".flow-attempt-group")) {
      group.querySelectorAll(".flow-sampling-message").forEach(element => element.remove());
      if (["sampling", "circuit_ready", "base_selected"].includes(group.querySelector(".flow-attempt-state")?.dataset.state)) {
        setAttemptState(group, "INTERRUPTED");
      }
    }
    for (const stage of ["quantum_observation", "recovered_structure", "secret_recovery", "validation"]) {
      const stageState = document.querySelector(`[data-flow-state="${stage}"]`).dataset.state;
      if (stageState === "running") setFlowState(stage, "failed", "INTERRUPTED");
      else if (stageState === "waiting") setFlowState(stage, "not_reached", "NOT REACHED");
    }
    showToast(message);
  } finally {
    window.clearTimeout(deadline);
    if (isCurrentRun()) {
      // An obsolete request must not unlock controls belonging to another run.
      activeRunId = null;
      setRunControlsDisabled(false);
      updateRunAvailability();
    }
  }
});
