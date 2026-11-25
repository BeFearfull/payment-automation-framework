"""
PAY-13..PAY-18 — create-order API validation and amount integrity.

Live Test Mode server for happy-path amount checks; negatives do not create
meaningful Razorpay payments beyond rejected requests.
"""

from __future__ import annotations

import logging
import uuid

import pytest

from config.settings import PRODUCT
from tests.helpers.api import create_order, post_raw

logger = logging.getLogger("tests.payment.test_order_api")


@pytest.mark.payment
def test_pay_13_create_order_rejects_non_object_json(api_client, base_url: str) -> None:
    """PAY-13: create-order rejects JSON arrays and non-object bodies."""
    array_body = post_raw(
        api_client,
        base_url,
        "/create-order",
        data=b'[{"product_id":"wireless-headphones"}]',
        content_type="application/json",
    )
    assert array_body.status_code == 400, array_body.text
    assert "JSON object" in array_body.json().get("error", "")

    empty = post_raw(
        api_client,
        base_url,
        "/create-order",
        data=b"",
        content_type="application/json",
    )
    assert empty.status_code == 400, empty.text

    plain = post_raw(
        api_client,
        base_url,
        "/create-order",
        data=b"not-json",
        content_type="text/plain",
    )
    assert plain.status_code == 400, plain.text
    logger.info("PAY-13 passed: non-object create-order bodies rejected")


@pytest.mark.payment
@pytest.mark.parametrize(
    ("quantity", "expected_fragment"),
    [
        (0, "quantity=1"),
        (-1, "quantity=1"),
        (2, "quantity=1"),
        (999, "quantity=1"),
        ("abc", "integer"),
        (1.5, "integer"),
        (None, "integer"),
    ],
    ids=["zero", "negative", "two", "large", "string", "float", "null"],
)
def test_pay_14_create_order_quantity_boundaries(
    api_client,
    base_url: str,
    quantity,
    expected_fragment: str,
) -> None:
    """PAY-14: Invalid / boundary quantities are rejected (demo allows quantity=1 only)."""
    response = api_client.post(
        f"{base_url}/create-order",
        json={
            "product_id": PRODUCT["id"],
            "quantity": quantity,
            "client_request_id": str(uuid.uuid4()),
        },
        timeout=30,
    )
    assert response.status_code == 400, response.text
    error = response.json().get("error", "")
    assert expected_fragment.lower() in error.lower(), error
    logger.info("PAY-14 passed: quantity=%r rejected (%s)", quantity, error)


@pytest.mark.payment
def test_pay_15_create_order_missing_product_id(api_client, base_url: str) -> None:
    """PAY-15: Missing product_id is rejected as unknown product."""
    response = api_client.post(
        f"{base_url}/create-order",
        json={"quantity": 1, "client_request_id": str(uuid.uuid4())},
        timeout=30,
    )
    assert response.status_code == 400, response.text
    assert "Unknown product" in response.json().get("error", "")
    logger.info("PAY-15 passed: missing product_id rejected")


@pytest.mark.payment
def test_pay_16_client_cannot_override_amount_or_currency(
    api_client,
    base_url: str,
) -> None:
    """
    PAY-16: Client-supplied amount/currency must not alter the server order.

    Amount and currency are bound to PRODUCT on the server, not attacker-controlled.
    """
    response = api_client.post(
        f"{base_url}/create-order",
        json={
            "product_id": PRODUCT["id"],
            "quantity": 1,
            "client_request_id": str(uuid.uuid4()),
            "amount": 1,
            "currency": "USD",
            "amount_paise": 1,
        },
        timeout=30,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["amount"] == PRODUCT["amount_paise"], body
    assert body["currency"] == PRODUCT["currency"], body
    assert body["amount"] != 1
    assert body["currency"] != "USD"
    logger.info(
        "PAY-16 passed: order amount=%s currency=%s (client overrides ignored)",
        body["amount"],
        body["currency"],
    )


@pytest.mark.payment
def test_pay_17_missing_signature_rejected(api_client, base_url: str) -> None:
    """PAY-17: Missing razorpay_signature is rejected."""
    from tests.helpers.api import verify_payment

    response = verify_payment(
        api_client,
        base_url,
        payload={
            "razorpay_order_id": "order_missing_sig",
            "razorpay_payment_id": "pay_missing_sig",
        },
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert "razorpay_signature" in body.get("missing", [])
    logger.info("PAY-17 passed: missing signature rejected")


@pytest.mark.payment
def test_pay_18_order_response_maps_product_price_currency(
    api_client,
    base_url: str,
) -> None:
    """PAY-18: Successful order maps catalog price/currency correctly."""
    response = create_order(api_client, base_url, client_request_id=str(uuid.uuid4()))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["amount"] == PRODUCT["amount_paise"]
    assert body["currency"] == "INR"
    assert body["product_name"] == PRODUCT["name"]
    assert body["order_id"].startswith("order_")
    logger.info("PAY-18 passed: order fields map to catalog")
