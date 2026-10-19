function apiBase() {
  const configured = String(window.JOBFINDER_API || "").replace(/\/$/, "");
  if (configured) return configured;
  // location.origin omits a username in the address bar, which fetch() rejects.
  return window.location.origin;
}

let csrfToken = "";
let visitorId = "";

function stored(key) {
  try {
    return sessionStorage.getItem(key) || "";
  } catch (error) {
    return "";
  }
}

function store(key, value) {
  try {
    sessionStorage.setItem(key, value);
  } catch (error) {
    return;
  }
}

csrfToken = stored("jobfinder_csrf");
visitorId = stored("jobfinder_visitor");

function rememberSession(data) {
  if (!data) return;
  if (data.csrf) {
    csrfToken = data.csrf;
    store("jobfinder_csrf", csrfToken);
  }
  if (data.visitor_id && String(data.visitor_id).indexOf("anon_") === 0) {
    visitorId = data.visitor_id;
    store("jobfinder_visitor", visitorId);
  }
}

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
  if (visitorId) headers.set("X-Visitor-Id", visitorId);
  if (csrfToken) headers.set("X-CSRF-Token", csrfToken);
  let response;
  try {
    response = await fetch(apiBase() + path, { method, body, headers, credentials: "include" });
  } catch (error) {
    const failure = new Error("The job finder API is not reachable. Check the API URL and try again.");
    showBanner(failure.message, "error");
    throw failure;
  }
  const data = await response.json().catch(() => ({}));
  rememberSession(data);
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
  rememberSession(data);
  return data;
}
