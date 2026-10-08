const form = document.querySelector("#audit-form");
const repositoryInput = document.querySelector("#repository");
const scanButton = document.querySelector("#scan-button");
const formMessage = document.querySelector("#form-message");
const report = document.querySelector("#report");
const actionMessage = document.querySelector("#action-message");
let lastReport = null;
let reviewFocus = "all";

function recordEvent(event) {
  if (document.body.dataset.visitorMetrics !== "true" || navigator.doNotTrack === "1") return;
  fetch("/api/event", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-QNode-Event": "1" },
    credentials: "same-origin",
    keepalive: true,
    body: JSON.stringify({ event }),
  }).catch(() => {});
}

const setText = (selector, value) => {
  document.querySelector(selector).textContent = value;
};

const formatDate = (value) => {
  if (!value) return "Updated —";
  return `Updated ${new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(value))}`;
};

const makeElement = (tag, className, text) => {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
};

function parseTarget(value) {
  const input = value.trim();
  const shortPull = input.match(/^([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+)#([1-9][0-9]*)$/);
  if (shortPull) return { repository: `${shortPull[1]}/${shortPull[2]}`, pull: shortPull[3] };

  const githubUrl = input.match(
    /^(?:https?:\/\/)?(?:www\.)?github\.com\/([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+?)(?:\.git)?(?:\/pull\/([1-9][0-9]*))?\/?(?:[?#].*)?$/,
  );
  if (githubUrl) {
    return { repository: `${githubUrl[1]}/${githubUrl[2]}`, pull: githubUrl[3] || "" };
  }
  if (/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(input)) {
    return { repository: input, pull: "" };
  }
  return null;
}

function renderChecks(checks) {
  const container = document.querySelector("#checks");
  container.replaceChildren();
  checks.forEach((check) => {
    const card = makeElement("article", `check${check.passed ? " passed" : ""}`);
    const top = makeElement("div", "check-top");
    top.append(
      makeElement("span", "check-status", check.passed ? "✓" : "○"),
      makeElement("strong", "", check.label),
      makeElement("b", "", `${check.weight} PT`),
    );
    card.append(top, makeElement("p", "", check.evidence));
    container.append(card);
  });
}

function renderRecommendations(recommendations) {
  const list = document.querySelector("#recommendation-list");
  list.replaceChildren();
  if (!recommendations.length) {
    const item = makeElement("li", "empty-recommendation");
    item.append(
      makeElement("strong", "", "Core safeguards detected"),
      makeElement("p", "", "Keep the repository current and review pull-request signals through the installed app."),
    );
    list.append(item);
    return;
  }
  recommendations.slice(0, 5).forEach((recommendation) => {
    const item = makeElement("li");
    const title = makeElement("strong", "", recommendation.label);
    title.append(" ", makeElement("b", "", `+${recommendation.points}`));
    item.append(title, makeElement("p", "", recommendation.recommendation));
    list.append(item);
  });
}

function renderRisks(risks) {
  const section = document.querySelector("#risk-section");
  const container = document.querySelector("#risks");
  container.replaceChildren();
  section.hidden = !lastReport?.pull_request;
  setText("#risk-count", risks.length ? `${risks.length} DETECTED` : "CLEAR");
  if (!risks.length) {
    const empty = makeElement("article", "risk-card clear");
    empty.append(
      makeElement("strong", "", "No structural risk signals detected"),
      makeElement("p", "", "QNode found no path-level warnings in this change set. Code review and tests are still required."),
    );
    container.append(empty);
    return;
  }
  const feedbackShown = new Set();
  risks.forEach((risk) => {
    const card = makeElement("article", `risk-card ${risk.severity}`);
    const header = makeElement("div", "risk-header");
    header.append(
      makeElement("span", "risk-level", risk.severity.toUpperCase()),
      makeElement("strong", "", risk.title),
    );
    card.append(header, makeElement("p", "", risk.detail));
    if (risk.path) card.append(makeElement("code", "risk-path", risk.path));
    if (risk.recommendation) card.append(makeElement("p", "risk-fix", risk.recommendation));
    if (document.body.dataset.visitorMetrics === "true" && navigator.doNotTrack !== "1"
      && !feedbackShown.has(risk.key)) {
      feedbackShown.add(risk.key);
      const controls = makeElement("div", "signal-feedback");
      const status = makeElement("span", "signal-feedback-status");
      const voteButtons = [];
      controls.append(makeElement("small", "", "Was this signal useful?"));
      [true, false].forEach((useful) => {
        const button = makeElement("button", "ghost-button", useful ? "Yes" : "No");
        button.type = "button";
        button.setAttribute("aria-pressed", "false");
        button.addEventListener("click", async () => {
          button.disabled = true;
          try {
            const response = await fetch("/api/signal-feedback", {
              method: "POST",
              headers: { "Content-Type": "application/json", "X-QNode-Feedback": "1" },
              credentials: "same-origin",
              body: JSON.stringify({ signal: risk.key, useful }),
            });
            if (!response.ok) throw new Error("Feedback could not be saved.");
            voteButtons.forEach((item) => item.setAttribute("aria-pressed", item === button ? "true" : "false"));
            status.textContent = "Thanks. Your latest vote for this signal category was saved.";
          } catch {
            status.textContent = "Feedback could not be saved. Please try again.";
          } finally {
            button.disabled = false;
          }
        });
        voteButtons.push(button);
        controls.append(button);
      });
      controls.append(status);
      card.append(controls);
    }
    container.append(card);
  });
}

function renderFollowup(data) {
  const list = document.querySelector("#followup-list");
  list.replaceChildren();
  setText("#followup-count", `${data.observed_unresolved} OBSERVED OPEN`);
  const scope = data.complete ? "Complete GitHub thread listing." : "First 200 threads only; counts may be incomplete.";
  const more = data.observed_unresolved > data.threads.length
    ? ` Showing the first ${data.threads.length} unresolved threads.` : "";
  setText("#followup-message", `${scope} ${data.observed_unresolved} unresolved, ${data.observed_resolved} resolved observed.${more} Outdated does not mean addressed.`);
  if (!data.observed_unresolved) {
    list.append(makeElement("p", "section-note", data.complete
      ? "No unresolved review threads were found." : "No unresolved thread appeared in this bounded listing."));
    return;
  }
  data.threads.forEach((thread) => {
    const row = makeElement("article", "insight-row");
    row.append(makeElement("strong", "insight-state", thread.outdated ? "OUTDATED · OPEN" : "OPEN"));
    const link = makeElement("a", "", thread.path);
    link.href = thread.url;
    link.target = "_blank";
    link.rel = "noreferrer";
    row.append(link);
    list.append(row);
  });
}

function renderDelta(delta) {
  const section = document.querySelector("#delta-section");
  const container = document.querySelector("#delta-signals");
  container.replaceChildren();
  section.hidden = !delta || !lastReport?.pull_request;
  if (!delta) return;
  setText("#delta-count", `${delta.changed_path_count} CHANGED PATHS`);
  setText(
    "#delta-summary",
    `Compared with review commit ${delta.baseline_sha.slice(0, 12)} · ${delta.new_signals.length} new and ${delta.resolved_signals.length} resolved QNode signals. A signal is not proof of a code defect.`,
  );
  const changes = [
    ...delta.new_signals.map((signal) => ({ signal, label: "NEW" })),
    ...delta.resolved_signals.map((signal) => ({ signal, label: "RESOLVED" })),
  ];
  if (!changes.length) {
    container.append(makeElement("p", "section-note", "No QNode risk-signal changes since the review. Changed paths still need human review."));
  }
  changes.slice(0, 12).forEach(({ signal, label }) => {
    const card = makeElement("article", `risk-card ${signal.severity}`);
    const header = makeElement("div", "risk-header");
    header.append(makeElement("span", "risk-level", label), makeElement("strong", "", signal.title));
    card.append(header, makeElement("p", "", signal.path || "Pull request-wide signal"));
    container.append(card);
  });
  if (delta.changed_paths.length) {
    container.append(makeElement("p", "section-note", `Changed paths: ${delta.changed_paths.slice(0, 8).join(", ")}${delta.changed_path_count > 8 ? " …" : ""}`));
  }
  const lanes = document.querySelector("#delta-lanes");
  lanes.replaceChildren();
  const maximum = Math.max(1, ...(delta.changed_lanes || []).map((lane) => lane.changed_paths));
  (delta.changed_lanes || []).slice(0, 12).forEach((lane) => {
    const row = makeElement("div", "delta-lane");
    row.append(makeElement("code", "", lane.lane === "." ? "Repository root" : `${lane.lane}/`));
    const track = makeElement("div", "delta-track");
    const bar = makeElement("span", "delta-bar");
    bar.style.width = `${Math.max(4, Math.round(100 * lane.changed_paths / maximum))}%`;
    track.append(bar);
    row.append(track, makeElement("strong", "", `${lane.changed_paths}`));
    lanes.append(row);
  });
}

function contractCard(contract) {
  const card = makeElement("article", `contract-card ${contract.status}`);
  const heading = makeElement("div", "contract-heading");
  heading.append(
    makeElement("strong", "", contract.id),
    makeElement("span", "contract-status", contract.status.toUpperCase()),
  );
  card.append(heading);
  if (contract.reason) card.append(makeElement("p", "contract-reason", contract.reason));
  const flow = makeElement("div", "evidence-flow");
  const trigger = makeElement("div", "evidence-node");
  trigger.append(makeElement("b", "", `CHANGED · ${contract.trigger_count}`));
  contract.trigger_paths.forEach((path) => trigger.append(makeElement("code", "", path)));
  const evidence = makeElement("div", "evidence-node");
  evidence.append(makeElement("b", "", "EXPECTED COMPANIONS"));
  contract.requirements.forEach((item) => {
    const line = makeElement("div", `evidence-requirement ${item.status}`);
    line.append(
      makeElement("span", "", item.status.toUpperCase()),
      makeElement("code", "", `${item.mode === "any" ? "one of: " : ""}${item.patterns.join(" | ")}`),
    );
    item.matched_paths.forEach((path) => line.append(makeElement("small", "", `matched: ${path}`)));
    evidence.append(line);
  });
  const handoff = makeElement("div", "evidence-node");
  handoff.append(
    makeElement("b", "", "DECLARED HANDOFF"),
    makeElement("span", "", contract.owners.length ? contract.owners.join(", ") : "No CODEOWNERS match supplied"),
    makeElement("small", "", `Review lanes: ${contract.lanes.join(", ")}`),
  );
  flow.append(trigger, evidence, handoff);
  card.append(flow);
  return card;
}

function renderContracts(contracts) {
  const section = document.querySelector("#contract-section");
  const container = document.querySelector("#contract-list");
  container.replaceChildren();
  section.hidden = !lastReport?.pull_request || !contracts.length;
  setText("#contract-count", `${contracts.length} ${contracts.length === 1 ? "RULE" : "RULES"}`);
  contracts.forEach((contract) => container.append(contractCard(contract)));
}

function renderReviewMap(lanes) {
  const section = document.querySelector("#review-map-section");
  const container = document.querySelector("#review-lanes");
  container.replaceChildren();
  section.hidden = !lastReport?.pull_request;
  const delta = lastReport?.audit.review_delta;
  const changed = new Set(delta?.changed_paths || []);
  const sourcePath = (path) => /\.(?:py|js|jsx|ts|tsx|go|rs|java|kt|c|cc|cpp|h|hpp|cs|rb|php|swift|scala)$/.test(path)
    && !/(?:^|\/)(?:tests?|__tests__|specs?|fixtures?)\//.test(path)
    && !/(?:test|spec)\.[^.]+$/.test(path);
  const generatedPath = (path) => /(?:^|\/)(?:generated|gen|dist|build|vendor|node_modules)\//i.test(path)
    || /(?:\.min\.(?:js|css)|\.g\.(?:py|go)|\.generated\.)/i.test(path);
  const visible = lanes.map((lane) => ({ ...lane, visiblePaths: lane.paths.filter((path) =>
    reviewFocus === "all" || (reviewFocus === "source" && sourcePath(path))
      || (reviewFocus === "generated" && !generatedPath(path))
      || (reviewFocus === "review" && changed.has(path)),
  ) })).filter((lane) => lane.visiblePaths.length);
  setText("#lane-count", `${visible.length}/${lanes.length} LANES`);
  setText("#focus-message", reviewFocus === "review" && !delta
    ? "No complete submitted-review comparison is available for this PR."
    : reviewFocus === "review" && !visible.length
      ? "No file in the current PR appears in the since-review tree difference. Other repository paths may still have changed."
      : `${visible.reduce((count, lane) => count + lane.visiblePaths.length, 0)} visible paths. Filters affect the display only; signals and exported evidence remain unchanged.`);
  if (!visible.length) {
    container.append(makeElement("p", "section-note", "No paths match this display filter."));
  }

  visible.forEach((lane) => {
    const card = makeElement("article", `review-lane ${lane.attention}`);
    const header = makeElement("div", "lane-header");
    header.append(
      makeElement("strong", "", lane.label),
      makeElement("span", "lane-attention", lane.attention.toUpperCase()),
    );
    const metrics = makeElement(
      "p",
      "lane-metrics",
      `${lane.visiblePaths.length}/${lane.file_count} visible files · full lane +${lane.additions} / −${lane.deletions}`,
    );
    const focus = makeElement(
      "p",
      "lane-focus",
      lane.signals.length ? lane.signals.join(" · ") : "Standard review",
    );
    const ownership = makeElement(
      "p",
      `lane-owners${lane.unowned_files ? " incomplete" : ""}`,
      lane.owners.length
        ? `Route to ${lane.owners.join(", ")}${lane.unowned_files ? ` · ${lane.unowned_files} unowned` : ""}`
        : `No CODEOWNERS match · ${lane.unowned_files} unowned`,
    );
    const testEvidence = makeElement(
      "p",
      `lane-tests${lane.source_files && lane.test_path_matches < lane.source_files ? " incomplete" : ""}`,
      lane.source_files
        ? `Changed test-path matches: ${lane.test_path_matches}/${lane.source_files} source files (not a coverage result)`
        : "No source-file test match needed for this lane",
    );
    const questions = makeElement("ul", "lane-questions");
    (lane.review_questions || []).forEach((question) => {
      questions.append(makeElement("li", "", question));
    });
    const paths = makeElement("div", "lane-paths");
    lane.visiblePaths.slice(0, 30).forEach((path) => paths.append(makeElement("code", "", path)));
    if (lane.visiblePaths.length > 30) paths.append(makeElement("small", "", `${lane.visiblePaths.length - 30} more visible paths in JSON export`));
    const targets = makeElement("p", "lane-tests", lane.test_targets?.length
      ? `Candidate test targets: ${lane.test_targets.join(", ")}`
      : "No existing same-lane test target detected");
    const jobs = makeElement("p", "lane-tests", lane.configured_jobs?.length
      ? `Configured CI jobs: ${lane.configured_jobs.join(", ")}`
      : "No CI job mapping configured");
    card.append(header, metrics, focus, ownership, testEvidence, targets, jobs, questions, paths);
    container.append(card);
  });
}

function renderCi(evidence) {
  const section = document.querySelector("#ci-section");
  const container = document.querySelector("#ci-list");
  container.replaceChildren();
  section.hidden = !lastReport?.pull_request;
  if (!lastReport?.pull_request) return;
  if (!evidence?.available) {
    setText("#ci-count", "UNAVAILABLE");
    setText("#ci-summary", "GitHub check-run evidence was unavailable. QNode cannot infer whether tests ran.");
    return;
  }
  setText("#ci-count", `${evidence.observed.length} OBSERVED`);
  setText("#ci-summary", `${evidence.complete ? "Complete latest-check listing" : "First 100 latest checks only; listing incomplete"}. Configured job labels are hints, not required-check or test-execution proof.`);
  evidence.observed.forEach((run) => {
    const row = makeElement("div", `insight-row ${run.state}`);
    row.append(makeElement("span", "insight-state", run.state.toUpperCase()));
    const title = makeElement("strong", "", run.name || "Unnamed check");
    if (run.html_url && /^https:\/\//.test(run.html_url)) {
      const link = makeElement("a", "", title.textContent);
      link.href = run.html_url;
      link.target = "_blank";
      link.rel = "noreferrer";
      row.append(link);
    } else row.append(title);
    if (run.configured) row.append(makeElement("small", "", "Mapped in .qnode.json"));
    container.append(row);
  });
  evidence.not_observed.forEach((name) => {
    const row = makeElement("div", "insight-row unknown");
    row.append(makeElement("span", "insight-state", "NOT OBSERVED"), makeElement("strong", "", name));
    container.append(row);
  });
  if (!evidence.observed.length && !evidence.not_observed.length) {
    container.append(makeElement("p", "section-note", "No check runs were returned for this commit."));
  }
}

function renderHandoff(handoff) {
  const section = document.querySelector("#handoff-section");
  const facts = document.querySelector("#handoff-facts");
  const questions = document.querySelector("#handoff-questions");
  const lanes = document.querySelector("#handoff-lanes");
  facts.replaceChildren();
  questions.replaceChildren();
  lanes.replaceChildren();
  section.hidden = !lastReport?.pull_request || !handoff;
  if (section.hidden) return;
  setText("#handoff-count", `${handoff.total_lanes} ${handoff.total_lanes === 1 ? "LANE" : "LANES"}`);
  handoff.facts.forEach((fact) => facts.append(makeElement("li", "", fact)));
  handoff.questions.slice(0, 12).forEach((question) => questions.append(makeElement("li", "", question)));
  handoff.lanes.slice(0, 8).forEach((lane) => {
    const card = makeElement("article", `handoff-lane ${lane.attention}`);
    card.append(makeElement("strong", "", `${lane.label} · ${lane.files} ${lane.files === 1 ? "file" : "files"}`));
    card.append(makeElement("p", "", lane.owners.length
      ? `Declared owners: ${lane.owners.join(", ")}${lane.unowned_files ? ` · ${lane.unowned_files} paths unowned` : ""}`
      : "No declared CODEOWNERS match"));
    card.append(makeElement("p", "", lane.source_files
      ? `Changed test-path matches: ${lane.test_path_matches}/${lane.source_files} source files; not coverage.`
      : "No changed source file needs a test-path match in this lane."));
    card.append(makeElement("p", "", lane.jobs.length
      ? `Mapped checks: ${lane.jobs.map((job) => `${job.name} (${job.states.join("/")})`).join(", ")}`
      : "No CI job mapping configured; test execution is unknown."));
    lanes.append(card);
  });
  if (handoff.total_lanes > 8) {
    lanes.append(makeElement("p", "section-note", `${handoff.total_lanes - 8} more lanes in the JSON export.`));
  }
}

function renderComparison(comparison) {
  const container = document.querySelector("#compare-results");
  container.replaceChildren();
  [comparison.base, comparison.head].forEach((point) => {
    const row = makeElement("div", "compare-row");
    row.append(makeElement("code", "", point.ref), makeElement("strong", "", `${point.score}/100 · ${point.grade}`));
    const track = makeElement("div", "compare-track");
    const bar = makeElement("span", "compare-bar");
    bar.style.width = `${point.score}%`;
    track.append(bar);
    row.append(track);
    container.append(row);
  });
  container.append(makeElement("p", "section-note", `Score change: ${comparison.score_delta > 0 ? "+" : ""}${comparison.score_delta} points. ${comparison.note}`));
  comparison.changed_checks.forEach((check) => container.append(makeElement("p", "section-note", `${check.after ? "Gained" : "Lost"}: ${check.label}`)));
}

function renderCompanions(suggestions) {
  const section = document.querySelector("#companion-section");
  const container = document.querySelector("#companions");
  container.replaceChildren();
  section.hidden = !lastReport?.pull_request;
  setText("#companion-count", suggestions.length ? `${suggestions.length} SUGGESTED` : "COMPLETE");

  if (!suggestions.length) {
    const empty = makeElement("article", "companion-card complete");
    empty.append(
      makeElement("strong", "", "No obvious companion changes missing"),
      makeElement("p", "", "Changed source files have matching tests, and dependency manifests have recognized lockfile updates."),
    );
    container.append(empty);
    return;
  }

  suggestions.forEach((suggestion) => {
    const card = makeElement("article", "companion-card");
    const header = makeElement("div", "companion-header");
    header.append(
      makeElement("span", "companion-action", suggestion.action.toUpperCase()),
      makeElement("strong", "", suggestion.kind === "test" ? "Focused test" : "Dependency lock"),
    );
    card.append(
      header,
      makeElement("code", "companion-path", suggestion.suggested_path),
      makeElement("p", "", `For ${suggestion.source_path}`),
      makeElement("p", "companion-reason", suggestion.reason),
    );
    container.append(card);
  });
}

function renderPullRequest(pull) {
  const summary = document.querySelector("#pull-summary");
  summary.hidden = !pull;
  if (!pull) return;
  const title = document.querySelector("#pull-title");
  title.replaceChildren();
  const link = makeElement("a", "", `#${pull.number} · ${pull.title}`);
  link.href = pull.html_url;
  link.target = "_blank";
  link.rel = "noreferrer";
  title.append(link);
  setText("#pull-state", pull.draft ? "DRAFT" : pull.state.toUpperCase());
  setText("#pull-files", `${pull.changed_files} ${pull.changed_files === 1 ? "FILE" : "FILES"}`);
  setText("#pull-lines", `+${pull.additions.toLocaleString()} / −${pull.deletions.toLocaleString()}`);
}

function renderReport(data) {
  lastReport = data;
  const { repository, audit } = data;
  setText("#score", audit.score);
  setText("#report-grade", `GRADE ${audit.grade}`);
  setText("#report-ref", data.pull_request ? `PR #${data.pull_request.number}` : data.ref);
  setText("#report-description", repository.description || "No repository description provided.");
  setText("#report-language", repository.language || "Language —");
  setText("#report-paths", `${data.scanned_paths.toLocaleString()} paths`);
  setText("#report-updated", formatDate(repository.updated_at));
  setText("#passed-count", `${audit.passed}/${audit.total}`);
  setText("#cache-state", data.cached ? "CACHED" : "LIVE");

  const link = document.querySelector("#report-link");
  link.textContent = repository.full_name;
  link.href = repository.html_url;
  link.target = "_blank";
  link.rel = "noreferrer";

  document.querySelector("#score-orbit").style.setProperty("--score", `${audit.score * 3.6}deg`);
  document.querySelector("#truncated-warning").hidden = !audit.tree_truncated;
  document.querySelector("#files-truncated-warning").hidden = !audit.files_truncated;
  const policyWarning = document.querySelector("#policy-warning");
  policyWarning.textContent = audit.policy_warning || "";
  policyWarning.hidden = !audit.policy_warning;
  const ignoredNote = document.querySelector("#ignored-note");
  ignoredNote.textContent = audit.ignored_files
    ? `${audit.ignored_files} changed file(s) excluded from heuristic warnings by .qnode.json. Credential-like and critical paths are still flagged.`
    : "";
  ignoredNote.hidden = !audit.ignored_files;
  renderChecks(audit.checks);
  renderRecommendations(audit.recommendations);
  renderPullRequest(data.pull_request);
  renderRisks(audit.risks);
  renderDelta(audit.review_delta);
  renderCi(data.ci_evidence);
  renderHandoff(data.review_handoff);
  const followupSection = document.querySelector("#followup-section");
  followupSection.hidden = !data.pull_request;
  document.querySelector("#followup-list").replaceChildren();
  setText("#followup-count", "ON DEMAND");
  setText("#followup-message", "");
  renderContracts(audit.change_contracts || []);
  renderCompanions(audit.companion_suggestions || []);
  renderReviewMap(audit.review_map || []);
  document.querySelector("#compare-base").value = data.pull_request?.base_sha || repository.default_branch || "";
  document.querySelector("#compare-head").value = data.pull_request?.head_sha || data.ref || "";
  document.querySelector("#compare-results").replaceChildren();
  setText("#compare-message", "");
  report.hidden = false;
  report.scrollIntoView({ behavior: "smooth", block: "start" });
}

document.querySelectorAll("[data-focus]").forEach((button) => {
  button.addEventListener("click", () => {
    reviewFocus = button.dataset.focus;
    document.querySelectorAll("[data-focus]").forEach((item) => {
      item.classList.toggle("active", item === button);
      item.setAttribute("aria-pressed", item === button ? "true" : "false");
    });
    if (lastReport) renderReviewMap(lastReport.audit.review_map || []);
  });
});

document.querySelector("#attention-button").addEventListener("click", async () => {
  const target = parseTarget(repositoryInput.value);
  if (!target) {
    formMessage.textContent = "Enter a public owner/repository first.";
    return;
  }
  const section = document.querySelector("#attention-section");
  const container = document.querySelector("#attention-list");
  const button = document.querySelector("#attention-button");
  section.hidden = false;
  container.replaceChildren();
  setText("#attention-message", "Loading recent open PRs…");
  button.disabled = true;
  try {
    const response = await fetch(`/api/attention?${new URLSearchParams({ repository: target.repository })}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Attention signals unavailable.");
    setText("#attention-message", data.items.length ? data.scope : "No open PRs in this repository.");
    data.items.forEach((item) => {
      const row = makeElement("article", "insight-row");
      const link = makeElement("a", "", `#${item.number} · ${item.title}`);
      link.href = item.html_url;
      link.target = "_blank";
      link.rel = "noreferrer";
      row.append(link, makeElement("small", "", item.signals.join(" · ") || "No attention signal observed"));
      container.append(row);
    });
  } catch (error) {
    setText("#attention-message", error.message);
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#compare-button").addEventListener("click", async () => {
  if (!lastReport) return;
  const repository = lastReport.repository.full_name;
  const base = document.querySelector("#compare-base").value.trim();
  const head = document.querySelector("#compare-head").value.trim();
  const button = document.querySelector("#compare-button");
  setText("#compare-message", "Comparing refs…");
  button.disabled = true;
  try {
    const response = await fetch(`/api/compare?${new URLSearchParams({ repository, base, head })}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Comparison unavailable.");
    renderComparison(data.comparison);
    setText("#compare-message", "Comparison complete.");
  } catch (error) {
    document.querySelector("#compare-results").replaceChildren();
    setText("#compare-message", error.message);
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#followup-button").addEventListener("click", async () => {
  if (!lastReport?.pull_request) return;
  const repository = lastReport.repository.full_name;
  const pull = lastReport.pull_request.number;
  const button = document.querySelector("#followup-button");
  setText("#followup-message", "Loading review threads…");
  button.disabled = true;
  try {
    const response = await fetch(`/api/review-followup?${new URLSearchParams({ repository, pull })}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Review threads unavailable.");
    if (lastReport?.repository.full_name === repository && lastReport?.pull_request?.number === pull) {
      renderFollowup(data);
    }
  } catch (error) {
    document.querySelector("#followup-list").replaceChildren();
    setText("#followup-message", error.message);
  } finally {
    button.disabled = false;
  }
});

function reportUrl(target) {
  const url = new URL(window.location.href);
  url.search = "";
  url.searchParams.set("repository", target.repository);
  if (target.pull) url.searchParams.set("pull", target.pull);
  url.hash = "scanner";
  return url;
}

async function copyText(text, successMessage) {
  await navigator.clipboard.writeText(text);
  actionMessage.textContent = successMessage;
  window.setTimeout(() => { actionMessage.textContent = ""; }, 2500);
}

async function runAudit(event) {
  if (event) event.preventDefault();
  formMessage.textContent = "";
  actionMessage.textContent = "";
  const target = parseTarget(repositoryInput.value);
  if (!target) {
    formMessage.textContent = "Enter owner/repository, owner/repository#42, or a GitHub pull-request URL.";
    repositoryInput.focus();
    return;
  }

  scanButton.disabled = true;
  scanButton.classList.add("loading");
  try {
    const query = new URLSearchParams({ repository: target.repository });
    if (target.pull) query.set("pull", target.pull);
    const response = await fetch(`/api/audit?${query}`, { headers: { Accept: "application/json" } });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "The audit could not be completed.");
    repositoryInput.value = target.pull ? `${target.repository}#${target.pull}` : target.repository;
    window.history.replaceState({}, "", reportUrl(target));
    renderReport(data);
  } catch (error) {
    formMessage.textContent = error.message;
  } finally {
    scanButton.disabled = false;
    scanButton.classList.remove("loading");
  }
}

document.querySelector("#share-report").addEventListener("click", async () => {
  if (lastReport) {
    await copyText(window.location.href, "Report link copied.");
    recordEvent("share_report");
  }
});

document.querySelector("#copy-markdown").addEventListener("click", async () => {
  if (lastReport) {
    await copyText(lastReport.audit.markdown, "Markdown copied.");
    recordEvent("copy_markdown");
  }
});

document.querySelector("#download-json").addEventListener("click", () => {
  if (!lastReport) return;
  const blob = new Blob([JSON.stringify(lastReport, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${lastReport.repository.full_name.replace("/", "-")}-qnode-report.json`;
  link.click();
  URL.revokeObjectURL(url);
  actionMessage.textContent = "JSON downloaded.";
  recordEvent("download_json");
});

document.querySelector("#copy-handoff").addEventListener("click", async () => {
  if (lastReport?.review_handoff) {
    await copyText(lastReport.review_handoff.markdown, "Editable review handoff copied.");
    recordEvent("copy_handoff");
  }
});

document.querySelector("#star-qnode").addEventListener("click", () => recordEvent("star"));
document.querySelector("#use-qnode-action").addEventListener("click", () => recordEvent("use_action"));

document.querySelector("#preview-button").addEventListener("click", async () => {
  const message = document.querySelector("#preview-message");
  const results = document.querySelector("#preview-results");
  results.replaceChildren();
  message.textContent = "";
  let policy;
  try {
    policy = JSON.parse(document.querySelector("#preview-policy").value);
  } catch {
    message.textContent = "The policy is not valid JSON.";
    return;
  }
  const changedPaths = document.querySelector("#preview-paths").value
    .split(/\r?\n/).map((path) => path.trim()).filter(Boolean);
  try {
    const response = await fetch("/api/policy-preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ policy, changed_paths: changedPaths }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Preview unavailable.");
    message.textContent = data.change_contracts.length
      ? `${data.change_contracts.length} rule(s) matched these changed paths.`
      : "No declared rule matched these changed paths.";
    data.change_contracts.forEach((contract) => results.append(contractCard(contract)));
  } catch (error) {
    message.textContent = error.message;
  }
});

if (document.body.dataset.publicAudit === "true") {
  form.addEventListener("submit", runAudit);
  const params = new URLSearchParams(window.location.search);
  const repository = params.get("repository");
  const pull = params.get("pull");
  if (repository) {
    repositoryInput.value = pull ? `${repository}#${pull}` : repository;
    runAudit();
  }
} else {
  repositoryInput.disabled = true;
  scanButton.disabled = true;
  formMessage.textContent = "Public scanning is disabled on this deployment.";
}

if (document.body.dataset.visitorMetrics === "true" && navigator.doNotTrack !== "1") {
  fetch("/api/visit", {
    method: "POST",
    headers: { "X-QNode-Visit": "1" },
    credentials: "same-origin",
    keepalive: true,
  }).catch(() => {});
}
