"""Rebuild a fresh, temporary database and compare it to the deployed snapshot."""

import json
import os
import secrets
import time
from pathlib import Path

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parent


def main():
    if (ROOT / ".env").exists():
        for line in (ROOT / ".env").read_text(encoding="utf8").splitlines():
            key, value = line.split("=", 1)
            os.environ.setdefault(key, value)
    name = "nominal_verify_" + secrets.token_hex(4)
    started = time.perf_counter()
    with psycopg.connect(os.environ["ADMIN_URL"], autocommit=True) as admin:
        admin.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
        try:
            with psycopg.connect(os.environ["ADMIN_URL"], dbname=name) as clean:
                clean.execute((ROOT / "sql/001_library.sql").read_text(encoding="utf8"))
                for table in ("names", "terms", "cities"):
                    with clean.cursor().copy(
                        sql.SQL("copy nominal.{} from stdin with (format csv)").format(
                            sql.Identifier(table)
                        )
                    ) as stream:
                        stream.write(
                            (ROOT / "data" / f"{table}.csv").read_text(encoding="utf8")
                        )
                for locale in ("en_US", "de_DE"):
                    clean.execute("call nominal.rebuild_locale(%s)", (locale,))
                    new = clean.execute(
                        "call nominal.batch(%s,%s,0,25,null)", (locale, "42")
                    ).fetchone()[0]
                    live = admin.execute(
                        "call nominal.batch(%s,%s,0,25,null)", (locale, "42")
                    ).fetchone()[0]
                    assert new == live, locale
                clean.commit()
        finally:
            # Only the uniquely named database created by this run is removed.
            admin.execute(sql.SQL("drop database {}").format(sql.Identifier(name)))
    result = {
        "passed": True,
        "check": "Fresh SQL schema, CSV COPY and SQL Markov training reproduce live 25-contact batches for both locales",
        "temporary_database_removed": True,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    (ROOT / "artifacts/install-check.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf8"
    )
    print("Fresh installation reproduces both locales; temporary database removed.")


if __name__ == "__main__":
    main()
