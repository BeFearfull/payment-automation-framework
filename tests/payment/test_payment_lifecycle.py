"""
LIFE-01..LIFE-14 — Phase 2 secure payment lifecycle verification.

All Razorpay payment/order fetches here are mocked unless noted.
These are not live captures.
"""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import MagicMock, patch

import pytest
from razorpay.errors import SignatureVerificationError

from config.settings import PRODUCT
from tests.helpers.lifecycle_mocks import (
    captured_payment,
    matching_order,
    mock_captured_lifecycle,
)
from utils.payment_verification import (
    PaymentLifecycleError,
    validate_payment_lifecycle,
    verify_payment_lifecycle,
)

logger = logging.getLogger("tests.payment.test_payment_lifecycle")


def _verify(flask_client, order_id: str, payment_id: str, signature: str = "mock-sig"):
    return flask_client.post(
        "/verify-payment",
        json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": payment_id,
            "razorpay_signature": signature,
        },
    )


@pytest.mark.unit
@pytest.mark.payment
def test_life_01_valid_signature_captured_unlocks_success(flask_client) -> None:
    """LIFE-01: Valid signature + captured payment unlocks success session."""
    order_id = f"order_life1_{uuid.uuid4().hex[:8]}"
    payment_id = f"pay_life1_{uuid.uuid4().hex[:8]}"
    with mock_captured_lifecycle(order_id=order_id, payment_id=payment_id):
        response = _verify(flask_client, order_id, payment_id)
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["status"] == "verified"
    assert body["payment_status"] == "captured"
    assert body["redirect_url"] == "/payment-success"
    success = flask_client.get("/payment-success", follow_redirects=False)
    assert success.status_code == 200
    assert b"payment-success-page" in success.data
    logger.info("LIFE-01 passed: captured payment unlocks success")


@pytest.mark.unit
@pytest.mark.payment
def test_life_02_authorized_does_not_unlock_success(flask_client) -> None:
    """LIFE-02: Authorized but uncaptured payment must not unlock success."""
    order_id = f"order_life2_{uuid.uuid4().hex[:8]}"
    payment_id = f"pay_life2_{uuid.uuid4().hex[:8]}"
    with patch("app.verify_payment_signature", return_value=True):
        with patch(
            "app.verify_payment_lifecycle",
            side_effect=PaymentLifecycleError(
                "Payment is authorized but not captured; success is not granted.",
                code="authorized_not_captured",
                payment_status="authorized",
            ),
        ):
            response = _verify(flask_client, order_id, payment_id)
    assert response.status_code == 400
    body = response.get_json()
    assert body.get("code") == "authorized_not_captured"
    assert body.get("payment_status") == "authorized"
    blocked = flask_client.get("/payment-success", follow_redirects=False)
    assert blocked.status_code in {302, 303}
    logger.info("LIFE-02 passed: authorized does not unlock success")


@pytest.mark.unit
@pytest.mark.payment
def test_life_03_failed_payment_does_not_unlock_success(flask_client) -> None:
    """LIFE-03: Valid signature + failed payment status is rejected."""
    order_id = f"order_life3_{uuid.uuid4().hex[:8]}"
    payment_id = f"pay_life3_{uuid.uuid4().hex[:8]}"
    with patch("app.verify_payment_signature", return_value=True):
        with patch(
            "app.verify_payment_lifecycle",
            side_effect=PaymentLifecycleError(
                "Payment status is failed; success is not granted.",
                code="payment_failed",
                payment_status="failed",
            ),
        ):
            response = _verify(flask_client, order_id, payment_id)
    assert response.status_code == 400
    assert response.get_json().get("code") == "payment_failed"
    logger.info("LIFE-03 passed: failed payment rejected")


@pytest.mark.unit
@pytest.mark.payment
def test_life_04_created_payment_does_not_unlock_success(flask_client) -> None:
    """LIFE-04: Valid signature + created/pending payment is rejected."""
    order_id = f"order_life4_{uuid.uuid4().hex[:8]}"
    payment_id = f"pay_life4_{uuid.uuid4().hex[:8]}"
    with patch("app.verify_payment_signature", return_value=True):
        with patch(
            "app.verify_payment_lifecycle",
            side_effect=PaymentLifecycleError(
                "Payment status is created/pending; success is not granted.",
                code="payment_pending",
                payment_status="created",
            ),
        ):
            response = _verify(flask_client, order_id, payment_id)
    assert response.status_code == 400
    assert response.get_json().get("code") == "payment_pending"
    logger.info("LIFE-04 passed: created payment rejected")


