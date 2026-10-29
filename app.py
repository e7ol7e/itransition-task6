"""FastHTML routes: Python owns data, validation and rendered fragments."""

import json
import secrets
from pathlib import Path

import markdown
from fasthtml.common import FastHTML, HttpHeader, Link, Meta, Script
from starlette.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.staticfiles import StaticFiles

import services
import views

ROOT = Path(__file__).resolve().parent


class ResponsePolicy(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store, no-transform"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


async def http_error(request, exc):
    if request.url.path.startswith("/api/") or request.url.path == "/healthz":
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    if request.headers.get("hx-request") == "true":
        return HTMLResponse(
            views.render_error(exc.detail),
            status_code=exc.status_code,
            headers={"HX-Retarget": "#error", "HX-Reswap": "innerHTML"},
        )
    return HTMLResponse(views.render_error(exc.detail), status_code=exc.status_code)


app = FastHTML(
    title="Nominal — The identity atelier",
    lifespan=services.lifespan,
    htmlkw={"lang": "en"},
    htmx=False,
    surreal=False,
    default_hdrs=False,
    sess_cls=None,
    secret_key=secrets.token_urlsafe(32),
    exception_handlers={HTTPException: http_error},
    hdrs=[
        Meta(charset="utf-8"),
        Meta(name="viewport", content="width=device-width, initial-scale=1"),
        Meta(
            name="description",
            content="Fictional people. Real SQL. Explore reproducible synthetic identities generated entirely by PostgreSQL.",
        ),
        Meta(name="color-scheme", content="dark light"),
        Meta(
            name="htmx-config",
            content=json.dumps(
                {"metaCharacter": "-", "allowEval": False, "allowScriptTags": False}
            ),
        ),
        Link(rel="icon", href="/static/favicon.svg", type="image/svg+xml"),
        Script(src=views.asset("js/theme.js")),
        Link(rel="stylesheet", href=views.asset("style.css")),
        Script(src=views.asset("vendor/htmx-4.0.0.min.js"), defer=True),
        Script(src=views.asset("js/browser.js"), defer=True),
        Script(src=views.asset("js/globe.js"), defer=True),
    ],
)
app.add_middleware(ResponsePolicy)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


def parameters(request):
    q = request.query_params
    try:
        page = int(q.get("page", "0"))
        if "batch_number" in q:
            page = int(q["batch_number"]) - 1
        return (
            q.get("locale", "en_US"),
            q.get("seed", "42"),
            page,
            int(q.get("size", "10")),
        )
    except ValueError as exc:
        raise HTTPException(
            422, "Batch number and batch size must be whole numbers."
        ) from exc


@app.get("/")
async def home(request: Request):
    return views.layout(
        views.generator(await services.batch(*parameters(request))), "lab"
    )


@app.get("/fragment")
async def fragment(request: Request):
    data = await services.batch(*parameters(request))
    return views.results(data), HttpHeader("HX-Replace-Url", views.url("/", data))


@app.get("/contact")
async def contact(request: Request):
    args = parameters(request)
    try:
        index = int(request.query_params.get("index", "0"))
    except ValueError as exc:
        raise HTTPException(422, "Contact index must be a whole number.") from exc
    if index < 0 or index >= args[3]:
        raise HTTPException(422, "Choose a contact within this batch.")
    data = await services.batch(*args)
    content = views.contact_detail(data["contacts"][index], data)
    if request.headers.get("hx-request") == "true":
        return content
    return views.layout(views.detail_page(content), "lab", "Contact dossier")


@app.get("/api/contacts")
async def contacts(request: Request):
    return JSONResponse(await services.batch(*parameters(request)))


@app.get("/download")
async def download(request: Request):
    format = request.query_params.get("format", "csv")
    if format not in ("csv", "json"):
        raise HTTPException(422, "Choose CSV or JSON export.")
    return await services.export_batch(*parameters(request), format)


@app.get("/library")
async def library():
    content = markdown.markdown(
        (ROOT / "LIBRARY.md").read_text(encoding="utf8"),
        extensions=["fenced_code", "tables", "toc"],
    )
    return views.layout(views.library(content), "library", "The SQL library")


def measured_benchmark():
    path = ROOT / "artifacts/benchmark.json"
    return json.loads(path.read_text()) if path.exists() else None


@app.get("/benchmark")
async def benchmark():
    return views.layout(
        views.benchmark(measured_benchmark()), "benchmark", "Measured performance"
    )


@app.get("/api/benchmark")
async def benchmark_json():
    result = measured_benchmark()
    if result is None:
        raise HTTPException(404, "Benchmark not yet available")
    return JSONResponse(result)


@app.get("/api/docs")
async def api_docs():
    return views.layout(views.api_reference(), "library", "HTTP reference")


@app.get("/healthz")
async def health():
    async with services.pool.connection() as conn:
        await conn.execute("select 1")
    return JSONResponse({"status": "ok"})
