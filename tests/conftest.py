"""Shared Pytest fixtures for web and payment automation."""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests
from playwright.sync_api import Page

from config.settings import PRODUCT

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = ROOT / "artifacts"
SCREENSHOTS_DIR = ARTIFACTS_DIR / "screenshots"
REPORTS_DIR = ROOT / "reports"

logger = logging.getLogger("tests")


def pytest_configure(config: pytest.Config) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    config.addinivalue_line("markers", "web: Web UI automation tests")
    config.addinivalue_line(
        "markers",
        "payment: Payment verification and order-security tests",
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_server(url: str, timeout_seconds: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = requests.get(url, timeout=1.5)
            if response.status_code < 500:
                return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError(f"Flask test server did not start at {url}: {last_error}")


@pytest.fixture(scope="session")
def product_catalog() -> dict:
    return PRODUCT


@pytest.fixture(scope="session")
def live_server() -> str:
    """
    Start a dedicated Flask process for Playwright tests.

    Uses a free local port so it does not clash with a developer server on :5000.
    Secrets still come from .env via config.settings — never hardcoded.
    """
    port = _free_port()
    host = "127.0.0.1"
    base_url = f"http://{host}:{port}"
    env = os.environ.copy()
    env["FLASK_HOST"] = host
    env["FLASK_PORT"] = str(port)
    env["FLASK_DEBUG"] = "false"

    command = [
        sys.executable,
        "-c",
        (
            "from app import app; "
            f"app.run(host='{host}', port={port}, debug=False, "
            "use_reloader=False, threaded=True)"
        ),
    ]
    logger.info("Starting Flask test server on %s", base_url)
    server_log = ARTIFACTS_DIR / "flask_test_server.log"
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    log_handle = server_log.open("w", encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=str(ROOT),
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_for_server(base_url + "/")
        logger.info("Flask test server is ready (log=%s)", server_log)
        yield base_url
    finally:
        logger.info("Stopping Flask test server pid=%s", process.pid)
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log_handle.close()



@pytest.fixture(scope="session")
def base_url(live_server: str) -> str:
    return live_server


@pytest.fixture
def home_page(page: Page, base_url: str):
    from tests.pages.home_page import HomePage

    return HomePage(page, base_url)


@pytest.fixture
def checkout_page(page: Page, base_url: str):
    from tests.pages.checkout_page import CheckoutPage

    return CheckoutPage(page, base_url)


@pytest.fixture
def payment_page(page: Page, base_url: str):
    from tests.pages.payment_page import PaymentPage

    return PaymentPage(page, base_url)


@pytest.fixture
def api_client(base_url: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    session.base_url = base_url  # type: ignore[attr-defined]
    return session


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)

    if report.when != "call" or not report.failed:
        return

    page = item.funcargs.get("page")
    if page is None:
        return

    safe_name = item.nodeid.replace("/", "_").replace("::", "_").replace(" ", "_")
    screenshot_path = SCREENSHOTS_DIR / f"{safe_name}.png"
    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
        logger.error("Saved failure screenshot: %s", screenshot_path)
        if hasattr(report, "extras"):
            from pytest_html import extras

            report.extras.append(extras.image(str(screenshot_path)))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not capture failure screenshot: %s", exc)
