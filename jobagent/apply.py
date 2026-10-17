"""Fill an application in a normal browser and stop when a step is not safe.

CAPTCHA, payment, and login walls are not bypassed. The CV on disk is the file
that gets uploaded. Free-text answers come only from saved profile facts.
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path

from jobagent.answers import Answer, answer_question, factual_motivation, is_eeo, match_option
from jobagent.gmail_otp import GmailNotConnected, mail_domains
from jobagent.models import ApplyResult, Job, Secrets
from jobagent.profile import Profile
from jobagent.safety import (
    PAYMENT_SELECTORS,
    captcha_in_text,
    is_login_control,
    is_otp_field,
    verification_in_text,
)
from jobagent.textutil import safe_http_url

LOGIN_HOSTS = ("myworkdayjobs.com", "taleo.net")
DECLINE = re.compile(r"decline|prefer not|do not wish|don't wish|choose not|not disclosed|self-identify", re.I)
CONSENT = re.compile(
    r"certif|information (?:is|provided is) (?:true|accurate)|privacy (?:policy|notice)|terms (?:of|and)|i agree to the|acknowledge",
    re.I,
)
PAY_BOX = re.compile(r"\b(pay|payment|fee|charge|purchase|deposit|billing)\b", re.I)
_SUBMIT = re.compile(r"submit application|^submit$|send application|send my application", re.I)
_NEXT = re.compile(r"^(next|continue)$|save and continue|continue application", re.I)
_APPLY = (
    re.compile(r"^apply$", re.I),
    re.compile(r"apply now", re.I),
    re.compile(r"apply for this (job|position)", re.I),
)
_CONFIRM = (
    "thank you for applying",
    "thanks for applying",
    "application submitted",
    "application has been submitted",
    "we have received your application",
    "we received your application",
    "your application was submitted",
    "successfully submitted",
)
_READ_FIELDS = """
() => {
  function text(node) {
    return ((node && node.innerText) || "").replace(/\\s+/g, " ").trim();
  }
  const nodes = [...document.querySelectorAll("input, textarea, select")];
  return nodes.map((el, index) => {
    const tag = el.tagName.toLowerCase();
    const typeAttr = (el.getAttribute("type") || "").toLowerCase();
    const type = tag === "select" ? "select" : tag === "textarea" ? "textarea" : (typeAttr || "text");
    let direct = "";
    if (el.id) {
      const lab = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lab) direct = text(lab);
    }
    if (!direct) {
      const wrap = el.closest("label");
      if (wrap) direct = text(wrap);
    }
    if (!direct && el.getAttribute("aria-label")) direct = el.getAttribute("aria-label").trim();
    const legend = text(el.closest("fieldset") ? el.closest("fieldset").querySelector("legend") : null);
    const style = window.getComputedStyle(el);
    const shown = style.display !== "none" && style.visibility !== "hidden" && !!(el.offsetParent || el.getClientRects().length);
    const ariaHidden = el.getAttribute("aria-hidden") === "true";
    const visible = type === "file" ? true : type !== "hidden" && shown && !ariaHidden;
    let value = "";
    if (type === "checkbox" || type === "radio") value = el.checked ? "checked" : "";
    else if (tag === "select") {
      const option = el.options[el.selectedIndex];
      value = option ? ((option.text || "").trim() || option.value || "") : "";
      if ((value || "").toLowerCase() === "select") value = "";
    } else {
      value = el.value || "";
      if (!value && el.getAttribute("role") === "combobox") {
        const shell = el.closest(".select-shell");
        const single = shell && shell.querySelector(".select__single-value");
        if (single) value = ((single.innerText || "").replace(/\\s+/g, " ").trim());
      }
    }
    const options = tag === "select" ? [...el.options].map((option) => ({
      value: option.value,
      label: (option.text || "").trim(),
    })) : [];
    return {
      index,
      id: el.id || "",
      name: el.name || "",
      type,
      tag,
      label: direct,
      legend,
      required: !!(el.required || el.getAttribute("aria-required") === "true" || /\\*/.test(direct) || /\\*/.test(legend)),
      value,
      options,
      visible,
      role: el.getAttribute("role") || "",
      maxlength: el.getAttribute("maxlength") || "",
    };
  });
}
"""


def default_headless() -> bool:
    env = os.environ.get("JOBAGENT_HEADLESS")
    if env is not None and env.strip() != "":
        return env.strip().casefold() not in {"0", "false", "no"}
    if os.name == "nt":
        return False
    return not bool(os.environ.get("DISPLAY"))


def _needs(reason: str, blocks: bool = True, clicked: bool = False) -> ApplyResult:
    return ApplyResult("needs_user", "", reason, blocks, clicked)


def _failed(reason: str) -> ApplyResult:
    return ApplyResult("failed", "", reason, False, False)


def field_kind(field: dict) -> str:
    label = field.get("label") or ""
    blob = f"{label} {field.get('name') or ''} {field.get('id') or ''}".casefold()
    field_id = (field.get("id") or "").casefold()
    if field.get("type") == "file":
        if "cover" in blob:
            return "cover_file"
        if re.search(r"resume|cv|curriculum", blob) or field_id == "resume":
            return "resume"
        return "other_file"
    if is_otp_field(label, field.get("name") or "", field.get("id") or ""):
        return "otp"
    if is_eeo(label) or is_eeo(field.get("legend") or ""):
        return "eeo"
    if re.search(r"social security|national insurance|passport|driver'?s license", blob):
        return "sensitive_id"
    if re.search(r"e-?mail", blob) or field_id == "email":
        return "email"
    if re.search(r"first name|given name", blob) or field_id in {"first_name", "firstname"}:
        return "first"
    if re.search(r"last name|family name|surname", blob) or field_id in {"last_name", "lastname"}:
        return "last"
    if re.search(r"preferred name|name you", blob):
        return "preferred"
    name_label = label.casefold()
    if "pronounc" not in name_label and (
        re.search(r"\bfull name\b|\blegal name\b|^name$|\byour name\b", name_label) or field.get("name") == "name"
    ):
        return "full"
    if re.search(r"\b(phone|mobile)\b|\btel\b", blob):
        return "phone"
    if re.search(r"\bcity\b", blob) and "capacity" not in blob:
        return "city"
    # "authorized to work in this country" is a yes/no question, not a country picker.
    if re.search(r"\bcountry\b", blob) and "country code" not in blob:
        if not re.search(r"authori|sponsor|eligible|visa|right to work|in this country", blob):
            return "country"
    if "linkedin" in blob:
        return "linkedin"
    if "github" in blob:
        return "github"
    if re.search(r"portfolio|personal website|\bwebsite\b", blob):
        return "portfolio"
    if re.search(r"\b(college|university|school|institute)\b", blob):
        return "college"
    if re.search(r"\b(degree|qualification|major)\b", blob):
        return "degree"
    if re.search(r"graduat|year of (?:passing|completion)|passing year", blob):
        return "graduation"
    if re.search(r"\bskills?\b", blob) and "year" not in blob:
        return "skills"
    return "question"


def _locator(target, field):
    field_id = (field.get("id") or "").strip()
    if field_id and "'" not in field_id and "]" not in field_id:
        located = target.locator(f"[id='{field_id}']")
        try:
            if located.count() == 1:
                return located
        except Exception:
            pass
    return target.locator("input, textarea, select").nth(field["index"])


def _visible_text(target) -> str:
    try:
        return target.locator("body").inner_text(timeout=3000)
    except Exception:
        return ""


def _has_visible(target, selector: str) -> bool:
    locator = target.locator(selector)
    count = min(locator.count(), 6)
    for index in range(count):
        try:
            if locator.nth(index).is_visible():
                return True
        except Exception:
            continue
    return False


def detect_captcha(target) -> bool:
    # The corner reCAPTCHA badge is not a challenge. A checkbox, image challenge,
    # or a visible human-check is.
    challenge_selectors = (
        ".g-recaptcha",
        ".h-captcha",
        ".cf-turnstile",
        "#px-captcha",
        "iframe[src*='hcaptcha']",
        "iframe[src*='turnstile']",
        "iframe[src*='challenges.cloudflare.com']",
    )
    if any(_has_visible(target, selector) for selector in challenge_selectors):
        return True
    frames = target.locator("iframe[src*='recaptcha'], iframe[title*='captcha' i]")
    count = min(frames.count(), 6)
    for index in range(count):
        frame = frames.nth(index)
        try:
            if not frame.is_visible():
                continue
            src = (frame.get_attribute("src") or "").casefold()
            box = frame.bounding_box() or {}
            height = box.get("height") or 0
        except Exception:
            continue
        if "bframe" in src or height > 120:
            return True
    return captcha_in_text(_visible_text(target))


def detect_payment(target) -> bool:
    if any(_has_visible(target, selector) for selector in PAYMENT_SELECTORS):
        return True
    buttons = target.locator("button, input[type='submit']")
    count = min(buttons.count(), 30)
    for index in range(count):
        button = buttons.nth(index)
        try:
            if not button.is_visible():
                continue
            name = (button.inner_text(timeout=500) or "").strip() or (button.get_attribute("value") or "")
        except Exception:
            continue
        if re.fullmatch(r"pay(?: now)?", name.strip(), re.I) or re.search(r"pay and|checkout|\bpayment\b", name, re.I):
            return True
    return False


def _has_email_field(target) -> bool:
    return target.locator("input[type='email'], input#email, input[name='email' i], input[autocomplete='email']").count() > 0


def detect_login(target) -> bool:
    try:
        if target.locator("input[type='password']:visible").count() > 0:
            return True
    except Exception:
        pass
    if _has_email_field(target):
        return False
    folded = _visible_text(target)[:5000].casefold()
    return any(phrase in folded for phrase in (
        "sign in to apply",
        "log in to apply",
        "login to apply",
        "create an account to apply",
        "sign in to continue",
    ))


def detect_block(target) -> ApplyResult | None:
    if detect_captcha(target):
        return _needs("A CAPTCHA or human check appeared. This application was stopped and will not be bypassed.")
    if detect_payment(target):
        return _needs("The site asked for a payment. Nothing was paid and the application was stopped.")
    if detect_login(target):
        return _needs("The site asked for a login or a new account. Login protection was not bypassed.")
    if verification_in_text(_visible_text(target)[:8000]):
        return _needs("An identity check appeared that this agent will not complete.")
    return None


def read_fields(target) -> list[dict]:
    try:
        fields = target.evaluate(_READ_FIELDS)
    except Exception:
        return []
    return fields if isinstance(fields, list) else []


def open_application_form(page):
    if _has_email_field(page):
        return page
    for pattern in _APPLY:
        for role in ("link", "button"):
            locator = page.get_by_role(role, name=pattern)
            count = min(locator.count(), 6)
            for index in range(count):
                item = locator.nth(index)
                try:
                    if not item.is_visible():
                        continue
                    name = item.inner_text(timeout=1000)
                except Exception:
                    continue
                if is_login_control(name) or re.search(r"pay and|checkout|\bpayment\b", name or "", re.I):
                    continue
                item.click()
                page.wait_for_timeout(800)
                if _has_email_field(page):
                    return page
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        try:
            if _has_email_field(frame):
                return frame
        except Exception:
            continue
    return page


def _button_name(button) -> str:
    try:
        if not button.is_visible():
            return ""
        return ((button.inner_text(timeout=500) or "").strip() or (button.get_attribute("value") or "")).strip()
    except Exception:
        return ""


def find_action(target):
    buttons = target.locator("button, input[type='submit']")
    count = min(buttons.count(), 40)
    submit = None
    nxt = None
    payment = None
    for index in range(count):
        button = buttons.nth(index)
        name = _button_name(button)
        if not name:
            continue
        if re.fullmatch(r"pay(?: now)?", name, re.I) or re.search(r"pay and|checkout|\bpayment\b", name, re.I):
            payment = button
            continue
        if _SUBMIT.search(name):
            submit = submit or button
            continue
        if _NEXT.search(name) and not is_login_control(name):
            nxt = nxt or button
    if payment is not None:
        return "payment", payment
    if submit is not None:
        return "submit", submit
    if nxt is not None:
        return "next", nxt
    return None, None


def _abandon_combobox(locator) -> None:
    try:
        locator.press("Escape")
    except Exception:
        pass
    try:
        locator.fill("")
    except Exception:
        pass


def _open_listbox(target, locator):
    """The menu that belongs to this combobox, never another question's options."""
    controls = (locator.get_attribute("aria-controls") or locator.get_attribute("aria-owns") or "").strip()
    if controls and "'" not in controls:
        menu = target.locator(f"[id='{controls}']")
        if menu.count():
            return menu
    menus = target.locator("[role='listbox']")
    visible = []
    count = min(menus.count(), 8)
    for index in range(count):
        item = menus.nth(index)
        try:
            if item.is_visible():
                visible.append(item)
        except Exception:
            continue
    if len(visible) == 1:
        return visible[0]
    return None


