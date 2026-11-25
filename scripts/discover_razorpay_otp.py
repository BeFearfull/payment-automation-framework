"""
Phase A — Razorpay Test Mode OTP / mock ACS discovery.

Drives the demo shop to the Checkout mock authentication challenge,
inspects frames/controls, and stops WITHOUT completing payment.

Safety:
- Test Mode card values are used in the browser only; never written to logs.
- No SMS access, no real customer OTPs, no live credentials.
- Existing tests and application code are not modified by this script.
"""

from __future__ import annotations

import json
import re
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from playwright.sync_api import Frame, Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import FLASK_HOST, FLASK_PORT  # noqa: E402

ARTIFACT_DIR = ROOT / "artifacts" / "otp_discovery"
LOG_PATH = ARTIFACT_DIR / "discovery_log.json"
SUMMARY_PATH = ARTIFACT_DIR / "discovery_summary.md"

# Documented Razorpay Test Mode values — used in browser only, never logged.
# Prefer Mastercard if Visa path shows a Test Mode "facing issues" banner.
_TEST_CARD_VISA = "4100280000001007"
_TEST_CARD_MC = "5555510000081006"
_TEST_EXPIRY = "1230"  # MMYY future
_TEST_CVV = "123"
# Dummy Indian-format mobiles for Checkout contact modal (not real customers).
# Razorpay rejects some obviously fake sequences; try a small set.
_TEST_MOBILES = ("9123456789", "9810098100", "9000012345")

def sanitize_url(url: str | None) -> str:
    if not url:
        return ""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def redact_text(value: str) -> str:
    """Remove accidental card/OTP-looking sequences from discovery text."""
    text = value
    text = re.sub(r"\b4100280000001007\b", "[REDACTED_CARD]", text)
    text = re.sub(r"\b(?:\d[ -]*?){13,19}\b", "[REDACTED_DIGITS]", text)
    text = re.sub(r"\b\d{3,4}\b", "[REDACTED_SHORT]", text)
    return text


def screenshot(page: Page, name: str) -> str:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACT_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return str(path.relative_to(ROOT))


def port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex((host, port)) == 0


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def ensure_flask() -> tuple[str, subprocess.Popen[str] | None]:
    """
    Start a dedicated discovery server on a free port.

    Set DISCOVERY_REUSE_FLASK=1 to reuse FLASK_HOST:FLASK_PORT when already up.
    """
    import os
    import urllib.request

    host = "127.0.0.1"
    reuse = os.getenv("DISCOVERY_REUSE_FLASK", "").strip() in {"1", "true", "yes"}
    if reuse and port_open(FLASK_HOST, FLASK_PORT):
        try:
            with urllib.request.urlopen(
                f"http://{FLASK_HOST}:{FLASK_PORT}/", timeout=5
            ) as resp:
                if resp.status == 200:
                    base = f"http://{FLASK_HOST}:{FLASK_PORT}"
                    print(f"[discovery] Reusing Flask at {base}")
                    return base, None
        except Exception as exc:  # noqa: BLE001
            print(f"[discovery] Reuse failed ({type(exc).__name__}); starting dedicated server")

    port = free_port()
    base = f"http://{host}:{port}"
    print(f"[discovery] Starting dedicated Flask at {base}")
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    log_file = ARTIFACT_DIR / "flask_discovery_server.log"
    handle = log_file.open("w", encoding="utf-8")
    env = dict(os.environ)
    env["FLASK_HOST"] = host
    env["FLASK_PORT"] = str(port)
    env["FLASK_DEBUG"] = "false"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "from app import app; "
                f"app.run(host={host!r}, port={port}, "
                "debug=False, use_reloader=False, threaded=True)"
            ),
        ],
        cwd=str(ROOT),
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if port_open(host, port):
            print("[discovery] Flask is ready")
            proc._discovery_log_handle = handle  # type: ignore[attr-defined]
            return base, proc
        if proc.poll() is not None:
            handle.close()
            raise RuntimeError("Flask process exited before becoming ready")
        time.sleep(0.25)
    handle.close()
    proc.terminate()
    raise RuntimeError("Timed out waiting for Flask")


