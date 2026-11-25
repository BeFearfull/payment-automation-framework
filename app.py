"""Flask demo shop with Razorpay Test Mode Standard Checkout."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from razorpay.errors import BadRequestError, SignatureVerificationError

from config.settings import (
    FLASK_DEBUG,
    FLASK_HOST,
    FLASK_PORT,
    FLASK_SECRET_KEY,
    PRODUCT,
    RAZORPAY_KEY_ID,
    RAZORPAY_KEY_SECRET,
)
from utils.logger import get_logger
from utils.payment_verification import (
    PaymentLifecycleError,
    create_razorpay_client,
    verify_payment_lifecycle,
    verify_payment_signature,
)

logger = get_logger(__name__)

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY

razorpay_client = create_razorpay_client(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)

# In-memory guards for this demo process (not a production store).
_order_lock = threading.Lock()
_recent_receipts: dict[str, float] = {}
_verified_orders: set[str] = set()
_RECEIPT_TTL_SECONDS = 120


def _prune_recent_receipts(now: float) -> None:
    expired = [
        receipt
        for receipt, created_at in _recent_receipts.items()
        if now - created_at > _RECEIPT_TTL_SECONDS
    ]
    for receipt in expired:
        _recent_receipts.pop(receipt, None)


@app.get("/")
def home() -> str:
    """Demo shopping homepage."""
    return render_template(
        "index.html",
        product=PRODUCT,
        razorpay_key_id=RAZORPAY_KEY_ID,
    )


@app.get("/checkout")
def checkout_page() -> Any:
    """Keep existing checkout route; shopping flow lives on the homepage."""
    return redirect(url_for("home"))


@app.post("/create-order")
def create_order() -> Any:
    """Create a Razorpay Test Mode order on the server."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object."}), 400
    product_id = payload.get("product_id")
    quantity = payload.get("quantity", 1)
    client_request_id = str(payload.get("client_request_id") or "").strip()

    if product_id != PRODUCT["id"]:
        return jsonify({"error": "Unknown product."}), 400

    # Reject bool (subclass of int) and non-integral floats before coercion.
    if isinstance(quantity, bool) or isinstance(quantity, float):
        return jsonify({"error": "quantity must be an integer."}), 400
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        return jsonify({"error": "quantity must be an integer."}), 400

    if quantity != 1:
        return jsonify({"error": "This demo supports quantity=1 only."}), 400

    if not client_request_id:
        return jsonify({"error": "client_request_id is required."}), 400

    now = time.time()
    with _order_lock:
        _prune_recent_receipts(now)
        if client_request_id in _recent_receipts:
            return (
                jsonify(
                    {
                        "error": "Duplicate order request detected. Please wait and retry.",
                    }
                ),
                409,
            )
        _recent_receipts[client_request_id] = now

    receipt = f"rcpt_{uuid.uuid4().hex[:16]}"
    order_data = {
        "amount": PRODUCT["amount_paise"],
        "currency": PRODUCT["currency"],
        "receipt": receipt,
        "notes": {
            "product_id": PRODUCT["id"],
            "product_name": PRODUCT["name"],
            "client_request_id": client_request_id,
        },
    }

    try:
        order = razorpay_client.order.create(data=order_data)
    except BadRequestError as exc:
        logger.exception("Razorpay rejected order creation")
        with _order_lock:
            _recent_receipts.pop(client_request_id, None)
        return jsonify({"error": "Unable to create order.", "details": str(exc)}), 400
    except Exception as exc:  # noqa: BLE001 - surface upstream failures cleanly
        logger.exception("Unexpected error while creating Razorpay order")
        with _order_lock:
            _recent_receipts.pop(client_request_id, None)
        return jsonify({"error": "Order creation failed.", "details": str(exc)}), 502

    logger.info("Created Razorpay order id=%s receipt=%s", order.get("id"), receipt)

    # Only the public key ID is returned to the browser.
    return jsonify(
        {
            "order_id": order["id"],
            "amount": order["amount"],
            "currency": order["currency"],
            "key_id": RAZORPAY_KEY_ID,
            "product_name": PRODUCT["name"],
            "receipt": order.get("receipt"),
        }
    ), 201


def _session_has_protected_verification() -> bool:
    """True when the browser session already holds a successfully verified order."""
    if not session.get("payment_verified"):
        return False
    verified = session.get("verified_payment") or {}
    order_id = str(verified.get("razorpay_order_id") or "").strip()
    if not order_id:
        return False
    with _order_lock:
        return order_id in _verified_orders


