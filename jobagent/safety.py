"""Stops for captcha, payment, login, and unsafe listings.

Visible challenges are detected. Nothing here solves or skips them.
"""

from __future__ import annotations

import re

FEE_PATTERNS = [
    re.compile(pattern, re.I)
    for pattern in (
        r"application fee",
        r"processing fee",
        r"training fee",
        r"registration fee",
        r"pay to apply",
        r"fee to apply",
        r"payment required to (?:apply|start|join|register)",
        r"western union",
        r"gift cards?",
        r"pay in (?:crypto|cryptocurrency|bitcoin)",
        r"send (?:us )?(?:money|a payment)",
        r"upfront (?:payment|fee|deposit)",
        r"refundable deposit",
        r"purchase (?:a |the )?(?:starter |training )?(?:kit|equipment|package) (?:from|before)",
        r"whatsapp only",
        r"telegram only",
        r"include your social security",
        r"send (?:us )?your social security",
    )
]

_NEGATION = re.compile(r"\b(no|not|without|zero|never|don't|dont|do not|free of)\b", re.I)

CAPTCHA_SELECTORS = (
    "iframe[src*='recaptcha']",
    "iframe[src*='hcaptcha']",
    "iframe[src*='turnstile']",
    "iframe[src*='challenges.cloudflare.com']",
    "iframe[title*='captcha' i]",
    ".g-recaptcha",
    ".h-captcha",
    ".cf-turnstile",
    "#px-captcha",
)

CAPTCHA_TEXT = (
    "verify you are human",
    "i'm not a robot",
    "i am not a robot",
    "complete the captcha",
    "please complete the security check",
    "unusual traffic",
)

PAYMENT_SELECTORS = (
    "input[autocomplete='cc-number']",
    "input[autocomplete='cc-csc']",
    "input[name*='cardnumber' i]",
    "input[name*='card-number' i]",
    "iframe[src*='js.stripe.com']",
    "iframe[src*='paypal.com/']",
    "iframe[src*='braintree']",
)

LOGIN_TEXT = (
    "sign in to apply",
    "log in to apply",
    "login to apply",
    "create an account to apply",
    "sign in to continue",
    "please log in",
    "please sign in",
)

VERIFICATION_TEXT = (
    "upload a photo of your id",
    "upload your passport",
    "scan your passport",
    "take a selfie",
    "video identification",
    "provide your social security",
    "enter your social security",
)

OTP_HINT = re.compile(
    r"\botp\b|one[- ]time|verification code|security code|email code|authenticator|sign[- ]in code",
    re.I,
)
OTP_SKIP = re.compile(
    r"postal|zip|country code|area code|referral|promo|job code|discount|barcode",
    re.I,
)


def mentions_fee(text: str) -> bool:
    if not text:
        return False
    for pattern in FEE_PATTERNS:
        for match in pattern.finditer(text):
            window = text[max(0, match.start() - 60) : match.start()]
            if _NEGATION.search(window):
                continue
            return True
    return False


def captcha_in_text(text: str) -> bool:
    folded = (text or "").casefold()
    return any(phrase in folded for phrase in CAPTCHA_TEXT)


def verification_in_text(text: str) -> bool:
    folded = (text or "").casefold()
    return any(phrase in folded for phrase in VERIFICATION_TEXT)


def login_in_text(text: str) -> bool:
    folded = (text or "").casefold()
    return any(phrase in folded for phrase in LOGIN_TEXT)


def is_otp_field(label: str, name: str = "", field_id: str = "") -> bool:
    blob = f"{label} {name} {field_id}"
    if OTP_SKIP.search(blob):
        return False
    return bool(OTP_HINT.search(blob))


def is_payment_control(name: str) -> bool:
    return bool(re.search(r"\bpay\b|payment|checkout|billing|donate", name or "", re.I))


def is_login_control(name: str) -> bool:
    return bool(
        re.search(
            r"continue with|sign in with|log in with|sign in|log in|create an account|with linkedin|with google|with facebook",
            name or "",
            re.I,
        )
    )
