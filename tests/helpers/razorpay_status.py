"""Razorpay payment status helpers (Test Mode API)."""

from __future__ import annotations

import logging
from typing import Any

from config.settings import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET
from utils.payment_verification import create_razorpay_client

logger = logging.getLogger("tests.helpers.razorpay_status")


def fetch_payment_status(payment_id: str) -> dict[str, Any]:
    """
    Fetch payment entity via official SDK payment.fetch.

    Returns a sanitized dict suitable for assertions/logging (no secrets).
    """
    if not payment_id.startswith("pay_"):
        raise ValueError("payment_id must look like a Razorpay payment id")

    client = create_razorpay_client(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)
    payment = client.payment.fetch(payment_id)
    status = str(payment.get("status") or "")
    logger.info(
        "Razorpay payment.fetch id=%s status=%s method=%s amount=%s",
        payment_id,
        status,
        payment.get("method"),
        payment.get("amount"),
    )
    return {
        "id": payment.get("id"),
        "status": status,
        "method": payment.get("method"),
        "amount": payment.get("amount"),
        "currency": payment.get("currency"),
        "order_id": payment.get("order_id"),
        "captured": bool(payment.get("captured")),
    }


def assert_successful_test_status(status: str) -> None:
    """
    Assert a Razorpay payment reached a non-failed terminal Test Mode state.

    Phase 2 app success requires **captured** specifically; use an explicit
    `status == "captured"` assertion when checking /payment-success eligibility.
    """
    normalized = (status or "").lower()
    assert normalized in {"authorized", "captured"}, (
        f"Expected authorized/captured Test Mode status, got {status!r}"
    )
