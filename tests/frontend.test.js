const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function setup() {
  const elements = new Map();
  const focusButtons = ["all", "source", "generated", "review"].map((focus) => {
    const button = new Element("button");
    button.dataset.focus = focus;
    return button;
  });

  function Element(tag) {
    this.tag = tag;
    this.children = [];
    this.textContent = "";
    this.value = "";
    this.dataset = {};
    this.listeners = {};
    this.style = { setProperty() {} };
  }
  Element.prototype.append = function (...children) { this.children.push(...children); };
  Element.prototype.replaceChildren = function (...children) { this.children = children; };
  Element.prototype.addEventListener = function (name, handler) { this.listeners[name] = handler; };
  Element.prototype.setAttribute = function (name, value) { this[name] = value; };
  Element.prototype.scrollIntoView = function () {};
  Element.prototype.classList = { add() {}, remove() {}, toggle() {} };

  const document = {
    body: { dataset: { publicAudit: "false", visitorMetrics: "false" } },
    querySelector(selector) {
      if (!elements.has(selector)) elements.set(selector, new Element("div"));
      return elements.get(selector);
    },
    querySelectorAll(selector) { return selector === "[data-focus]" ? focusButtons : []; },
    createElement(tag) { return new Element(tag); },
  };
  const context = vm.createContext({ document, window: {}, navigator: {}, URL, URLSearchParams,
    Blob, fetch: async () => { throw new Error("unexpected fetch"); } });
  const script = fs.readFileSync(path.join(__dirname, "../qnode_auditor/static/app.js"), "utf8");
  vm.runInContext(script, context);
  const get = (selector) => document.querySelector(selector);
  const text = (node) => [node.textContent, ...node.children.map((child) =>
    typeof child === "string" ? child : text(child))].join(" ");
  return { context, get, text, focusButtons };
}

test("Review Map filters all paths, source, generated, and since-review", () => {
  const { context, get, text, focusButtons } = setup();
  const lanes = [{ label: "src/", attention: "routine", file_count: 4, additions: 4,
    deletions: 0, signals: [], owners: [], unowned_files: 4, source_files: 1,
    test_path_matches: 0, review_questions: [], test_targets: [], configured_jobs: [],
    paths: ["src/app.py", "tests/test_app.py", "generated/client.ts", "docs/guide.md"] }];
  context.fixture = { pull_request: { number: 1 }, audit: {
    review_delta: { changed_paths: ["src/app.py"] }, review_map: lanes } };
  vm.runInContext("lastReport = fixture; renderReviewMap(fixture.audit.review_map)", context);
  assert.match(text(get("#review-lanes")), /generated\/client.ts/);
  focusButtons[1].listeners.click();
  assert.match(text(get("#review-lanes")), /src\/app.py/);
  assert.doesNotMatch(text(get("#review-lanes")), /tests\/test_app.py/);
  focusButtons[2].listeners.click();
  assert.doesNotMatch(text(get("#review-lanes")), /generated\/client.ts/);
  focusButtons[3].listeners.click();
  assert.match(text(get("#review-lanes")), /src\/app.py/);
  assert.doesNotMatch(text(get("#review-lanes")), /docs\/guide.md/);
});

test("CI display distinguishes failed, skipped, and unobserved jobs", () => {
  const { context, get, text } = setup();
  context.fixture = { pull_request: { number: 1 } };
  context.evidence = { available: true, complete: false, observed: [
    { name: "unit", state: "failed", html_url: "https://github.com/o/r/actions/runs/1",
      configured: true },
    { name: "lint", state: "skipped", html_url: "", configured: false },
  ], not_observed: ["integration"] };
  vm.runInContext("lastReport = fixture; renderCi(evidence)", context);
  assert.match(text(get("#ci-list")), /FAILED.*unit/);
  assert.match(text(get("#ci-list")), /SKIPPED.*lint/);
  assert.match(text(get("#ci-list")), /NOT OBSERVED.*integration/);
  assert.match(get("#ci-summary").textContent, /incomplete/);
});

