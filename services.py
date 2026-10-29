"""Read-only PostgreSQL boundary. All synthetic values are generated in SQL."""

import csv
import io
import json
import os
import time

from psycopg_pool import AsyncConnectionPool
from starlette.exceptions import HTTPException
from starlette.responses import Response

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


async def lifespan(app):
    await pool.open(wait=True)
    try:
        yield
    finally:
        await pool.close()


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


async def export_batch(locale, seed, page, size, format):
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
