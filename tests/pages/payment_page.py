"""Payment result pages and Razorpay Checkout modal page object."""

from __future__ import annotations

import logging

from playwright.sync_api import FrameLocator, Locator, Page, expect

logger = logging.getLogger("tests.pages.payment_page")


class PaymentPage:
    """Razorpay Checkout modal + success/failure outcome pages."""

    def __init__(self, page: Page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url.rstrip("/")

    @property
    def success_root(self) -> Locator:
        return self.page.get_by_test_id("payment-success-page")

    @property
    def success_title(self) -> Locator:
        return self.page.get_by_test_id("success-title")

    @property
    def success_product(self) -> Locator:
        return self.page.get_by_test_id("success-product")

    @property
    def success_amount(self) -> Locator:
        return self.page.get_by_test_id("success-amount")

    @property
    def success_order_id(self) -> Locator:
        return self.page.get_by_test_id("success-order-id")

    @property
    def success_payment_id(self) -> Locator:
        return self.page.get_by_test_id("success-payment-id")

    @property
    def failure_root(self) -> Locator:
        return self.page.get_by_test_id("payment-failure-page")

    @property
    def failure_title(self) -> Locator:
        return self.page.get_by_test_id("failure-title")

    @property
    def failure_message(self) -> Locator:
        return self.page.get_by_test_id("failure-message")

    @property
    def checkout_iframe(self) -> Locator:
        # Razorpay Standard Checkout injects a checkout iframe on the host page.
        return self.page.locator(
            "iframe.razorpay-checkout-frame, iframe[src*='razorpay'], "
            "iframe[name*='razorpay'], iframe[id*='razorpay']"
        ).first

    @property
    def razorpay_frame(self) -> FrameLocator:
        return self.page.frame_locator(
            "iframe.razorpay-checkout-frame, iframe[src*='razorpay'], "
            "iframe[name*='razorpay'], iframe[id*='razorpay']"
        ).first

    def expect_checkout_open(self, timeout_ms: int = 30000) -> None:
        logger.info("Waiting for Razorpay Checkout iframe")
        expect(self.checkout_iframe).to_be_attached(timeout=timeout_ms)
        expect(self.checkout_iframe).to_be_visible(timeout=timeout_ms)
        expect(self.razorpay_frame.locator("body")).to_be_attached(timeout=timeout_ms)
        logger.info("Razorpay Checkout appears open")

    def dismiss_checkout(self) -> None:
        """Close the Checkout modal when possible to free the page for later tests."""
        logger.info("Dismissing Razorpay Checkout modal if open")
        self.page.keyboard.press("Escape")
        try:
            expect(self.checkout_iframe).to_be_hidden(timeout=5000)
        except AssertionError:
            logger.warning("Checkout iframe still visible after Escape; continuing")

    def open_success(self) -> None:
        logger.info("Navigating to /payment-success")
        self.page.goto(f"{self.base_url}/payment-success", wait_until="domcontentloaded")

    def open_failure(self) -> None:
        logger.info("Navigating to /payment-failure")
        self.page.goto(f"{self.base_url}/payment-failure", wait_until="domcontentloaded")

    def expect_success(
        self,
        *,
        product_name: str,
        amount_text: str,
        order_id: str | None = None,
        payment_id: str | None = None,
    ) -> None:
        expect(self.success_root).to_be_visible()
        expect(self.success_title).to_have_text("Payment successful")
        expect(self.success_product).to_have_text(product_name)
        expect(self.success_amount).to_have_text(amount_text)
        if order_id:
            expect(self.success_order_id).to_have_text(order_id)
        if payment_id:
            expect(self.success_payment_id).to_have_text(payment_id)

    def expect_failure(self) -> None:
        expect(self.failure_root).to_be_visible()
        expect(self.failure_title).to_have_text("Payment failed")

    def expect_redirected_away_from_success(self) -> None:
        expect(self.page).not_to_have_url(f"{self.base_url}/payment-success")
        self.expect_failure()
