"""Server-side Razorpay signature + payment lifecycle verification."""

from __future__ import annotations

from typing import Any

import razorpay
from razorpay.errors import BadRequestError, SignatureVerificationError

from utils.logger import get_logger

logger = get_logger(__name__)

REQUIRED_SUCCESS_STATUS = "captured"


class PaymentLifecycleError(Exception):
    """Raised when signature is valid but payment lifecycle checks fail."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int = 400,
        code: str = "lifecycle_rejected",
        payment_status: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.http_status = http_status
        self.code = code
        self.payment_status = payment_status


def create_razorpay_client(key_id: str, key_secret: str) -> razorpay.Client:
    """Create an authenticated Razorpay SDK client."""
    return razorpay.Client(auth=(key_id, key_secret))


def verify_payment_signature(
    client: razorpay.Client,
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> bool:
    """
    Verify Checkout response authenticity using the official SDK.

    Uses client.utility.verify_payment_signature as documented by Razorpay.
    Raises SignatureVerificationError when the signature does not match.
    """
    payload: dict[str, Any] = {
        "razorpay_order_id": razorpay_order_id,
        "razorpay_payment_id": razorpay_payment_id,
        "razorpay_signature": razorpay_signature,
    }
    result = client.utility.verify_payment_signature(payload)
    logger.info(
        "Payment signature verified for order_id=%s payment_id=%s",
        razorpay_order_id,
        razorpay_payment_id,
    )
    return bool(result)


def fetch_razorpay_payment(client: razorpay.Client, payment_id: str) -> dict[str, Any]:
    """Fetch a payment entity from Razorpay (server-side only)."""
    payment = client.payment.fetch(payment_id)
    if not isinstance(payment, dict):
        raise PaymentLifecycleError(
            "Payment fetch returned an unexpected payload.",
            http_status=502,
            code="fetch_invalid_payload",
        )
    return payment


def fetch_razorpay_order(client: razorpay.Client, order_id: str) -> dict[str, Any]:
    """Fetch an order entity from Razorpay (server-side only)."""
    order = client.order.fetch(order_id)
    if not isinstance(order, dict):
        raise PaymentLifecycleError(
            "Order fetch returned an unexpected payload.",
            http_status=502,
            code="fetch_invalid_payload",
        )
    return order


def validate_payment_lifecycle(
    payment: dict[str, Any],
    order: dict[str, Any],
    *,
    expected_order_id: str,
    expected_amount: int,
    expected_currency: str,
) -> dict[str, Any]:
    """
    Confirm payment belongs to the order and is captured for the expected amount.

    Does not trust browser-supplied amount/currency/status.
    """
    payment_order_id = str(payment.get("order_id") or "").strip()
    payment_status = str(payment.get("status") or "").strip().lower()
    payment_amount = payment.get("amount")
    payment_currency = str(payment.get("currency") or "").strip().upper()

    order_amount = order.get("amount")
    order_currency = str(order.get("currency") or "").strip().upper()
    order_id = str(order.get("id") or "").strip()

    if order_id and order_id != expected_order_id:
        raise PaymentLifecycleError(
            "Fetched order does not match the verification order id.",
            code="order_mismatch",
        )

    if payment_order_id != expected_order_id:
        raise PaymentLifecycleError(
            "Payment does not belong to the expected order.",
            code="payment_order_mismatch",
            payment_status=payment_status or None,
        )

    try:
        payment_amount_int = int(payment_amount)
        order_amount_int = int(order_amount)
        expected_amount_int = int(expected_amount)
    except (TypeError, ValueError) as exc:
        raise PaymentLifecycleError(
            "Payment or order amount is missing or invalid.",
            code="amount_invalid",
            payment_status=payment_status or None,
        ) from exc

    if payment_amount_int != order_amount_int:
        raise PaymentLifecycleError(
            "Payment amount does not match the Razorpay order amount.",
            code="amount_mismatch",
            payment_status=payment_status or None,
        )

    if payment_amount_int != expected_amount_int:
        raise PaymentLifecycleError(
            "Payment amount does not match the server catalog amount.",
            code="amount_mismatch",
            payment_status=payment_status or None,
        )

    expected_currency_norm = expected_currency.strip().upper()
    if payment_currency != order_currency:
        raise PaymentLifecycleError(
            "Payment currency does not match the Razorpay order currency.",
            code="currency_mismatch",
            payment_status=payment_status or None,
        )
    if payment_currency != expected_currency_norm:
        raise PaymentLifecycleError(
            "Payment currency does not match the server catalog currency.",
            code="currency_mismatch",
            payment_status=payment_status or None,
        )

    if payment_status == "authorized":
        raise PaymentLifecycleError(
            "Payment is authorized but not captured; success is not granted.",
            code="authorized_not_captured",
            payment_status=payment_status,
        )
    if payment_status == "failed":
        raise PaymentLifecycleError(
            "Payment status is failed; success is not granted.",
            code="payment_failed",
            payment_status=payment_status,
        )
    if payment_status == "created":
        raise PaymentLifecycleError(
            "Payment status is created/pending; success is not granted.",
            code="payment_pending",
            payment_status=payment_status,
        )
    if payment_status != REQUIRED_SUCCESS_STATUS:
        raise PaymentLifecycleError(
            f"Payment status '{payment_status or 'unknown'}' is not captured.",
            code="status_not_captured",
            payment_status=payment_status or None,
        )

    # Prefer explicit captured flag when present.
    if "captured" in payment and not bool(payment.get("captured")):
        raise PaymentLifecycleError(
            "Payment is not marked captured by Razorpay.",
            code="not_captured_flag",
            payment_status=payment_status,
        )

    return {
        "payment_id": payment.get("id"),
        "order_id": expected_order_id,
        "amount": payment_amount_int,
        "currency": payment_currency,
        "status": payment_status,
        "captured": True,
    }


def verify_payment_lifecycle(
    client: razorpay.Client,
    *,
    razorpay_order_id: str,
    razorpay_payment_id: str,
    expected_amount: int,
    expected_currency: str,
) -> dict[str, Any]:
    """
    Fetch payment + order from Razorpay and validate captured lifecycle state.

    Call only after signature verification succeeds.
    """
    try:
        payment = fetch_razorpay_payment(client, razorpay_payment_id)
        order = fetch_razorpay_order(client, razorpay_order_id)
    except PaymentLifecycleError:
        raise
    except BadRequestError as exc:
        raise PaymentLifecycleError(
            "Unable to fetch payment or order from Razorpay.",
            http_status=400,
            code="fetch_bad_request",
        ) from exc
    except Exception as exc:  # noqa: BLE001
        # Includes timeouts / connection errors from the underlying HTTP client.
        raise PaymentLifecycleError(
            "Razorpay payment fetch failed.",
            http_status=502,
            code="fetch_failed",
        ) from exc

    return validate_payment_lifecycle(
        payment,
        order,
        expected_order_id=razorpay_order_id,
        expected_amount=expected_amount,
        expected_currency=expected_currency,
    )


__all__ = [
    "REQUIRED_SUCCESS_STATUS",
    "PaymentLifecycleError",
    "SignatureVerificationError",
    "BadRequestError",
    "create_razorpay_client",
    "verify_payment_signature",
    "fetch_razorpay_payment",
    "fetch_razorpay_order",
    "validate_payment_lifecycle",
    "verify_payment_lifecycle",
]
