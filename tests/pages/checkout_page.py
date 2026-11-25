"""Checkout / order-initiation page object (homepage cart actions)."""

from __future__ import annotations

import logging
from typing import Any

from playwright.sync_api import Locator, Page, Response, expect

logger = logging.getLogger("tests.pages.checkout_page")


class CheckoutPage:
    """Cart checkout and Razorpay order-creation interactions."""

    def __init__(self, page: Page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url.rstrip("/")

    @property
    def proceed_to_payment_button(self) -> Locator:
        return self.page.get_by_test_id("proceed-to-payment")

    @property
    def payment_status(self) -> Locator:
        return self.page.get_by_test_id("payment-status")

    def expect_checkout_enabled(self) -> None:
        expect(self.proceed_to_payment_button).to_be_enabled()

    def expect_checkout_disabled(self) -> None:
        expect(self.proceed_to_payment_button).to_be_disabled()

    def click_proceed_to_payment(self) -> None:
        logger.info("Clicking Proceed to Payment")
        self.expect_checkout_enabled()
        self.proceed_to_payment_button.click()

    def start_checkout_and_wait_for_order(self, timeout_ms: int = 30000) -> dict[str, Any]:
        """
        Click checkout and wait for a successful POST /create-order response.
        Returns the parsed JSON body.
        """
        logger.info("Starting checkout and waiting for /create-order")
        with self.page.expect_response(
            lambda response: self._is_create_order_success(response),
            timeout=timeout_ms,
        ) as response_info:
            self.click_proceed_to_payment()

        response = response_info.value
        payload = response.json()
        logger.info(
            "Order created: status=%s order_id=%s amount=%s",
            response.status,
            payload.get("order_id"),
            payload.get("amount"),
        )
        expect(self.payment_status).to_contain_text("Opening Razorpay Checkout")
        return payload

    @staticmethod
    def _is_create_order_success(response: Response) -> bool:
        try:
            return (
                "/create-order" in response.url
                and response.request.method == "POST"
                and response.status == 201
            )
        except Exception:  # noqa: BLE001
            return False
