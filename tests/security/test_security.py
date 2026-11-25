"""
SEC-01..SEC-06 — Security-focused checks (API + UI).

Uses Test Mode keys from .env only. Never logs secrets, PAN, CVV, or OTP.
"""

from __future__ import annotations

import logging
import re
import uuid

import pytest
import requests
from playwright.sync_api import Page, expect

from config.settings import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET
from tests.helpers.api import create_order, verify_payment
from tests.pages.home_page import HomePage
from tests.pages.payment_page import PaymentPage

logger = logging.getLogger("tests.security.test_security")


@pytest.mark.security
@pytest.mark.payment
def test_sec_01_direct_success_without_session_blocked(
    page: Page,
    base_url: str,
    payment_page: PaymentPage,
) -> None:
    """SEC-01: Direct /payment-success access without session is blocked."""
    page.context.clear_cookies()
    payment_page.open_success()
    payment_page.expect_redirected_away_from_success()
    expect(page.get_by_test_id("payment-success-page")).to_have_count(0)
    logger.info("SEC-01 passed: direct success access blocked")


@pytest.mark.security
@pytest.mark.payment
def test_sec_02_forged_session_cookie_does_not_unlock_success(
    page: Page,
    base_url: str,
    payment_page: PaymentPage,
) -> None:
    """SEC-02: A forged unsigned session cookie must not unlock success."""
    page.context.clear_cookies()
    page.context.add_cookies(
        [
            {
                "name": "session",
                "value": "forged.payload.signature",
                "url": base_url,
            }
        ]
    )
    payment_page.open_success()
    expect(page.get_by_test_id("payment-success-page")).to_have_count(0)
    payment_page.expect_redirected_away_from_success()
    logger.info("SEC-02 passed: forged session cookie rejected")


@pytest.mark.security
@pytest.mark.payment
def test_sec_03_responses_never_expose_secret_key(
    api_client,
    base_url: str,
    flask_client,
) -> None:
    """SEC-03: HTML and JSON surfaces never expose RAZORPAY_KEY_SECRET."""
    home = flask_client.get("/")
    assert RAZORPAY_KEY_SECRET not in home.get_data(as_text=True)

    order = create_order(api_client, base_url, client_request_id=str(uuid.uuid4()))
    assert order.status_code == 201
    assert RAZORPAY_KEY_SECRET not in order.text
    assert order.json()["key_id"] == RAZORPAY_KEY_ID
    assert order.json()["key_id"].startswith("rzp_test_")

    bad = verify_payment(
        api_client,
        base_url,
        razorpay_order_id="order_sec",
        razorpay_payment_id="pay_sec",
        razorpay_signature="0" * 64,
    )
    assert RAZORPAY_KEY_SECRET not in bad.text
    logger.info("SEC-03 passed: secret not exposed in responses")


@pytest.mark.security
@pytest.mark.payment
def test_sec_04_failed_verify_never_creates_success_session(
    api_client,
    base_url: str,
) -> None:
    """SEC-04: Failed verification must not unlock /payment-success for that client."""
    session = requests.Session()
    response = verify_payment(
        session,
        base_url,
        razorpay_order_id="order_sec_fail",
        razorpay_payment_id="pay_sec_fail",
        razorpay_signature="not-valid",
    )
    assert response.status_code == 400

    success = session.get(f"{base_url}/payment-success", allow_redirects=False, timeout=30)
    assert success.status_code in {302, 303}
    assert "/payment-failure" in success.headers.get("Location", "")
    logger.info("SEC-04 passed: failed verify does not create success session")


@pytest.mark.security
@pytest.mark.payment
def test_sec_05_concurrent_duplicate_verify_stays_consistent(flask_client) -> None:
    """
    SEC-05: Parallel identical verifies remain consistent (verified / already_verified).

    Mocked captured lifecycle — not a live Razorpay capture.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from tests.helpers.lifecycle_mocks import mock_captured_lifecycle

    order_id = f"order_conc_{uuid.uuid4().hex[:8]}"
    payment_id = f"pay_conc_{uuid.uuid4().hex[:8]}"
    payload = {
        "razorpay_order_id": order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": "mock-sig",
    }

    def _once() -> tuple[int, str]:
        # Flask test client is not fully thread-safe; use app context + fresh client.
        from app import app

        with app.test_client() as client:
            response = client.post("/verify-payment", json=payload)
            body = response.get_json() or {}
            return response.status_code, str(body.get("status", ""))

    results: list[tuple[int, str]] = []
    with mock_captured_lifecycle(order_id=order_id, payment_id=payment_id):
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(_once) for _ in range(4)]
            for future in as_completed(futures):
                results.append(future.result())

    assert all(status == 200 for status, _ in results), results
    statuses = {status_name for _, status_name in results}
    assert statuses <= {"verified", "already_verified"}, statuses
    assert "verified" in statuses
    logger.info("SEC-05 passed: concurrent verifies statuses=%s", results)


@pytest.mark.security
@pytest.mark.web
def test_sec_06_homepage_config_exposes_public_key_only(
    home_page: HomePage,
    page: Page,
) -> None:
    """SEC-06: window.APP_CONFIG / page source expose public key id only."""
    home_page.open()
    html = page.content()
    assert RAZORPAY_KEY_SECRET not in html
    assert "key_secret" not in html.lower()
    # Public test key may appear; secret must not.
    assert RAZORPAY_KEY_ID.startswith("rzp_test_")
    config_blob = page.evaluate("() => JSON.stringify(window.APP_CONFIG || {})")
    assert RAZORPAY_KEY_SECRET not in config_blob
    assert not re.search(r"rzp_live_", config_blob)
    logger.info("SEC-06 passed: APP_CONFIG has no secret / live key")
