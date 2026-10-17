const root = document.querySelector("#status-line");
if (root) {
  const csrf = document.querySelector('meta[name="csrf"]').content;

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[ch]));
  }

  function safeUrl(url) {
    try {
      const parsed = new URL(url);
      if (parsed.protocol === "http:" || parsed.protocol === "https:") {
        return esc(parsed.href);
      }
    } catch (error) {
      return "";
    }
    return "";
  }

  function setHtml(id, html) {
    const node = document.getElementById(id);
    if (!node || node.dataset.raw === html) return;
    node.innerHTML = html;
    node.dataset.raw = html;
  }

  function render(data) {
    document.getElementById("status-line").textContent = data.status_line || "";
    document.getElementById("search-status").textContent = data.search_status || "stopped";
    document.getElementById("found").textContent = data.found;
    const rejected = document.getElementById("rejected");
    if (rejected) rejected.textContent = data.rejected || 0;
    const queueNode = document.getElementById("queue-size");
    if (queueNode) queueNode.textContent = data.queue_size || 0;
    document.getElementById("qualified").textContent = data.qualified || 0;
    document.getElementById("needs-review").textContent = data.needs_review || 0;
    document.getElementById("filled").textContent = data.filled || 0;
    document.getElementById("submitted").textContent = data.submitted;
    document.getElementById("skipped").textContent = data.skipped || 0;
    document.getElementById("failed").textContent = data.failed;
    const analyzed = document.getElementById("analyzed");
    if (analyzed) analyzed.textContent = data.analyzed || 0;
    const active = document.getElementById("active");
    if (active) active.textContent = data.active || 0;
    const duplicates = document.getElementById("duplicates");
    if (duplicates) duplicates.textContent = data.duplicates || 0;
    const finalCount = document.getElementById("final-count");
    if (finalCount) finalCount.textContent = data.final_count || 0;
    const current = data.current;
    const currentNode = document.getElementById("current");
    if (currentNode && !(document.activeElement && currentNode.contains(document.activeElement))) {
      if (!current) {
        setHtml("current", "");
      } else {
        const href = safeUrl(current.url);
        const link = href ? `<p><a href="${href}" rel="noopener noreferrer">${href}</a></p>` : "";
        const lines = (items, title) => items && items.length ? `<p>${title}: ${items.map(esc).join("; ")}</p>` : "";
        setHtml("current", `<h2>Current application</h2><article class="note"><p><strong>${esc(current.company)}</strong> — ${esc(current.role)}</p><p>Match score ${esc(current.match_score)} · Pay ${esc(current.compensation)} · ${esc(current.location)} · Posted ${esc(current.posted || "date not listed")}</p>${link}${lines(current.filled, "Fields filled")}${lines(current.answered, "Questions answered")}${lines(current.needs_input, "Needs your input")}</article>`);
      }
    }
    document.getElementById("start-form").hidden = !!data.running;
    document.getElementById("stop-form").hidden = !data.running;

    const reasons = Object.entries(data.rejection_counts || {});
    setHtml("reasons", reasons.length
      ? `<h2>Why listings were skipped</h2><ul>${reasons.map(([reason, count]) => `<li>${esc(reason)}: ${esc(count)}</li>`).join("")}</ul>`
      : "");

    const attempts = data.attempts || [];
    setHtml("attempts", attempts.length
      ? `<h2>Recent application attempts</h2><ul>${attempts.map((item) => `<li>${esc(item.company)} — ${esc(item.role)} — ${esc(item.status)}${item.reason ? ` — ${esc(item.reason)}` : ""}</li>`).join("")}</ul>`
      : "");

    const failures = data.failures || [];
    setHtml("failures", failures.length
      ? `<h2>Failed this run</h2><ul>${failures.map((item) => `<li>${esc(item.company)} — ${esc(item.role)} — ${esc(item.reason)}</li>`).join("")}</ul>`
      : "");

    const attention = data.attention || [];
    setHtml("attention", attention.length ? `<h2>Needs you</h2>${attention.map((row) => {
      const href = safeUrl(row.url);
      const link = href ? `<p><a href="${href}" rel="noopener noreferrer">Application page</a></p>` : "";
      const shot = row.screenshot ? `<p class="hint">Screenshot: ${esc(row.screenshot)}</p>` : "";
      return `<article class="note"><strong>${esc(row.company)} — ${esc(row.role)}</strong><p>${esc(row.reason)}</p>${link}${shot}
        <div class="actions">
          <form method="post" action="/attention/${esc(row.id)}/retry"><input type="hidden" name="csrf" value="${esc(csrf)}"><button type="submit">Try again</button></form>
          <form method="post" action="/attention/${esc(row.id)}/dismiss"><input type="hidden" name="csrf" value="${esc(csrf)}"><button class="secondary" type="submit">Don't apply</button></form>
        </div></article>`;
    }).join("")}` : "");

    const sourceNode = document.getElementById("sources");
    const sourceRows = data.source_report || [];
    if (sourceNode) {
      setHtml("sources", sourceRows.length
        ? `<h2>Sources searched</h2><ul>${sourceRows.map((row) => `<li>${esc(row.name)}: ${row.status === "ok" ? `${esc(row.count)} listings` : row.status === "unavailable" ? "Unavailable / not accessible" : "No public listings"}</li>`).join("")}</ul>`
        : "");
    }
    const oppNode = document.getElementById("opportunities");
    const cards = data.opportunities || [];
    if (oppNode && !oppNode.querySelector("input:checked") && !(document.activeElement && oppNode.contains(document.activeElement))) {
      const body = cards.map((card) => {
        const official = card.official_verified && safeUrl(card.official_url);
        const listing = safeUrl(card.url);
        const link = official
          ? `<p><a href="${official}" rel="noopener noreferrer">Open official application</a></p>`
          : `<p>Official application link could not be verified.${listing ? ` <a href="${listing}" rel="noopener noreferrer">Open listing</a>` : ""}</p>`;
        const why = (card.why || []).map((item) => `✓ ${esc(item)}`).join(" ");
        return `<article class="note"><h3>${esc(card.role)}</h3><p>Company: ${esc(card.company)}</p><p>Match: ${esc(card.match_score)}%</p><p>Source: ${esc((card.sources || []).join(" + "))}</p><p>Location: ${esc(card.location || "Not stated")}</p><p>Work mode: ${esc(card.work_mode)}</p><p>Stipend: ${esc(card.compensation)}</p><p>Posted: ${esc(card.posted || "date not listed")}</p><p>Availability: ${esc(card.availability)}</p>${why ? `<p>Why it matches: ${why}</p>` : ""}<p>Application: ${esc(card.application)}</p>${link}<label class="check"><input type="checkbox" name="job_id" value="${esc(card.id)}"> Select</label> <button type="submit" name="apply_one" value="${esc(card.id)}">Apply directly</button></article>`;
      }).join("");
      setHtml("opportunities", cards.length
        ? `<h2>Opportunities</h2><form method="post" action="/opportunities/apply"><input type="hidden" name="csrf" value="${esc(csrf)}">${body}<button type="submit">Apply to selected</button></form>`
        : "");
    }

    const rows = data.applications || [];
    const body = rows.length
      ? rows.map((row) => {
          const href = safeUrl(row.url);
          const link = href ? `<a href="${href}" rel="noopener noreferrer">${href}</a>` : "";
          return `<tr><td>${esc(row.company)}</td><td>${esc(row.role)}</td><td>${esc(row.date)}</td><td>${link}</td><td>${esc(row.match_score)}</td><td>${esc(row.resume || "")}</td><td>${esc(row.status)}</td></tr>`;
        }).join("")
      : `<tr><td colspan="7">No applications submitted yet.</td></tr>`;
    setHtml("applications", body);
  }

  async function refresh() {
    try {
      const response = await fetch("/api/status");
      if (!response.ok) return;
      render(await response.json());
    } catch (error) {
      return;
    }
  }

  window.setInterval(refresh, 2000);
}
