"""Homepage page object."""

from __future__ import annotations

import logging

from playwright.sync_api import Locator, Page, expect

logger = logging.getLogger("tests.pages.home_page")


class HomePage:
    """Shopping homepage interactions."""

    def __init__(self, page: Page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url.rstrip("/")

    @property
    def root(self) -> Locator:
        return self.page.get_by_test_id("homepage")

    @property
    def brand(self) -> Locator:
        return self.page.get_by_test_id("site-brand")

    @property
    def test_mode_badge(self) -> Locator:
        return self.page.get_by_test_id("test-mode-badge")

    @property
    def product_card(self) -> Locator:
        return self.page.get_by_test_id("product-card")

    @property
    def product_name(self) -> Locator:
        return self.page.get_by_test_id("product-name")

    @property
    def product_price(self) -> Locator:
        return self.page.get_by_test_id("product-price")

    @property
    def product_image(self) -> Locator:
        return self.page.get_by_test_id("product-image")

    @property
    def add_to_cart_button(self) -> Locator:
        return self.page.get_by_test_id("add-to-cart")

    @property
    def cart_panel(self) -> Locator:
        return self.page.get_by_test_id("cart-panel")

    @property
    def cart_summary(self) -> Locator:
        return self.page.get_by_test_id("cart-summary")

    @property
    def cart_empty(self) -> Locator:
        return self.page.get_by_test_id("cart-empty")

    @property
    def cart_item(self) -> Locator:
        return self.page.get_by_test_id("cart-item")

    @property
    def cart_item_name(self) -> Locator:
        return self.page.get_by_test_id("cart-item-name")

    @property
    def cart_item_price(self) -> Locator:
        return self.page.get_by_test_id("cart-item-price")

    @property
    def cart_total(self) -> Locator:
        return self.page.get_by_test_id("cart-total")

    @property
    def payment_status(self) -> Locator:
        return self.page.get_by_test_id("payment-status")

    def open(self) -> None:
        logger.info("Opening homepage: %s/", self.base_url)
        self.page.goto(f"{self.base_url}/", wait_until="domcontentloaded")
        expect(self.root).to_be_visible()

    def expect_loaded(self) -> None:
        expect(self.root).to_be_visible()
        expect(self.brand).to_contain_text("Payment Automation Framework")
        expect(self.test_mode_badge).to_contain_text("Razorpay Test Mode")
        expect(self.product_card).to_be_visible()
        expect(self.product_image).to_be_visible()

    def expect_product(self, name: str, price_text: str) -> None:
        expect(self.product_name).to_have_text(name)
        expect(self.product_price).to_have_text(price_text)

    def add_to_cart(self) -> None:
        logger.info("Clicking Add to Cart")
        expect(self.add_to_cart_button).to_be_enabled()
        self.add_to_cart_button.click()
        expect(self.cart_item).to_be_visible()

    def expect_cart_summary(self, name: str, price_text: str) -> None:
        expect(self.cart_item_name).to_have_text(name)
        expect(self.cart_item_price).to_have_text(price_text)
        expect(self.cart_total).to_have_text(price_text)
        expect(self.payment_status).to_contain_text("Added Wireless Headphones to cart")
