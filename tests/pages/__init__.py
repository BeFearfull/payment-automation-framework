"""Page Object Model classes for the Payment Automation Framework."""

from tests.pages.checkout_page import CheckoutPage
from tests.pages.home_page import HomePage
from tests.pages.mock_otp_challenge_page import MockOtpChallengePage
from tests.pages.payment_page import PaymentPage
from tests.pages.razorpay_checkout_page import RazorpayCheckoutPage

__all__ = [
    "CheckoutPage",
    "HomePage",
    "MockOtpChallengePage",
    "PaymentPage",
    "RazorpayCheckoutPage",
]
