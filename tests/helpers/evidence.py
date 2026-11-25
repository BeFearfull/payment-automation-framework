"""Screenshot helpers for OTP evidence (no secrets written to logs)."""

from __future__ import annotations

import logging
from pathlib import Path

from playwright.sync_api import Page

ROOT = Path(__file__).resolve().parents[2]
OTP_EVIDENCE_DIR = ROOT / "artifacts" / "otp"

logger = logging.getLogger("tests.helpers.evidence")


def save_otp_screenshot(page: Page, name: str) -> Path:
    """
    Save a stage screenshot under artifacts/otp/.

    Does not write card/OTP values into log text.
    """
    OTP_EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    filename = name if name.endswith(".png") else f"{name}.png"
    path = OTP_EVIDENCE_DIR / filename
    page.screenshot(path=str(path), full_page=True)
    logger.info("Saved OTP evidence screenshot: %s", path.name)
    return path
