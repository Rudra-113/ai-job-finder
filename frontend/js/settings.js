function field(label, html) {
  return `<label>${label}</label>${html}`;
}

function input(id, value, type = "text", extra = "") {
  return `<input id="${id}" name="${id}" type="${type}" value="${escAttr(value)}" ${extra}>`;
}

function escAttr(value) {
  return String(value ?? "").replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
}

function select(id, value, options) {
  return `<select id="${id}" name="${id}">${options.map(([item, label]) => `<option value="${item}" ${item === value ? "selected" : ""}>${label}</option>`).join("")}</select>`;
}

function check(name, label, checked) {
  return `<label class="check"><input type="checkbox" name="${name}" value="1" ${checked ? "checked" : ""}> ${label}</label>`;
}

async function startSettings() {
  const session = await bootShell();
  if (!session) return;
  const settings = await api("/api/settings");
  const form = document.getElementById("settings-form");
  const weights = settings.match_weights || {};
  form.innerHTML = `
    ${field("Target sector", input("sector", settings.sector))}
    ${field("Target roles", input("roles", settings.role_text))}
    ${field("Required skills", input("required_skills", settings.required_skills_text))}
    <p class="hint">Every skill here must appear in the listing.</p>
    ${field("Preferred skills", input("preferred_skills", settings.preferred_skills_text))}
    ${field("Location", input("location", settings.location))}
    ${check("allow_hybrid", "Allow hybrid", settings.allow_hybrid)}
    ${field("Remote / hybrid / on-site", select("workplace", settings.workplace, [["any", "Any"], ["remote", "Remote"], ["hybrid", "Hybrid"], ["onsite", "On-site"]]))}
    ${field("Internship / full-time", select("employment", settings.employment, [["any", "Any"], ["intern", "Internship"], ["full-time", "Full-time"], ["part-time", "Part-time"], ["contract", "Contract"]]))}
    ${field("Minimum stipend", input("minimum_stipend", settings.minimum_stipend, "number", 'min="0" step="1"'))}
    ${field("Minimum salary", input("minimum_salary", settings.minimum_salary, "number", 'min="0" step="1"'))}
    <p class="hint">Monthly amount. Internships use the stipend. Other roles use the salary when it is set.</p>
    ${field("Experience level", select("experience_level", settings.experience_level, [["any", "Any"], ["intern", "Intern"], ["junior", "Junior"]]))}
    ${field("Preferred companies", input("preferred_companies", settings.preferred_companies_text))}
    ${field("Excluded companies", input("excluded_companies", settings.excluded_companies_text))}
    ${field("Posting age, in days", input("max_posting_age", settings.max_posting_age, "number", 'min="0" max="365"'))}
    ${field("Minimum match score", input("minimum_score", settings.minimum_score, "number", 'min="0" max="100"'))}
    ${field("Number of opportunities", input("opportunity_count", settings.opportunity_count, "number", 'min="1" max="100"'))}
    ${check("avoid_unpaid", "Skip unpaid roles", settings.avoid_unpaid)}
    ${check("avoid_video", "Skip mandatory video applications", settings.avoid_video)}
    ${check("avoid_relocation", "Skip relocation requirements", settings.avoid_relocation)}
    ${check("avoid_sales", "Skip sales roles", settings.avoid_sales)}
    ${check("avoid_above_level", "Skip roles above my experience level", settings.avoid_above_level)}
    ${check("require_disclosed_pay", "Require disclosed compensation", settings.require_disclosed_pay)}
    <h2>Match weights</h2>
    <p class="hint">These should add up to 100. They are scaled if they do not.</p>
    ${field("Skill match", input("weight_skill", weights.skill, "number", 'min="0" max="100"'))}
    ${field("Role relevance", input("weight_role", weights.role, "number", 'min="0" max="100"'))}
    ${field("Experience fit", input("weight_experience", weights.experience, "number", 'min="0" max="100"'))}
    ${field("Education fit", input("weight_education", weights.education, "number", 'min="0" max="100"'))}
    ${field("Location and work mode", input("weight_location", weights.location, "number", 'min="0" max="100"'))}
    ${field("Compensation", input("weight_compensation", weights.compensation, "number", 'min="0" max="100"'))}
    ${field("Preferred companies", input("weight_preference", weights.preference, "number", 'min="0" max="100"'))}
    <button type="submit">Save settings</button>`;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = {};
    new FormData(form).forEach((value, key) => {
      body[key] = value;
    });
    try {
      const saved = await api("/api/settings", { method: "POST", body });
      showBanner(saved.message || "Settings saved.");
    } catch (error) {
      return;
    }
  });
}

startSettings();
