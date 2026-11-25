"""
Payment edge cases against the live Test Mode app server.

These tests exercise our Flask verification/order gates.
HMAC-based success paths validate server-side signature checking only —
they are not live Razorpay captured transactions.
"""

from __future__ import annotations

import logging
import uuid

import pytest
from playwright.sync_api import Page, expect

from tests.helpers.api import create_order, make_test_signature, post_raw, verify_payment
from tests.pages.checkout_page import CheckoutPage
from tests.pages.home_page import HomePage
from tests.pages.payment_page import PaymentPage

logger = logging.getLogger("tests.payment.test_payment_edge_cases")


@pytest.mark.payment
def test_pay_01_missing_order_id_rejected(api_client, base_url: str) -> None:
    """Missing order ID is rejected."""
    response = verify_payment(
        api_client,
        base_url,
        payload={
            "razorpay_payment_id": "pay_missing_order",
            "razorpay_signature": "abc",
        },
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert "razorpay_order_id" in body.get("missing", [])
    logger.info("PAY-01 passed: missing order id rejected")


@pytest.mark.payment
def test_pay_02_missing_payment_id_rejected(api_client, base_url: str) -> None:
    """Missing payment ID is rejected."""
    response = verify_payment(
        api_client,
        base_url,
        payload={
            "razorpay_order_id": "order_missing_pay",
            "razorpay_signature": "abc",
        },
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert "razorpay_payment_id" in body.get("missing", [])
    logger.info("PAY-02 passed: missing payment id rejected")


@pytest.mark.payment
def test_pay_03_invalid_signature_rejected(api_client, base_url: str) -> None:
    """Invalid signature is rejected."""
    response = verify_payment(
        api_client,
        base_url,
        razorpay_order_id="order_bad_sig",
        razorpay_payment_id="pay_bad_sig",
        razorpay_signature="not-a-valid-hmac-signature",
    )
    assert response.status_code == 400, response.text
    assert "signature" in response.json().get("error", "").lower()
    logger.info("PAY-03 passed: invalid signature rejected")


@pytest.mark.payment
def test_pay_04_wrong_order_id_rejected(api_client, base_url: str) -> None:
    """
    Signature computed for order A must not validate when order B is submitted.

    Gate-only check using local HMAC — not a live Razorpay transaction.
    """
    order_a = f"order_a_{uuid.uuid4().hex[:8]}"
    order_b = f"order_b_{uuid.uuid4().hex[:8]}"
    payment_id = f"pay_{uuid.uuid4().hex[:8]}"
    signature_for_a = make_test_signature(order_a, payment_id)

    response = verify_payment(
        api_client,
        base_url,
        razorpay_order_id=order_b,
        razorpay_payment_id=payment_id,
        razorpay_signature=signature_for_a,
    )
    assert response.status_code == 400, response.text
    assert "signature" in response.json().get("error", "").lower()
    logger.info("PAY-04 passed: wrong order id rejected")


@pytest.mark.payment
def test_pay_05_repeated_verification_request(flask_client) -> None:
    """
    Repeated verify with the same valid captured lifecycle is idempotent.

    Mocked signature + captured fetch — not a live Razorpay capture.
    """
    from tests.helpers.lifecycle_mocks import mock_captured_lifecycle

    order_id = f"order_repeat_{uuid.uuid4().hex[:8]}"
    payment_id = f"pay_repeat_{uuid.uuid4().hex[:8]}"
    payload = {
        "razorpay_order_id": order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": "mock-sig",
    }

    with mock_captured_lifecycle(order_id=order_id, payment_id=payment_id):
        first = flask_client.post("/verify-payment", json=payload)
        second = flask_client.post("/verify-payment", json=payload)

    assert first.status_code == 200, first.get_json()
    assert first.get_json().get("status") == "verified"
    assert first.get_json().get("payment_status") == "captured"
    assert second.status_code == 200, second.get_json()
    assert second.get_json().get("status") == "already_verified"
    logger.info("PAY-05 passed: repeated verification is idempotent")


@pytest.mark.payment
def test_pay_06_expired_or_invalid_session_blocked(
    page: Page,
    base_url: str,
    payment_page: PaymentPage,
    flask_client,
) -> None:
    """Clearing session cookies after verify blocks success access."""
    from tests.helpers.lifecycle_mocks import flask_session_cookie, mock_captured_lifecycle

    order_id = f"order_sess_{uuid.uuid4().hex[:8]}"
    payment_id = f"pay_sess_{uuid.uuid4().hex[:8]}"

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
    cookie_value = flask_session_cookie(flask_client)
    assert cookie_value
    page.context.add_cookies(
        [{"name": "session", "value": cookie_value, "url": base_url, "httpOnly": True}]
    )

    # Simulate expired/invalid session: no cookies in the browser.
    page.context.clear_cookies()
    payment_page.open_success()
    payment_page.expect_redirected_away_from_success()
    logger.info("PAY-06 passed: cleared session cannot open success")


@pytest.mark.payment
def test_pay_07_failed_payment_callback_shows_failure(
    payment_page: PaymentPage,
) -> None:
    """
    Simulated failed Checkout callback lands on the failure page.

    Mirrors frontend payment.failed redirect behaviour — not a live decline event.
    """
    reason = "Payment failed at Razorpay Checkout (simulated)."
    payment_page.page.goto(
        f"{payment_page.base_url}/payment-failure?reason={reason}",
        wait_until="domcontentloaded",
    )
    payment_page.expect_failure()
    expect(payment_page.failure_message).to_contain_text("simulated")
    logger.info("PAY-07 passed: failed callback path shows failure page")


@pytest.mark.payment
def test_pay_08_malformed_request_body_rejected(api_client, base_url: str) -> None:
    """Malformed verify-payment bodies are rejected."""
    empty = post_raw(
        api_client,
        base_url,
        "/verify-payment",
        data=b"",
        content_type="application/json",
    )
    assert empty.status_code == 400, empty.text

    array_body = post_raw(
        api_client,
        base_url,
        "/verify-payment",
        data=b"[1,2,3]",
        content_type="application/json",
    )
    assert array_body.status_code == 400, array_body.text
    assert "JSON object" in array_body.json().get("error", "")

    plain = post_raw(
        api_client,
        base_url,
        "/verify-payment",
        data=b"not-json",
        content_type="text/plain",
    )
    assert plain.status_code == 400, plain.text

    whitespace = verify_payment(
        api_client,
        base_url,
        razorpay_order_id="   ",
        razorpay_payment_id="pay_x",
        razorpay_signature="sig_x",
    )
    assert whitespace.status_code == 400, whitespace.text
    logger.info("PAY-08 passed: malformed bodies rejected")


@pytest.mark.payment
def test_pay_09_duplicate_checkout_submission_ui(
    home_page: HomePage,
    checkout_page: CheckoutPage,
) -> None:
    """Duplicate checkout clicks are gated by disabled button / in-flight lock."""
    home_page.open()
    home_page.add_to_cart()
    checkout_page.expect_checkout_enabled()

    order = checkout_page.start_checkout_and_wait_for_order()
    assert order.get("order_id", "").startswith("order_")
    # After click, button is disabled while order/checkout is in flight.
    expect(checkout_page.proceed_to_payment_button).to_be_disabled()
    logger.info("PAY-09 passed: duplicate checkout submission blocked in UI")


@pytest.mark.payment
def test_pay_10_replay_forged_payment_id_after_verify_rejected(flask_client) -> None:
    """
    After a verified order, replaying with a forged payment_id must fail.

    Also asserts the verified session is preserved (Phase 2 failed-replay rule).
    """
    from unittest.mock import patch

    from razorpay.errors import SignatureVerificationError

    from tests.helpers.lifecycle_mocks import mock_captured_lifecycle

    order_id = f"order_forge_{uuid.uuid4().hex[:8]}"
    payment_id = f"pay_real_{uuid.uuid4().hex[:8]}"

    with mock_captured_lifecycle(order_id=order_id, payment_id=payment_id):
        first = flask_client.post(
            "/verify-payment",
            json={
                "razorpay_order_id": order_id,
                "razorpay_payment_id": payment_id,
                "razorpay_signature": "mock-sig",
            },
        )
    assert first.status_code == 200, first.get_json()

    with patch(
        "app.verify_payment_signature",
        side_effect=SignatureVerificationError("forged"),
    ):
        forged = flask_client.post(
            "/verify-payment",
            json={
                "razorpay_order_id": order_id,
                "razorpay_payment_id": "pay_forged_attacker",
                "razorpay_signature": "0" * 64,
            },
        )
    assert forged.status_code == 400, forged.get_json()
    assert "signature" in forged.get_json().get("error", "").lower()

    with flask_client.session_transaction() as sess:
        assert sess.get("payment_verified") is True
        assert sess["verified_payment"]["razorpay_order_id"] == order_id
        assert sess["verified_payment"]["razorpay_payment_id"] == payment_id

    success = flask_client.get("/payment-success", follow_redirects=False)
    assert success.status_code == 200
    assert b"payment-success-page" in success.data
    logger.info("PAY-10 passed: forged replay rejected; verified session preserved")


@pytest.mark.payment
def test_pay_11_create_order_missing_client_request_id(
    api_client,
    base_url: str,
) -> None:
    """Order creation without client_request_id is rejected."""
    response = api_client.post(
        f"{base_url}/create-order",
        json={"product_id": "wireless-headphones", "quantity": 1},
        timeout=30,
    )
    assert response.status_code == 400, response.text
    assert "client_request_id" in response.json().get("error", "")
    logger.info("PAY-11 passed: missing client_request_id rejected")


@pytest.mark.payment
def test_pay_12_create_order_response_never_leaks_secret(
    api_client,
    base_url: str,
) -> None:
    """Successful order response must not expose the key secret."""
    response = create_order(api_client, base_url, client_request_id=str(uuid.uuid4()))
    assert response.status_code == 201, response.text
    body = response.json()
    blob = str(body).lower()
    assert "key_secret" not in blob
    assert "secret" not in blob
    assert body.get("key_id", "").startswith("rzp_test_")
    logger.info("PAY-12 passed: order response has public key only")
