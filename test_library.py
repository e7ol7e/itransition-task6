"""Integration and distribution tests against a real PostgreSQL instance.

Set ADMIN_URL/DATABASE_URL, or use the ignored local .env (SSH tunnel).
Run: uv run python -m unittest -v test_library
"""

import json
import math
import os
import re
import unittest
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent
if (ROOT / ".env").exists():
    for line in (ROOT / ".env").read_text().splitlines():
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)


class Library(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = psycopg.connect(os.environ["ADMIN_URL"], autocommit=True)
        cls.reader = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.reader.close()

    def batch(self, locale="en_US", seed="42", page=0, size=10):
        return self.reader.execute(
            "call nominal.batch(%s,%s,%s,%s,null)", (locale, seed, page, size)
        ).fetchone()[0]

    def test_01_fixed_golden_record(self):
        c = self.batch(size=1)["contacts"][0]
        self.assertEqual(c["name"]["full"], "Dr. Melissa Goodwin")
        self.assertEqual(c["phone"], "(512) 555-0137")
        self.assertEqual(c["email"], "melissa.goodwin.765528ad.0@example.com")
        self.assertAlmostEqual(c["coordinates"]["latitude"], 22.892549004498516)

    def test_02_reproducible_interleaved_and_concurrent_connections(self):
        first = self.batch()
        self.batch(locale="de_DE", seed="different", page=99)
        self.batch(seed="different")
        self.assertEqual(first, self.batch())
        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as other:
            self.assertEqual(
                first,
                other.execute("call nominal.batch('en_US','42',0,10,null)").fetchone()[
                    0
                ],
            )

    def test_03_page_size_preserves_positions(self):
        a = self.batch(page=2, size=10)["contacts"][5:]
        b = self.batch(page=1, size=25)["contacts"][:5]
        self.assertEqual(a, b)
        self.assertNotEqual(self.batch(page=1)["contacts"], self.batch()["contacts"])

    def test_04_seed_locale_and_unicode(self):
        self.assertNotEqual(self.batch(seed="42"), self.batch(seed="042"))
        self.assertNotEqual(
            self.batch()["contacts"], self.batch(locale="de_DE")["contacts"]
        )
        seed = "quotes \" ' / [] = <script> ä中文"
        self.assertEqual(self.batch(seed=seed), self.batch(seed=seed))
        self.assertEqual(self.batch(seed="")["seed"], "")

    def test_05_schema_and_procedure_only_generation(self):
        rows = self.db.execute(
            "select proname,prokind from pg_proc join pg_namespace n on n.oid=pronamespace where n.nspname='nominal'"
        ).fetchall()
        self.assertEqual(len(rows), 15)
        self.assertTrue(all(kind == "p" for _, kind in rows))
        counts = dict(
            self.db.execute(
                "select locale,count(*) from nominal.names group by locale"
            ).fetchall()
        )
        self.assertGreater(counts["en_US"], 1500)
        self.assertGreater(counts["de_DE"], 2000)
        self.assertGreater(
            self.db.execute(
                "select count(*) from nominal.markov_transitions"
            ).fetchone()[0],
            1000,
        )

    def test_06_contact_shapes_and_fictional_channels(self):
        seen = set()
        for locale in ("en_US", "de_DE"):
            for page in range(10):
                for c in self.batch(locale=locale, page=page, size=100)["contacts"]:
                    self.assertNotIn(c["email"], seen)
                    seen.add(c["email"])
                    self.assertTrue(c["email"].endswith("@example.com"))
                    self.assertLessEqual(len(c["email"].split("@")[0]), 64)
                    digits = re.sub(r"\D", "", c["phone"])
                    if locale == "en_US":
                        digits = digits.removeprefix("1")
                        self.assertRegex(digits, r"^\d{3}55501\d{2}$")
                    else:
                        national = digits[2:] if digits.startswith("49") else digits[1:]
                        self.assertRegex(
                            national,
                            r"^(3023125|6990009|4066969|2214710|8999998)\d{3}$",
                        )
                    self.assertRegex(c["address"]["postal_code"], r"^\d{5}$")
                    self.assertTrue(-90 < c["coordinates"]["latitude"] < 90)
                    self.assertTrue(-180 < c["coordinates"]["longitude"] < 180)
                    self.assertTrue(110 <= c["physical"]["height_cm"] <= 230)
                    self.assertTrue(35 <= c["physical"]["weight_kg"] <= 180)
        self.assertEqual(len(seen), 2000)

    def test_07_bounds_rejected(self):
        for args in [
            ("xx", "42", 0, 10),
            ("en_US", "x" * 65, 0, 10),
            ("en_US", "42", -1, 10),
            ("en_US", "42", 0, 0),
            ("en_US", "42", 0, 101),
            ("en_US", None, 0, 10),
        ]:
            with self.assertRaises(psycopg.errors.RaiseException):
                self.reader.execute("call nominal.batch(%s,%s,%s,%s,null)", args)

    def test_08_read_only_privileges(self):
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            self.reader.execute("call nominal.rebuild_locale('en_US')")
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            self.reader.execute("call nominal.benchmark('en_US','42',1,null)")
        with self.assertRaises(
            (
                psycopg.errors.ReadOnlySqlTransaction,
                psycopg.errors.InsufficientPrivilege,
            )
        ):
            self.reader.execute("delete from nominal.names")

    def test_09_one_millionth_position(self):
        c = self.batch(page=99999)["contacts"][-1]
        self.assertEqual(c["position"], 999999)
        self.assertIn(".999999@example.com", c["email"])

    def test_09b_integer_full_range_and_normal_zero_sd(self):
        n = self.db.execute(
            "call nominal.integer('en_US','42',0,'bounds',-2147483648,2147483647,null)"
        ).fetchone()[0]
        self.assertTrue(-2147483648 <= n <= 2147483647)
        self.assertEqual(
            self.db.execute(
                "call nominal.normal('en_US','42',0,'zero',172,0,null)"
            ).fetchone()[0],
            172,
        )
        with self.assertRaises(psycopg.errors.RaiseException):
            self.db.execute("call nominal.integer('en_US','42',0,'bounds',10,1,null)")

    def test_10_distributions_20000_draws(self):
        # Equal-area sphere bins use sin(latitude), never equally spaced latitude.
        self.db.execute(
            "create temporary table if not exists nominal_test_stats(result jsonb)"
        )
        self.db.execute("truncate nominal_test_stats")
        self.db.execute("""do $$
declare i int; u float8; n float8; g jsonb; z float8; lon float8;
 su float8:=0; su2 float8:=0; sn float8:=0; sn2 float8:=0;
 sx float8:=0; sy float8:=0; sz float8:=0; polar int:=0;
 bins int[]:=array[0,0,0,0,0,0,0,0,0,0]; b int;
begin
 for i in 0..19999 loop
  call nominal.uniform('en_US','statistics-v1',i,'test/uniform',u);
  if u<=0 or u>=1 then raise exception 'Invalid uniform'; end if;
  su:=su+u;su2:=su2+u*u;
  call nominal.normal('en_US','statistics-v1',i,'test/normal',0,1,n);
  sn:=sn+n;sn2:=sn2+n*n;
  call nominal.coordinates('en_US','statistics-v1',i,g);
  z:=sin(radians((g->>'latitude')::float8));lon:=radians((g->>'longitude')::float8);
  b:=least(10,floor((z+1)*5)::int+1); bins[b]:=bins[b]+1;
  sx:=sx+sqrt(1-z*z)*cos(lon);sy:=sy+sqrt(1-z*z)*sin(lon);sz:=sz+z;
  if abs((g->>'latitude')::float8)>60 then polar:=polar+1;end if;
 end loop;
 insert into nominal_test_stats values(jsonb_build_object('uniform_mean',su/20000,'uniform_variance',su2/20000-(su/20000)^2,'normal_mean',sn/20000,'normal_sd',sqrt(sn2/20000-(sn/20000)^2),'xyz_mean',jsonb_build_array(sx/20000,sy/20000,sz/20000),'equal_area_bins',bins,'polar_fraction',polar/20000.0));
end $$;""")
        stats = self.db.execute("select result from nominal_test_stats").fetchone()[0]
        self.assertAlmostEqual(stats["uniform_mean"], 0.5, delta=0.012)
        self.assertAlmostEqual(stats["uniform_variance"], 1 / 12, delta=0.004)
        self.assertAlmostEqual(stats["normal_mean"], 0, delta=0.04)
        self.assertAlmostEqual(stats["normal_sd"], 1, delta=0.035)
        self.assertTrue(all(abs(m) < 0.02 for m in stats["xyz_mean"]))
        self.assertTrue(all(1800 < n < 2200 for n in stats["equal_area_bins"]))
        self.assertAlmostEqual(
            stats["polar_fraction"], 1 - math.sin(math.radians(60)), delta=0.012
        )
        (ROOT / "artifacts/statistics.json").write_text(
            json.dumps(stats, indent=2) + "\n"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
