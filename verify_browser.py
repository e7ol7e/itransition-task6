"""End-to-end checks against the deployed service, using real Chrome."""

import csv
import io
import json
import sys
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright

sys.stdout.reconfigure(encoding="utf8")
URL = "https://task6.evgeniy.win"
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
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(URL, wait_until="networkidle")
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
        page.locator('[data-index="0"]').click()
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
        expect(page.locator(".detail-foot")).to_have_count(1)
        page.wait_for_function(
            "document.querySelector('#batch-data').textContent.includes('PWNED')"
        )
        assert page.evaluate("window.PWNED") is None
        page.locator('[data-index="0"]').click()
        expect(page.locator("#detail")).to_contain_text("<script>")
        assert page.evaluate("window.PWNED") is None
        page.keyboard.press("Escape")
        checks.append("Arbitrary seed is escaped in HTML and JSON")
        page.locator("#seed").fill("42")
        page.locator("#locale").select_option("en_US")
        expect(page.locator('[data-index="0"]')).to_contain_text("Dr. Melissa Goodwin")
        # Error feedback must preserve the last good batch and unlock controls.
        page.route("**/fragment?*", lambda route: route.abort())
        page.locator("#generate").click()
        expect(page.locator("#error")).to_be_visible()
        expect(page.locator("#generate")).to_be_enabled()
        assert page.locator("[data-index]").count() == 10
        page.unroute("**/fragment?*")
        checks.append("Network failure feedback and recovery")
        page.locator("#generate").click()
        expect(page.locator("#error")).not_to_be_visible()
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
        page.locator('[data-index="0"]').click()
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
        checks.append("Documentation, benchmark route and no JavaScript errors")
        browser.close()
    (ROOT / "artifacts/browser-checks.json").write_text(
        json.dumps({"passed": len(checks), "checks": checks}, indent=2) + "\n"
    )
    for c in checks:
        print("PASS", c)


if __name__ == "__main__":
    main()