def _option_exact(menu, value: str):
    wanted = (value or "").strip()
    if not wanted:
        return None
    exact = re.compile(rf"^\s*{re.escape(wanted)}\s*$", re.I)
    prefix = re.compile(rf"^\s*{re.escape(wanted)}(?:\s|\+|,|$)", re.I) if len(wanted) >= 4 else None
    options = menu.get_by_role("option")
    count = min(options.count(), 40)
    fallback = None
    for index in range(count):
        item = options.nth(index)
        try:
            if not item.is_visible():
                continue
            name = item.inner_text(timeout=500).strip()
        except Exception:
            continue
        if exact.match(name):
            return item
        if prefix is not None and fallback is None and prefix.match(name):
            fallback = item
    return fallback


def _pick_option(target, locator, value: str) -> bool:
    try:
        locator.click(timeout=3000)
        menu = _open_listbox(target, locator)
        if menu is None:
            _abandon_combobox(locator)
            return False
        locator.fill(value)
        try:
            target.wait_for_timeout(400)
        except Exception:
            pass
        option = _option_exact(menu, value)
        if option is None:
            _abandon_combobox(locator)
            return False
        option.click(timeout=3000)
        return True
    except Exception:
        _abandon_combobox(locator)
        return False


def _clear_demographic_values(target) -> None:
    """A click in one dropdown must not leave an answer in a demographic field."""
    try:
        fields = read_fields(target)
    except Exception:
        return
    for field in fields:
        if not field.get("visible") or field.get("type") in {"hidden", "checkbox", "radio", "file", "submit"}:
            continue
        if field_kind(field) != "eeo":
            continue
        value = str(field.get("value") or "").strip()
        if not value or DECLINE.search(value):
            continue
        locator = _locator(target, field)
        try:
            if field.get("tag") == "select":
                locator.select_option(index=0)
            else:
                _abandon_combobox(locator)
        except Exception:
            continue


