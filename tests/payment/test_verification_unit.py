"""
Isolated unit tests with mocks.

These do NOT contact Razorpay and must not be treated as real transactions.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
from razorpay.errors import BadRequestError, SignatureVerificationError

logger = logging.getLogger("tests.payment.test_verification_unit")


@pytest.mark.unit
@pytest.mark.payment
def test_unit_01_verify_missing_fields_mocked(flask_client) -> None:
    """Unit: missing verification fields return 400 without calling Razorpay."""
    with patch("app.verify_payment_signature") as mocked:
        response = flask_client.post("/verify-payment", json={})
        assert response.status_code == 400
        assert set(response.get_json()["missing"]) == {
            "razorpay_order_id",
            "razorpay_payment_id",
            "razorpay_signature",
        }
        mocked.assert_not_called()
    logger.info("UNIT-01 passed: missing fields short-circuit (mocked)")


@pytest.mark.unit
@pytest.mark.payment
def test_unit_02_verify_invalid_signature_mocked(flask_client) -> None:
    """Unit: SignatureVerificationError maps to HTTP 400."""
    with patch(
        "app.verify_payment_signature",
        side_effect=SignatureVerificationError("Razorpay Signature Verification Failed"),
    ):
        response = flask_client.post(
            "/verify-payment",
            json={
                "razorpay_order_id": "order_mock",
                "razorpay_payment_id": "pay_mock",
                "razorpay_signature": "bad",
            },
        )
    assert response.status_code == 400
    assert "signature" in response.get_json()["error"].lower()
    logger.info("UNIT-02 passed: mocked invalid signature → 400")


@pytest.mark.unit
@pytest.mark.payment
def test_unit_03_verify_success_sets_session_mocked(flask_client) -> None:
    """Unit: successful mocked verify + captured lifecycle sets session flags."""
    from tests.helpers.lifecycle_mocks import mock_captured_lifecycle

    with mock_captured_lifecycle(order_id="order_mock_ok", payment_id="pay_mock_ok"):
        response = flask_client.post(
            "/verify-payment",
            json={
                "razorpay_order_id": "order_mock_ok",
                "razorpay_payment_id": "pay_mock_ok",
                "razorpay_signature": "valid-mock",
            },
        )
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "verified"
    assert body["payment_status"] == "captured"
    assert body["redirect_url"] == "/payment-success"

    with flask_client.session_transaction() as sess:
        assert sess.get("payment_verified") is True
        assert sess["verified_payment"]["razorpay_order_id"] == "order_mock_ok"
        assert sess["verified_payment"]["payment_status"] == "captured"

    success = flask_client.get("/payment-success", follow_redirects=False)
    assert success.status_code == 200
    assert b"payment-success-page" in success.data
    logger.info("UNIT-03 passed: mocked captured verify unlocks success session")


@pytest.mark.unit
@pytest.mark.payment
def test_unit_04_success_without_session_redirects(flask_client) -> None:
    """Unit: success page redirects when session is empty."""
    response = flask_client.get("/payment-success", follow_redirects=False)
    assert response.status_code in {302, 303}
    assert "/payment-failure" in response.headers.get("Location", "")
    logger.info("UNIT-04 passed: empty session blocked from success")


@pytest.mark.unit
@pytest.mark.payment
def test_unit_05_create_order_duplicate_mocked(flask_client) -> None:
    """Unit: duplicate client_request_id returns 409 without second Razorpay call."""
    import uuid

    request_id = f"dup-unit-{uuid.uuid4().hex[:12]}"
    fake_order = {
        "id": "order_mock_dup",
        "amount": 149900,
        "currency": "INR",
        "receipt": "rcpt_mock",
    }
    with patch("app.razorpay_client") as client:
        client.order.create.return_value = fake_order
        first = flask_client.post(
            "/create-order",
            json={
                "product_id": "wireless-headphones",
                "quantity": 1,
                "client_request_id": request_id,
            },
        )
        second = flask_client.post(
            "/create-order",
            json={
                "product_id": "wireless-headphones",
                "quantity": 1,
                "client_request_id": request_id,
            },
        )

    assert first.status_code == 201, first.get_json()
    assert second.status_code == 409
    assert client.order.create.call_count == 1
    logger.info("UNIT-05 passed: mocked duplicate checkout submission → 409")


@pytest.mark.unit
@pytest.mark.payment
def test_unit_06_create_order_razorpay_rejection_mocked(flask_client) -> None:
    """Unit: Razorpay BadRequestError surfaces as 400."""
    with patch("app.razorpay_client") as client:
        client.order.create.side_effect = BadRequestError("amount invalid")
        response = flask_client.post(
            "/create-order",
            json={
                "product_id": "wireless-headphones",
                "quantity": 1,
                "client_request_id": "unit-bad-request",
            },
        )
    assert response.status_code == 400
    assert "Unable to create order" in response.get_json()["error"]
    logger.info("UNIT-06 passed: mocked Razorpay rejection → 400")


@pytest.mark.unit
@pytest.mark.payment
def test_unit_07_homepage_does_not_embed_secret(flask_client) -> None:
    """Unit: rendered homepage HTML must not contain the secret key."""
    from config.settings import RAZORPAY_KEY_SECRET

    response = flask_client.get("/")
    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert RAZORPAY_KEY_SECRET not in html
    assert "key_secret" not in html.lower()
    logger.info("UNIT-07 passed: secret not embedded in homepage")


@pytest.mark.unit
@pytest.mark.payment
def test_unit_08_utility_verify_wrapper_mocked() -> None:
    """Unit: payment_verification helper delegates to SDK utility."""
    from utils.payment_verification import verify_payment_signature

    client = MagicMock()
    client.utility.verify_payment_signature.return_value = True

    result = verify_payment_signature(
        client,
        razorpay_order_id="order_x",
        razorpay_payment_id="pay_x",
        razorpay_signature="sig_x",
    )
    assert result is True
    client.utility.verify_payment_signature.assert_called_once_with(
        {
            "razorpay_order_id": "order_x",
            "razorpay_payment_id": "pay_x",
            "razorpay_signature": "sig_x",
        }
    )
    logger.info("UNIT-08 passed: helper delegates to SDK (mocked)")
