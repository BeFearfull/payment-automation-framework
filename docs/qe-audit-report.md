# QE Audit Report — Payment Automation Framework

**Date:** 2026-11-25
**Stack:** Flask · Razorpay Test Mode · Pytest · Playwright
**Auditor role:** Quality Engineering architect review (automation + risk)

## 1. Executive summary

The framework already had strong coverage of the **verify-before-success** contract, order deduplication, secret non-exposure on the happy path, and Test Mode mock OTP (AUTH-01/02). The audit found real gaps in **create-order validation**, **session clearing on failed verify**, **client amount tampering**, **HTTP error handlers**, and **checkout dismiss / isolation** UI paths.

This audit **added targeted tests** (not count-padding) and one **genuine defect fix**: quantity validation previously coerced floats such as `1.5` to `1` via `int()`, which is incorrect for a strict integer field.

**Passing test count is not complete coverage.** Residual gaps and manual cases are listed in `test-coverage-matrix.md`.

## 2. Application behaviour reviewed

| Area | Finding |
|------|---------|
| Order amount/currency | Server-bound to `PRODUCT`; client overrides ignored (now covered by PAY-16). |
| Quantity | Demo allows `quantity=1` only; bool/float now rejected (defect fix). |
| Verify | Always re-checks HMAC; failed verify clears session flags (UNIT-11). |
| Success page | Session-gated only; **does not** call `payment.fetch` before render. |
| Secrets | Not embedded in templates/order JSON; error paths audited (SEC/UNIT). |
| OTP | Checkout iframe mock ACS; short OTP (`<4` digits) fails; `12345` succeeds in practice. |

## 3. Defect fixed during audit

**Quantity float coercion (`app.py`)**

`int(1.5) == 1` allowed a non-integer JSON quantity to create an order.

**Fix:** Reject `bool` and `float` quantity values before integer coercion.

**Covered by:** PAY-14 (`float` case).

## 4. Tests added (this audit)

| ID | Layer | Intent |
|----|-------|--------|
| PAY-13 | API | create-order non-object JSON |
| PAY-14 | API | Quantity boundaries / types |
| PAY-15 | API | Missing `product_id` |
| PAY-16 | API/Security | Client cannot override amount/currency |
| PAY-17 | API | Missing signature |
| PAY-18 | API | Order maps catalog price/currency |
| UNIT-09 | Unit | create-order unexpected → 502 |
| UNIT-10 | Unit | verify unexpected → 500 |
| UNIT-11 | Unit/Security | Failed verify clears success session |
| UNIT-12 | Unit | 404/405 + `/checkout` redirect |
| UNIT-13 | Unit/Security | Error bodies never leak secret |
| UNIT-14 | Security | Flask secret key present / demo-default warning |
| UNIT-15 | Unit | Status helper rejects failed/pending |
| SEC-01 | Security UI | Direct success blocked |
| SEC-02 | Security UI | Forged session cookie blocked |
| SEC-03 | Security API | Secret not in responses |
| SEC-04 | Security API | Failed verify — no success session |
| SEC-05 | Security API | Concurrent duplicate verifies |
| SEC-06 | Security UI | `APP_CONFIG` public key only |
| WEB-13 | UI | Checkout dismiss does not succeed |
| WEB-14 | UI | Currency / paise consistency |
| WEB-15 | UI | Session isolation between attempts |
| WEB-16 | UI | Refresh resets client cart |

## 5. Remaining untested / gaps

| Gap | Why not automated now | Risk |
|-----|------------------------|------|
| ~~Success page unlocks on HMAC only~~ | **Addressed in Phase 2** — signature + `payment.fetch`/`order.fetch` require `captured` | Closed |
| Auto-capture must be enabled in Test Mode | AUTH-01 fails if payments stay `authorized` | P1 config |
| Receipt TTL (120s) reuse | Needs long wait or clock injection | P2 |
| Real Checkout `payment.failed` from gateway | Flaky / card-dependent; PAY-07 simulates URL only | P2 |
| Browser Back during Checkout | Cross-origin iframe history unreliable in CI | P2 manual |
| Checkout / OTP timeout | Multi-minute wait | P2 manual |
| `payment.fetch` failure paths | No production caller in app today (helper used in AUTH-01 only) | P2 |
| CSRF tokens on JSON POST | App has no CSRF middleware; SPA JSON + cookie session residual risk | P2 |
| Live Mode key misconfiguration in CI | Settings raises at import; dedicated pytest needs isolated subprocess | P2 |
| Headless OTP flake | Prefer `--headed` for AUTH | Known limitation |
| Visible hCaptcha | Explicit skip · never bypass | Manual prerequisite |

## 6. Manual test cases

1. **CAPTCHA:** If hCaptcha challenge appears in Checkout, solve manually or skip AUTH; do not automate bypass.
2. **Checkout timeout ribbon:** Leave OTP open until timeout; confirm merchant failure/cancel handling.
3. **Browser Back / forward:** During an open Checkout modal.
4. **Dashboard reconciliation:** After AUTH-01, confirm order/payment in Razorpay Test Mode dashboard.
5. **Rotate `FLASK_SECRET_KEY`:** Away from `dev-only-change-me` before any shared environment.
6. **Network throttle:** Slow 3G while verifying; ensure UI failure path is acceptable.

## 7. Reliability notes

- Playwright waits use expect/locator timeouts; no arbitrary `time.sleep()` in tests (only server readiness poll in `conftest`).
- OTP selectors live in page objects.
- AUTH tests clear cookies/storage for isolation.
- Unrelated external-site Playwright smoke (`tests/test_browser.py` / `test_browser_launch` against playwright.dev) was **intentionally removed**. WEB/AUTH UI tests already validate browser launch and navigation against the payment application.
- In-memory `_recent_receipts` / `_verified_orders` reset when the test Flask process restarts (session-scoped live server).

## 8. Actual run results (clean state)

| Suite | Passed | Failed | Skipped | Blocked | Report |
|-------|--------|--------|---------|---------|--------|
| Security (`-m security`) | **12** | 0 | 0 | 0 | Historical; prefer `reports/security_phase2_report.html` |
| Full regression (`tests` headed) | **64** | 0 | 0 | 0 | Historical; prefer `reports/full_regression_phase2_report.html` |

Notes on counts:
- Baseline before this audit: **35** collected tests.
- Added **29** collected items (PAY-13..18 including 7× PAY-14 params, UNIT-09..15, SEC-01..06, WEB-13..16).
- **0 skipped / 0 blocked** in these runs. CAPTCHA skip path exists but did not trigger.
- OTP tests remain Test Mode mock ACS only — not live SMS.

## 9. Reports

| Suite | Command hint | Report path |
|-------|--------------|-------------|
| Full regression | `pytest tests --headed --html=reports/full_regression_phase2_report.html --self-contained-html --browser chromium` | `reports/full_regression_phase2_report.html` |
| Security | `pytest tests -m security --html=reports/security_phase2_report.html --self-contained-html --browser chromium` | `reports/security_phase2_report.html` |

## 10. Conclusion

Coverage is **strong for the demo’s security gate and Test Mode OTP paths**, and is **improved** for order validation and session/secret hardening. It is **not** equivalent to a production payment platform test pack: payment-status gating after signature, CSRF, TTL, and long-running Checkout edge cases remain intentional open or manual.
