"""HTTP helpers for order and payment verification endpoints."""

from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from typing import Any

import requests

from config.settings import PRODUCT, RAZORPAY_KEY_SECRET

logger = logging.getLogger("tests.helpers.api")


def create_order(
    session: requests.Session,
    base_url: str,
    *,
    product_id: str = PRODUCT["id"],
    quantity: int = 1,
    client_request_id: str | None = None,
) -> requests.Response:
    payload = {
        "product_id": product_id,
        "quantity": quantity,
        "client_request_id": client_request_id or str(uuid.uuid4()),
    }
    logger.info("POST /create-order payload=%s", payload)
    return session.post(f"{base_url}/create-order", json=payload, timeout=30)


def verify_payment(
    session: requests.Session,
    base_url: str,
    *,
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> requests.Response:
    payload = {
        "razorpay_order_id": razorpay_order_id,
        "razorpay_payment_id": razorpay_payment_id,
        "razorpay_signature": razorpay_signature,
    }
    logger.info(
        "POST /verify-payment order_id=%s payment_id=%s",
        razorpay_order_id,
        razorpay_payment_id,
    )
    return session.post(f"{base_url}/verify-payment", json=payload, timeout=30)


def make_test_signature(order_id: str, payment_id: str) -> str:
    """
    Build an HMAC-SHA256 signature the same way Razorpay documents.

    Used only to exercise our server-side verification gate in Test Mode.
    This does not create or claim a live Razorpay capture.
    """
    message = f"{order_id}|{payment_id}".encode("utf-8")
    secret = RAZORPAY_KEY_SECRET.encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def verified_success_session(
    base_url: str,
    *,
    order_id: str = "order_test_gate_001",
    payment_id: str = "pay_test_gate_001",
) -> tuple[requests.Session, dict[str, Any]]:
    """Verify with a locally computed Test Mode signature and keep cookies."""
    session = requests.Session()
    signature = make_test_signature(order_id, payment_id)
    response = verify_payment(
        session,
        base_url,
        razorpay_order_id=order_id,
        razorpay_payment_id=payment_id,
        razorpay_signature=signature,
    )
    logger.info("Gate verification status=%s body=%s", response.status_code, response.text)
    response.raise_for_status()
    return session, response.json()
