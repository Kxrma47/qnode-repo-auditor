const form = document.querySelector("#audit-form");
const repositoryInput = document.querySelector("#repository");
const scanButton = document.querySelector("#scan-button");
const formMessage = document.querySelector("#form-message");
const report = document.querySelector("#report");
const actionMessage = document.querySelector("#action-message");
let lastReport = null;

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
    container.append(card);
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
}

function renderReviewMap(lanes) {
  const section = document.querySelector("#review-map-section");
  const container = document.querySelector("#review-lanes");
  container.replaceChildren();
  section.hidden = !lastReport?.pull_request;
  setText("#lane-count", `${lanes.length} ${lanes.length === 1 ? "LANE" : "LANES"}`);

  lanes.forEach((lane) => {
    const card = makeElement("article", `review-lane ${lane.attention}`);
    const header = makeElement("div", "lane-header");
    header.append(
      makeElement("strong", "", lane.label),
      makeElement("span", "lane-attention", lane.attention.toUpperCase()),
    );
    const metrics = makeElement(
      "p",
      "lane-metrics",
      `${lane.file_count} ${lane.file_count === 1 ? "file" : "files"} · +${lane.additions} / −${lane.deletions}`,
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
    lane.paths.forEach((path) => paths.append(makeElement("code", "", path)));
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
  setText("#pull-files", `${pull.changed_files} FILES`);
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
  renderCompanions(audit.companion_suggestions || []);
  renderReviewMap(audit.review_map || []);
  report.hidden = false;
  report.scrollIntoView({ behavior: "smooth", block: "start" });
}

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
  if (lastReport) await copyText(window.location.href, "Report link copied.");
});

document.querySelector("#copy-markdown").addEventListener("click", async () => {
  if (lastReport) await copyText(lastReport.audit.markdown, "Markdown copied.");
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