test("review handoff displays facts separately from questions and mapped evidence", () => {
  const { context, get, text } = setup();
  context.fixture = { pull_request: { number: 3 } };
  context.handoff = { total_lanes: 1, facts: ["GitHub reports two changed files."],
    questions: ["Which commands verified the change?"], lanes: [{ label: "src/",
      attention: "medium", files: 2, owners: ["@team"], unowned_files: 0,
      source_files: 1, test_path_matches: 0,
      jobs: [{ name: "unit", states: ["failed"] }] }] };
  vm.runInContext("lastReport = fixture; renderHandoff(handoff)", context);
  assert.match(text(get("#handoff-facts")), /GitHub reports two changed files/);
  assert.doesNotMatch(text(get("#handoff-facts")), /Which commands/);
  assert.match(text(get("#handoff-questions")), /Which commands/);
  assert.match(text(get("#handoff-lanes")), /unit \(failed\)/);
  assert.equal(get("#handoff-section").hidden, false);
});

test("handoff copy action copies only the editable Markdown", async () => {
  const { context, get } = setup();
  let copied = "";
  context.navigator.clipboard = { writeText: async (value) => { copied = value; } };
  context.window.setTimeout = () => 0;
  context.fixture = { review_handoff: { markdown: "## Review handoff\n- [ ] Verify tests" } };
  vm.runInContext("lastReport = fixture", context);
  await get("#copy-handoff").listeners.click();
  assert.equal(copied, "## Review handoff\n- [ ] Verify tests");
  assert.equal(get("#action-message").textContent, "Editable review handoff copied.");
});

test("before and after chart renders both scores and check transitions", () => {
  const { context, get, text } = setup();
  context.comparison = { base: { ref: "main", score: 50, grade: "F" },
    head: { ref: "next", score: 70, grade: "C" }, score_delta: 20,
    changed_checks: [{ label: "License", after: true }], note: "Not proof of tests." };
  vm.runInContext("renderComparison(comparison)", context);
  assert.match(text(get("#compare-results")), /main.*50\/100/);
  assert.match(text(get("#compare-results")), /next.*70\/100/);
  assert.match(text(get("#compare-results")), /Gained: License/);
});

test("attention queue renders observed signals from its on-demand response", async () => {
  const { context, get, text } = setup();
  get("#repository").value = "owner/repo";
  context.fetch = async () => ({ ok: true, json: async () => ({ scope: "Recent open PRs", items: [
    { number: 3, title: "Fix", html_url: "https://github.com/owner/repo/pull/3",
      signals: ["Observed check failure"] },
  ] }) });
  await get("#attention-button").listeners.click();
  assert.match(text(get("#attention-list")), /#3.*Fix.*Observed check failure/);
  assert.equal(get("#attention-section").hidden, false);
});

test("review follow-up shows open outdated threads without treating them as addressed", async () => {
  const { context, get, text } = setup();
  context.fixture = { repository: { full_name: "owner/repo" }, pull_request: { number: 3 } };
  vm.runInContext("lastReport = fixture", context);
  context.fetch = async () => ({ ok: true, json: async () => ({ complete: false,
    observed_unresolved: 2, observed_resolved: 1, threads: [
      { path: "src/app.py", outdated: true, url: "https://github.com/owner/repo/pull/3#discussion_r1" },
      { path: "tests/app.test.js", outdated: false, url: "https://github.com/owner/repo/pull/3#discussion_r2" },
    ] }) });
  await get("#followup-button").listeners.click();
  assert.match(get("#followup-message").textContent, /First 200 threads only/);
  assert.match(get("#followup-message").textContent, /Outdated does not mean addressed/);
  assert.match(text(get("#followup-list")), /OUTDATED · OPEN.*src\/app.py.*OPEN.*tests\/app.test.js/);
});

test("signal feedback sends only category and vote, without repository or path", async () => {
  const { context, get } = setup();
  context.document.body.dataset.visitorMetrics = "true";
  let request;
  context.fetch = async (url, options) => {
    request = { url, options };
    return { ok: true };
  };
  context.fixture = { pull_request: { number: 3 } };
  context.risks = [{ key: "workflow-change", severity: "low", title: "CI changed",
    detail: "Review permissions", path: ".github/workflows/test.yml" }];
  vm.runInContext("lastReport = fixture; renderRisks(risks)", context);
  const card = get("#risks").children[0];
  const controls = card.children.find((child) => child.className === "signal-feedback");
  const yes = controls.children.find((child) => child.tag === "button");
  await yes.listeners.click();
  assert.equal(request.url, "/api/signal-feedback");
  assert.deepEqual(JSON.parse(request.options.body), { signal: "workflow-change", useful: true });
  assert.equal(yes["aria-pressed"], "true");
  assert.match(controls.children.at(-1).textContent, /saved/);
});
