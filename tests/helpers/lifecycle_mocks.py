"""Mock helpers for Phase 2 payment lifecycle verification tests."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator
from unittest.mock import patch

from config.settings import PRODUCT


def captured_payment(
    *,
    order_id: str,
    payment_id: str,
    amount: int | None = None,
    currency: str | None = None,
    status: str = "captured",
    captured: bool | None = None,
) -> dict[str, Any]:
    """Build a Razorpay-like payment entity for mocks."""
    amt = PRODUCT["amount_paise"] if amount is None else amount
    cur = PRODUCT["currency"] if currency is None else currency
    if captured is None:
        captured = status == "captured"
    return {
        "id": payment_id,
        "order_id": order_id,
        "amount": amt,
        "currency": cur,
        "status": status,
        "captured": captured,
        "method": "card",
    }


def matching_order(
    *,
    order_id: str,
    amount: int | None = None,
    currency: str | None = None,
) -> dict[str, Any]:
    """Build a Razorpay-like order entity for mocks."""
    return {
        "id": order_id,
        "amount": PRODUCT["amount_paise"] if amount is None else amount,
        "currency": PRODUCT["currency"] if currency is None else currency,
        "status": "paid",
    }


@contextmanager
def mock_captured_lifecycle(
    *,
    order_id: str,
    payment_id: str,
    amount: int | None = None,
    currency: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Patch app verify helpers for a successful captured payment."""
    payment = captured_payment(
        order_id=order_id,
        payment_id=payment_id,
        amount=amount,
        currency=currency,
        status="captured",
    )
    details = {
        "payment_id": payment_id,
        "order_id": order_id,
        "amount": payment["amount"],
        "currency": str(payment["currency"]).upper(),
        "status": "captured",
        "captured": True,
    }
    with (
        patch("app.verify_payment_signature", return_value=True),
        patch("app.verify_payment_lifecycle", return_value=details),
    ):
        yield {"payment": payment, "lifecycle": details}


def flask_session_cookie(flask_client) -> str | None:
    """Return the Flask session cookie value from a test client, if present."""
    cookie = flask_client.get_cookie("session")
    if cookie is None:
        return None
    return cookie.value
