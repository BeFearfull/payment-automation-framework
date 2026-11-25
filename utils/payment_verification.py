"""Server-side Razorpay payment signature verification helpers."""

from __future__ import annotations

from typing import Any

import razorpay
from razorpay.errors import SignatureVerificationError

from utils.logger import get_logger

logger = get_logger(__name__)


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


__all__ = [
    "SignatureVerificationError",
    "create_razorpay_client",
    "verify_payment_signature",
]
