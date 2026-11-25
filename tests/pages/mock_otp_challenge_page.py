"""Page object for Razorpay Test Mode mock OTP / ACS challenge."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from playwright.sync_api import FrameLocator, Page, expect

from tests.pages.razorpay_checkout_page import CHECKOUT_IFRAME

logger = logging.getLogger("tests.pages.mock_otp_challenge_page")


@dataclass
class AuthResult:
    """Outcome of mock OTP authentication (Test Mode only)."""

    succeeded: bool
    outcome: str
    detail: str


class MockOtpChallengePage:
    """Detect and complete the in-Checkout mock OTP challenge."""

    def __init__(self, page: Page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url.rstrip("/")

    @property
    def frame(self) -> FrameLocator:
        return self.page.frame_locator(CHECKOUT_IFRAME).first

    def expect_visible(self, timeout_ms: int = 45000) -> None:
        logger.info("Asserting mock OTP challenge is visible")
        expect(self.frame.locator("input[name='otp']")).to_be_visible(timeout=timeout_ms)
        expect(
            self.frame.locator("button:has-text('Continue')").last
        ).to_be_visible(timeout=timeout_ms)

    def otp_digit_count(self) -> int:
        """Return digits currently in the OTP field (value never logged)."""
        raw = self.frame.locator("input[name='otp']").input_value()
        return len(re.sub(r"\D", "", raw or ""))

    def enter_otp(self, otp: str) -> int:
        """
        Enter a documented Test Mode OTP. The value is never logged.

        Returns the number of digits present in the field after entry.
        Raises if the input maxlength would truncate the OTP (which can turn a
        documented failure OTP such as 12345 into a succeeding 4-digit value).
        """
        expected_digits = re.sub(r"\D", "", otp or "")
        if not expected_digits:
            raise AssertionError("OTP value is empty after stripping non-digits")

        logger.info(
            "Entering documented Test Mode OTP (value redacted, expected_digits=%s)",
            len(expected_digits),
        )
        otp_input = self.frame.locator("input[name='otp']")
        expect(otp_input).to_be_visible(timeout=20000)

        maxlength = otp_input.get_attribute("maxlength")
        if maxlength and maxlength.isdigit() and int(maxlength) < len(expected_digits):
            raise AssertionError(
                f"OTP input maxlength={maxlength} would truncate a "
                f"{len(expected_digits)}-digit failure OTP into a shorter value "
                "that may succeed in Test Mode. Use a documented short OTP "
                "(fewer than 4 digits) or an OTP that fits the field."
            )

        # RBI / confirm overlays can sit above the OTP field after card Continue.
        overlay = self.frame.locator(
            "button[data-testid='confirm-negative'], button:has-text('Maybe later')"
        )
        try:
            if overlay.count() and overlay.first.is_visible():
                logger.info("Dismissing overlay before OTP entry")
                overlay.first.click(force=True)
                expect(overlay.first).to_be_hidden(timeout=5000)
        except Exception:  # noqa: BLE001
            pass

        # Force focus: overlays occasionally intercept a normal click.
        otp_input.click(force=True)
        otp_input.fill("")
        otp_input.type(otp, delay=40)

        actual = self.otp_digit_count()
        assert actual == len(expected_digits), (
            f"OTP field has {actual} digits after entry; expected {len(expected_digits)}. "
            "Configured OTP was not present in the field (value redacted)."
        )
        return actual

    def submit(self) -> None:
        logger.info("Submitting mock OTP challenge")
        # Prefer the Continue inside the OTP panel (z-overlay), force if needed.
        button = self.frame.locator(
            "input[name='otp'] >> xpath=ancestor::div[contains(@class,'z-')][1] "
            "//button[normalize-space()='Continue']"
        )
        if button.count() == 0:
            button = self.frame.locator("button:has-text('Continue')").last
        expect(button.first).to_be_visible(timeout=15000)
        button.first.click(force=True)

    def success_page_visible(self) -> bool:
        try:
            return self.page.get_by_test_id("payment-success-page").count() > 0
        except Exception:  # noqa: BLE001
            return False

    def failure_page_visible(self) -> bool:
        try:
            return self.page.get_by_test_id("payment-failure-page").count() > 0
        except Exception:  # noqa: BLE001
            return False

    def wait_for_authentication_result(self, timeout_ms: int = 90000) -> AuthResult:
        """
        Wait until the merchant app reflects success or failure.

        Success requires backend verification redirect to /payment-success.
        """
        logger.info("Waiting for authentication / payment outcome")
        outcome = self.page.locator(
            "[data-testid='payment-success-page'], "
            "[data-testid='payment-failure-page']"
        ).first
        try:
            outcome.wait_for(state="visible", timeout=timeout_ms)
        except Exception:  # noqa: BLE001
            # Still inside Checkout — inspect for inline error cues / remaining OTP.
            try:
                error = self.frame.locator(
                    "text=/invalid|incorrect|failed|unable|authentication/i"
                ).first
                if error.count() and error.is_visible():
                    return AuthResult(
                        succeeded=False,
                        outcome="checkout_error",
                        detail="Checkout showed an authentication error message.",
                    )
            except Exception:  # noqa: BLE001
                pass
            try:
                if self.frame.locator("input[name='otp']").is_visible():
                    return AuthResult(
                        succeeded=False,
                        outcome="otp_still_visible",
                        detail="OTP challenge remained visible after submit.",
                    )
            except Exception:  # noqa: BLE001
                pass
            return AuthResult(
                succeeded=False,
                outcome="unknown",
                detail=f"No success/failure page after OTP submit. url={self.page.url}",
            )

        # Prefer an explicit success check so a success page can never be
        # misreported as failure.
        if self.success_page_visible():
            return AuthResult(
                succeeded=True,
                outcome="success_page",
                detail="Reached payment-success after server-side verification.",
            )

        message = "payment-failure page visible"
        try:
            message = self.page.get_by_test_id("failure-message").inner_text()
        except Exception:  # noqa: BLE001
            pass
        return AuthResult(
            succeeded=False,
            outcome="failure_page",
            detail=message,
        )

    def complete_with_otp(self, otp: str, timeout_ms: int = 90000) -> AuthResult:
        self.expect_visible()
        self.enter_otp(otp)
        self.submit()
        return self.wait_for_authentication_result(timeout_ms=timeout_ms)
