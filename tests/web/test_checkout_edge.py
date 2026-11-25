"""
WEB-13..WEB-16 — checkout dismissal, currency, isolation, refresh.

UI-level coverage that complements WEB-01..WEB-09 without duplicating OTP E2E.
"""

from __future__ import annotations

import logging

import pytest
from playwright.sync_api import Page, expect

from config.settings import PRODUCT
from tests.pages.checkout_page import CheckoutPage
from tests.pages.home_page import HomePage
from tests.pages.payment_page import PaymentPage

logger = logging.getLogger("tests.web.test_checkout_edge")

PRICE_TEXT = f"₹{PRODUCT['price_inr']:,}"


@pytest.mark.web
def test_web_13_checkout_dismissal_does_not_succeed(
    home_page: HomePage,
    checkout_page: CheckoutPage,
    payment_page: PaymentPage,
    page: Page,
) -> None:
    """WEB-13: Dismissing Razorpay Checkout must not unlock payment success."""
    home_page.open()
    home_page.add_to_cart()
    checkout_page.start_checkout_and_wait_for_order()
    payment_page.expect_checkout_open()
    payment_page.dismiss_checkout()

    expect(page.get_by_test_id("payment-success-page")).to_have_count(0)
    payment_page.open_success()
    payment_page.expect_redirected_away_from_success()
    logger.info("WEB-13 passed: checkout dismiss did not create success session")


@pytest.mark.web
def test_web_14_product_currency_and_paise_consistency(
    home_page: HomePage,
    product_catalog: dict,
) -> None:
    """WEB-14: Catalog currency INR and paise mapping stay consistent with UI price."""
    assert product_catalog["currency"] == "INR"
    assert product_catalog["amount_paise"] == product_catalog["price_inr"] * 100
    assert product_catalog["amount_paise"] == 149900
    home_page.open()
    home_page.expect_product(PRODUCT["name"], PRICE_TEXT)
    logger.info("WEB-14 passed: currency/paise/UI price consistent")


@pytest.mark.web
@pytest.mark.payment
def test_web_15_session_isolation_between_attempts(
    page: Page,
    home_page: HomePage,
    checkout_page: CheckoutPage,
    payment_page: PaymentPage,
) -> None:
    """
    WEB-15: Clearing browser state between attempts keeps success locked.

    Simulates independent payment attempts without shared mutable browser session.
    """
    home_page.open()
    home_page.add_to_cart()
    order_one = checkout_page.start_checkout_and_wait_for_order()
    assert order_one["order_id"].startswith("order_")
    payment_page.dismiss_checkout()

    page.context.clear_cookies()
    page.evaluate(
        """() => {
          try { localStorage.clear(); } catch (e) {}
          try { sessionStorage.clear(); } catch (e) {}
        }"""
    )

    home_page.open()
    home_page.add_to_cart()
    order_two = checkout_page.start_checkout_and_wait_for_order()
    assert order_two["order_id"].startswith("order_")
    assert order_two["order_id"] != order_one["order_id"]

    payment_page.open_success()
    payment_page.expect_redirected_away_from_success()
    logger.info(
        "WEB-15 passed: isolated attempts order_one=%s order_two=%s",
        order_one["order_id"],
        order_two["order_id"],
    )


@pytest.mark.web
def test_web_16_refresh_after_add_to_cart_resets_client_cart(
    home_page: HomePage,
    checkout_page: CheckoutPage,
    page: Page,
) -> None:
    """
    WEB-16: Full page refresh clears in-memory cart (no persistence).

    Documents actual client behaviour — cart is JS memory only.
    """
    home_page.open()
    home_page.add_to_cart()
    expect(home_page.cart_item).to_be_visible()
    checkout_page.expect_checkout_enabled()

    page.reload(wait_until="domcontentloaded")
    expect(home_page.cart_empty).to_be_visible()
    checkout_page.expect_checkout_disabled()
    logger.info("WEB-16 passed: refresh resets client-side cart")
