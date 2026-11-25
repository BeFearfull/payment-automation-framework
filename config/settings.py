"""Application settings loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            "Copy .env.example to .env and set Test Mode credentials."
        )
    return value


RAZORPAY_KEY_ID = _require_env("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = _require_env("RAZORPAY_KEY_SECRET")

if not RAZORPAY_KEY_ID.startswith("rzp_test_"):
    raise RuntimeError(
        "Only Razorpay Test Mode key IDs (rzp_test_*) are allowed in this project."
    )

FLASK_SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-only-change-me")
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "true").lower() in {"1", "true", "yes"}
FLASK_HOST = os.getenv("FLASK_HOST", "127.0.0.1")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))

# Documented Razorpay Test Mode OTP (never log this value in tests).
RAZORPAY_TEST_OTP = os.getenv("RAZORPAY_TEST_OTP", "1234").strip() or "1234"
# Observed Checkout iframe mock-ACS failure OTP: fewer than 4 digits.
# NOTE: Some Razorpay docs also list "5 digits starting with 1" (e.g. 12345) as a
# failure case, but Standard Checkout's in-iframe OTP challenge accepts 12345 and
# completes payment. AUTH-02 must use a short OTP (<4 digits). Never log this value.
RAZORPAY_TEST_OTP_FAIL = os.getenv("RAZORPAY_TEST_OTP_FAIL", "12").strip() or "12"

# Product catalogue used by the demo shop (amount in paise for Razorpay).
PRODUCT = {
    "id": "wireless-headphones",
    "name": "Wireless Headphones",
    "price_inr": 1499,
    "amount_paise": 149900,
    "currency": "INR",
    "description": "Noise-cancelling over-ear wireless headphones",
}