def _education_parts(profile: Profile) -> tuple[str, str, str]:
    line = ""
    for raw in (profile.education_raw or "").splitlines():
        if raw.strip():
            line = raw.strip()
            break
    parts = [part.strip() for part in line.split("|")]
    while len(parts) < 4:
        parts.append("")
    degree = " ".join(part for part in (parts[0], parts[1]) if part)
    return degree, parts[2], parts[3]


def _profile_value(kind: str, profile: Profile) -> str:
    degree, school, graduated = _education_parts(profile)
    values = {
        "email": profile.email,
        "first": profile.first_name,
        "last": profile.last_name,
        "full": profile.full_name,
        "preferred": profile.full_name,
        "phone": profile.phone,
        "city": profile.city,
        "country": profile.country,
        "linkedin": profile.linkedin,
        "github": profile.github,
        "portfolio": profile.portfolio,
        "degree": degree,
        "college": school,
        "graduation": graduated,
        "skills": ", ".join(profile.skills),
    }
    return (values.get(kind) or "").strip()


def _missing_profile(kind: str) -> str:
    return {
        "email": "Your Profile has no email.",
        "first": "Your Profile needs a first and last name.",
        "last": "Your Profile needs a first and last name.",
        "full": "Your Profile needs a first and last name.",
        "preferred": "Your Profile needs a name.",
        "phone": "Add a phone number on your Profile. The form requires one.",
        "city": "Add a city on your Profile. The form requires one.",
        "country": "Add a country on your Profile. The form requires one.",
        "linkedin": "Add a LinkedIn URL on your Profile. This required field was not guessed.",
        "github": "Add a GitHub URL on your Profile. This required field was not guessed.",
        "portfolio": "Add a portfolio URL on your Profile. This required field was not guessed.",
        "degree": "Add education on your Profile. The degree was not guessed.",
        "college": "Add a school on your Profile. It was not guessed.",
        "graduation": "Add a graduation date on your Profile. It was not guessed.",
        "skills": "Add skills on your Profile. None were guessed.",
    }.get(kind, "A required answer is missing from your Profile.")


