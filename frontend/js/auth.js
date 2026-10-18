async function startAuth() {
  const session = await bootShell();
  if (session && session.logged_in) {
    window.location.href = "dashboard.html";
    return;
  }
  const google = document.getElementById("google-button");
  if (session && session.google_ready && google) {
    google.hidden = false;
    google.href = googleStartUrl();
    google.target = "_blank";
    google.rel = "noopener";
  }
  const finish = document.getElementById("finish-form");
  if (session && session.remote_auth && finish) finish.hidden = false;
  if (new URLSearchParams(window.location.search).get("notice") === "google") {
    showBanner("Google opened a page that this browser cannot load. Copy that address and paste it below.", "error");
  }
  const missing = document.getElementById("google-missing");
  if (missing) missing.hidden = Boolean(session && session.google_ready);
  document.getElementById("local-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const result = await api("/api/auth/local", { method: "POST" });
      window.location.href = (result.next || "/dashboard.html").replace(/^\//, "");
    } catch (error) {
      return;
    }
  });
  const copied = document.getElementById("use-copied");
  if (copied) {
    copied.addEventListener("click", async () => {
      try {
        const text = (await navigator.clipboard.readText()).trim();
        if (text.includes("/auth/google/callback")) document.getElementById("returned").value = text;
        else showBanner("Copy the full address from the page that did not load.", "error");
      } catch (error) {
        showBanner("Paste the address into the box, then finish sign-in.", "error");
      }
    });
  }
  if (finish) {
    finish.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const result = await api("/api/auth/google/finish", {
          method: "POST",
          body: { returned: document.getElementById("returned").value },
        });
        window.location.href = (result.next || "/dashboard.html").replace(/^\//, "");
      } catch (error) {
        return;
      }
    });
  }
}

startAuth();
