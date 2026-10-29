# Nominal · SQL contact lab

A Python web application backed by a small Faker-style **PostgreSQL stored-procedure library**. Contact generation, including formatting, happens exclusively in SQL.

- **Application:** https://task6.evgeniy.win/
- **Procedure documentation:** https://task6.evgeniy.win/library
- **Measured benchmark:** https://task6.evgeniy.win/benchmark
- **Silent demonstration:** https://task6.evgeniy.win/submission/demo.mp4
- **Author:** Evgeniy Bebeshko

## Features

- English/USA and German/Germany; names, addresses, fictional phones, reserved-domain emails.
- Seeded deterministic contacts with random-access pagination and stable absolute positions.
- 4,109 static name dictionary entries; shared, locale-keyed lookup tables.
- SQL-trained order-2 character Markov chain for invented street names.
- Area-uniform sphere coordinates; interactive globe, independent of postal addresses.
- Box–Muller normal physical attributes with rejection bounds; discrete localized eye colors.
- Server-rendered Python/Jinja interface, contact details, CSV/JSON exports, responsive layouts.
- Separate read-only app role, SQL-bound parameters, bounded requests, no runtime Faker dependency.

## Architecture

```text
Browser → FastAPI → CALL nominal.batch(locale, seed, batch, size, NULL)
                       └─ contact
                           ├─ full_name → choose → integer → uniform
                           ├─ address → word (Markov) + choose + integer
                           ├─ coordinates → uniform
                           ├─ physical → normal (Box–Muller) + choose
                           ├─ phone → integer
                           └─ email
```

There are 15 real PostgreSQL procedures (`prokind = 'p'`), no SQL generation functions or Python contact generators. Built-in SQL functions are used inside the procedures. `build_lookups.py` only extracts static dictionary constants from the MIT-licensed Faker development package; it never calls Faker's contact generation methods.

## Run with Docker

Requirements: Docker Compose and Python 3.12+ for the dependency-free administrative setup script. The app image uses Python 3.13 and PostgreSQL 18.

1. Create a private `.env` in this directory (do not commit it):

   ```sh
   python -c "import secrets; from pathlib import Path; Path('.env').write_text('DB_PASSWORD='+secrets.token_hex(24)+'\nAPP_PASSWORD='+secrets.token_hex(24)+'\n')"
   chmod 600 .env
   ```

2. Start PostgreSQL and wait for its health check:

   ```sh
   docker compose up -d --wait database
   python admin.py install
   docker compose up -d --build web
   ```

3. Open `http://127.0.0.1:5007`. PostgreSQL's port 5436 is bound to loopback for administration, not exposed publicly. For a fresh install, `admin.py install` runs schema creation, CSV COPY, Markov training, role setup, and grants in one transaction. Existing initialized schemas are left alone. It does **not** reset or migrate existing data.

4. Run the real benchmark:

   ```sh
   python admin.py benchmark
   ```

   Three 100,000-contact trials per locale, sequentially. Results are atomically written to `artifacts/benchmark.json`, mounted read-only in the web container. The `/benchmark` page reads that file. Each contact's complete JSON contributes to the checksum; no row-count shortcut is used. The benchmark takes several minutes per trial on a shared VPS.

The deployed VPS uses Caddy on loopback port 5006, proxying to the app on 5007, with Cloudflare Tunnel providing HTTPS. The stack is isolated from other assignments. No existing application containers are modified.

## Local development and verification

```sh
uv sync --frozen
```

Set `DATABASE_URL` for the application role and `ADMIN_URL` for an administrative test connection. The tests can also read an ignored `.env`. Do not expose the admin connection to the web application.

```sh
uv run python -m unittest -v test_library
uv run python verify_browser.py
```

- Database integration checks: fixed golden record, deterministic interleaved requests and separate connections, cross-size position stability, Unicode/quoted seeds, procedure types and dictionaries, 2,000 complete contacts, fictional channel ranges, invalid inputs, role permissions, millionth position, full-range integer sampling, and 20,000-draw distribution checks.
- Sphere tests use equal-area bins in `sin(latitude)`, Cartesian means, and polar-cap probability. They deliberately do not test for uniform latitude.
- Browser checks use installed Chrome via Playwright: locale changes, pagination, millionth contact, detail dialog, exports, seed escaping, network failure recovery, mobile layouts, documentation, and JavaScript errors.
- Measured statistics and browser checks are checked in under `artifacts/`.

For a local Windows server, put a local `DATABASE_URL` in `.env`, then `uv run python run_local.py`. It selects an event loop compatible with Psycopg's async connection pool on Windows. On Linux: `uv run uvicorn app:app --port 8066`.

`record_demo.py` captures the actual full-screen Chrome window using portable OBS on Windows, with no subtitles or audio. It requires the portable OBS and FFmpeg paths configured at the top of the script. Video binaries are excluded from Git and hosted separately.

## Reproducibility and scope

The same **library version + dictionaries + locale + seed + absolute position** gives identical contact values. Page boundaries can change; people at those positions do not. Timing metadata is intentionally variable. Locale snapshots and stream names form part of the versioned contract; changing them can change results.

Generated addresses are not validated delivery destinations. Coordinates are global samples rather than geocoded addresses. Emails are unique by position within a locale/seed; full names and fictional phone numbers can repeat. All contacts are synthetic. See [LIBRARY.md](LIBRARY.md) for every procedure's signature, algorithms, limits, and call examples.

## Files

| File | Role |
|---|---|
| `sql/001_library.sql` | Schema and all 15 stored procedures |
| `data/*.csv` | Locale-keyed static dictionaries and city anchors |
| `build_lookups.py` | Reproducible static-dictionary extraction; development only |
| `admin.py` | Transactional installation and measured SQL benchmark |
| `app.py` | Procedure calls, HTML rendering, exports and docs |
| `templates/`, `static/` | Interface, globe projection and styles |
| `LIBRARY.md` | Stored-procedure reference, published at `/library` |
| `test_library.py`, `verify_browser.py` | Real database and live browser checks |
| `compose.yaml`, `Dockerfile` | Isolated production deployment |

Name dictionaries retain their original [Faker MIT license](data/LICENSE-Faker.txt). Fonts: DM Sans, Manrope, IBM Plex Mono, loaded from Google Fonts with system fallbacks.
