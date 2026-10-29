"""Optional real-Chrome WCAG audit; downloads a pinned dev-only axe release."""

import base64
import hashlib
import io
import json
import os
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

URL = os.environ.get("TASK6_URL", "https://task6.evgeniy.win")
ROOT = Path(__file__).resolve().parent


def main():
    package = json.load(urlopen("https://registry.npmjs.org/axe-core/4.14.0"))
    raw = urlopen(package["dist"]["tarball"]).read()
    digest = base64.b64encode(hashlib.sha512(raw).digest()).decode()
    assert package["dist"]["integrity"] == "sha512-" + digest
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        axe = archive.extractfile("package/axe.min.js").read().decode()
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page()
        for width in (390, 1440):
            page.set_viewport_size({"width": width, "height": 1000})
            for theme in ("dark", "light"):
                for route in ("/", "/library", "/benchmark", "/api/docs"):
                    page.goto(URL + route, wait_until="networkidle")
                    if page.locator("html").get_attribute("data-theme") != theme:
                        page.locator("#theme-toggle").click()
                    page.add_script_tag(content=axe)
                    violations = page.evaluate("""async () => {
                        const result = await axe.run(document, {runOnly: {
                            type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21aa']
                        }});
                        return result.violations.map(v => ({id: v.id, impact: v.impact,
                            targets: v.nodes.map(n => n.target)}));
                    }""")
                    results.append(
                        {
                            "width": width,
                            "theme": theme,
                            "route": route,
                            "violations": violations,
                        }
                    )
        browser.close()
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "target": URL,
        "axe_version": "4.14.0",
        "scope": "Automated WCAG 2 A/AA and 2.1 AA rules; does not replace manual accessibility review.",
        "passed": sum(not item["violations"] for item in results),
        "total": len(results),
        "checks": results,
    }
    (ROOT / "artifacts/accessibility.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf8"
    )
    assert report["passed"] == report["total"], report
    print(
        "PASS",
        report["passed"],
        "desktop/mobile and dark/light accessibility scenarios",
    )


if __name__ == "__main__":
    main()
