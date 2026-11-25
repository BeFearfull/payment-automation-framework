"""WEB-10 .. WEB-12 — payment verification gate and success-page access control."""

from __future__ import annotations

import logging
import uuid

import pytest
from playwright.sync_api import Page

from tests.helpers.api import verify_payment
from tests.helpers.lifecycle_mocks import flask_session_cookie, mock_captured_lifecycle
from tests.pages.payment_page import PaymentPage

logger = logging.getLogger("tests.payment.test_payment")

PRICE_TEXT = "₹1,499"
PRODUCT_NAME = "Wireless Headphones"


def _inject_session_cookie(page: Page, base_url: str, session_value: str) -> None:
    page.context.add_cookies(
        [
            {
                "name": "session",
                "value": session_value,
                "url": base_url,
                "httpOnly": True,
            }
        ]
    )


@pytest.mark.payment
def test_web_10_success_only_after_server_verification(
    page: Page,
    base_url: str,
    payment_page: PaymentPage,
    flask_client,
) -> None:
    """
    WEB-10: Payment success is displayed only after server-side verification.

    Uses mocked signature + captured lifecycle (not a live Razorpay capture).
    Unverified access is checked against the live Test Mode app server.
    """
    # Negative: unverified browser session cannot open success.
    payment_page.open_success()
    payment_page.expect_redirected_away_from_success()
    logger.info("WEB-10 negative path: unverified access redirected to failure")

    order_id = f"order_gate_{uuid.uuid4().hex[:10]}"
    payment_id = f"pay_gate_{uuid.uuid4().hex[:10]}"

    with mock_captured_lifecycle(order_id=order_id, payment_id=payment_id):
        response = flask_client.post(
            "/verify-payment",
            json={
                "razorpay_order_id": order_id,
                "razorpay_payment_id": payment_id,
                "razorpay_signature": "mock-sig",
            },
        )
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body.get("status") in {"verified", "already_verified"}
    assert body.get("payment_status") == "captured"

    cookie_value = flask_session_cookie(flask_client)
    assert cookie_value, "Expected Flask session cookie after successful verify"
    _inject_session_cookie(page, base_url, cookie_value)

    payment_page.open_success()
    payment_page.expect_success(
        product_name=PRODUCT_NAME,
        amount_text=PRICE_TEXT,
        order_id=order_id,
        payment_id=payment_id,
    )
    logger.info(
        "WEB-10 passed: success page rendered only after verify-payment "
        "(mocked captured lifecycle; not a live Razorpay capture claim)."
    )


@pytest.mark.payment
def test_web_11_invalid_payment_signature_rejected(
    api_client,
    base_url: str,
) -> None:
    """WEB-11: Invalid payment signature is rejected."""
    response = verify_payment(
        api_client,
        base_url,
        razorpay_order_id="order_invalid_sig",
        razorpay_payment_id="pay_invalid_sig",
        razorpay_signature="0" * 64,
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert "signature" in body.get("error", "").lower()
    logger.info("WEB-11 passed: invalid signature rejected (%s)", body)


@pytest.mark.payment
def test_web_12_direct_success_access_without_verification_rejected(
    payment_page: PaymentPage,
) -> None:
    """WEB-12: Direct access to success page without verification is rejected."""
    payment_page.open_success()
    payment_page.expect_redirected_away_from_success()
    logger.info("WEB-12 passed: direct success access redirected to failure")