@pytest.mark.unit
@pytest.mark.payment
def test_life_05_invalid_signature_rejected(flask_client) -> None:
    """LIFE-05: Invalid signature is rejected before lifecycle fetch."""
    with patch(
        "app.verify_payment_signature",
        side_effect=SignatureVerificationError("bad"),
    ) as mocked_sig:
        with patch("app.verify_payment_lifecycle") as mocked_life:
            response = _verify(
                flask_client,
                "order_bad_sig",
                "pay_bad_sig",
                signature="bad",
            )
            mocked_life.assert_not_called()
    assert response.status_code == 400
    assert "signature" in response.get_json()["error"].lower()
    mocked_sig.assert_called_once()
    logger.info("LIFE-05 passed: invalid signature short-circuits lifecycle")


@pytest.mark.unit
@pytest.mark.payment
def test_life_06_mismatched_order_id_rejected() -> None:
    """LIFE-06: Payment belonging to another order is rejected."""
    payment = captured_payment(
        order_id="order_other",
        payment_id="pay_x",
        status="captured",
    )
    order = matching_order(order_id="order_expected")
    with pytest.raises(PaymentLifecycleError) as exc:
        validate_payment_lifecycle(
            payment,
            order,
            expected_order_id="order_expected",
            expected_amount=PRODUCT["amount_paise"],
            expected_currency=PRODUCT["currency"],
        )
    assert exc.value.code == "payment_order_mismatch"
    logger.info("LIFE-06 passed: mismatched payment order_id rejected")


@pytest.mark.unit
@pytest.mark.payment
def test_life_07_mismatched_amount_rejected() -> None:
    """LIFE-07: Amount mismatch vs order/catalog is rejected."""
    payment = captured_payment(
        order_id="order_amt",
        payment_id="pay_amt",
        amount=100,
        status="captured",
    )
    order = matching_order(order_id="order_amt", amount=100)
    with pytest.raises(PaymentLifecycleError) as exc:
        validate_payment_lifecycle(
            payment,
            order,
            expected_order_id="order_amt",
            expected_amount=PRODUCT["amount_paise"],
            expected_currency=PRODUCT["currency"],
        )
    assert exc.value.code == "amount_mismatch"
    logger.info("LIFE-07 passed: amount mismatch rejected")


@pytest.mark.unit
@pytest.mark.payment
def test_life_08_mismatched_currency_rejected() -> None:
    """LIFE-08: Currency mismatch is rejected."""
    payment = captured_payment(
        order_id="order_cur",
        payment_id="pay_cur",
        currency="USD",
        status="captured",
    )
    order = matching_order(order_id="order_cur", currency="USD")
    with pytest.raises(PaymentLifecycleError) as exc:
        validate_payment_lifecycle(
            payment,
            order,
            expected_order_id="order_cur",
            expected_amount=PRODUCT["amount_paise"],
            expected_currency=PRODUCT["currency"],
        )
    assert exc.value.code == "currency_mismatch"
    logger.info("LIFE-08 passed: currency mismatch rejected")


@pytest.mark.unit
@pytest.mark.payment
def test_life_09_payment_fetch_api_failure(flask_client) -> None:
    """LIFE-09: payment.fetch API failure does not unlock success."""
    with patch("app.verify_payment_signature", return_value=True):
        with patch(
            "app.verify_payment_lifecycle",
            side_effect=PaymentLifecycleError(
                "Unable to fetch payment or order from Razorpay.",
                http_status=400,
                code="fetch_bad_request",
            ),
        ):
            response = _verify(flask_client, "order_fetch_fail", "pay_fetch_fail")
    assert response.status_code == 400
    assert response.get_json().get("code") == "fetch_bad_request"
    blocked = flask_client.get("/payment-success", follow_redirects=False)
    assert blocked.status_code in {302, 303}
    logger.info("LIFE-09 passed: fetch API failure rejected")


@pytest.mark.unit
@pytest.mark.payment
def test_life_10_payment_fetch_timeout(flask_client) -> None:
    """LIFE-10: Fetch timeout/network error maps to safe failure (502)."""
    with patch("app.verify_payment_signature", return_value=True):
        with patch(
            "app.verify_payment_lifecycle",
            side_effect=PaymentLifecycleError(
                "Razorpay payment fetch failed.",
                http_status=502,
                code="fetch_failed",
            ),
        ):
            response = _verify(flask_client, "order_timeout", "pay_timeout")
    assert response.status_code == 502
    assert response.get_json().get("code") == "fetch_failed"
    logger.info("LIFE-10 passed: fetch timeout → 502")


@pytest.mark.unit
@pytest.mark.payment
def test_life_11_repeated_successful_verification(flask_client) -> None:
    """LIFE-11: Repeated successful verification remains idempotent."""
    order_id = f"order_life11_{uuid.uuid4().hex[:8]}"
    payment_id = f"pay_life11_{uuid.uuid4().hex[:8]}"
    with mock_captured_lifecycle(order_id=order_id, payment_id=payment_id):
        first = _verify(flask_client, order_id, payment_id)
        second = _verify(flask_client, order_id, payment_id)
    assert first.get_json()["status"] == "verified"
    assert second.get_json()["status"] == "already_verified"
    assert second.get_json()["payment_status"] == "captured"
    logger.info("LIFE-11 passed: repeated successful verification")


