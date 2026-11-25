"""WEB-10 .. WEB-12 — payment verification gate and success-page access control."""

from __future__ import annotations

import logging
import uuid

import pytest
from playwright.sync_api import Page

from tests.helpers.api import make_test_signature, verify_payment
from tests.pages.payment_page import PaymentPage

logger = logging.getLogger("tests.payment.test_payment")

PRICE_TEXT = "₹1,499"
PRODUCT_NAME = "Wireless Headphones"


def _inject_session_cookies(page: Page, base_url: str, requests_session) -> None:
    cookies = []
    for cookie in requests_session.cookies:
        cookies.append(
            {
                "name": cookie.name,
                "value": cookie.value,
                "url": base_url,
                "httpOnly": True,
            }
        )
    if cookies:
        page.context.add_cookies(cookies)


@pytest.mark.payment
def test_web_10_success_only_after_server_verification(
    page: Page,
    base_url: str,
    payment_page: PaymentPage,
) -> None:
    """
    WEB-10: Payment success is displayed only after server-side verification.

    Uses a locally computed Test Mode HMAC to exercise the verification gate.
    This does not create or claim a live Razorpay captured payment.
    """
    # Negative: unverified browser session cannot open success.
    payment_page.open_success()
    payment_page.expect_redirected_away_from_success()
    logger.info("WEB-10 negative path: unverified access redirected to failure")

    # Positive gate: valid server-side signature unlocks success page.
    import requests

    order_id = f"order_gate_{uuid.uuid4().hex[:10]}"
    payment_id = f"pay_gate_{uuid.uuid4().hex[:10]}"
    signature = make_test_signature(order_id, payment_id)

    api = requests.Session()
    response = verify_payment(
        api,
        base_url,
        razorpay_order_id=order_id,
        razorpay_payment_id=payment_id,
        razorpay_signature=signature,
    )
    assert response.status_code == 200, response.text
    assert response.json().get("status") in {"verified", "already_verified"}

    _inject_session_cookies(page, base_url, api)
    payment_page.open_success()
    payment_page.expect_success(
        product_name=PRODUCT_NAME,
        amount_text=PRICE_TEXT,
        order_id=order_id,
        payment_id=payment_id,
    )
    logger.info(
        "WEB-10 passed: success page rendered only after verify-payment. "
        "Note: signature was computed for gate testing; not a live Razorpay capture."
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