def _question_text(field: dict) -> str:
    if field.get("type") == "radio":
        raw = field.get("legend") or field.get("label") or ""
    else:
        raw = field.get("label") or field.get("legend") or ""
    return raw.replace("*", " ").strip()


def _fill_answer(target, field, answer: Answer) -> str | None:
    locator = _locator(target, field)
    if answer.action != "fill":
        return None
    if field["tag"] == "select":
        chosen = match_option(answer.value, field.get("options") or [])
        if not chosen:
            return f"No matching choice for: {_question_text(field)[:120]}"
        locator.select_option(label=chosen)
        return None
    if field.get("role") == "combobox":
        if not _pick_option(target, locator, answer.value):
            return f"Could not choose an option for: {_question_text(field)[:120]}"
        return None
    locator.fill(answer.value)
    return None


def fill_fields(target, fields, job: Job, profile: Profile, secrets: Secrets, otp_reader, work_dir: Path, confirmed: set[int], gaps: list[str] | None = None) -> ApplyResult | None:
    def finish(outcome: ApplyResult | None) -> ApplyResult | None:
        _clear_demographic_values(target)
        return outcome

    otp_fields = [
        field
        for field in fields
        if field.get("visible") and field.get("type") in {"text", "tel", "number"} and field_kind(field) == "otp"
    ]
    if otp_fields:
        try:
            code = otp_reader(mail_domains(job.apply_url or job.url)) if otp_reader else None
        except GmailNotConnected:
            return finish(_needs("Connect Gmail on the Profile page to read a one-time code. Your Gmail password is never stored."))
        if not code:
            return finish(_needs("No matching one-time code email was found. The rest of the inbox was not read."))
        if len(otp_fields) == 1:
            _locator(target, otp_fields[0]).fill(code)
            confirmed.add(otp_fields[0]["index"])
        elif len(otp_fields) == len(code) and all(str(field.get("maxlength")) == "1" for field in otp_fields):
            for field, digit in zip(otp_fields, code):
                _locator(target, field).fill(digit)
                confirmed.add(field["index"])
        else:
            return finish(_needs("The one-time code was not a single field, so it was not entered."))

    seen_radios: set[str] = set()
    for field in fields:
        if field.get("type") in {"hidden", "submit", "button", "reset", "image"}:
            continue
        if not field.get("visible"):
            continue
        if field.get("type") == "radio":
            key = field.get("name") or f"radio-{field['index']}"
            if key in seen_radios:
                continue
            seen_radios.add(key)
            group = [item for item in fields if item.get("type") == "radio" and (item.get("name") or f"radio-{item['index']}") == key]
            outcome = _fill_radio_group(target, group, job, profile, secrets, confirmed, gaps)
            if outcome:
                return finish(outcome)
            continue
        outcome = _fill_one(target, field, job, profile, secrets, work_dir, confirmed, gaps)
        if outcome:
            return finish(outcome)
    return finish(None)


