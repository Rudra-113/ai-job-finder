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
    const queueNode = document.getElementById("queue-size");
    if (queueNode) queueNode.textContent = data.queue_size || 0;
    document.getElementById("qualified").textContent = data.qualified || 0;
    document.getElementById("needs-review").textContent = data.needs_review || 0;
    document.getElementById("filled").textContent = data.filled || 0;
    document.getElementById("submitted").textContent = data.submitted;
    document.getElementById("skipped").textContent = data.skipped || 0;
    document.getElementById("failed").textContent = data.failed;
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
