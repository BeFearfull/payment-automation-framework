"""
AUTH-01 / AUTH-02 — Razorpay Test Mode mock OTP automation.

These tests complete a documented Test Mode mock OTP challenge.
They are NOT live bank OTP / SMS flows and must not be described as such.
"""

from __future__ import annotations

import logging
import re

import pytest
from playwright.sync_api import Page, Response, expect

from config.settings import (
    PRODUCT,
    RAZORPAY_TEST_OTP,
    RAZORPAY_TEST_OTP_FAIL,
)
from tests.helpers.evidence import save_otp_screenshot
from tests.helpers.razorpay_status import fetch_payment_status
from tests.pages.checkout_page import CheckoutPage
from tests.pages.home_page import HomePage
from tests.pages.mock_otp_challenge_page import MockOtpChallengePage
from tests.pages.payment_page import PaymentPage
from tests.pages.razorpay_checkout_page import RazorpayCheckoutPage

logger = logging.getLogger("tests.payment.test_otp_auth")

PRICE_TEXT = f"₹{PRODUCT['price_inr']:,}"


def _skip_if_hcaptcha(checkout: RazorpayCheckoutPage) -> None:
    try:
        checkout.assert_no_visible_hcaptcha()
    except RuntimeError as exc:
        pytest.skip(str(exc))


def _isolate_browser(page: Page) -> None:
    """Drop cookies/storage so prior verified sessions cannot leak into this test."""
    page.context.clear_cookies()
    try:
        page.evaluate(
            """() => {
              try { localStorage.clear(); } catch (e) {}
              try { sessionStorage.clear(); } catch (e) {}
            }"""
        )
    except Exception:  # noqa: BLE001
        # Page may not be on an origin yet; cookies are already cleared.
        pass


def _track_verify_payment(page: Page) -> list[int]:
    """Collect HTTP statuses for POST /verify-payment (no payload logging)."""
    statuses: list[int] = []

    def _on_response(response: Response) -> None:
        try:
            if (
                "/verify-payment" in response.url
                and response.request.method == "POST"
            ):
                statuses.append(response.status)
        except Exception:  # noqa: BLE001
            return

    page.on("response", _on_response)
    return statuses


@pytest.mark.otp
@pytest.mark.payment
def test_auth_01_complete_mock_otp_payment(
    page: Page,
    base_url: str,
    home_page: HomePage,
    checkout_page: CheckoutPage,
    payment_page: PaymentPage,
) -> None:
    """
    AUTH-01: Complete Razorpay Test Mode mock OTP payment.

    Success is asserted only after backend verification + success page.
    """
    _isolate_browser(page)
    razorpay = RazorpayCheckoutPage(page)
    otp_page = MockOtpChallengePage(page, base_url)

    home_page.open()
    _isolate_browser(page)
    razorpay.apply_contact_prefill()
    home_page.add_to_cart()

    order = checkout_page.start_checkout_and_wait_for_order()
    assert order.get("order_id", "").startswith("order_"), order
    assert order.get("key_id", "").startswith("rzp_test_"), "Expected Test Mode key id"

    razorpay.expect_open()
    _skip_if_hcaptcha(razorpay)
    save_otp_screenshot(page, "checkout_open.png")

    razorpay.select_cards()
    razorpay.fill_test_card()
    save_otp_screenshot(page, "card_entered.png")

    razorpay.dismiss_rbi_save_card_if_present()
    razorpay.continue_to_authentication()
    razorpay.wait_for_otp_challenge()
    # Capture challenge before typing OTP so evidence avoids OTP digits.
    save_otp_screenshot(page, "otp_challenge.png")

    _skip_if_hcaptcha(razorpay)
    result = otp_page.complete_with_otp(RAZORPAY_TEST_OTP, timeout_ms=120000)
    save_otp_screenshot(page, "authentication_result.png")

    assert result.succeeded, (
        "AUTH-01 expected success after documented Test Mode OTP, "
        f"got outcome={result.outcome} detail={result.detail}"
    )

    payment_page.expect_success(product_name=PRODUCT["name"], amount_text=PRICE_TEXT)
    order_id = page.get_by_test_id("success-order-id").inner_text().strip()
    payment_id = page.get_by_test_id("success-payment-id").inner_text().strip()
    assert order_id.startswith("order_"), order_id
    assert payment_id.startswith("pay_"), payment_id
    assert order_id == order["order_id"], "Success page order_id must match create-order"

    # Backend requires captured lifecycle; confirm independently via payment.fetch.
    status_info = fetch_payment_status(payment_id)
    assert status_info["status"] == "captured", (
        "Phase 2 success requires captured status; "
        f"got {status_info['status']!r}. Enable automatic capture in Test Mode "
        "or capture the payment before expecting /payment-success."
    )
    assert status_info.get("captured") is True
    assert status_info.get("amount") == PRODUCT["amount_paise"]
    assert str(status_info.get("currency") or "").upper() == PRODUCT["currency"]
    fetched_order = status_info.get("order_id")
    if fetched_order:
        assert fetched_order == order_id, (
            f"payment.fetch order_id mismatch: {fetched_order} != {order_id}"
        )

    save_otp_screenshot(page, "payment_success.png")
    logger.info(
        "AUTH-01 passed (Test Mode mock OTP). payment_id=%s status=%s captured=%s",
        payment_id,
        status_info["status"],
        status_info.get("captured"),
    )


