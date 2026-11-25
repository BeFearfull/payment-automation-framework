# Payment Automation Framework

QA automation foundation for an e-commerce payment journey using **Razorpay Test Mode**, Flask, Playwright, and Pytest.

## Stack

- Python + Flask
- Razorpay Python SDK (orders + signature verification)
- Razorpay Standard Checkout (frontend)
- Playwright / Pytest (browser automation readiness)

## Setup

```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# Put Razorpay Test Mode keys in .env
python app.py
```

Open `http://127.0.0.1:5000`.

## Payment flow

1. Homepage shows **Wireless Headphones** at ₹1,499.
2. User adds the product to cart and clicks **Proceed to Payment**.
3. Browser calls `POST /create-order` (server creates a Razorpay order).
4. Frontend opens Razorpay Standard Checkout with `order_id` + public `key_id` only.
5. On Checkout success, frontend posts payment fields to `POST /verify-payment`.
6. Backend verifies the signature with `client.utility.verify_payment_signature`.
7. Only after verification does the app allow `GET /payment-success`.
8. Failures / dismissals route to `GET /payment-failure`.

Card numbers, CVV, and OTP are never stored by this application.

## Important routes

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Shopping homepage |
| POST | `/create-order` | Create Razorpay test order |
| POST | `/verify-payment` | Verify payment signature |
| GET | `/payment-success` | Success page (verified only) |
| GET | `/payment-failure` | Failure page |

## Security notes

- Secret key stays on the server (`.env`).
- Frontend receives only the public key ID.
- Frontend success callback alone is never trusted.

## Web automation

Page objects live under `tests/pages/`. Markers:

- `@pytest.mark.web` — homepage/cart/checkout UI
- `@pytest.mark.payment` — verification gate / success access control

```powershell
.\venv\Scripts\Activate.ps1
python -m playwright install chromium

# WEB + payment suite
python -m pytest tests -m "web or payment" --html=reports/web_payment_report.html --self-contained-html --browser chromium

# Full suite (includes tests/test_browser.py)
python -m pytest tests --html=reports/full_test_report.html --self-contained-html --browser chromium
```

Failure screenshots are stored in `artifacts/screenshots/`.

**Manual step:** Completing card entry/OTP inside Razorpay Checkout is not fully automated here. WEB-07 asserts Checkout opens; enter Razorpay Test Mode card details manually if you need an end-to-end captured payment.
