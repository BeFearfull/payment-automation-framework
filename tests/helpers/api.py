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
    razorpay_order_id: str | None = None,
    razorpay_payment_id: str | None = None,
    razorpay_signature: str | None = None,
    payload: dict[str, Any] | None = None,
) -> requests.Response:
    if payload is None:
        payload = {}
        if razorpay_order_id is not None:
            payload["razorpay_order_id"] = razorpay_order_id
        if razorpay_payment_id is not None:
            payload["razorpay_payment_id"] = razorpay_payment_id
        if razorpay_signature is not None:
            payload["razorpay_signature"] = razorpay_signature
    logger.info(
        "POST /verify-payment fields=%s",
        sorted(payload.keys()),
    )
    return session.post(f"{base_url}/verify-payment", json=payload, timeout=30)


def post_raw(
    session: requests.Session,
    base_url: str,
    path: str,
    *,
    data: bytes | str,
    content_type: str,
) -> requests.Response:
    logger.info("POST %s content_type=%s", path, content_type)
    return session.post(
        f"{base_url}{path}",
        data=data,
        headers={"Content-Type": content_type},
        timeout=30,
    )


def make_test_signature(order_id: str, payment_id: str) -> str:
    """
    Build an HMAC-SHA256 signature the same way Razorpay documents.

    Used only to exercise our server-side verification gate in Test Mode.
    This does not create or claim a live Razorpay capture.
    """
    message = f"{order_id}|{payment_id}".encode("utf-8")
    secret = RAZORPAY_KEY_SECRET.encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()
