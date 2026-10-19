function renderChrome(session) {
  const header = document.querySelector("header");
  const footer = document.querySelector("footer");
  if (!header || !footer) return;
  const page = document.body.dataset.page || "";
  header.innerHTML = `
    <nav>
      <a href="dashboard.html" ${page === "search" ? 'aria-current="page"' : ""}>Search</a>
      <a href="profile.html" ${page === "profile" ? 'aria-current="page"' : ""}>Profile</a>
      <a href="settings.html" ${page === "settings" ? 'aria-current="page"' : ""}>Settings</a>
    </nav>
    <a class="logo" href="index.html" aria-label="AI Job Finder">
      <img src="assets/logo.svg" alt="AI Job Finder">
    </a>`;
  footer.innerHTML = `
    <p>Search, review the matches, and apply on the employer’s site.</p>
    <p><a href="privacy.html">Privacy</a> · <a href="terms.html">Terms</a></p>
    <p class="lab">Launched from Trident Tech Labs</p>`;
}

async function bootShell() {
  try {
    const session = await loadSession();
    renderChrome(session);
    return session;
  } catch (error) {
    renderChrome(null);
    showBanner(error.message || "The job finder API is not reachable.", "error");
    return null;
  }
}
