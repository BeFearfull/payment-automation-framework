"""WEB-01 .. WEB-09 — homepage, cart, checkout, and order API checks."""

from __future__ import annotations

import logging
import uuid

import pytest
from playwright.sync_api import expect

from tests.helpers.api import create_order
from tests.pages.checkout_page import CheckoutPage
from tests.pages.home_page import HomePage
from tests.pages.payment_page import PaymentPage

logger = logging.getLogger("tests.web.test_checkout")

PRICE_TEXT = "₹1,499"
PRODUCT_NAME = "Wireless Headphones"


@pytest.mark.web
def test_web_01_homepage_loads(home_page: HomePage) -> None:
    """WEB-01: Homepage loads successfully."""
    home_page.open()
    home_page.expect_loaded()
    logger.info("WEB-01 passed: homepage loaded")


@pytest.mark.web
def test_web_02_product_name_and_price(
    home_page: HomePage,
    product_catalog: dict,
) -> None:
    """WEB-02: Product name and price are correct."""
    home_page.open()
    assert product_catalog["name"] == PRODUCT_NAME
    assert product_catalog["price_inr"] == 1499
    home_page.expect_product(PRODUCT_NAME, PRICE_TEXT)
    logger.info("WEB-02 passed: product details correct")


@pytest.mark.web
def test_web_03_add_to_cart(home_page: HomePage) -> None:
    """WEB-03: Add to Cart works."""
    home_page.open()
    expect(home_page.cart_empty).to_be_visible()
    home_page.add_to_cart()
    expect(home_page.cart_item).to_be_visible()
    logger.info("WEB-03 passed: add to cart works")


@pytest.mark.web
def test_web_04_cart_summary(home_page: HomePage) -> None:
    """WEB-04: Cart summary is correct."""
    home_page.open()
    home_page.add_to_cart()
    home_page.expect_cart_summary(PRODUCT_NAME, PRICE_TEXT)
    logger.info("WEB-04 passed: cart summary correct")


@pytest.mark.web
def test_web_05_checkout_button_works(
    home_page: HomePage,
    checkout_page: CheckoutPage,
) -> None:
    """WEB-05: Checkout button works."""
    home_page.open()
    checkout_page.expect_checkout_disabled()
    home_page.add_to_cart()
    checkout_page.expect_checkout_enabled()
    # Wait for order creation so the request is not abandoned mid-flight.
    order = checkout_page.start_checkout_and_wait_for_order()
    assert order.get("order_id")
    expect(checkout_page.payment_status).not_to_have_text(
        "Ready. Add the product to cart to continue."
    )
    logger.info("WEB-05 passed: checkout button responds")


@pytest.mark.web
def test_web_06_backend_order_creation_succeeds(
    home_page: HomePage,
    checkout_page: CheckoutPage,
) -> None:
    """WEB-06: Backend order creation succeeds."""
    home_page.open()
    home_page.add_to_cart()
    order = checkout_page.start_checkout_and_wait_for_order()

    assert order.get("order_id", "").startswith("order_")
    assert order.get("amount") == 149900
    assert order.get("currency") == "INR"
    assert order.get("key_id", "").startswith("rzp_test_")
    assert "key_secret" not in order
    logger.info("WEB-06 passed: order_id=%s", order["order_id"])


@pytest.mark.web
def test_web_07_razorpay_checkout_opens(
    home_page: HomePage,
    checkout_page: CheckoutPage,
    payment_page: PaymentPage,
) -> None:
    """WEB-07: Razorpay Checkout opens."""
    home_page.open()
    home_page.add_to_cart()
    checkout_page.start_checkout_and_wait_for_order()
    payment_page.expect_checkout_open()
    logger.info(
        "WEB-07 passed: Razorpay Checkout opened. "
        "Completing card/OTP inside Checkout may need manual follow-up if challenged."
    )
    payment_page.dismiss_checkout()


@pytest.mark.web
def test_web_08_invalid_order_request_rejected(
    api_client,
    base_url: str,
) -> None:
    """WEB-08: Invalid order request is rejected."""
    response = create_order(
        api_client,
        base_url,
        product_id="unknown-product",
        client_request_id=str(uuid.uuid4()),
    )
    assert response.status_code == 400, response.text
    body = response.json()
    assert "error" in body
    logger.info("WEB-08 passed: invalid order rejected (%s)", body)


@pytest.mark.web
def test_web_09_duplicate_order_submission_handled(
    api_client,
    base_url: str,
) -> None:
    """WEB-09: Duplicate order submission is handled."""
    request_id = str(uuid.uuid4())
    first = create_order(
        api_client,
        base_url,
        client_request_id=request_id,
    )
    second = create_order(
        api_client,
        base_url,
        client_request_id=request_id,
    )

    assert first.status_code == 201, first.text
    assert second.status_code == 409, second.text
    assert "Duplicate" in second.json().get("error", "")
    logger.info("WEB-09 passed: duplicate submission returned 409")