def _fill_radio_group(target, group, job, profile, secrets, confirmed, gaps: list[str] | None = None) -> ApplyResult | None:
    legend = group[0].get("legend") or ""
    required = any(item.get("required") for item in group)
    if is_eeo(legend) or any(is_eeo(item.get("label") or "") for item in group):
        if not required:
            return None
        for item in group:
            if DECLINE.search(item.get("label") or ""):
                _locator(target, item).check(timeout=3000)
                confirmed.add(item["index"])
                return None
        return _needs("A required demographic question had no option to decline. Nothing was guessed.")
    question = legend or group[0].get("label") or ""
    answer = answer_question(question, required, profile, job, secrets)
    if answer.action == "stop":
        if gaps is not None:
            gaps.append(question[:160] or answer.reason)
            return None
        return _needs(answer.reason)
    if answer.action == "skip":
        if required and gaps is not None:
            gaps.append(question[:160] or "A required choice")
            return None
        return _needs(f"A required choice could not be answered from your Profile: {question[:120]}") if required else None
    for item in group:
        if match_option(answer.value, [{"label": item.get("label") or ""}]):
            _locator(target, item).check(timeout=3000)
            confirmed.add(item["index"])
            return None
    if required:
        return _needs(f"No matching choice for: {question[:120]}")
    return None


