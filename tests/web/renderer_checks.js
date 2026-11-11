globalThis.runRendererRegressionChecks = async function () {
  if (activeRunId !== null || activeKeySetup !== null) {
    throw new Error("Run browser regressions on a fresh page before key setup.");
  }
  const checks = [];
  function verify(condition, label) {
    if (!condition) throw new Error(label);
    checks.push(label);
  }
  try {
    resetFlow();
    renderFlowEvent({
      stage: "validation", category: "validation", description: "Rejected candidate.",
      evidence: {status: "failed", factors: [3, 5], product: 14}
    });
    verify(document.querySelector('[data-flow-state="validation"]').textContent === "FAILED", "explicit failed status wins");
    verify(!document.querySelector('.validation-equation').textContent.includes("= 14")
      || document.querySelector('.validation-equation').textContent.includes("expected"), "failed equation is not asserted true");

    resetFlow();
    const sampling = {
      stage: "quantum_observation", category: "run_state", description: "Measurements not available yet.",
      evidence: {attempt: 1, base: 2, shots: 9, seed: 1}
    };
    renderFlowEvent(sampling);
    renderFlowEvent({
      stage: "quantum_observation", category: "simulator_observation", label: "Measured phases",
      evidence: {attempt: 1, base: 2, counts: {0: 7, 64: 1, 128: 1}}
    });
    verify(!document.querySelector('.flow-sampling-message'), "completed sampling message removed");
    verify(!document.querySelector('.flow-histogram').closest('details'), "graph always visible");
    const tracks = [...document.querySelectorAll('.bar-item')];
    verify(tracks.every(element => {
      const count = element.querySelector('.bar-count').getBoundingClientRect();
      const track = element.querySelector('.bar-track').getBoundingClientRect();
      const label = element.querySelector('.bar-label').getBoundingClientRect();
      return count.bottom <= track.top && track.bottom <= label.top;
    }), "chart rows do not overlap");
    verify(new Set(tracks.map(element => getComputedStyle(element.querySelector('.bar-fill')).backgroundColor)).size === 1,
      "observation colors are not positional");
    if (innerWidth >= 1200) {
      verify(parseFloat(getComputedStyle(document.querySelector('.flow-section-heading h3')).fontSize) >= 26, "presentation stage font");
      verify(parseFloat(getComputedStyle(document.querySelector('.flow-attempt-label')).fontSize) >= 18, "presentation attempt font");
      verify(parseFloat(getComputedStyle(document.querySelector('.flow-attempt-group')).gridTemplateColumns.split(' ')[0]) > 0,
        "desktop attempt grid");
    }
    verify(document.documentElement.scrollWidth <= innerWidth, "no page overflow");

    resetFlow();
    renderFlowEvent(sampling);
    appendRawEvent(sampling);
    renderCompletedResult({algorithm: "rsa_factoring", run: {shots: 9, seed: 1}, events: [],
      outcome: {status: "error", summary: "Worker failed."}, limitations: []});
    verify(document.querySelector('.flow-attempt-state').textContent === "ERROR", "terminal error clears sampling state");
    verify(document.querySelector('[data-flow-state="validation"]').textContent === "NOT REACHED", "error skips validation");
    verify(document.querySelectorAll('#event-trace li').length === 1, "error retains trace");

    resetFlow();
    renderFlowEvent({stage: "recovered_structure", category: "classical_postprocessing",
      evidence: {attempt: 1, relation: "v = ku mod 7", frequencies: [{u: 7, v: 0, count: 1, status: "invalid_frequency"}]}});
    verify(document.querySelector('[data-flow-state="recovered_structure"]').textContent === "INVALID FREQUENCIES", "invalid frequencies distinguished");

    resetFlow();
    renderFlowEvent({stage: "quantum_observation", category: "simulator_observation", label: "ECC counts",
      evidence: {attempt: 1, frequencies: [{u: 1, v: 3, count: 4096}]}});
    const heatmap = document.querySelector('.frequency-heatmap');
    const canvas = document.querySelector('#flow-observation-content');
    verify(heatmap.getBoundingClientRect().right <= canvas.getBoundingClientRect().right,
      "heatmap stays within evidence canvas");
    verify(!heatmap.closest('details'), "heatmap always visible");

    resetFlow();
    initializePreparationStage({algorithm: "ecc", recovery: {supported: false}});
    verify([...document.querySelectorAll('[data-flow-state]')].every(element => element.textContent === "SETUP ONLY"),
      "setup-only stages not left waiting");
    return {passed: checks.length, checks, viewport: `${innerWidth}x${innerHeight}`};
  } finally {
    configurePublicInputStage("rsa");
    resetFlow();
  }
};