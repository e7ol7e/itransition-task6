"""Python renders HTML and reads SQL procedure results. No contact generation."""

import csv
import io
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import markdown
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from psycopg_pool import AsyncConnectionPool

ROOT = Path(__file__).resolve().parent
pool = AsyncConnectionPool(
    os.environ["DATABASE_URL"],
    min_size=1,
    max_size=4,
    open=False,
    kwargs={
        "autocommit": True,
        "options": "-c statement_timeout=8000 -c default_transaction_read_only=on",
    },
)


@asynccontextmanager
async def lifespan(app):
    await pool.open(wait=True)
    yield
    await pool.close()


app = FastAPI(
    title="Nominal SQL contact library",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")


@app.middleware("http")
async def response_policy(request, call_next):
    response = await call_next(request)
    # Cloudflare's HTML email obfuscator breaks dynamically inserted fragments.
    # These emails are deliberately fictional, and must survive byte-for-byte.
    response.headers["Cache-Control"] = "no-store, no-transform"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


async def batch(locale, seed, page, size):
    if (
        locale not in ("en_US", "de_DE")
        or len(seed) > 64
        or page < 0
        or page > 100000000
        or size not in (10, 25, 50)
    ):
        raise HTTPException(
            422,
            "Choose a supported locale, a seed of up to 64 characters, and a valid batch.",
        )
    start = time.perf_counter()
    try:
        async with pool.connection() as conn:
            cursor = await conn.execute(
                "call nominal.batch(%s,%s,%s,%s,null)", (locale, seed, page, size)
            )
            result = (await cursor.fetchone())[0]
    except Exception as exc:
        # Do not return credentials, SQL internals, or connection details.
        import logging

        logging.getLogger("nominal").exception("Batch request failed")
        raise HTTPException(
            503, "Generation is temporarily unavailable. Please try again."
        ) from exc
    result["elapsed_ms"] = round((time.perf_counter() - start) * 1000, 1)
    return result


@app.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    locale: str = "en_US",
    seed: str = "42",
    page: int = 0,
    size: int = 10,
):
    data = await batch(locale, seed, page, size)
    return templates.TemplateResponse(
        request=request, name="index.html", context={"data": data, "section": "lab"}
    )


@app.get("/api/contacts")
async def contacts(
    locale: str = "en_US",
    seed: str = Query("42", max_length=64),
    page: int = Query(0, ge=0, le=100000000),
    size: int = 10,
):
    return await batch(locale, seed, page, size)


@app.get("/fragment", response_class=HTMLResponse, include_in_schema=False)
async def fragment(
    request: Request,
    locale: str = "en_US",
    seed: str = "42",
    page: int = 0,
    size: int = 10,
):
    data = await batch(locale, seed, page, size)
    return templates.TemplateResponse(
        request=request, name="results.html", context={"data": data}
    )


@app.get("/download")
async def download(
    locale: str = "en_US",
    seed: str = "42",
    page: int = 0,
    size: int = 10,
    format: str = "csv",
):
    data = await batch(locale, seed, page, size)
    headers = {
        "Content-Disposition": f'attachment; filename="nominal-{locale}-batch-{page + 1}.{format if format in ("json", "csv") else "csv"}"',
        "X-Content-Type-Options": "nosniff",
    }
    if format == "json":
        return Response(
            json.dumps(data, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers=headers,
        )
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "position",
            "locale",
            "full_name",
            "address",
            "phone",
            "email",
            "latitude",
            "longitude",
            "height_cm",
            "weight_kg",
            "eye_color",
        ]
    )
    for c in data["contacts"]:
        writer.writerow(
            [
                c["position"],
                c["locale"],
                c["name"]["full"],
                c["address"]["full"],
                c["phone"],
                c["email"],
                c["coordinates"]["latitude"],
                c["coordinates"]["longitude"],
                c["physical"]["height_cm"],
                c["physical"]["weight_kg"],
                c["physical"]["eye_color"],
            ]
        )
    return Response(
        "\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


@app.get("/library", response_class=HTMLResponse)
async def library(request: Request):
    content = markdown.markdown(
        (ROOT / "LIBRARY.md").read_text(encoding="utf8"),
        extensions=["fenced_code", "tables", "toc"],
    )
    return templates.TemplateResponse(
        request=request,
        name="document.html",
        context={
            "content": content,
            "section": "library",
            "title": "A small Faker, entirely in SQL.",
        },
    )


@app.get("/benchmark", response_class=HTMLResponse)
async def benchmark(request: Request):
    path = ROOT / "artifacts/benchmark.json"
    results = json.loads(path.read_text()) if path.exists() else None
    return templates.TemplateResponse(
        request=request,
        name="benchmark.html",
        context={"results": results, "section": "benchmark"},
    )


@app.get("/api/benchmark", include_in_schema=False)
async def benchmark_json():
    path = ROOT / "artifacts/benchmark.json"
    if not path.exists():
        raise HTTPException(404, "Benchmark not yet available")
    return JSONResponse(json.loads(path.read_text()))


@app.get("/healthz", include_in_schema=False)
async def health():
    async with pool.connection() as conn:
        await conn.execute("select 1")
    return {"status": "ok"}