def _safe_clear_session_on_failure() -> None:
    """
    Clear unverified session state after a failed attempt.

    Never wipe a session that already completed lifecycle verification for a
    recorded order (failed replays must not overwrite success).
    """
    if _session_has_protected_verification():
        logger.info("Preserving verified payment session after failed replay")
        return
    session.pop("verified_payment", None)
    session.pop("payment_verified", None)


@app.post("/verify-payment")
def verify_payment() -> Any:
    """
    Verify Checkout fields, then confirm Razorpay payment lifecycle.

    Success requires: valid signature AND payment.fetch/order.fetch showing
    captured status with matching order, amount, and currency.
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object."}), 400
    required = ("razorpay_order_id", "razorpay_payment_id", "razorpay_signature")
    missing = [field for field in required if not payload.get(field)]
    if missing:
        return (
            jsonify({"error": "Missing required fields.", "missing": missing}),
            400,
        )

    order_id = str(payload["razorpay_order_id"]).strip()
    payment_id = str(payload["razorpay_payment_id"]).strip()
    signature = str(payload["razorpay_signature"]).strip()

    if not order_id or not payment_id or not signature:
        return jsonify({"error": "Malformed payment verification payload."}), 400

    # 1) Signature first — including idempotent retries — so a known order_id
    # cannot be replayed with a forged payment_id/signature.
    try:
        verify_payment_signature(
            razorpay_client,
            razorpay_order_id=order_id,
            razorpay_payment_id=payment_id,
            razorpay_signature=signature,
        )
    except SignatureVerificationError:
        logger.warning("Signature verification failed for order_id=%s", order_id)
        _safe_clear_session_on_failure()
        return jsonify({"error": "Payment signature verification failed."}), 400
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected signature verification error")
        return jsonify({"error": "Verification error.", "details": str(exc)}), 500

    # 2) Independent Razorpay lifecycle checks (never trust browser amount/status).
    try:
        lifecycle = verify_payment_lifecycle(
            razorpay_client,
            razorpay_order_id=order_id,
            razorpay_payment_id=payment_id,
            expected_amount=PRODUCT["amount_paise"],
            expected_currency=PRODUCT["currency"],
        )
    except PaymentLifecycleError as exc:
        logger.warning(
            "Payment lifecycle rejected order_id=%s code=%s status=%s",
            order_id,
            exc.code,
            exc.payment_status,
        )
        _safe_clear_session_on_failure()
        body: dict[str, Any] = {
            "error": exc.message,
            "code": exc.code,
        }
        if exc.payment_status:
            body["payment_status"] = exc.payment_status
        return jsonify(body), exc.http_status
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected payment lifecycle error")
        _safe_clear_session_on_failure()
        return jsonify({"error": "Verification error.", "details": str(exc)}), 500

    with _order_lock:
        already_seen = order_id in _verified_orders
        _verified_orders.add(order_id)

    session["verified_payment"] = {
        "razorpay_order_id": order_id,
        "razorpay_payment_id": payment_id,
        "product_name": PRODUCT["name"],
        "amount_inr": PRODUCT["price_inr"],
        "payment_status": lifecycle.get("status"),
        "currency": lifecycle.get("currency"),
        "amount_paise": lifecycle.get("amount"),
    }
    session["payment_verified"] = True

    return jsonify(
        {
            "status": "already_verified" if already_seen else "verified",
            "payment_status": lifecycle.get("status"),
            "redirect_url": url_for("payment_success"),
        }
    ), 200


@app.get("/payment-success")
def payment_success() -> Any:
    """Show success only after server-side verification."""
    if not session.get("payment_verified") or not session.get("verified_payment"):
        return redirect(url_for("payment_failure"))

    payment = session.get("verified_payment")
    return render_template("success.html", payment=payment, product=PRODUCT)


@app.get("/payment-failure")
def payment_failure() -> Any:
    """Display payment failure / unverified outcome."""
    reason = request.args.get("reason", "Payment was not completed or could not be verified.")
    return render_template("failure.html", reason=reason, product=PRODUCT), 200


@app.errorhandler(404)
def not_found(_: Exception) -> Any:
    return jsonify({"error": "Not found."}), 404


@app.errorhandler(405)
def method_not_allowed(_: Exception) -> Any:
    return jsonify({"error": "Method not allowed."}), 405


if __name__ == "__main__":
    logger.info(
        "Starting Payment Automation Framework on http://%s:%s (debug=%s)",
        FLASK_HOST,
        FLASK_PORT,
        FLASK_DEBUG,
    )
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)
