"""
UNIT-09..UNIT-15 / SEC helpers — verification session safety and API errors.

All Razorpay interactions here are mocked. Not live payments.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest
from razorpay.errors import SignatureVerificationError

from config.settings import FLASK_SECRET_KEY, PRODUCT, RAZORPAY_KEY_SECRET

logger = logging.getLogger("tests.payment.test_verification_security")


@pytest.mark.unit
@pytest.mark.payment
@pytest.mark.security
def test_unit_09_create_order_unexpected_error_returns_502(flask_client) -> None:
    """UNIT-09: Unexpected Razorpay/network failure maps to HTTP 502."""
    with patch("app.razorpay_client") as client:
        client.order.create.side_effect = RuntimeError("simulated upstream timeout")
        response = flask_client.post(
            "/create-order",
            json={
                "product_id": PRODUCT["id"],
                "quantity": 1,
                "client_request_id": "unit-timeout-sim",
            },
        )
    assert response.status_code == 502, response.get_json()
    body = response.get_json()
    assert "Order creation failed" in body["error"]
    assert RAZORPAY_KEY_SECRET not in str(body)
    logger.info("UNIT-09 passed: unexpected create-order error → 502")


@pytest.mark.unit
@pytest.mark.payment
@pytest.mark.security
def test_unit_10_verify_unexpected_error_returns_500(flask_client) -> None:
    """UNIT-10: Unexpected verification exception maps to HTTP 500."""
    with patch(
        "app.verify_payment_signature",
        side_effect=RuntimeError("simulated verify outage"),
    ):
        response = flask_client.post(
            "/verify-payment",
            json={
                "razorpay_order_id": "order_err",
                "razorpay_payment_id": "pay_err",
                "razorpay_signature": "sig_err",
            },
        )
    assert response.status_code == 500
    body = response.get_json()
    assert "Verification error" in body["error"]
    assert RAZORPAY_KEY_SECRET not in str(body)
    logger.info("UNIT-10 passed: unexpected verify error → 500")


@pytest.mark.unit
@pytest.mark.payment
@pytest.mark.security
def test_unit_11_failed_verify_clears_existing_success_session(flask_client) -> None:
    """
    UNIT-11: Failed verify clears an unverified/unprotected session.

    Phase 2: a fully verified (captured) session is protected from failed
    replays — covered by LIFE-12 / PAY-10. This case uses a non-protected
    session (flags set without recording the order as verified lifecycle).
    """
    with flask_client.session_transaction() as sess:
        sess["payment_verified"] = True
        sess["verified_payment"] = {
            "razorpay_order_id": "order_unprotected",
            "razorpay_payment_id": "pay_unprotected",
        }

    with patch(
        "app.verify_payment_signature",
        side_effect=SignatureVerificationError("bad"),
    ):
        bad = flask_client.post(
            "/verify-payment",
            json={
                "razorpay_order_id": "order_session_clear_2",
                "razorpay_payment_id": "pay_session_clear_2",
                "razorpay_signature": "bad",
            },
        )
    assert bad.status_code == 400
    with flask_client.session_transaction() as sess:
        assert sess.get("payment_verified") in (None, False)
        assert not sess.get("verified_payment")

    blocked = flask_client.get("/payment-success", follow_redirects=False)
    assert blocked.status_code in {302, 303}
    assert "/payment-failure" in blocked.headers.get("Location", "")
    logger.info("UNIT-11 passed: failed verify clears unprotected success session")


@pytest.mark.unit
@pytest.mark.payment
@pytest.mark.security
def test_unit_12_http_error_handlers_and_checkout_redirect(flask_client) -> None:
    """UNIT-12: 404/405 handlers and GET /checkout redirect."""
    not_found = flask_client.get("/no-such-route")
    assert not_found.status_code == 404
    assert not_found.get_json()["error"] == "Not found."
    assert RAZORPAY_KEY_SECRET not in not_found.data.decode("utf-8")

    method_not_allowed = flask_client.get("/create-order")
    assert method_not_allowed.status_code == 405
    assert method_not_allowed.get_json()["error"] == "Method not allowed."

    checkout = flask_client.get("/checkout", follow_redirects=False)
    assert checkout.status_code in {302, 303}
    assert checkout.headers.get("Location", "").endswith("/")
    logger.info("UNIT-12 passed: 404/405 and /checkout redirect")


@pytest.mark.unit
@pytest.mark.payment
@pytest.mark.security
def test_unit_13_error_bodies_never_include_secret(flask_client) -> None:
    """UNIT-13: Common error responses must not echo the key secret."""
    cases = [
        flask_client.post("/create-order", json=[]),
        flask_client.post("/create-order", json={"product_id": "x", "quantity": 1}),
        flask_client.post("/verify-payment", json={}),
        flask_client.post(
            "/verify-payment",
            json={
                "razorpay_order_id": "order_x",
                "razorpay_payment_id": "pay_x",
                "razorpay_signature": "bad",
            },
        ),
    ]
    for response in cases:
        blob = response.get_data(as_text=True)
        assert RAZORPAY_KEY_SECRET not in blob, blob[:200]
        assert "key_secret" not in blob.lower()
    logger.info("UNIT-13 passed: error bodies do not leak secrets")


@pytest.mark.unit
@pytest.mark.security
def test_unit_14_flask_secret_key_not_empty(flask_client) -> None:
    """
    UNIT-14: Flask secret key must be configured (warn if still the demo default).

    Does not fail CI on the documented demo default, but records the risk.
    """
    assert FLASK_SECRET_KEY, "FLASK_SECRET_KEY must not be empty"
    if FLASK_SECRET_KEY == "dev-only-change-me":
        logger.warning(
            "UNIT-14: FLASK_SECRET_KEY is still the demo default — "
            "change it before any shared/staging use"
        )
    # Session cookie signing still requires a non-empty key.
    with flask_client.session_transaction() as sess:
        sess["probe"] = True
    logger.info("UNIT-14 passed: Flask secret key present (length=%s)", len(FLASK_SECRET_KEY))


@pytest.mark.unit
@pytest.mark.payment
def test_unit_15_status_helper_rejects_non_success() -> None:
    """UNIT-15: payment status helper accepts only authorized/captured."""
    from tests.helpers.razorpay_status import assert_successful_test_status

    assert_successful_test_status("authorized")
    assert_successful_test_status("captured")
    for bad in ("failed", "created", "pending", "refunded", ""):
        with pytest.raises(AssertionError):
            assert_successful_test_status(bad)
    logger.info("UNIT-15 passed: status helper rejects non-success states")
