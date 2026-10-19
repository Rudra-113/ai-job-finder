function apiBase() {
  const configured = String(window.JOBFINDER_API || "").replace(/\/$/, "");
  if (configured) return configured;
  // location.origin omits a username in the address bar, which fetch() rejects.
  return window.location.origin;
}

let csrfToken = "";

function showBanner(message, kind) {
  const node = document.getElementById("banner");
  if (!node) return;
  node.hidden = !message;
  node.textContent = message || "";
  node.classList.toggle("warn", kind === "error");
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  let body = options.body;
  if (body && !(body instanceof FormData) && typeof body === "object") {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(body);
  }
  const method = options.method || "GET";
  if (csrfToken && method !== "GET" && method !== "HEAD") headers.set("X-CSRF-Token", csrfToken);
  let response;
  try {
    response = await fetch(apiBase() + path, { method, body, headers, credentials: "include" });
  } catch (error) {
    const failure = new Error("The job finder API is not reachable. Check the API URL and try again.");
    showBanner(failure.message, "error");
    throw failure;
  }
  const data = await response.json().catch(() => ({}));
  if (data && data.csrf) csrfToken = data.csrf;
  if (!response.ok || data.ok === false) {
    const failure = new Error(data.error || "The request could not be completed.");
    failure.status = response.status;
    failure.next = data.next || "";
    if (options.quiet !== true) showBanner(failure.message, "error");
    throw failure;
  }
  return data;
}

async function loadSession() {
  const data = await api("/api/session", { quiet: true });
  csrfToken = data.csrf || csrfToken;
  return data;
}
