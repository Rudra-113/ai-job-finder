import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from jobagent.answers import is_eeo
from jobagent.apply import complete_application, field_kind, is_otp_field
from jobagent.models import Job, Secrets
from jobagent.safety import is_otp_field as otp_from_safety
from tests.conftest import strong_profile

FORM = """
<!DOCTYPE html>
<html><body>
<form method="post" action="/submitted">
  <label for="first_name">First Name *</label>
  <input id="first_name" name="first_name" aria-required="true">
  <label for="last_name">Last Name *</label>
  <input id="last_name" name="last_name" aria-required="true">
  <label for="email">Email *</label>
  <input id="email" name="email" type="email" aria-required="true">
  <label for="phone">Phone</label>
  <input id="phone" name="phone" type="tel">
  <label for="zip">Postal code</label>
  <input id="zip" name="zip">
  <label for="resume">Resume *</label>
  <input id="resume" name="resume" type="file" required>
  <label for="auth">Are you legally authorized to work in this country? *</label>
  <select id="auth" name="auth" required>
    <option value="">Select</option>
    <option>Yes</option>
    <option>No</option>
  </select>
  <label for="sponsor">Will you now or in the future require sponsorship? *</label>
  <select id="sponsor" name="sponsor" required>
    <option value="">Select</option>
    <option>Yes</option>
    <option>No</option>
  </select>
  <label for="gender">Gender</label>
  <select id="gender" name="gender">
    <option value="">Select</option>
    <option>Female</option>
    <option>Decline to self-identify</option>
  </select>
  <label for="story">Tell us about a project you built. *</label>
  <textarea id="story" name="story" required></textarea>
  <label for="cert"><input id="cert" name="cert" type="checkbox" required> I certify this information is true</label>
  <button type="submit">Submit application</button>
</form>
</body></html>
"""

CAPTCHA = """
<!DOCTYPE html>
<html><body>
<h1>Please verify you are human</h1>
<form method="post" action="/submitted">
  <label for="email">Email *</label>
  <input id="email" type="email" required>
  <button type="submit">Submit application</button>
</form>
</body></html>
"""

PAYMENT = """
<!DOCTYPE html>
<html><body>
<form method="post" action="/submitted">
  <label for="email">Email *</label>
  <input id="email" type="email" required>
  <label for="card">Card</label>
  <input id="card" autocomplete="cc-number">
  <button type="submit">Submit application</button>
</form>
</body></html>
"""

PAY_BUTTON = """
<!DOCTYPE html>
<html><body>
<form method="post" action="/submitted">
  <label for="email">Email *</label>
  <input id="email" type="email" required>
  <button type="submit">Pay and submit</button>
</form>
</body></html>
"""

OTP = """
<!DOCTYPE html>
<html><body>
<form method="post" action="/submitted">
  <label for="first_name">First Name *</label>
  <input id="first_name" name="first_name" required>
  <label for="last_name">Last Name *</label>
  <input id="last_name" name="last_name" required>
  <label for="email">Email *</label>
  <input id="email" name="email" type="email" required>
  <label for="resume">Resume *</label>
  <input id="resume" name="resume" type="file" required>
  <label for="otp">Verification code *</label>
  <input id="otp" name="otp" aria-required="true">
  <button type="submit">Submit application</button>
</form>
</body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] != "/job":
            self.send_error(404)
            return
        body = self.server.form.encode()
        self._send(200, body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.server.posts.append(self.rfile.read(length))
        self._send(200, b"<html><body><h1>Application submitted</h1><p>Thank you for applying</p></body></html>")

    def _send(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


class FormServer(ThreadingHTTPServer):
    def __init__(self, form):
        super().__init__(("127.0.0.1", 0), Handler)
        self.form = form
        self.posts = []


@pytest.fixture
def browser_page():
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    try:
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=True)
    except Exception as exc:
        pytest.skip(f"Chromium is not available: {exc}")
    page = browser.new_page()
    yield page
    browser.close()
    playwright.stop()


def serve(form):
    server = FormServer(form)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def job_for(server) -> Job:
    url = f"http://127.0.0.1:{server.server_address[1]}/job"
    return Job(source="test", company="Northwind", title="Data Analyst Intern", url=url, apply_url=url, workplace="remote")


def run_form(page, form, profile, work_dir, reader, preview=False):
    server = serve(form)
    try:
        page.goto(job_for(server).url, wait_until="domcontentloaded")
        result = complete_application(page, job_for(server), profile, Secrets(), reader, work_dir, preview=preview)
        return result, list(server.posts)
    finally:
        server.shutdown()
        server.server_close()


COMBO = """
<!DOCTYPE html>
<html><body>
<form method="post" action="/submitted">
  <label for="first_name">First Name *</label>
  <input id="first_name" name="first_name" required>
  <label for="last_name">Last Name *</label>
  <input id="last_name" name="last_name" required>
  <label for="email">Email *</label>
  <input id="email" name="email" type="email" required>
  <label for="country">Country *</label>
  <input id="country" name="country" role="combobox" aria-controls="country-list" required>
  <div id="country-list" role="listbox">
    <div role="option">France +33</div>
    <div role="option">Germany +49</div>
  </div>
  <label for="work">Please confirm your Right to Work *</label>
  <input id="work" name="work" role="combobox" aria-controls="work-list" required>
  <div id="work-list" role="listbox">
    <div role="option">Yes</div>
    <div role="option">No</div>
  </div>
  <label for="gender">How would you describe your gender identity?</label>
  <input id="gender" name="gender" role="combobox" aria-controls="gender-list">
  <div id="gender-list" role="listbox">
    <div role="option">Yes</div>
    <div role="option">No</div>
  </div>
  <label for="trans">Do you identify as transgender?</label>
  <input id="trans" name="trans" role="combobox" aria-controls="trans-list">
  <div id="trans-list" role="listbox">
    <div role="option">Yes</div>
    <div role="option">No</div>
  </div>
  <label for="orient">What's your sexual orientation?</label>
  <input id="orient" name="orient" role="combobox">
  <label for="neuro">Are you neurodivergent?</label>
  <input id="neuro" name="neuro">
  <label for="said">How do you pronounce your name?</label>
  <input id="said" name="said">
  <button type="submit">Submit application</button>
