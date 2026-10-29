"""End-to-end checks against the deployed service, using real Chrome."""

import csv
import io
import json
import os
import sys
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

sys.stdout.reconfigure(encoding="utf8")
URL = os.environ.get("TASK6_URL", "https://task6.evgeniy.win")
ROOT = Path(__file__).resolve().parent


def main():
    checks = []
    with httpx.Client(base_url=URL, trust_env=False, timeout=30) as client:
        a = client.get("/api/contacts").json()
        assert a["contacts"] == client.get("/api/contacts").json()["contacts"]
        checks.append("HTTP reproducibility")
        for params in (
            {"locale": "invalid"},
            {"size": 101},
            {"size": 0},
            {"page": -1},
            {"seed": "x" * 65},
        ):
            assert client.get("/api/contacts", params=params).status_code == 422
        checks.append("HTTP input bounds")
        r = client.get("/download")
        r.raise_for_status()
        rows = list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))
        assert (
            len(rows) == 10 and rows[0]["full_name"] == a["contacts"][0]["name"]["full"]
        )
        assert client.get("/download?format=json").json()["contacts"] == a["contacts"]
        checks.append("CSV and JSON equal displayed batch")
        assert client.get("/healthz").json()["status"] == "ok"
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000}, device_scale_factor=1
        )
        page = context.new_page()
        errors = []
        requests = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("request", lambda r: requests.append(r.url))
        page.goto(URL, wait_until="networkidle")
        # A theme preference must survive navigation and reloads.
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        page.locator("#theme-toggle").click()
        expect(page.locator("html")).to_have_attribute("data-theme", "light")
        page.reload(wait_until="networkidle")
        expect(page.locator("html")).to_have_attribute("data-theme", "light")
        page.goto(URL + "/library", wait_until="networkidle")
        expect(page.locator("html")).to_have_attribute("data-theme", "light")
        page.locator("#theme-toggle").click()
        page.goto(URL, wait_until="networkidle")
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        assert page.evaluate("htmx.version") == "4.0.0"
        checks.append("Dark/light theme persists across reload and pages; HTMX 4.0.0")
        expect(page.locator("[data-index]")).to_have_count(10)
        expect(page.locator('[data-index="0"]')).to_contain_text("Dr. Melissa Goodwin")
        first = page.locator('[data-index="0"]').inner_text()
        page.locator("#next").click()
        expect(page.locator('[data-index="0"] .position')).to_have_text("0011")
        page.locator("#previous").click()
        expect(page.locator('[data-index="0"] .position')).to_have_text("0001")
        assert page.locator('[data-index="0"]').inner_text() == first
        checks.append("Next / previous restores exact contacts")
        page.locator("#locale").select_option("de_DE")
        expect(page.locator('[data-index="0"]')).to_contain_text("Harro Holt")
        page.locator('[data-index="0"] .person-name').click()
        expect(page.locator("#detail")).to_be_visible()
        expect(page.locator("#detail")).to_contain_text("Frankfurt am Main")
        expect(page.locator("#detail")).to_contain_text("LATITUDE")
        page.keyboard.press("Escape")
        expect(page.locator("#detail")).not_to_be_visible()
        checks.append("German locale and full contact dialog")
        page.locator("#size").select_option("25")
        expect(page.locator("[data-index]")).to_have_count(25)
        page.locator("#page-number").fill("40000")
        page.locator("#page-number").press("Enter")
        expect(page.locator('[data-index="24"] .position')).to_have_text("1000000")
        checks.append("Direct navigation to millionth contact")
        page.locator("#size").select_option("10")
        expect(page.locator("[data-index]")).to_have_count(10)
        page.locator("#seed").fill('a " & <script>window.PWNED=1</script>')
        page.locator("#generate").click()
        page.wait_for_function(
            "document.querySelector('#batch-data').textContent.includes('PWNED')"
        )
        assert page.evaluate("window.PWNED") is None
        page.locator('[data-index="0"] .person-name').click()
        expect(page.locator("#detail")).to_contain_text("<script>")
        assert page.evaluate("window.PWNED") is None
        page.keyboard.press("Escape")
        checks.append("Arbitrary seed is escaped in HTML and JSON")
        page.locator("#seed").fill("42")
        page.locator("#locale").select_option("en_US")
        expect(page.locator('[data-index="0"]')).to_contain_text("Dr. Melissa Goodwin")
        # Rapid changes must leave the newest request authoritative.
        page.evaluate("""() => {
            const select = document.querySelector('#locale');
            select.value = 'de_DE'; select.dispatchEvent(new Event('change', {bubbles:true}));
            select.value = 'en_US'; select.dispatchEvent(new Event('change', {bubbles:true}));
        }""")
        page.wait_for_function("!document.body.classList.contains('loading')")
        expect(page.locator('[data-index="0"]')).to_contain_text("Dr. Melissa Goodwin")
        expect(page.locator("#error")).to_be_empty()
        checks.append("Rapid locale changes retain newest state without an abort error")
        # Error feedback must preserve the last good batch and unlock controls.
        page.route("**/fragment?*", lambda route: route.abort())
        page.locator("#generate").click()
        expect(page.locator("#error")).to_contain_text("could not be completed")
        expect(page.locator("#generate")).to_be_enabled()
        assert page.locator("[data-index]").count() == 10
        page.unroute("**/fragment?*")
        checks.append("Network failure feedback and recovery")
        page.locator("#generate").click()
        expect(page.locator("#error")).to_be_empty()
        page.wait_for_function("!document.body.classList.contains('loading')")
        page.screenshot(
            path=str(ROOT / "artifacts/desktop-screenshot.png"), full_page=True
        )
        for width in (390, 768, 1440):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth"), (
                width
            )
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator('[data-index="0"] .person-name').click()
        expect(page.locator("#detail")).to_be_visible()
        assert page.locator("#detail").bounding_box()["width"] < 390
        page.keyboard.press("Escape")
        page.screenshot(
            path=str(ROOT / "artifacts/mobile-screenshot.png"), full_page=True
        )
        checks.append("390 / 768 / 1440px responsive layouts and mobile dialog")
        page.goto(URL + "/library")
        expect(page.locator(".doc-body")).to_contain_text("Box–Muller")
        assert page.locator(".doc-body pre").count() >= 15
        page.goto(URL + "/benchmark")
        expect(page.locator("h1")).to_contain_text("How fast")
        assert not errors, errors
        for route in ("/library", "/benchmark", "/api/docs"):
            page.goto(URL + route, wait_until="networkidle")
            for width in (390, 768, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                assert page.evaluate(
                    "document.documentElement.scrollWidth<=innerWidth"
                ), (route, width)
        checks.append(
            "Documentation, benchmark, HTTP reference responsive in all sizes"
        )
        checks.append("No JavaScript errors")
        assert all(url.startswith(URL) for url in requests), [
            url for url in requests if not url.startswith(URL)
        ]
        checks.append(
            "All scripts, styles and fonts are self-hosted; no external requests"
        )
        # The enhanced interface must still work as ordinary server-rendered HTML.
        fallback = browser.new_context(java_script_enabled=False)
        plain = fallback.new_page()
        plain.goto(URL, wait_until="networkidle")
        plain.locator("#locale").select_option("de_DE")
        plain.locator("#generate").click()
        expect(plain.locator('[data-index="0"]')).to_contain_text("Harro Holt")
        plain.locator("#next").click()
        expect(plain.locator('[data-index="0"] .position')).to_have_text("0011")
        plain.locator('[data-index="0"] .person-name').click()
        expect(plain.locator("#main #detail-title")).to_be_visible()
        checks.append(
            "Forms, pagination and standalone dossiers work without JavaScript"
        )
        fallback.close()
        browser.close()
    (ROOT / "artifacts/browser-checks.json").write_text(
        json.dumps({"passed": len(checks), "checks": checks}, indent=2) + "\n"
    )
    for c in checks:
        print("PASS", c)


if __name__ == "__main__":
    main()
