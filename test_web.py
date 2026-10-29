"""FastHTML contracts: escaping, authoritative state and failure preservation."""

import json
import os
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
from starlette.testclient import TestClient

os.environ.setdefault("DATABASE_URL", "postgresql://unused:unused@127.0.0.1:1/unused")

import services
import views
from app import app


def example(seed="42"):
    return {
        "locale": "en_US",
        "seed": seed,
        "batch": 2,
        "size": 10,
        "start": 20,
        "elapsed_ms": 2.5,
        "version": "1.0",
        "contacts": [
            {
                "position": 20,
                "locale": "en_US",
                "name": {"first": "Test", "last": "Person", "full": "Test <Person>"},
                "email": "test@example.com",
                "phone": "555-0100",
                "address": {
                    "street": "1 Sample Street",
                    "city": "Sample",
                    "region": "XX",
                    "postal_code": "00000",
                    "full": "1 Sample Street\nSample XX 00000",
                },
                "coordinates": {"latitude": 0.5, "longitude": 1.5},
                "physical": {"height_cm": 170, "weight_kg": 65, "eye_color": "Brown"},
            }
        ],
    }


class WebTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_seed_and_contact_are_escaped_in_html_and_json(self):
        seed = '</script><script>alert("x")</script> & "'
        data = example(seed)
        soup = BeautifulSoup(str(views.to_xml(views.results(data))), "html.parser")
        self.assertEqual(
            json.loads(soup.select_one("#batch-data").string)["seed"], seed
        )
        self.assertEqual(len(soup.select("script")), 1)
        self.assertEqual(soup.select_one(".person-name").text, "Test <Person>")
        self.assertIsNone(soup.find("person"))
        self.assertEqual(
            parse_qs(urlsplit(soup.select_one(".person-name")["hx-get"]).query)["seed"],
            [seed],
        )

    def test_fragment_keeps_authoritative_state_in_url_and_links(self):
        with patch.object(
            services, "batch", AsyncMock(return_value=example("a & b"))
        ) as call:
            response = self.client.get(
                "/fragment?locale=en_US&seed=a%20%26%20b&page=2&size=10",
                headers={"HX-Request": "true"},
            )
        call.assert_awaited_once_with("en_US", "a & b", 2, 10)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["HX-Replace-Url"],
            "/?locale=en_US&seed=a+%26+b&page=2&size=10",
        )
        self.assertNotIn("<html", response.text)
        soup = BeautifulSoup(response.text, "html.parser")
        self.assertIn("page=3", soup.select_one("#next")["hx-get"])
        self.assertEqual(soup.select_one("#page-number")["value"], "3")

    def test_dossier_is_rendered_by_python_and_validates_index(self):
        with patch.object(services, "batch", AsyncMock(return_value=example())):
            r = self.client.get("/contact?index=0", headers={"HX-Request": "true"})
        soup = BeautifulSoup(r.text, "html.parser")
        self.assertEqual(soup.select_one("#detail-title").text, "Test <Person>")
        self.assertEqual(
            json.loads(soup.select_one("#contact-json").string)["email"],
            "test@example.com",
        )
        for index in ("-1", "10", "invalid"):
            self.assertEqual(
                self.client.get(f"/contact?index={index}").status_code, 422
            )

    def test_invalid_parameters_are_rejected_without_sql(self):
        for query in (
            "page=abc",
            "page=-1",
            "page=100000001",
            "batch_number=0",
            "size=0",
            "size=11",
            "locale=xx",
            "seed=" + "x" * 65,
        ):
            r = self.client.get("/api/contacts?" + query)
            self.assertEqual(r.status_code, 422, query)
            self.assertIn("detail", r.json())

    def test_invalid_fragment_retargets_error_not_previous_results(self):
        response = self.client.get("/fragment?size=0", headers={"HX-Request": "true"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.headers["HX-Retarget"], "#error")
        self.assertNotIn('id="results"', response.text)

    def test_jump_is_one_based_and_home_is_progressively_enhanced(self):
        with patch.object(services, "batch", AsyncMock(return_value=example())) as call:
            r = self.client.get("/?batch_number=3")
        call.assert_awaited_once_with("en_US", "42", 2, 10)
        soup = BeautifulSoup(r.text, "html.parser")
        self.assertEqual(soup.html["lang"], "en")
        self.assertEqual(
            soup.select_one("label[for=locale]").text.strip(), "01 / Locale"
        )
        self.assertEqual(
            soup.select_one("label[for=size]").text.strip(), "03 / Batch size"
        )
        self.assertEqual(soup.select_one("#generator")["action"], "/")
        self.assertEqual(soup.select_one("#generator")["hx-get"], "/fragment")
        scripts = soup.select("script[src]")
        self.assertEqual(len([s for s in scripts if "htmx-4.0.0" in s["src"]]), 1)
        self.assertTrue(all("?v=" in s["src"] for s in scripts))
        self.assertFalse(any("cdn" in s["src"] for s in scripts))
        self.assertEqual(r.headers["Cache-Control"], "no-store, no-transform")

    def test_documentation_and_measured_benchmark_remain_available(self):
        for route in ("/library", "/benchmark", "/api/docs"):
            r = self.client.get(route)
            self.assertEqual(r.status_code, 200)
            self.assertIn('id="theme-toggle"', r.text)
        result = self.client.get("/api/benchmark").json()
        self.assertEqual(result["total_contacts"], 600000)

    def test_fonts_load_early_and_cache_without_caching_dynamic_pages(self):
        response = self.client.get('/library')
        soup = BeautifulSoup(response.text, 'html.parser')
        preloads = soup.select('link[rel=preload][as=font]')
        self.assertEqual(len(preloads), 3)
        css = soup.select('link[rel=stylesheet]')
        self.assertIn('/fonts/fonts.css?v=', css[0]['href'])
        self.assertIn('/style.css?v=', css[1]['href'])
        font_css = self.client.get(css[0]['href'])
        self.assertIn('immutable', font_css.headers['cache-control'])
        self.assertNotIn('font-display: swap', font_css.text)
        self.assertNotIn('@import', self.client.get(css[1]['href']).text)
        for preload in preloads:
            self.assertEqual(preload['crossorigin'], 'anonymous')
            self.assertIn(preload['href'], font_css.text)
            font = self.client.get(preload['href'])
            self.assertEqual(font.status_code, 200)
            self.assertIn('immutable', font.headers['cache-control'])
        self.assertIn('no-store', response.headers['cache-control'])
        self.assertIn('no-store', self.client.get('/api/benchmark').headers['cache-control'])
        self.assertIn('no-store', self.client.get('/static/fonts/000000000000.woff2').headers['cache-control'])


if __name__ == "__main__":
    unittest.main()
