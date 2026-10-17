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
    document.getElementById("found").textContent = data.found;
    document.getElementById("rejected").textContent = data.rejected;
    document.getElementById("submitted").textContent = data.submitted;
    document.getElementById("failed").textContent = data.failed;
    document.getElementById("start-form").hidden = !!data.running;
    document.getElementById("stop-form").hidden = !data.running;

    const reasons = Object.entries(data.rejection_counts || {});
    setHtml("reasons", reasons.length
      ? `<h2>Why listings were skipped</h2><ul>${reasons.map(([reason, count]) => `<li>${esc(reason)}: ${esc(count)}</li>`).join("")}</ul>`
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
          return `<tr><td>${esc(row.company)}</td><td>${esc(row.role)}</td><td>${esc(row.date)}</td><td>${link}</td><td>${esc(row.match_score)}</td><td>${esc(row.status)}</td></tr>`;
        }).join("")
      : `<tr><td colspan="6">No applications submitted yet.</td></tr>`;
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