def stop_flask(proc: subprocess.Popen[str] | None) -> None:
    if proc is None:
        return
    print("[discovery] Stopping Flask started by this script")
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    handle = getattr(proc, "_discovery_log_handle", None)
    if handle:
        handle.close()


def list_frames(page: Page) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for index, frame in enumerate(page.frames):
        frames.append(
            {
                "index": index,
                "name": frame.name or "",
                "url": sanitize_url(frame.url),
                "parent": sanitize_url(frame.parent_frame.url) if frame.parent_frame else None,
                "is_detached": frame.is_detached(),
            }
        )
    return frames


def collect_interactive(frame: Frame, limit: int = 80) -> list[dict[str, Any]]:
    script = """
    (limit) => {
      const out = [];
      const nodes = Array.from(document.querySelectorAll(
        'input, button, a, [role="button"], [role="textbox"], [role="radio"], ' +
        '[role="tab"], select, textarea, [contenteditable="true"]'
      ));
      for (const el of nodes.slice(0, limit)) {
        const style = window.getComputedStyle(el);
        const visible = style && style.visibility !== 'hidden' &&
          style.display !== 'none' && el.offsetParent !== null;
        out.push({
          tag: el.tagName.toLowerCase(),
          type: el.getAttribute('type') || '',
          id: el.id || '',
          name: el.getAttribute('name') || '',
          role: el.getAttribute('role') || '',
          ariaLabel: el.getAttribute('aria-label') || '',
          placeholder: el.getAttribute('placeholder') || '',
          text: (el.innerText || el.value || '').trim().slice(0, 80),
          className: (el.className || '').toString().slice(0, 120),
          visible: Boolean(visible),
        });
      }
      return out;
    }
    """
    try:
        raw = frame.evaluate(script, limit)
    except Exception as exc:  # noqa: BLE001
        return [{"error": f"frame evaluate failed: {type(exc).__name__}"}]

    sanitized: list[dict[str, Any]] = []
    for item in raw:
        sanitized.append(
            {
                "tag": item.get("tag"),
                "type": item.get("type"),
                "id": item.get("id"),
                "name": item.get("name"),
                "role": item.get("role"),
                "ariaLabel": redact_text(str(item.get("ariaLabel") or "")),
                "placeholder": redact_text(str(item.get("placeholder") or "")),
                "text": redact_text(str(item.get("text") or "")),
                "className": item.get("className"),
                "visible": item.get("visible"),
            }
        )
    return sanitized


def find_checkout_frame(page: Page) -> Frame | None:
    for frame in page.frames:
        url = (frame.url or "").lower()
        name = (frame.name or "").lower()
        if "razorpay" in url or "razorpay" in name or "checkout" in name:
            if frame != page.main_frame:
                return frame
    # Fallback: first child frame
    children = [f for f in page.frames if f.parent_frame == page.main_frame]
    return children[0] if children else None


def try_click(frame: Frame | Page, selectors: list[str], label: str) -> bool:
    for selector in selectors:
        locator = frame.locator(selector).first
        try:
            if locator.count() == 0:
                continue
            locator.click(timeout=4000, force=True)
            print(f"[discovery] Clicked {label} via selector family member")
            return True
        except Exception:  # noqa: BLE001
            continue
    # Role/text fallbacks commonly used by Checkout.
    role_names = {
        "contact continue": ["Continue"],
        "pay": ["Pay", "Pay Now"],
        "card method": ["Cards", "Card"],
    }
    for name in role_names.get(label, []):
        try:
            frame.get_by_role("button", name=name).first.click(timeout=4000, force=True)
            print(f"[discovery] Clicked {label} via role={name}")
            return True
        except Exception:  # noqa: BLE001
            try:
                frame.get_by_text(name, exact=True).first.click(timeout=4000, force=True)
                print(f"[discovery] Clicked {label} via text={name}")
                return True
            except Exception:  # noqa: BLE001
                continue
    return False


