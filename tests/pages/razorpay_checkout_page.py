"""Page object for Razorpay Standard Checkout (Test Mode)."""

from __future__ import annotations

import logging
import re

from playwright.sync_api import FrameLocator, Locator, Page, expect

logger = logging.getLogger("tests.pages.razorpay_checkout_page")

# Documented Razorpay Test Mode Mastercard — never logged by this class.
_TEST_CARD_NUMBER = "5555510000081006"
_TEST_EXPIRY = "1230"
_TEST_CVV = "123"

CHECKOUT_IFRAME = (
    "iframe.razorpay-checkout-frame, "
    "iframe[src*='api.razorpay.com/v1/checkout'], "
    "iframe[src*='razorpay']"
)


class RazorpayCheckoutPage:
    """Interactions inside the Razorpay Checkout iframe."""

    def __init__(self, page: Page) -> None:
        self.page = page

    @property
    def checkout_iframe(self) -> Locator:
        return self.page.locator(CHECKOUT_IFRAME).first

    @property
    def frame(self) -> FrameLocator:
        return self.page.frame_locator(CHECKOUT_IFRAME).first

    def apply_contact_prefill(self) -> None:
        """
        Runtime-only wrapper so Checkout receives Test Mode contact prefill.

        Does not modify application source files.
        """
        logger.info("Applying runtime Razorpay contact prefill wrapper")
        self.page.evaluate(
            """() => {
              if (!window.Razorpay || window.__rzpPrefillWrapped) return;
              const Original = window.Razorpay;
              function Wrapped(options) {
                const opts = Object.assign({}, options || {});
                opts.prefill = Object.assign({}, opts.prefill || {}, {
                  name: 'Test User',
                  email: 'test.user@example.com',
                  contact: '+919123456789'
                });
                return new Original(opts);
              }
              Wrapped.prototype = Original.prototype;
              Object.keys(Original).forEach((k) => { Wrapped[k] = Original[k]; });
              window.Razorpay = Wrapped;
              window.__rzpPrefillWrapped = true;
            }"""
        )

    def expect_open(self, timeout_ms: int = 45000) -> None:
        logger.info("Waiting for Razorpay Checkout iframe")
        expect(self.checkout_iframe).to_be_visible(timeout=timeout_ms)
        expect(self.frame.locator("body")).to_be_attached(timeout=timeout_ms)

    def assert_no_visible_hcaptcha(self) -> None:
        """Skip path if a visible hCaptcha challenge appears (do not bypass)."""
        captcha = self.page.locator(
            "iframe[src*='hcaptcha'][src*='challenge'], "
            "iframe[title*='hCaptcha challenge' i]"
        )
        if captcha.count() > 0 and captcha.first.is_visible():
            raise RuntimeError(
                "Visible hCaptcha challenge detected; manual solve required "
                "(automation will not bypass CAPTCHA)."
            )

    def select_cards(self) -> None:
        logger.info("Selecting Cards payment method")
        cards = self.frame.locator("div[role='button']:has-text('Cards')").first
        expect(cards).to_be_visible(timeout=20000)
        cards.click()

    def fill_test_card(self) -> None:
        """Fill documented Test Mode Mastercard details (values are not logged)."""
        logger.info("Filling Test Mode card fields (values redacted)")
        # Checkout may render more than one matching input; prefer visible.
        number = self.frame.locator("input[name='card.number']").locator("visible=true").last
        expiry = self.frame.locator("input[name='card.expiry']").locator("visible=true").last
        cvv = self.frame.locator("input[name='card.cvv']").locator("visible=true").last
        expect(number).to_be_visible(timeout=20000)

        self._fill_react_input(number, _TEST_CARD_NUMBER)
        expect(number).to_have_value(re.compile(r"(?:\d[\s-]*){15,}"), timeout=15000)

        expect(expiry).to_be_visible()
        self._fill_react_input(expiry, _TEST_EXPIRY)

        expect(cvv).to_be_visible()
        self._fill_react_input(cvv, _TEST_CVV)

        # Card validation error must be gone before Continue.
        error = self.frame.get_by_text("Please enter a valid card number")
        expect(error).to_have_count(0)

    @staticmethod
    def _fill_react_input(locator: Locator, value: str) -> None:
        """Fill Checkout inputs using native setter + input events (Svelte-safe)."""
        locator.click()
        locator.evaluate(
            """(el, value) => {
              const proto = window.HTMLInputElement.prototype;
              const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
              if (descriptor && descriptor.set) {
                descriptor.set.call(el, '');
                el.dispatchEvent(new Event('input', { bubbles: true }));
                descriptor.set.call(el, value);
              } else {
                el.value = value;
              }
              el.dispatchEvent(new Event('input', { bubbles: true }));
              el.dispatchEvent(new Event('change', { bubbles: true }));
              el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
            }""",
            value,
        )
        # Fallback typing if framework ignored the programmatic set.
        current = locator.input_value()
        digits = re.sub(r"\D", "", current or "")
        expected = re.sub(r"\D", "", value)
        if len(digits) < len(expected):
            locator.fill("")
            locator.type(value, delay=55)

    def dismiss_rbi_save_card_if_present(self) -> bool:
        logger.info("Checking for RBI save-card prompt")
        maybe_later = self.frame.locator(
            "button[data-testid='confirm-negative'], button:has-text('Maybe later')"
        )
        try:
            maybe_later.first.wait_for(state="visible", timeout=5000)
        except Exception:  # noqa: BLE001
            logger.info("RBI save-card prompt not shown")
            return False
        maybe_later.first.click(force=True)
        try:
            expect(maybe_later.first).to_be_hidden(timeout=5000)
        except AssertionError:
            logger.warning("RBI save-card prompt still visible after dismiss click")
        logger.info("Dismissed RBI save-card prompt")
        return True

    def continue_to_authentication(self) -> None:
        """Click Continue/Pay to advance from card form to mock OTP challenge."""
        logger.info("Continuing from card form toward authentication challenge")
        self.assert_no_visible_hcaptcha()
        otp = self.frame.locator("input[name='otp']")
        continue_btn = self.frame.locator(
            "button:has-text('Continue'), button:has-text('Pay'), button[type='submit']"
        ).first

        for attempt in range(4):
            if otp.count() and otp.first.is_visible():
                logger.info("OTP challenge already visible")
                return
            self.dismiss_rbi_save_card_if_present()
            if otp.count() and otp.first.is_visible():
                return
            try:
                expect(continue_btn).to_be_visible(timeout=8000)
                continue_btn.click(force=True)
                logger.info("Clicked Continue/Pay (attempt %s)", attempt + 1)
            except Exception as exc:  # noqa: BLE001
                logger.info("Continue click attempt %s: %s", attempt + 1, type(exc).__name__)
            try:
                otp.first.wait_for(state="visible", timeout=8000)
                return
            except Exception:  # noqa: BLE001
                continue

    def wait_for_otp_challenge(self, timeout_ms: int = 45000) -> None:
        logger.info("Waiting for mock OTP challenge")
        expect(self.frame.locator("input[name='otp']")).to_be_visible(timeout=timeout_ms)
        expect(
            self.frame.get_by_text("Enter OTP to complete payment")
        ).to_be_visible(timeout=timeout_ms)
        # Ensure save-card overlay is not covering the OTP field.
        self.dismiss_rbi_save_card_if_present()
