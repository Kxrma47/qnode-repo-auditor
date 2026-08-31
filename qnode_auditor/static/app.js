const form = document.querySelector("#audit-form");
const repositoryInput = document.querySelector("#repository");
const scanButton = document.querySelector("#scan-button");
const formMessage = document.querySelector("#form-message");
const report = document.querySelector("#report");

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

function renderReport(data) {
  const { repository, audit } = data;
  setText("#score", audit.score);
  setText("#report-grade", `GRADE ${audit.grade}`);
  setText("#report-ref", data.ref);
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
  renderChecks(audit.checks);
  renderRecommendations(audit.recommendations);
  report.hidden = false;
  report.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function runAudit(event) {
  event.preventDefault();
  formMessage.textContent = "";
  const repository = repositoryInput.value.trim();
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repository)) {
    formMessage.textContent = "Enter a repository as owner/name.";
    repositoryInput.focus();
    return;
  }

  scanButton.disabled = true;
  scanButton.classList.add("loading");
  try {
    const response = await fetch(`/api/audit?repository=${encodeURIComponent(repository)}`, {
      headers: { Accept: "application/json" },
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "The audit could not be completed.");
    renderReport(data);
  } catch (error) {
    formMessage.textContent = error.message;
  } finally {
    scanButton.disabled = false;
    scanButton.classList.remove("loading");
  }
}

if (document.body.dataset.publicAudit === "true") {
  form.addEventListener("submit", runAudit);
} else {
  repositoryInput.disabled = true;
  scanButton.disabled = true;
  formMessage.textContent = "Public scanning is disabled on this deployment.";
}
