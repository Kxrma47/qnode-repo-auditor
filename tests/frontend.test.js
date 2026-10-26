const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function setup(storage = new Map()) {
  const elements = new Map();
  const windowListeners = {};
  const focusButtons = ["all", "source", "generated", "review"].map((focus) => {
    const button = new Element("button");
    button.dataset.focus = focus;
    return button;
  });

  function Element(tag) {
    this.tag = tag;
    this.tagName = tag.toUpperCase();
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
  Element.prototype.focus = function () { document.activeElement = this; };
  Element.prototype.classList = { add() {}, remove() {}, toggle() {} };

  const document = {
    body: { dataset: { publicAudit: "false", visitorMetrics: "false" } },
    activeElement: null,
    querySelector(selector) {
      if (!elements.has(selector)) elements.set(selector, new Element("div"));
      return elements.get(selector);
    },
    querySelectorAll(selector) { return selector === "[data-focus]" ? focusButtons : []; },
    createElement(tag) { return new Element(tag); },
  };
  const window = {
    localStorage: {
      getItem(key) { return storage.get(key) ?? null; },
      setItem(key, value) { storage.set(key, value); },
      removeItem(key) { storage.delete(key); },
    },
    addEventListener(name, handler) { windowListeners[name] = handler; },
  };
  const context = vm.createContext({ document, window, navigator: {}, URL, URLSearchParams,
    Blob, fetch: async () => { throw new Error("unexpected fetch"); } });
  const script = fs.readFileSync(path.join(__dirname, "../qnode_auditor/static/app.js"), "utf8");
  vm.runInContext(script, context);
  const get = (selector) => document.querySelector(selector);
  const text = (node) => [node.textContent, ...node.children.map((child) =>
    typeof child === "string" ? child : text(child))].join(" ");
  return { context, get, text, focusButtons, storage, windowListeners };
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

test("Review Map search narrows paths and supports keyboard navigation", () => {
  const { context, get, text, windowListeners } = setup();
  context.fixture = { repository: { full_name: "owner/repo" },
    pull_request: { number: 7, head_sha: "head-a" }, audit: { review_delta: null } };
  context.lanes = [
    { label: "services/api/", attention: "high", file_count: 2, additions: 2,
      deletions: 0, signals: ["API schema"], owners: ["@api-team"], unowned_files: 0,
      source_files: 1, test_path_matches: 0, review_questions: [], paths: ["services/api/app.py", "services/api/test_app.py"] },
    { label: "docs/", attention: "routine", file_count: 1, additions: 1,
      deletions: 0, signals: [], owners: [], unowned_files: 1, source_files: 0,
      test_path_matches: 0, review_questions: [], paths: ["docs/readme.md"] },
  ];
  context.fixture.audit.review_map = context.lanes;
  vm.runInContext("lastReport = fixture; loadReviewSession(fixture); renderReviewMap(lanes)", context);
  const search = get("#review-search");
  search.value = "test_app";
  search.listeners.input({ target: search });
  assert.match(text(get("#review-lanes")), /test_app.py/);
  assert.doesNotMatch(text(get("#review-lanes")), /services\/api\/app\.py/);
  search.value = "@api-team";
  search.listeners.input({ target: search });
  assert.match(text(get("#review-lanes")), /app.py.*test_app.py/);
  assert.doesNotMatch(text(get("#review-lanes")), /docs\/readme.md/);
  search.listeners.keydown({ key: "Escape", target: search });
  assert.equal(search.value, "");
  assert.match(text(get("#review-lanes")), /docs\/readme.md/);
  get("#review-map-section").hidden = false;
  const document = context.document;
  let prevented = false;
  windowListeners.keydown({ key: "/", preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(document.activeElement, search);
});

test("local review marks restore only for the same PR head and filter unmarked lanes", () => {
  const storage = new Map();
  const { context, get, text } = setup(storage);
  context.fixture = { repository: { full_name: "owner/repo" },
    pull_request: { number: 7, head_sha: "head-a" }, audit: { review_delta: null } };
  context.lanes = [
    { label: "api/", attention: "high", file_count: 1, additions: 1, deletions: 0,
      signals: [], owners: [], unowned_files: 1, source_files: 1, test_path_matches: 0,
      paths: ["api/app.py"] },
    { label: "docs/", attention: "routine", file_count: 1, additions: 1, deletions: 0,
      signals: [], owners: [], unowned_files: 1, source_files: 0, test_path_matches: 0,
      paths: ["docs/readme.md"] },
  ];
  context.fixture.audit.review_map = context.lanes;
  vm.runInContext("lastReport = fixture; loadReviewSession(fixture); renderReviewMap(lanes)", context);
  const mark = get("#review-lanes").children[0].children.find((child) => child.className === "lane-action").children[0];
  mark.listeners.click();
  assert.equal(mark["aria-pressed"], "true");
  assert.match(get("#review-progress").textContent, /1\/2 lanes marked inspected locally/);
  assert.equal(storage.size, 1);
  get("#review-unmarked").listeners.click({ target: get("#review-unmarked") });
  assert.doesNotMatch(text(get("#review-lanes")), /api\/app.py/);
  assert.match(text(get("#review-lanes")), /docs\/readme.md/);
  vm.runInContext("loadReviewSession(fixture); reviewUnmarkedOnly = false; renderReviewMap(lanes)", context);
  const restored = get("#review-lanes").children[0].children.find((child) => child.className === "lane-action").children[0];
  assert.equal(restored["aria-pressed"], "true");
  get("#clear-review-marks").listeners.click();
  assert.equal(storage.size, 0);
  assert.match(get("#review-progress").textContent, /0\/2 lanes marked inspected locally/);
  vm.runInContext("fixture.pull_request.head_sha = 'head-b'; loadReviewSession(fixture); renderReviewMap(lanes)", context);
  assert.match(get("#review-progress").textContent, /0\/2 lanes marked inspected locally/);
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

test("post-scan star action records only an aggregate event key", async () => {
  const { context, get } = setup();
  context.document.body.dataset.visitorMetrics = "true";
  let request;
  context.fetch = async (url, options) => {
    request = { url, options };
    return { ok: true };
  };
  get("#star-qnode").listeners.click();
  assert.equal(request.url, "/api/event");
  assert.deepEqual(JSON.parse(request.options.body), { event: "star" });
  assert.equal(request.options.keepalive, true);
});

test("instant demo is labelled and does not require a repository input", async () => {
  const { context, get } = setup();
  context.fetch = async () => ({ ok: true, json: async () => ({
    demo: true, cached: false, ref: "demo-head", scanned_paths: 2,
    repository: { full_name: "QNode demonstration", html_url: "https://example.invalid",
      description: "Synthetic report", language: "TypeScript", updated_at: "2026-10-08" },
    pull_request: { number: 42, title: "Demo", html_url: "https://example.invalid", state: "open",
      draft: false, changed_files: 1, additions: 2, deletions: 1 },
    audit: { score: 80, grade: "B", passed: 8, total: 12, checks: [], recommendations: [],
      risks: [], review_delta: null, change_contracts: [], companion_suggestions: [],
      review_map: [], tree_truncated: false, files_truncated: false, policy_warning: "",
      ignored_files: 0, markdown: "demo" },
    ci_evidence: null, review_handoff: null,
  }) });
  await vm.runInContext("runDemo()", context);
  assert.equal(get("#cache-state").textContent, "DEMO");
  assert.equal(get("#repository").value, "Static QNode demonstration");
  assert.match(get("#form-message").textContent, /Demonstration data only/);
});

test("review intelligence renders graph, history, CI, split, and reviewer evidence", () => {
  const { context, get, text } = setup();
  context.fixture = { pull_request: { number: 4 } };
  context.intelligence = {
    decision_pack: { attention_count: 1, note: "Ten deterministic lenses.", items: [
      { key: "verification-debt", title: "Verification debt", status: "attention",
        value: "1 source gap(s)", detail: "One changed source has no matching changed test.",
        action: "Add a focused test.", evidence: "review-map + observed-checks" },
      { key: "ownership-coverage", title: "Ownership coverage", status: "clear",
        value: "100% owned", detail: "All paths have an owner.",
        action: "Keep ownership current.", evidence: "CODEOWNERS last-match rules" },
    ] },
    merge_readiness: { status: "blocked", headline: "2 OBSERVED BLOCKER(S)",
      note: "Observed metadata only.", complete: true, auto_merge_enabled: false,
      blockers: [{ label: "Checks failing", detail: "One observed check failed.",
        evidence: "observed-checks" }], waiting: [], warnings: [],
      satisfied: [{ label: "No merge conflict observed", detail: "Branches are mergeable.",
        evidence: "github-merge-state" }], next_actions: ["Fix the failing check."] },
    blast_radius: { score: 72, level: "high", factors: [{ label: "Operational reach" }] },
    review_freshness: { status: "stale", reasons: [{ text: "Two paths changed after review." }] },
    change_memory: { sampled_commits: 12, links: [{ source: "src/app.py", target: "tests/test_app.py" }],
      suggestions: [{ source_path: "src/app.py", suggested_path: "tests/test_app.py",
        confidence: 0.75, reason: "Changed together in 3 of 4 sampled commits." }], note: "history" },
    impact_graph: { nodes: [
      { id: "lane:src", kind: "lane", label: "src/" },
      { id: "path:src/app.py", kind: "path", label: "src/app.py" },
    ], edges: [{ source: "lane:src", target: "path:src/app.py", kind: "contains" }] },
    ci_plan: { jobs: [{ name: "unit", lane: "src/", evidence: "configured", reason: "Mapped" }] },
    split_plan: { recommended: true, groups: [{ title: "src/", file_count: 2,
      attention: "high", paths: ["src/app.py"] }], couplings: [] },
    reviewer_router: { load_available: true, routes: [{ lane: "src/", suggested: "@alice",
      unowned_files: 0, candidates: [{ owner: "@alice", observed_open_requests: 1 }] }] },
  };
  vm.runInContext("lastReport = fixture; renderIntelligence(intelligence)", context);
  assert.match(text(get("#intelligence-summary")), /2 OBSERVED BLOCKER.*72\/100 · HIGH.*STALE.*12 COMMITS.*SPLIT SUGGESTED/);
  assert.match(text(get("#merge-readiness-list")), /BLOCKER.*Checks failing.*observed-checks.*SATISFIED.*No merge conflict observed/);
  assert.match(text(get("#merge-actions")), /NEXT ACTIONS.*Fix the failing check/);
  assert.match(text(get("#decision-pack-list")), /Verification debt.*1 source gap.*review-map.*Add a focused test.*Ownership coverage.*100% owned/);
  assert.equal(get("#decision-pack-status").textContent, "1/10 NEED ATTENTION");
  assert.match(text(get("#impact-graph")), /src\/.*src\/app.py.*contains/);
  assert.match(text(get("#memory-list")), /tests\/test_app.py.*75%/);
  assert.match(text(get("#ci-plan-list")), /unit.*CONFIGURED/);
  assert.match(text(get("#split-list")), /src\/.*2 files/);
  assert.match(text(get("#router-list")), /First option: @alice.*@alice \(1 open\)/);
  const firstNode = get("#impact-graph").children[0].children[0];
  firstNode.listeners.click();
  assert.equal(get("#impact-graph").children[0].children[0]["aria-pressed"], "true");
});
