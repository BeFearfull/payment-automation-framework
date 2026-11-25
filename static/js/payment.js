(() => {
  "use strict";

  const product = window.APP_CONFIG?.product;
  const statusEl = document.querySelector('[data-testid="payment-status"]');
  const cartSummaryEl = document.querySelector('[data-testid="cart-summary"]');
  const cartTotalEl = document.querySelector('[data-testid="cart-total"]');
  const addToCartBtn = document.querySelector('[data-testid="add-to-cart"]');
  const checkoutBtn = document.querySelector('[data-testid="proceed-to-payment"]');

  let cartItem = null;
  let orderInFlight = false;
  let activeClientRequestId = null;

  function setStatus(message, tone = "") {
    if (!statusEl) return;
    statusEl.textContent = message;
    statusEl.classList.remove("is-error", "is-ok");
    if (tone) statusEl.classList.add(tone);
  }

  function renderCart() {
    if (!cartSummaryEl || !cartTotalEl) return;

    if (!cartItem) {
      cartSummaryEl.innerHTML =
        '<p class="cart-empty" data-testid="cart-empty">Your cart is empty.</p>';
      cartTotalEl.textContent = "₹0";
      if (checkoutBtn) checkoutBtn.disabled = true;
      return;
    }

    cartSummaryEl.innerHTML = `
      <div class="cart-line" data-testid="cart-item">
        <span data-testid="cart-item-name">${cartItem.name}</span>
        <span data-testid="cart-item-price">₹${cartItem.price_inr.toLocaleString("en-IN")}</span>
      </div>
    `;
    cartTotalEl.textContent = `₹${cartItem.price_inr.toLocaleString("en-IN")}`;
    if (checkoutBtn) checkoutBtn.disabled = false;
  }

  function createClientRequestId() {
    if (window.crypto?.randomUUID) {
      return window.crypto.randomUUID();
    }
    return `req_${Date.now()}_${Math.random().toString(16).slice(2)}`;
  }

  async function createOrder() {
    const response = await fetch("/create-order", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        product_id: product.id,
        quantity: 1,
        client_request_id: activeClientRequestId,
      }),
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = data.error || "Could not create order.";
      throw new Error(message);
    }
    return data;
  }

  async function verifyPayment(response) {
    const verifyResponse = await fetch("/verify-payment", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        razorpay_order_id: response.razorpay_order_id,
        razorpay_payment_id: response.razorpay_payment_id,
        razorpay_signature: response.razorpay_signature,
      }),
    });

    const data = await verifyResponse.json().catch(() => ({}));
    if (!verifyResponse.ok) {
      throw new Error(data.error || "Payment verification failed.");
    }
    return data;
  }

  function openCheckout(order) {
    if (typeof Razorpay === "undefined") {
      throw new Error("Razorpay Checkout script failed to load.");
    }

    const options = {
      key: order.key_id,
      amount: order.amount,
      currency: order.currency,
      name: "Payment Automation Demo",
      description: order.product_name || product.name,
      order_id: order.order_id,
      handler: async function handlePaymentSuccess(response) {
        try {
          setStatus("Verifying payment on server…");
          const result = await verifyPayment(response);
          setStatus("Payment verified. Redirecting…", "is-ok");
          window.location.href = result.redirect_url || "/payment-success";
        } catch (error) {
          setStatus(error.message || "Verification failed.", "is-error");
          window.location.href =
            "/payment-failure?reason=" +
            encodeURIComponent(error.message || "Verification failed");
        } finally {
          orderInFlight = false;
          activeClientRequestId = null;
          if (checkoutBtn) checkoutBtn.disabled = !cartItem;
        }
      },
      modal: {
        ondismiss: function onDismiss() {
          orderInFlight = false;
          activeClientRequestId = null;
          if (checkoutBtn) checkoutBtn.disabled = !cartItem;
          setStatus("Checkout closed before payment completed.");
        },
      },
      theme: {
        color: "#0f766e",
      },
    };

    const rzp = new Razorpay(options);

    rzp.on("payment.failed", function onPaymentFailed(response) {
      orderInFlight = false;
      activeClientRequestId = null;
      if (checkoutBtn) checkoutBtn.disabled = !cartItem;

      const description =
        response?.error?.description || "Payment failed at Razorpay Checkout.";
      setStatus(description, "is-error");
      window.location.href =
        "/payment-failure?reason=" + encodeURIComponent(description);
    });

    rzp.open();
  }

  async function startCheckout() {
    if (!cartItem || orderInFlight) return;

    orderInFlight = true;
    activeClientRequestId = createClientRequestId();
    if (checkoutBtn) checkoutBtn.disabled = true;
    setStatus("Creating Razorpay order…");

    try {
      const order = await createOrder();
      setStatus("Opening Razorpay Checkout…");
      openCheckout(order);
    } catch (error) {
      orderInFlight = false;
      activeClientRequestId = null;
      if (checkoutBtn) checkoutBtn.disabled = !cartItem;
      setStatus(error.message || "Checkout could not start.", "is-error");
    }
  }

  if (addToCartBtn) {
    addToCartBtn.addEventListener("click", () => {
      cartItem = {
        id: product.id,
        name: product.name,
        price_inr: product.price_inr,
      };
      renderCart();
      setStatus("Added Wireless Headphones to cart.", "is-ok");
    });
  }

  if (checkoutBtn) {
    checkoutBtn.addEventListener("click", startCheckout);
  }

  renderCart();
  setStatus("Ready. Add the product to cart to continue.");
})();