def _fill_one(target, field, job, profile, secrets, work_dir, confirmed, gaps: list[str] | None = None) -> ApplyResult | None:
    kind = field_kind(field)
    required = bool(field.get("required"))
    locator = _locator(target, field)
    if kind == "otp":
        return None
    if kind == "sensitive_id":
        return _needs("The form asks for a government or financial identifier. It was left blank and the application was stopped.")
    if kind == "eeo":
        if not required:
            return None
        if _select_decline(locator, field):
            confirmed.add(field["index"])
            return None
        return _needs("A required demographic question had no option to decline. Nothing was guessed.")
    if kind == "resume":
        if not profile.cv_path or not Path(profile.cv_path).is_file():
            return _needs("Upload your CV on the Profile page.")
        try:
            locator.set_input_files(profile.cv_path)
        except Exception:
            return _needs("The CV could not be attached.")
        confirmed.add(field["index"])
        return None
    if kind == "cover_file":
        if not required:
            return None
        text = factual_motivation(profile)
        if not text:
            return _needs("A cover letter file is required, and there is not enough saved experience to write one without guessing.")
        path = work_dir / "cover.txt"
        path.write_text(text, encoding="utf-8")
        locator.set_input_files(str(path))
        confirmed.add(field["index"])
        return None
    if kind == "other_file":
        return _needs("A required file could not be identified safely.") if required else None
    if field.get("type") == "checkbox":
        label = field.get("label") or ""
        if PAY_BOX.search(label):
            return _needs("The site asked for a payment. Nothing was paid and the application was stopped.")
        if CONSENT.search(label):
            locator.check(timeout=3000)
            confirmed.add(field["index"])
            return None
        if required:
            return _needs(f"A required checkbox was not checked because its meaning was not clear: {label[:120]}")
        return None
    if kind in {"email", "first", "last", "full", "preferred", "phone", "city", "country", "linkedin", "github", "portfolio", "degree", "college", "graduation", "skills"}:
        value = _profile_value(kind, profile)
        if not value:
            if required and gaps is not None:
                gaps.append(_missing_profile(kind))
                return None
            return _needs(_missing_profile(kind)) if required else None
        typed = kind in {"email", "first", "last", "full", "preferred", "phone", "linkedin", "github", "portfolio", "degree", "college", "graduation", "skills"}
        if field["tag"] == "select":
            chosen = match_option(value, field.get("options") or [])
            if not chosen:
                if gaps is not None:
                    gaps.append(f"{_question_text(field)[:80]}: no matching choice")
                    return None
                return _needs(f"No matching choice for: {value}") if required else None
            locator.select_option(label=chosen)
        elif field.get("role") == "combobox" and not typed:
            if not _pick_option(target, locator, value):
                if gaps is not None:
                    gaps.append(f"{_question_text(field)[:80]}: no matching choice")
                    return None
                return _needs(f"Could not choose an option for: {value}") if required else None
        else:
            locator.fill(value)
        if kind == "email":
            actual = locator.input_value(timeout=2000)
            if actual.strip().casefold() != value.casefold():
                return _needs("Email could not be entered correctly.")
        confirmed.add(field["index"])
        return None
    question = _question_text(field)
    answer = answer_question(question, required, profile, job, secrets)
    if answer.action == "stop":
        if gaps is not None:
            gaps.append(question[:160] or answer.reason)
            return None
        return _needs(answer.reason)
    if answer.action != "fill":
        if required and gaps is not None:
            gaps.append(question[:160] or "Needs user input")
        return None
    problem = _fill_answer(target, field, answer)
    if problem:
        if gaps is not None:
            gaps.append(problem)
            return None
        return _needs(problem) if required else None
    confirmed.add(field["index"])
    return None


def _select_decline(locator, field) -> bool:
    if field.get("tag") != "select":
        return False
    for option in field.get("options") or []:
        if DECLINE.search(option.get("label") or ""):
            locator.select_option(label=option["label"])
            return True
    return False


def review_fields(fields: list[dict], confirmed: set[int], profile: Profile) -> list[str]:
    issues: list[str] = []
    seen: set[str] = set()
    for field in fields:
        if field.get("type") in {"hidden", "submit", "button", "reset", "image"}:
            continue
        if field.get("type") == "radio":
            key = field.get("name") or str(field.get("index"))
            if key in seen:
                continue
            seen.add(key)
            group = [
                item
                for item in fields
                if item.get("type") == "radio" and (item.get("name") or str(item.get("index"))) == key
            ]
            if any(item.get("required") for item in group) and not any(
                item.get("index") in confirmed or item.get("value") == "checked" for item in group
            ):
                issues.append(group[0].get("legend") or group[0].get("label") or "A required choice")
            continue
        if not field.get("visible") or not field.get("required"):
            continue
        if field.get("index") in confirmed:
            continue
        if field.get("type") == "checkbox" and field.get("value") == "checked":
            continue
        if field.get("type") != "file" and str(field.get("value") or "").strip():
            continue
        issues.append(field.get("label") or field.get("id") or "A required field")
    for field in fields:
        kind = field_kind(field)
        value = str(field.get("value") or "").strip()
        if not value:
            continue
        if kind == "email" and value.casefold() != profile.email.strip().casefold():
            issues.append("Email does not match your profile")
        if kind == "first" and value.casefold() != profile.first_name.casefold():
            issues.append("First name does not match your profile")
        if kind == "last" and value.casefold() != profile.last_name.casefold():
            issues.append("Last name does not match your profile")
    unique: list[str] = []
    for item in issues:
        if item and item not in unique:
            unique.append(item)
    return unique


