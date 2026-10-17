const root = document.querySelector("#status-line");
if (root) {
  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[ch]));
  }
  function safeUrl(url) {
    try {
      const parsed = new URL(url, window.location.origin);
      if (parsed.protocol === "http:" || parsed.protocol === "https:") return esc(parsed.href);
    } catch (error) {
      return "";
    }
    return "";
  }
  function render(data) {
    const status = document.getElementById("status-line");
    status.textContent = data.status_line || "";
    status.classList.toggle("live", Boolean(data.running));
    const map = {
      discovered: data.discovered,
      analyzed: data.analyzed,
      active: data.active,
      strong: data.strong_matches,
      "final-count": data.final_count,
    };
    Object.entries(map).forEach(([id, value]) => {
      const node = document.getElementById(id);
      if (node) node.textContent = value || 0;
    });
    const stop = document.getElementById("stop-form");
    if (stop) stop.hidden = !data.running;
    const loading = document.getElementById("loading");
    if (loading) loading.hidden = !data.running;
    const sources = document.getElementById("sources");
    const rows = data.source_report || [];
    if (sources) {
      sources.innerHTML = rows.length
        ? `<h2>Sources searched</h2><ul class="clean">${rows.map((row) => `<li>${esc(row.name)}: ${row.status === "ok" ? `${esc(row.count)} listings` : row.status === "unavailable" ? "Unavailable" : "No public listings"}</li>`).join("")}</ul>`
        : "";
    }
    const board = document.getElementById("opportunities");
    if (!board || data.running) return;
    const cards = data.opportunities || [];
    const heading = data.relaxed ? "closest opportunities" : "best opportunities";
    board.innerHTML = cards.length ? `<h2>${esc(data.final_count)} ${heading}</h2><div class="grid">${cards.map((card) => {
      const href = safeUrl(card.apply_url || card.official_url || card.url);
      const label = esc(card.apply_label || "Apply");
      const link = href
        ? `<p class="direct-link"><span>Apply here</span><a href="${href}" target="_blank" rel="noopener noreferrer">${href}</a></p>`
        : "";
      const button = href
        ? `<a class="button-link" href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>`
        : "";
      const why = (card.why || []).map((item) => `✓ ${esc(item)}`).join(" ");
      const gaps = (card.gaps || []).map((item) => `△ ${esc(item)}`).join(" ");
      const note = card.fit_note ? `<p class="badge warn">${esc(card.fit_note)}</p>` : "";
      return `<article class="opportunity"><p class="match" style="--score: ${esc(card.match_score)}">${esc(card.match_score)}% match</p><h3>${esc(card.role)}</h3><p>${esc(card.company)}</p><p class="meta">${esc(card.work_mode)} · ${esc(card.location || "Location not stated")}</p><p>${esc(card.compensation)}</p><p class="meta">Posted ${esc(card.posted || "date not listed")} · ${esc(card.availability)}</p><p class="meta">Found on ${esc((card.sources || []).join(" · "))}</p>${note}${why ? `<p class="why">Why it matches: ${why}</p>` : ""}${gaps ? `<p class="why">Potential gaps: ${gaps}</p>` : ""}${link}<div class="button-row"><a class="button-link secondary" href="/opportunities/${esc(card.id)}">View details</a>${button}</div></article>`;
    }).join("")}</div>` : `<div class="empty card"><h2>No opportunities on screen yet</h2><p>Run a search. Every result includes a direct application link you can open yourself.</p></div>`;
  }
  async function tick() {
    const response = await fetch("/api/status", { headers: { Accept: "application/json" } });
    if (!response.ok) return;
    render(await response.json());
  }
  tick();
  setInterval(tick, 2000);
}