</form>
<script>
document.querySelectorAll("[role=option]").forEach((opt) => {
  opt.addEventListener("click", () => {
    const list = opt.closest("[role=listbox]");
    const input = document.querySelector("[aria-controls='" + list.id + "']");
    if (input) input.value = opt.textContent.trim();
  });
});
</script>
</body></html>
"""


def test_demographic_questions_are_not_profile_fields():
    labels = (
        "How would you describe your gender identity?",
        "Do you identify as transgender?",
        "What's your sexual orientation?",
        "How would you describe your ethnicity?",
        "Are you neurodivergent?",
        "Disability status",
        "Pronouns",
    )
    for label in labels:
        assert is_eeo(label), label
        assert field_kind({"label": label, "name": "", "id": "", "type": "text"}) == "eeo"
    assert not is_eeo("Do you need a disability accommodation?")
    assert field_kind({"label": "How do you pronounce your name?", "name": "", "id": "", "type": "text"}) == "question"


def test_otp_field_detection():
    assert is_otp_field("Verification code", "otp", "otp")
    assert otp_from_safety("Verification code")
    assert not is_otp_field("Postal code", "zip", "zip")
    assert field_kind({"label": "Postal code", "name": "zip", "id": "zip", "type": "text"}) == "question"


def test_submits_known_fields_and_does_not_guess_gender(browser_page, tmp_path):
    def reader(_domains):
        raise AssertionError("postal code must not be treated as a one-time code")

    result, posts = run_form(browser_page, FORM, strong_profile(tmp_path), tmp_path, reader)
    assert result.status == "submitted", result.reason
    assert posts
    body = posts[0]
    assert b"ada%40example.com" in body or b"ada@example.com" in body
    assert b"dashboard" in body
    assert b"Female" not in body


def test_stops_for_captcha_payment_and_pay_button(browser_page, tmp_path):
    profile = strong_profile(tmp_path)
    for form, phrase in (
        (CAPTCHA, b"CAPTCHA"),
        (PAYMENT, b"payment"),
        (PAY_BUTTON, b"payment"),
    ):
        result, posts = run_form(browser_page, form, profile, tmp_path, lambda _domains: None)
        assert posts == []
        assert result.status == "needs_user"
        assert phrase.decode().lower() in result.reason.lower() or phrase.lower() in result.reason.lower().encode()


def test_missing_work_authorization_does_not_submit(browser_page, tmp_path):
    profile = strong_profile(tmp_path)
    profile.work_authorized = ""
    result, posts = run_form(browser_page, FORM, profile, tmp_path, lambda _domains: None)
    assert posts == []
    assert result.status == "needs_user"
    assert "authorization" in result.reason.lower()


def test_preview_fills_without_submitting(browser_page, tmp_path):
    result, posts = run_form(
        browser_page,
        FORM,
        strong_profile(tmp_path),
        tmp_path,
        lambda _domains: None,
        preview=True,
    )
    assert result.status == "filled", result.reason
    assert result.submit_clicked is False
    assert posts == []
    assert any("ada@example.com" in item for item in result.filled)


def test_combobox_yes_does_not_fill_demographic_fields(browser_page, tmp_path):
    result, posts = run_form(
        browser_page,
        COMBO,
        strong_profile(tmp_path),
        tmp_path,
        lambda _domains: None,
        preview=True,
    )
    assert result.status == "filled", result.reason
    assert result.submit_clicked is False
    assert posts == []
    page = browser_page
    assert page.locator("#gender").input_value() == ""
    assert page.locator("#trans").input_value() == ""
    assert page.locator("#orient").input_value() == ""
    assert page.locator("#neuro").input_value() == ""
    assert page.locator("#work").input_value().casefold() == "yes"
    assert page.locator("#country").input_value() == "Germany +49"
    assert page.locator("#said").input_value() == ""
    blob = " ".join(result.filled + result.answered).casefold()
    assert "gender" not in blob
    assert "transgender" not in blob
    assert "orientation" not in blob
    assert "neurodivergent" not in blob


def test_email_otp_is_entered(browser_page, tmp_path):
    result, posts = run_form(
        browser_page,
        OTP,
        strong_profile(tmp_path),
        tmp_path,
        lambda _domains: "445566",
    )
    assert result.status == "submitted", result.reason
    assert b"445566" in posts[0]
