function textList(items) {
  if (!items || !items.length) return `<p class="hint">Not stated.</p>`;
  return `<ul class="clean">${items.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>`;
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

async function startOpportunity() {
  const session = await bootShell();
  if (!session) return;
  const id = new URLSearchParams(window.location.search).get("id") || "";
  const root = document.getElementById("detail");
  try {
    const card = await api(`/api/opportunities/${encodeURIComponent(id)}`);
    const href = card.apply_url || "";
    const safe = href.startsWith("http://") || href.startsWith("https://") ? href : "";
    root.innerHTML = `
      <p class="match" style="--score: ${esc(card.match_score)}">${esc(card.match_score)}% match</p>
      <h1>${esc(card.role)}</h1>
      <p>${esc(card.company)}</p>
      <p class="meta">${esc(card.work_mode)} · ${esc(card.location || "Location not stated")} · ${esc(card.compensation)}</p>
      <p class="meta">Posted ${esc(card.posted || "date not listed")} · Availability ${esc(card.availability)}</p>
      <p>Found on ${esc((card.sources || []).join(" · ") || card.source || "")}</p>
      ${card.employment ? `<p>Job type: ${esc(card.employment)}</p>` : ""}
      ${card.experience ? `<p>Experience: ${esc(card.experience)}</p>` : ""}
      ${card.deadline ? `<p>Deadline: ${esc(card.deadline)}</p>` : ""}
      <h2>Why this matches</h2>
      ${card.why && card.why.length ? `<ul class="clean">${card.why.map((item) => `<li>✓ ${esc(item)}</li>`).join("")}</ul>` : `<p class="hint">No skill from your profile was found in the listing text.</p>`}
      <h2>Potential gaps</h2>
      ${card.gaps && card.gaps.length ? `<ul class="clean">${card.gaps.map((item) => `<li>△ ${esc(item)}</li>`).join("")}</ul>` : `<p class="hint">No extra requirement in the listing was clearly missing from your profile.</p>`}
      <h2>Required skills</h2>${textList(card.required_skills)}
      <h2>Preferred skills</h2>${textList(card.preferred_skills)}
      <h2>Responsibilities</h2>${textList(card.responsibilities)}
      <h2>Description</h2>
      <p>${esc(card.description || "The listing did not include a description.")}</p>
      <h2>Direct application link</h2>
      ${safe ? `<p class="direct-link"><span>Apply here</span><a href="${esc(safe)}" target="_blank" rel="noopener noreferrer">${esc(safe)}</a></p>${card.official_verified ? "" : `<p class="hint">This is the listing’s own application page. A separate company careers link was not verified.</p>`}` : `<p class="hint">This listing did not include an application link.</p>`}
      <div class="button-row">
        ${safe ? `<a class="button-link" href="${esc(safe)}" target="_blank" rel="noopener noreferrer">${esc(card.apply_label || "Apply")}</a>` : ""}
        <a class="button-link secondary" href="dashboard.html">Back to results</a>
      </div>`;
  } catch (error) {
    root.innerHTML = `<h1>Opportunity</h1><p>That opportunity is not in the current results.</p><p><a href="dashboard.html">Back to results</a></p>`;
  }
}

startOpportunity();