def _confirmation(target) -> bool:
    text = _visible_text(target).casefold()
    return any(phrase in text for phrase in _CONFIRM)


def click_submit(target, button) -> ApplyResult:
    blocked = detect_block(target)
    if blocked:
        return blocked
    try:
        if button.is_disabled():
            return _needs("The submit button is disabled, so a required field is still missing.")
    except Exception:
        pass
    button.click()
    try:
        target.wait_for_timeout(1200)
    except Exception:
        pass
    if detect_captcha(target):
        return _needs(
            "A CAPTCHA or human check appeared. This application was stopped and will not be bypassed.",
            clicked=True,
        )
    if detect_payment(target):
        return _needs("The site asked for a payment. Nothing was paid and the application was stopped.", clicked=True)
    if _confirmation(target):
        return ApplyResult("submitted", "The site confirmed the application.", "", True, True)
    return _needs(
        "No confirmation appeared. It was not submitted again, because the form may already have been sent.",
        clicked=True,
    )


def _summarize(fields: list[dict], confirmed: set[int], gaps: list[str]) -> tuple[list[str], list[str], list[str]]:
    filled: list[str] = []
    answered: list[str] = []
    needs = list(gaps)
    for field in fields:
        if field.get("type") in {"hidden", "submit", "button", "reset", "image"} or not field.get("visible"):
            continue
        label = _question_text(field) or field.get("id") or "Field"
        value = str(field.get("value") or "").strip()
        attached = field.get("type") == "file" and field.get("index") in confirmed
        if field_kind(field) == "eeo":
            if value and not DECLINE.search(value):
                needs.append(f"{label}: demographic questions are left for you")
            elif value:
                filled.append(f"{label}: {value[:180]}")
            continue
        if field_kind(field) == "question" and value:
            answered.append(f"{label}: {value[:180]}")
        elif value or attached:
            filled.append(f"{label}: {('file attached' if attached else value)[:180]}")
        elif field.get("required"):
            label_key = label.casefold()
            if any(label_key and label_key in item.casefold() for item in needs):
                continue
            if label_key in {"field", "a required field"} and any("no label" in item.casefold() for item in needs):
                continue
            needs.append(label[:160])
    unique: list[str] = []
    for item in needs:
        if item and item not in unique:
            unique.append(item)
    return filled[:30], answered[:20], unique[:20]


def _filled_result(fields: list[dict], confirmed: set[int], gaps: list[str]) -> ApplyResult:
    filled, answered, needs = _summarize(fields, confirmed, gaps)
    return ApplyResult(
        "filled",
        "The form is filled and the browser is still on the application page. Nothing was submitted.",
        "",
        True,
        False,
        filled=filled,
        answered=answered,
        needs_input=needs,
    )


def complete_application(page, job: Job, profile: Profile, secrets: Secrets, otp_reader, work_dir: Path, preview: bool = False) -> ApplyResult:
    blocked = detect_block(page)
    if blocked:
        return blocked
    target = open_application_form(page)
    for _step in range(6):
        blocked = detect_block(target)
        if blocked:
            return blocked
        fields = read_fields(target)
        visible = [field for field in fields if field.get("visible") and field.get("type") not in {"hidden", "submit", "button"}]
        if not visible:
            return _needs("Could not find an application form on this page.")
        confirmed: set[int] = set()
        gaps: list[str] = []
        outcome = fill_fields(
            target, fields, job, profile, secrets, otp_reader, work_dir, confirmed, gaps if preview else None
        )
        if outcome:
            return outcome
        blocked = detect_block(target)
        if blocked:
            return blocked
        action, button = find_action(target)
        if action == "payment":
            return _needs("The site asked for a payment. Nothing was paid and the application was stopped.")
        if action == "next":
            button.click()
            target.wait_for_timeout(800)
            continue
        current = read_fields(target)
        if preview:
            if action != "submit":
                gaps.append("Could not find a submit button. The page was left open and nothing was submitted.")
            return _filled_result(current, confirmed, gaps)
        issues = review_fields(current, confirmed, profile)
        if issues:
            return _needs("Stopped before submit. Required fields were not confirmed: " + "; ".join(issues[:8]))
        if action == "submit":
            return click_submit(target, button)
        return _needs("Could not find a submit button that is clearly an application submit.")
    return _needs("The application has more steps than this agent will follow automatically.")