def try_fill(frame: Frame | Page, selectors: list[str], value: str, label: str) -> bool:
    for selector in selectors:
        locator = frame.locator(selector).first
        try:
            if locator.count() == 0:
                continue
            locator.click(timeout=3000)
            locator.fill("")
            locator.type(value, delay=40)
            print(f"[discovery] Filled {label} (value not logged)")
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


def classify_challenge(elements: list[dict[str, Any]]) -> str:
    blob = " ".join(
        f"{e.get('ariaLabel','')} {e.get('placeholder','')} {e.get('text','')} {e.get('name','')} {e.get('id','')}"
        for e in elements
    ).lower()
    has_otp = any(k in blob for k in ("otp", "one time", "one-time", "passcode", "authentication"))
    has_success = "success" in blob
    has_failure = "failure" in blob or "fail" in blob
    if has_otp and (has_success or has_failure):
        return "mock_otp_and_success_failure"
    if has_otp:
        return "mock_otp_input"
    if has_success and has_failure:
        return "mock_success_failure_buttons"
    if has_success or has_failure:
        return "partial_mock_bank_controls"
    return "unknown_or_not_reached"


def build_selector_hints(elements: list[dict[str, Any]]) -> dict[str, list[str]]:
    otp: list[str] = []
    submit: list[str] = []
    success: list[str] = []
    failure: list[str] = []

    for el in elements:
        if not el.get("visible"):
            continue
        label = " ".join(
            [
                str(el.get("ariaLabel") or ""),
                str(el.get("placeholder") or ""),
                str(el.get("name") or ""),
                str(el.get("id") or ""),
                str(el.get("text") or ""),
            ]
        ).lower()
        css_bits = []
        if el.get("id"):
            css_bits.append(f"#{el['id']}")
        if el.get("name"):
            css_bits.append(f"[name='{el['name']}']")
        if el.get("ariaLabel"):
            css_bits.append(f"[aria-label='{el['ariaLabel']}']")
        if el.get("placeholder"):
            css_bits.append(f"[placeholder='{el['placeholder']}']")
        role = el.get("role") or ""
        tag = el.get("tag") or ""
        text = (el.get("text") or "").strip()

        if any(k in label for k in ("otp", "one time", "passcode")) and tag in {"input", "textarea"}:
            otp.extend(css_bits or [f"{tag}[type='{el.get('type') or 'text'}']"])
        if tag == "button" or role == "button":
            if "submit" in label or text.lower() in {"submit", "verify", "continue", "pay"}:
                if text:
                    submit.append(f"button:has-text('{text[:40]}')")
                submit.extend(css_bits)
            if "success" in label or text.lower() == "success":
                success.append(f"button:has-text('{text[:40] or 'Success'}')")
                success.extend(css_bits)
            if "fail" in label or text.lower() in {"failure", "fail"}:
                failure.append(f"button:has-text('{text[:40] or 'Failure'}')")
                failure.extend(css_bits)

    def uniq(items: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for item in items:
            if item and item not in seen:
                seen.add(item)
                out.append(item)
        return out

    return {
        "otp_input_candidates": uniq(otp),
        "submit_candidates": uniq(submit),
        "success_candidates": uniq(success),
        "failure_candidates": uniq(failure),
    }


def run_discovery(base_url: str) -> dict[str, Any]:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "stages": [],
        "frames": [],
        "challenge": {},
        "notes": [],
        "console_errors": [],
        "network": [],
    }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False, slow_mo=150)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.set_default_timeout(20000)

        def on_console(msg) -> None:
            if msg.type in {"error", "warning"}:
                report["console_errors"].append(
                    {"type": msg.type, "text": redact_text(msg.text)}
                )

        def on_response(resp) -> None:
            if "/create-order" in resp.url or "/verify-payment" in resp.url:
                report["network"].append(
                    {
                        "url": sanitize_url(resp.url),
                        "status": resp.status,
                        "method": resp.request.method,
                    }
                )

        page.on("console", on_console)
        page.on("response", on_response)

        try:
            print("[discovery] Opening homepage")
            page.goto(f"{base_url}/", wait_until="domcontentloaded")
            page.get_by_test_id("homepage").wait_for(state="visible")
            report["stages"].append(
                {"stage": "homepage", "screenshot": screenshot(page, "01_homepage")}
            )

            page.get_by_test_id("add-to-cart").click()
            page.get_by_test_id("cart-item").wait_for(state="visible")
            page.get_by_test_id("proceed-to-payment").wait_for(state="visible")
            # Ensure enabled before clicking.
            page.wait_for_function(
                """() => {
                  const btn = document.querySelector('[data-testid="proceed-to-payment"]');
                  return btn && !btn.disabled;
                }"""
            )
            report["stages"].append(
                {"stage": "cart", "screenshot": screenshot(page, "02_cart")}
            )

            # Runtime-only prefill wrapper (does not modify application source).
            # Helps skip/satisfy Checkout contact collection during discovery.
            page.evaluate(
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
            report["notes"].append(
                "Applied runtime Razorpay prefill wrapper for contact (source files unchanged)."
            )

            print("[discovery] Initiating checkout / create-order")
            try:
                with page.expect_response(
                    lambda r: "/create-order" in r.url and r.request.method == "POST",
                    timeout=60000,
                ) as order_info:
                    page.get_by_test_id("proceed-to-payment").click()
                order_response = order_info.value
                report["stages"].append(
                    {
                        "stage": "create_order_response",
                        "status": order_response.status,
                        "url": sanitize_url(order_response.url),
                    }
                )
                if order_response.status != 201:
                    report["notes"].append(
                        f"create-order returned HTTP {order_response.status}"
                    )
            except Exception as exc:  # noqa: BLE001
                report["notes"].append(
                    f"create-order wait failed: {type(exc).__name__}"
                )
                report["stages"].append(
                    {
                        "stage": "create_order_timeout",
                        "screenshot": screenshot(page, "02b_create_order_timeout"),
                        "payment_status": redact_text(
                            page.get_by_test_id("payment-status").inner_text()
                        ),
                    }
                )
                # Continue discovery attempt anyway in case Checkout opened.

            page.locator(
                "iframe.razorpay-checkout-frame, iframe[src*='razorpay'], "
                "iframe[name*='razorpay'], iframe[id*='razorpay']"
            ).first.wait_for(state="visible", timeout=45000)
            page.wait_for_timeout(1500)
            report["stages"].append(
                {
                    "stage": "checkout_open",
                    "screenshot": screenshot(page, "03_checkout_open"),
                    "frames": list_frames(page),
                }
            )

            checkout = find_checkout_frame(page)
            if checkout is None:
                report["notes"].append("Checkout iframe not found after open()")
                report["frames"] = list_frames(page)
                return report

            # Prefer Card method.
            card_clicked = try_click(
                checkout,
                [
                    "div[role='button']:has-text('Cards')",
                    "button:has-text('Cards')",
                    "button:has-text('Card')",
                    "[data-value='card']",
                    "text=Cards",
                    "text=Card",
                    "[aria-label*='Card' i]",
                ],
                "card method",
            )
            if not card_clicked:
                # Try main page frame locators as fallback.
                card_clicked = try_click(
                    page,
                    [
                        "iframe >> text=Card",
                        "text=Card",
                    ],
                    "card method (page)",
                )
            page.wait_for_timeout(1000)
            report["stages"].append(
                {
                    "stage": "card_method",
                    "card_method_clicked": card_clicked,
                    "screenshot": screenshot(page, "04_card_method"),
                    "checkout_elements": collect_interactive(checkout),
                }
            )

            # Fill card fields inside checkout / nested frames without logging values.
            fill_targets = [checkout] + [
                f for f in page.frames if f.parent_frame == checkout
            ]
            filled = {"number": False, "expiry": False, "cvv": False}
            # Try Mastercard first to avoid intermittent Visa Test Mode banners.
            card_candidates = [_TEST_CARD_MC, _TEST_CARD_VISA]
            for target in fill_targets:
                if not filled["number"]:
                    for card_value in card_candidates:
                        ok = try_fill(
                            target,
                            [
                                "input[name='card.number']",
                                "input[name='card[number]']",
                                "input[name='card_number']",
                                "input[autocomplete='cc-number']",
                                "input[aria-label='Card Number']",
                                "input[placeholder*='Card Number' i]",
                            ],
                            card_value,
                            "card number",
                        )
                        if ok:
                            filled["number"] = True
                            break
                if not filled["expiry"]:
                    filled["expiry"] = try_fill(
                        target,
                        [
                            "input[name='card.expiry']",
                            "input[name='card[expiry]']",
                            "input[name='card_expiry']",
                            "input[autocomplete='cc-exp']",
                            "input[placeholder*='MM' i]",
                            "input[aria-label*='Expir' i]",
                        ],
                        _TEST_EXPIRY,
                        "expiry",
                    )
                if not filled["cvv"]:
                    filled["cvv"] = try_fill(
                        target,
                        [
                            "input[name='card.cvv']",
                            "input[name='card[cvv]']",
                            "input[name='card_cvv']",
                            "input[autocomplete='cc-csc']",
                            "input[placeholder*='CVV' i]",
                            "input[aria-label*='CVV' i]",
                        ],
                        _TEST_CVV,
                        "cvv",
                    )

            report["stages"].append(
                {
                    "stage": "card_fields_attempted",
                    "filled_flags": filled,
                    "screenshot": screenshot(page, "05_card_fields"),
                    "frames": list_frames(page),
                }
            )

            # Razorpay may require contact/mobile before Pay.
            checkout = find_checkout_frame(page) or checkout
            contact_filled = False
            continue_clicked = False
            contact_accepted = False
            for mobile in _TEST_MOBILES:
                try:
                    mobile_input = checkout.get_by_label("Mobile number", exact=False)
                    if mobile_input.count() == 0:
                        mobile_input = checkout.locator(
                            "input[placeholder*='Mobile' i], input[aria-label*='Mobile' i]"
                        ).first
                    mobile_input.click(timeout=3000)
                    mobile_input.fill("")
                    mobile_input.type(mobile, delay=50)
                    contact_filled = True
                    print("[discovery] Filled mobile contact (value not logged)")
                except Exception:  # noqa: BLE001
                    contact_filled = try_fill(
                        checkout,
                        [
                            "input[name='contact']",
                            "input[placeholder*='Mobile' i]",
                            "input[aria-label*='Mobile' i]",
                        ],
                        mobile,
                        "mobile contact",
                    )
                continue_clicked = try_click(
                    checkout,
                    ["button:has-text('Continue')"],
                    "contact continue",
                )
                page.wait_for_timeout(1200)
                # Contact modal gone => accepted.
                try:
                    still_open = checkout.get_by_text("Contact details").count() > 0
                except Exception:  # noqa: BLE001
                    still_open = False
                if contact_filled and continue_clicked and not still_open:
                    contact_accepted = True
                    break
                report["notes"].append(
                    "Contact attempt rejected or modal still open; trying next dummy mobile."
                )

            report["stages"].append(
                {
                    "stage": "contact_details",
                    "contact_filled": contact_filled,
                    "continue_clicked": continue_clicked,
                    "contact_accepted": contact_accepted,
                    "screenshot": screenshot(page, "05b_contact"),
                }
            )

            # Refresh frame list after contact step.
            checkout = find_checkout_frame(page) or checkout
            fill_targets = [checkout] + [
                f
                for f in page.frames
                if f.parent_frame and "razorpay" in (f.parent_frame.url or "").lower()
            ]

            # Dismiss RBI save-card interstitial if present.
            rbi_dismissed = try_click(
                checkout,
                [
                    "button:has-text('Maybe later')",
                    "button:has-text('Maybe Later')",
                ],
                "rbi maybe later",
            )
            if not rbi_dismissed:
                try:
                    checkout.get_by_role("button", name="Maybe later").click(
                        timeout=3000, force=True
                    )
                    rbi_dismissed = True
                    print("[discovery] Dismissed RBI save-card modal")
                except Exception:  # noqa: BLE001
                    pass
            page.wait_for_timeout(1000)
            report["stages"].append(
                {
                    "stage": "rbi_save_card",
                    "dismissed": rbi_dismissed,
                    "screenshot": screenshot(page, "05c_rbi"),
                }
            )

            pay_clicked = False
            for target in [t for t in fill_targets if t] + [page]:
                pay_clicked = try_click(
                    target,
                    [
                        "button:has-text('Continue')",
                        "button:has-text('Pay')",
                        "button:has-text('Pay Now')",
                        "button:has-text('Proceed')",
                        "button[type='submit']",
                        "button:has-text('₹')",
                    ],
                    "pay",
                )
                if pay_clicked:
                    break
            # Second Continue sometimes required after RBI dismiss.
            page.wait_for_timeout(1000)
            try_click(
                checkout,
                ["button:has-text('Continue')", "button:has-text('Pay')"],
                "pay",
            )

            # Wait for mock ACS / OTP challenge to appear (do not complete it).
            for _ in range(20):
                page.wait_for_timeout(500)
                blob = " ".join(
                    json.dumps(collect_interactive(frame)).lower()
                    for frame in page.frames
                )
                if any(
                    token in blob
                    for token in ("otp", "success", "failure", "one time", "authentication")
                ):
                    break

            report["stages"].append(
                {
                    "stage": "after_pay_click",
                    "pay_clicked": pay_clicked,
                    "screenshot": screenshot(page, "06_after_pay"),
                    "frames": list_frames(page),
                    "page_url": sanitize_url(page.url),
                }
            )

            # Inventory all frames after pay.
            frame_inventory: list[dict[str, Any]] = []
            all_elements: list[dict[str, Any]] = []
            challenge_frame_meta: dict[str, Any] | None = None
            best_score = -1

            for index, frame in enumerate(page.frames):
                elements = collect_interactive(frame)
                meta = {
                    "index": index,
                    "name": frame.name or "",
                    "url": sanitize_url(frame.url),
                    "title": "",
                    "element_count": len(elements),
                    "elements": elements,
                }
                try:
                    meta["title"] = redact_text(frame.title())
                except Exception:  # noqa: BLE001
                    meta["title"] = ""
                frame_inventory.append(meta)
                all_elements.extend(elements)

                challenge_type = classify_challenge(elements)
                score = 0
                if challenge_type != "unknown_or_not_reached":
                    score += 5
                blob = json.dumps(elements).lower()
                score += blob.count("otp")
                score += blob.count("success")
                score += blob.count("failure")
                if score > best_score:
                    best_score = score
                    challenge_frame_meta = {
                        "index": index,
                        "name": frame.name or "",
                        "url": sanitize_url(frame.url),
                        "title": meta["title"],
                        "detected_challenge_type": challenge_type,
                        "selector_hints": build_selector_hints(elements),
                        "inside_checkout_tree": bool(
                            frame != page.main_frame
                            and (
                                "razorpay" in (frame.url or "").lower()
                                or (
                                    frame.parent_frame is not None
                                    and "razorpay" in (frame.parent_frame.url or "").lower()
                                )
                            )
                        ),
                    }

            report["frames"] = frame_inventory
            report["challenge"] = challenge_frame_meta or {
                "detected_challenge_type": "unknown_or_not_reached",
                "notes": "No OTP/Success/Failure controls detected after Pay.",
            }
            report["stages"].append(
                {
                    "stage": "challenge_inventory",
                    "screenshot": screenshot(page, "07_challenge_inventory"),
                    "frame_count": len(page.frames),
                }
            )

            # Explicitly do NOT submit OTP or click Success/Failure.
            report["notes"].append(
                "Discovery stopped before completing payment; OTP/Success were not submitted."
            )
            report["playwright_can_list_challenge"] = best_score > 0
            report["manual_interaction_still_required"] = (
                challenge_frame_meta is None
                or challenge_frame_meta.get("detected_challenge_type")
                == "unknown_or_not_reached"
                or not filled["number"]
            )

            # Keep headed window briefly for human observation.
            page.wait_for_timeout(5000)
        finally:
            context.close()
            browser.close()

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    return report


def write_summary(report: dict[str, Any]) -> None:
    challenge = report.get("challenge") or {}
    hints = challenge.get("selector_hints") or {}
    frames = report.get("frames") or []
    checkout_frames = [
        f
        for f in frames
        if "razorpay" in str(f.get("url", "")).lower()
        or "hcaptcha" in str(f.get("url", "")).lower()
        or "sardine" in str(f.get("url", "")).lower()
    ]
    lines = [
        "# Razorpay OTP Discovery Summary",
        "",
        f"- Started: `{report.get('started_at')}`",
        f"- Finished: `{report.get('finished_at')}`",
        f"- Base URL: `{report.get('base_url')}`",
        f"- Frame count: `{len(frames)}`",
        f"- Challenge type: `{challenge.get('detected_challenge_type')}`",
        f"- Challenge frame index: `{challenge.get('index')}`",
        f"- Challenge frame name: `{challenge.get('name')}`",
        f"- Challenge frame URL: `{challenge.get('url')}`",
        f"- Inside checkout tree: `{challenge.get('inside_checkout_tree')}`",
        "",
        "## Confirmed Checkout structure",
        "- Primary Checkout frame URL pattern: `https://api.razorpay.com/v1/checkout/public`",
        "- Checkout remains an iframe on the merchant page (not a popup window).",
        "- Nested frames observed: fraud/collector + hCaptcha (may require manual solve).",
        "- Card fields inside Checkout iframe:",
        "  - `input[name='card.number']` (aria-label: Card Number)",
        "  - `input[name='card.expiry']`",
        "  - `input[name='card.cvv']`",
        "- Contact gate before Pay: modal text `Contact details` / `Mobile number` / button `Continue`",
        "",
        "## Nested frame URLs (sanitized)",
    ]
    for frame in checkout_frames[:12]:
        lines.append(
            f"- index={frame.get('index')} name=`{frame.get('name')}` url=`{frame.get('url')}`"
        )
    lines.extend(
        [
            "",
            "## OTP / mock ACS selector candidates (sanitized)",
            f"- OTP input: `{hints.get('otp_input_candidates')}`",
            f"- Submit: `{hints.get('submit_candidates')}`",
            f"- Success: `{hints.get('success_candidates')}`",
            f"- Failure: `{hints.get('failure_candidates')}`",
            "",
            "## Feasibility",
            f"- Playwright can list challenge controls: `{report.get('playwright_can_list_challenge')}`",
            f"- Manual interaction still required: `{report.get('manual_interaction_still_required')}`",
            "",
            "## Notes",
        ]
    )
    for note in report.get("notes") or []:
        lines.append(f"- {note}")
    if challenge.get("detected_challenge_type") == "unknown_or_not_reached":
        lines.append(
            "- Mock OTP/ACS screen was NOT reached in this run; do not invent OTP selectors."
        )
    SUMMARY_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    flask_proc = None
    try:
        base_url, flask_proc = ensure_flask()
        report = run_discovery(base_url)
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        LOG_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
        write_summary(report)
        print(f"[discovery] Wrote {LOG_PATH.relative_to(ROOT)}")
        print(f"[discovery] Wrote {SUMMARY_PATH.relative_to(ROOT)}")
        challenge = report.get("challenge") or {}
        print("[discovery] Challenge type:", challenge.get("detected_challenge_type"))
        print("[discovery] Challenge frame:", challenge.get("name"), challenge.get("url"))
        # Non-zero only on hard failures before meaningful artifacts.
        if not report.get("stages"):
            return 1
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[discovery] FAILED: {exc}")
        return 1
    finally:
        stop_flask(flask_proc)


if __name__ == "__main__":
    raise SystemExit(main())
