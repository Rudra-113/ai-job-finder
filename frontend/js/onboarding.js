function fill(profile, settings) {
  ["full_name", "email", "phone", "degree", "branch", "college", "graduation_year", "city", "languages", "frameworks", "tools", "certifications", "projects", "experience_raw", "education_raw", "achievements", "domains"].forEach((id) => {
    const node = document.getElementById(id);
    if (node && profile) node.value = profile[id] || "";
  });
  const skills = document.getElementById("skills");
  if (skills && profile) skills.value = (profile.skills || []).join(", ");
  const roles = document.getElementById("roles");
  if (roles && settings) roles.value = settings.role_text || "";
  const sector = document.getElementById("sector");
  if (sector && settings) sector.value = settings.sector || "";
  const location = document.getElementById("location");
  if (location && settings) location.value = settings.location || "";
  const stipend = document.getElementById("minimum_stipend");
  if (stipend && settings) stipend.value = settings.minimum_stipend || 0;
  const workplace = document.getElementById("workplace");
  if (workplace && settings) workplace.value = settings.workplace || "remote";
  document.querySelectorAll('input[name="employment_choice"]').forEach((box) => {
    box.checked = settings && (settings.employment === box.value || settings.employment === "any");
  });
  ["avoid_unpaid", "avoid_relocation", "avoid_sales", "avoid_video", "avoid_above_level"].forEach((name) => {
    const box = document.querySelector(`input[name="${name}"]`);
    if (box && settings) box.checked = Boolean(settings[name]);
  });
  const confirm = document.getElementById("confirm-section");
  if (confirm) confirm.hidden = !(profile && profile.has_resume);
}

async function startOnboarding() {
  const session = await bootShell();
  if (!session) return;
  const state = await api("/api/onboarding");
  fill(state.profile, state.settings);
  document.getElementById("resume-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const saved = await api("/api/onboarding/resume", { method: "POST", body: new FormData(event.currentTarget) });
      const next = await api("/api/onboarding");
      fill(next.profile, next.settings);
      showBanner(saved.message || "Resume read.");
    } catch (error) {
      return;
    }
  });
  document.getElementById("confirm-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = { employment_choice: [] };
    new FormData(event.currentTarget).forEach((value, key) => {
      if (key === "employment_choice") body.employment_choice.push(value);
      else body[key] = value;
    });
    try {
      const result = await api("/api/onboarding/confirm", { method: "POST", body });
      window.location.href = (result.next || "/dashboard.html").replace(/^\//, "");
    } catch (error) {
      return;
    }
  });
}

startOnboarding();