class ApplicationSession:
    """One open application. Playwright is only used on the agent thread."""

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self.page = None
        self.job: Job | None = None

    def is_open(self) -> bool:
        return self.page is not None

    def close(self) -> None:
        browser, playwright = self._browser, self._playwright
        self.page = None
        self._browser = None
        self._playwright = None
        self.job = None
        try:
            if browser is not None:
                browser.close()
        except Exception:
            pass
        try:
            if playwright is not None:
                playwright.stop()
        except Exception:
            pass

    def open_and_fill(self, job, profile, secrets, home: Path, otp_reader, headless: bool, screenshot_path: Path | None) -> ApplyResult:
        self.close()
        url = safe_http_url(job.apply_url or job.url)
        if not url:
            return _failed("The listing has no application link.")
        host = url.split("/")[2].lower() if "//" in url else ""
        if any(token in host for token in LOGIN_HOSTS):
            return _needs("This site requires an account login. Login was not bypassed.")
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeout
            from playwright.sync_api import sync_playwright
        except ImportError:
            return _failed("Playwright is not installed. Run: python -m playwright install chromium")
        try:
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(headless=headless)
            page = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
            page.set_default_timeout(8000)
            self._playwright = playwright
            self._browser = browser
            self.page = page
            self.job = job
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            result = complete_application(page, job, profile, secrets, otp_reader, home, preview=True)
        except PlaywrightTimeout:
            self.close()
            return _failed("The application page did not load.")
        except Exception:
            self.close()
            return _needs("The browser stopped unexpectedly. The application was not submitted.")
        if result.status != "filled":
            if screenshot_path is not None and self.page is not None:
                _save_shot(self.page, screenshot_path, result)
            self.close()
            return result
        if screenshot_path is not None:
            _save_shot(page, screenshot_path, result)
        return result

    def submit(self) -> ApplyResult:
        if self.page is None:
            return _failed("No application is open.")
        blocked = detect_block(self.page)
        if blocked:
            self.close()
            return blocked
        action, button = find_action(self.page)
        if action != "submit" or button is None:
            return _needs("Could not find a submit button. The page was left open and nothing was submitted.")
        result = click_submit(self.page, button)
        self.close()
        return result

    def apply_answers(self, answers: dict[str, str]) -> ApplyResult:
        if self.page is None:
            return _failed("No application is open.")
        fields = read_fields(self.page)
        confirmed: set[int] = set()
        for field in fields:
            label = _question_text(field)
            for key, value in answers.items():
                if not key or not str(value).strip():
                    continue
                if key.casefold() in label.casefold() or label.casefold() in key.casefold():
                    try:
                        _locator(self.page, field).fill(str(value).strip())
                        confirmed.add(field["index"])
                    except Exception:
                        continue
        current = read_fields(self.page)
        return _filled_result(current, confirmed, [])


def _save_shot(page, path: Path, result: ApplyResult) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path), full_page=True)
        result.screenshot = str(path)
    except Exception:
        return


def apply_to_job(
    job: Job,
    profile: Profile,
    secrets: Secrets,
    home: Path,
    otp_reader=None,
    headless: bool | None = None,
    screenshot_path: Path | None = None,
) -> ApplyResult:
    url = safe_http_url(job.apply_url or job.url)
    if not url:
        return _failed("The listing has no application link.")
    host = url.split("/")[2].lower() if "//" in url else ""
    if any(token in host for token in LOGIN_HOSTS):
        return _needs("This site requires an account login. Login was not bypassed.")
    if headless is None:
        headless = default_headless()
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeout
        from playwright.sync_api import sync_playwright
    except ImportError:
        return _failed("Playwright is not installed. Run: python -m playwright install chromium")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=headless)
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()
            page.set_default_timeout(8000)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
            except PlaywrightTimeout:
                browser.close()
                return _failed("The application page did not load.")
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            result = complete_application(page, job, profile, secrets, otp_reader, home)
            if result.status == "needs_user" and screenshot_path is not None:
                try:
                    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(screenshot_path), full_page=True)
                    result.screenshot = str(screenshot_path)
                except Exception:
                    pass
            browser.close()
            return result
    except Exception:
        return _needs("The browser stopped unexpectedly. The application was not retried.")