@pytest.mark.otp
@pytest.mark.payment
def test_auth_02_mock_otp_failure_does_not_succeed(
    page: Page,
    base_url: str,
    home_page: HomePage,
    checkout_page: CheckoutPage,
    payment_page: PaymentPage,
) -> None:
    """
    AUTH-02: Documented Test Mode OTP failure must not unlock success.

    Uses a short failure OTP (<4 digits). Inspected against Checkout iframe:
    the commonly cited 5-digit failure OTP (12345) actually succeeds there and
    must not be used for this negative test.
    """
    fail_digits = re.sub(r"\D", "", RAZORPAY_TEST_OTP_FAIL or "")
    assert fail_digits, "RAZORPAY_TEST_OTP_FAIL is empty"
    assert len(fail_digits) < 4, (
        "AUTH-02 requires a short failure OTP (<4 digits). "
        f"Configured length={len(fail_digits)}. "
        "Do not use 12345: Checkout iframe mock ACS accepts it and pays successfully."
    )

    _isolate_browser(page)
    verify_statuses = _track_verify_payment(page)
    razorpay = RazorpayCheckoutPage(page)
    otp_page = MockOtpChallengePage(page, base_url)

    # Baseline: this fresh context must not already hold a verified session.
    home_page.open()
    _isolate_browser(page)
    payment_page.open_success()
    payment_page.expect_redirected_away_from_success()
    expect(page.get_by_test_id("payment-success-page")).to_have_count(0)

    home_page.open()
    razorpay.apply_contact_prefill()
    home_page.add_to_cart()
    order = checkout_page.start_checkout_and_wait_for_order()
    order_id = order.get("order_id", "")
    assert order_id.startswith("order_"), order
    assert order.get("key_id", "").startswith("rzp_test_"), "Expected Test Mode key id"
    logger.info("AUTH-02 fresh order_id=%s", order_id)

    razorpay.expect_open()
    _skip_if_hcaptcha(razorpay)
    razorpay.select_cards()
    razorpay.fill_test_card()
    razorpay.dismiss_rbi_save_card_if_present()
    razorpay.continue_to_authentication()
    razorpay.wait_for_otp_challenge()
    save_otp_screenshot(page, "otp_challenge.png")

    expect(page.get_by_test_id("payment-success-page")).to_have_count(
        0,
        timeout=1000,
    )

    entered = otp_page.enter_otp(RAZORPAY_TEST_OTP_FAIL)
    assert entered == len(fail_digits), (
        f"Failure OTP was not present in the field (digits={entered})"
    )
    otp_page.submit()

    # Confirm the OTP value we typed is what Checkout still held at submit time
    # only if the challenge remains; otherwise the challenge already navigated.
    result = otp_page.wait_for_authentication_result(timeout_ms=60000)
    save_otp_screenshot(page, "authentication_result.png")

    if result.succeeded or otp_page.success_page_visible():
        # Do NOT write payment_failure.png — that would fake failure evidence.
        success_order = ""
        try:
            success_order = page.get_by_test_id("success-order-id").inner_text().strip()
        except Exception:  # noqa: BLE001
            pass
        pytest.fail(
            "AUTH-02 must not reach Payment successful after a failure OTP. "
            f"fresh_order_id={order_id} success_page_order_id={success_order or 'n/a'} "
            f"outcome={result.outcome} detail={result.detail} "
            f"verify_payment_statuses={verify_statuses}"
        )

    assert result.outcome == "failure_page", (
        "AUTH-02 expected the merchant payment-failure page after the documented "
        f"short failure OTP, got outcome={result.outcome} detail={result.detail}. "
        "Staying on Checkout without a gateway failure is not sufficient proof."
    )
    expect(payment_page.failure_root).to_be_visible()
    failure_text = payment_page.failure_message.inner_text()
    assert re.search(r"otp|incorrect|authentication|failed", failure_text, re.I), (
        f"Failure page message did not indicate OTP/auth failure: {failure_text!r}"
    )

    # Capture failure evidence only after the failure state is confirmed.
    save_otp_screenshot(page, "payment_failure.png")

    successful_verifies = [status for status in verify_statuses if status == 200]
    assert not successful_verifies, (
        "AUTH-02 must not POST /verify-payment successfully. "
        f"Observed statuses={verify_statuses} for order_id={order_id}"
    )

    # Direct success access with this browser session must still be blocked.
    # If a prior test's verified session leaked, this surfaces as Payment successful.
    payment_page.open_success()
    expect(page.get_by_test_id("payment-success-page")).to_have_count(0)
    expect(page).not_to_have_url(re.compile(r"/payment-success/?$"))
    payment_page.expect_redirected_away_from_success()

    logger.info(
        "AUTH-02 passed: failure OTP produced failure_page; "
        "no verified session; order_id=%s verify_statuses=%s",
        order_id,
        verify_statuses,
    )
