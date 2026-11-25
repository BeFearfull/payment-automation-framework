
from playwright.sync_api import Page, expect


def test_browser_launch(page: Page):

    page.goto("https://playwright.dev/")

    expect(
        page.get_by_role("heading", name="Playwright enables reliable web automation for testing, scripting, and AI agents.")
    ).to_be_visible()

    print("Browser automation working!")
