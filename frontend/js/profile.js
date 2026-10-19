function val(id) {
  const node = document.getElementById(id);
  return node ? node.value : "";
}

function fill(profile) {
  const fields = ["full_name", "email", "phone", "city", "country", "portfolio", "linkedin", "github", "degree", "branch", "college", "graduation_year", "education_raw", "languages", "frameworks", "tools", "experience_raw", "projects", "certifications", "achievements", "domains", "extra_facts"];
  fields.forEach((id) => {
    const node = document.getElementById(id);
    if (node) node.value = profile[id] || "";
  });
  const skills = document.getElementById("skills");
  if (skills) skills.value = (profile.skills || []).join(", ");
  ["work_authorized", "needs_sponsorship"].forEach((id) => {
    const node = document.getElementById(id);
    if (node) node.value = profile[id] || "";
  });
  const current = document.getElementById("cv-name");
  if (current) current.textContent = profile.cv_name ? `Current file: ${profile.cv_name}` : "No resume uploaded.";
}

async function startProfile() {
  const session = await bootShell();
  if (!session) return;
  fill(await api("/api/profile"));
  document.getElementById("profile-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = {};
    new FormData(event.currentTarget).forEach((value, key) => {
      body[key] = value;
    });
    try {
      const saved = await api("/api/profile", { method: "POST", body });
      fill(saved.profile);
      showBanner(saved.message || "Profile saved.");
    } catch (error) {
      return;
    }
  });
  document.getElementById("resume-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = new FormData(event.currentTarget);
    try {
      const saved = await api("/api/profile/resume", { method: "POST", body });
      fill(saved.profile);
      showBanner(saved.message || "Resume replaced.");
    } catch (error) {
      return;
    }
  });
  document.getElementById("reanalyze").addEventListener("click", async () => {
    try {
      const result = await api("/api/profile/reanalyze", { method: "POST" });
      window.location.href = (result.next || "/onboarding.html").replace(/^\//, "");
    } catch (error) {
      return;
    }
  });
  document.getElementById("delete-resume").addEventListener("click", async () => {
    try {
      const saved = await api("/api/profile/resume/delete", { method: "POST" });
      fill(saved.profile);
      showBanner(saved.message || "Resume deleted.");
    } catch (error) {
      return;
    }
  });
  document.getElementById("delete-account").addEventListener("click", async () => {
    if (!window.confirm("Delete the profile, resume, settings, and saved searches in this browser?")) return;
    try {
      await api("/api/account/delete", { method: "POST" });
      window.location.href = "index.html";
    } catch (error) {
      return;
    }
  });
}

startProfile();
