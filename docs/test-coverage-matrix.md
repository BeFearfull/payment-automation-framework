# Test Coverage Matrix — Payment Automation Framework

**Phase 2:** Success requires signature **and** Razorpay `payment.fetch`/`order.fetch` with **`captured`** status.
**Latest full headed regression:** 79 passed / 0 failed / 0 skipped (`reports/full_regression_phase2_report.html`).
**Security suite:** 15 passed (`reports/security_phase2_report.html`).
**Scope:** Flask + Razorpay **Test Mode** only. Not live bank OTP / live settlements.

Legend: **E** = Existing · **A** = Added this audit · **M** = Manual / blocked · **G** = Gap (documented, not automated)

| Requirement | Scenario | Test ID | Type | Status | Priority |
|-------------|----------|---------|------|--------|----------|
| Product displayed correctly | Homepage product name/price | WEB-01, WEB-02 | UI | E | P0 |
| Product currency / paise map | INR and amount_paise = price×100 | WEB-14 | UI | A | P1 |
| Cart add / summary | Add to cart and totals | WEB-03, WEB-04 | UI | E | P0 |
| Checkout enabled only with cart | Button disabled when empty | WEB-05 | UI | E | P0 |
| Checkout creates order | UI → POST /create-order 201 | WEB-05, WEB-06 | UI/API | E | P0 |
| Invalid product | Unknown product_id → 400 | WEB-08 | API | E | P0 |
| Missing product_id | Omit product_id → 400 | PAY-15 | API | A | P1 |
| Invalid quantity | 0, negative, >1, non-int | PAY-14 | API | A | P0 |
| Missing client_request_id | create-order → 400 | PAY-11 | API | E | P0 |
| Duplicate client_request_id | Second call → 409 | WEB-09, UNIT-05, PAY-09 | API/UI/Unit | E | P0 |
| Malformed create-order JSON | Array / empty / plain text | PAY-13 | API | A | P0 |
| Client amount/currency override | Attacker fields ignored | PAY-16 | API/Security | A | P0 |
| Order field mapping | amount/currency/product_name | PAY-18 | API | A | P1 |
| Razorpay order rejection | BadRequestError → 400 | UNIT-06 | Unit | E | P1 |
| Razorpay/network failure | Unexpected error → 502 | UNIT-09 | Unit | A | P1 |
| Unsupported currency (client) | Client currency ignored (server INR) | PAY-16 | API | A | P1 |
| Zero/negative/large amount (client) | Client cannot set amount | PAY-16 | API | A | P0 |
| Receipt TTL reuse after 120s | Same client_request_id after TTL | — | API | G | P2 |
| Razorpay Checkout opens | iframe visible | WEB-07 | UI | E | P0 |
| Checkout dismissal | Escape; no success session | WEB-07, WEB-13 | UI | E/A | P0 |
| Duplicate checkout click | In-flight button disabled | PAY-09 | UI | E | P1 |
| Cart refresh behaviour | Reload clears in-memory cart | WEB-16 | UI | A | P2 |
| Session isolation attempts | Clear cookies; new order; success blocked | WEB-15 | UI | A | P1 |
| Valid signature + captured | Lifecycle unlocks success | LIFE-01, WEB-10, UNIT-03 | Unit/API | A/E | P0 |
| Valid signature + authorized | Does not unlock success | LIFE-02, LIFE-16 | Unit | A | P0 |
| Valid signature + failed | Does not unlock success | LIFE-03 | Unit | A | P0 |
| Valid signature + created | Does not unlock success | LIFE-04 | Unit | A | P0 |
| Invalid signature | → 400 (before fetch) | LIFE-05, WEB-11, PAY-03, UNIT-02 | Unit/API | A/E | P0 |
| Mismatched payment order_id | Rejected | LIFE-06 | Unit | A | P0 |
| Mismatched amount | Rejected | LIFE-07 | Unit | A | P0 |
| Mismatched currency | Rejected | LIFE-08 | Unit | A | P0 |
| payment.fetch API failure | Rejected | LIFE-09 | Unit | A | P0 |
| payment.fetch timeout | → 502 | LIFE-10 | Unit | A | P0 |
| Repeated successful verify | already_verified | LIFE-11, PAY-05 | Unit/API | A/E | P0 |
| Failed replay after success | Session preserved | LIFE-12, PAY-10 | Unit/API | A/E | P0 |
| Concurrent verification | verified / already_verified | LIFE-14, SEC-05 | Unit/Security | A/E | P1 |
| Valid signature verify | HMAC + captured lifecycle | WEB-10, PAY-05, UNIT-03 | API/Unit | E | P0 |
| Missing signature | → 400 + missing list | PAY-17, UNIT-01 | API/Unit | E/A | P0 |
| Missing order/payment id | → 400 | PAY-01, PAY-02 | API | E | P0 |
| Tampered order id | Sig for A + order B → 400 | PAY-04 | API | E | P0 |
| Forged payment id replay | After verify → 400 | PAY-10 | API | E | P0 |
| Malformed verify body | Empty/array/plain/whitespace | PAY-08 | API | E | P0 |
| Repeated verify idempotent | verified → already_verified | PAY-05 | API | E | P0 |
| Concurrent duplicate verify | Parallel HMAC verifies | SEC-05 | API/Security | A | P1 |
| Failed verify clears session | Session popped; success blocked | UNIT-11, SEC-04 | Unit/Security | A | P0 |
| Unexpected verify error | → 500, no secret leak | UNIT-10 | Unit | A | P2 |
| Direct success access | Redirect to failure | WEB-12, UNIT-04, SEC-01 | UI/Unit/Security | E/A | P0 |
| Cleared/expired session | Cookies cleared → blocked | PAY-06 | UI | E | P0 |
| Forged session cookie | Unsigned cookie → blocked | SEC-02 | Security | A | P0 |
| Secret not in HTML/JSON | Homepage, order, errors | UNIT-07, PAY-12, UNIT-13, SEC-03, SEC-06 | Security | E/A | P0 |
| Test Mode key only | settings rejects non-rzp_test_ | settings load | Config | E* | P0 |
| Default Flask secret | Non-empty; warn on demo default | UNIT-14 | Security | A | P1 |
| 404 / 405 handlers | JSON errors, no secret | UNIT-12 | Unit | A | P2 |
| GET /checkout redirect | Redirects home | UNIT-12 | Unit | A | P2 |
| Mock OTP success E2E | AUTH-01 + payment.fetch | AUTH-01 | E2E | E | P0 |
| Mock OTP failure E2E | Short OTP; no verify 200 | AUTH-02 | E2E | E | P0 |
| CAPTCHA visible | Skip, never bypass | AUTH-01/02 helper | E2E | E | P0 |
| OTP / PAN / CVV not logged | Logging policy in POMs | AUTH + pages | Security | E | P0 |
| Authorized vs captured | App requires captured; helper documents both | AUTH-01, LIFE-02, UNIT-15 | E2E/Unit | E/A | P0 |
| Failed payment UI | Failure page + reason | PAY-07, AUTH-02 | UI/E2E | E | P0 |
| Cancelled payment (Checkout) | Gateway cancel mid-flow | — | E2E | M | P2 |
| payment.fetch failure | Mocked lifecycle + helper | LIFE-09, LIFE-10, LIFE-15 | Unit | A | P0 |
| Success requires captured status | Enforced in `/verify-payment` | LIFE-01..04, AUTH-01 | Unit/E2E | A/E | P0 |
| Browser back mid-checkout | History navigation | — | UI | M | P2 |
| Checkout / OTP timeout | Long wait / expire | — | E2E | M | P2 |
| CSRF on JSON APIs | No CSRF tokens today | — | Security | G | P2 |

Browser launch/navigation against this app is covered by WEB/AUTH UI tests (for example WEB-01, WEB-07, AUTH-01). An unrelated external-site Playwright smoke (`tests/test_browser.py` / `test_browser_lifecycle`) remains outside application scope.

\* Enforced at import time in `config/settings.py` (raises if key is not `rzp_test_*`); not a separate pytest case.

## Markers

| Marker | Purpose |
|--------|---------|
| `web` | Homepage / cart / checkout UI |
| `payment` | Order + verification API / gates |
| `unit` | Mocked, no live Razorpay calls |
| `otp` | Test Mode mock OTP E2E |
| `security` | Session, secrets, forgery, concurrent verify |