@pytest.mark.unit
@pytest.mark.payment
@pytest.mark.security
def test_life_12_failed_replay_after_success_preserves_session(flask_client) -> None:
    """LIFE-12: Failed replay after success must not overwrite verified session."""
    order_id = f"order_life12_{uuid.uuid4().hex[:8]}"
    payment_id = f"pay_life12_{uuid.uuid4().hex[:8]}"
    with mock_captured_lifecycle(order_id=order_id, payment_id=payment_id):
        ok = _verify(flask_client, order_id, payment_id)
    assert ok.status_code == 200

    with patch(
        "app.verify_payment_signature",
        side_effect=SignatureVerificationError("replay"),
    ):
        bad = _verify(flask_client, order_id, "pay_attacker", signature="bad")
    assert bad.status_code == 400

    with flask_client.session_transaction() as sess:
        assert sess.get("payment_verified") is True
        assert sess["verified_payment"]["razorpay_payment_id"] == payment_id

    success = flask_client.get("/payment-success", follow_redirects=False)
    assert success.status_code == 200
    logger.info("LIFE-12 passed: failed replay preserves verified session")


@pytest.mark.unit
@pytest.mark.payment
@pytest.mark.security
def test_life_13_direct_success_access_blocked(flask_client) -> None:
    """LIFE-13: Direct success-page access without session is blocked."""
    response = flask_client.get("/payment-success", follow_redirects=False)
    assert response.status_code in {302, 303}
    assert "/payment-failure" in response.headers.get("Location", "")
    logger.info("LIFE-13 passed: direct success access blocked")


@pytest.mark.unit
@pytest.mark.payment
@pytest.mark.security
def test_life_14_concurrent_verification_requests() -> None:
    """LIFE-14: Concurrent captured verifies stay consistent."""
    from app import app

    order_id = f"order_life14_{uuid.uuid4().hex[:8]}"
    payment_id = f"pay_life14_{uuid.uuid4().hex[:8]}"
    payload = {
        "razorpay_order_id": order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": "mock-sig",
    }

    def _once() -> tuple[int, str]:
        with app.test_client() as client:
            response = client.post("/verify-payment", json=payload)
            body = response.get_json() or {}
            return response.status_code, str(body.get("status", ""))

    with mock_captured_lifecycle(order_id=order_id, payment_id=payment_id):
        results: list[tuple[int, str]] = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(_once) for _ in range(4)]
            for future in as_completed(futures):
                results.append(future.result())

    assert all(code == 200 for code, _ in results), results
    statuses = {name for _, name in results}
    assert statuses <= {"verified", "already_verified"}
    assert "verified" in statuses
    logger.info("LIFE-14 passed: concurrent verification statuses=%s", results)


@pytest.mark.unit
@pytest.mark.payment
def test_life_15_verify_lifecycle_helper_uses_sdk_fetch() -> None:
    """LIFE-15: verify_payment_lifecycle fetches payment+order via SDK client."""
    order_id = "order_helper"
    payment_id = "pay_helper"
    client = MagicMock()
    client.payment.fetch.return_value = captured_payment(
        order_id=order_id,
        payment_id=payment_id,
        status="captured",
    )
    client.order.fetch.return_value = matching_order(order_id=order_id)

    result = verify_payment_lifecycle(
        client,
        razorpay_order_id=order_id,
        razorpay_payment_id=payment_id,
        expected_amount=PRODUCT["amount_paise"],
        expected_currency=PRODUCT["currency"],
    )
    assert result["status"] == "captured"
    client.payment.fetch.assert_called_once_with(payment_id)
    client.order.fetch.assert_called_once_with(order_id)
    logger.info("LIFE-15 passed: lifecycle helper uses payment.fetch + order.fetch")


@pytest.mark.unit
@pytest.mark.payment
def test_life_16_authorized_validator_path() -> None:
    """LIFE-16: Validator distinguishes authorized from captured."""
    payment = captured_payment(
        order_id="order_auth",
        payment_id="pay_auth",
        status="authorized",
        captured=False,
    )
    order = matching_order(order_id="order_auth")
    with pytest.raises(PaymentLifecycleError) as exc:
        validate_payment_lifecycle(
            payment,
            order,
            expected_order_id="order_auth",
            expected_amount=PRODUCT["amount_paise"],
            expected_currency=PRODUCT["currency"],
        )
    assert exc.value.code == "authorized_not_captured"
    logger.info("LIFE-16 passed: authorized validator path")
