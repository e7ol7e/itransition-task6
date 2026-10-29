"""Run on the deployment host, from the project directory. Never logs passwords."""

import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def sql(query, timeout=3600):
    process = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "database",
            "psql",
            "-X",
            "-q",
            "-A",
            "-t",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "nominal_admin",
            "-d",
            "nominal",
        ],
        input=query,
        text=True,
        capture_output=True,
        cwd=ROOT,
        timeout=timeout,
        check=False,  # Preserve psql's diagnostic when a transactional install fails.
    )
    if process.returncode:
        raise RuntimeError(process.stderr)
    return process.stdout.strip()


def install():
    if (
        sql(
            "select exists(select 1 from information_schema.schemata where schema_name='nominal');"
        )
        == "t"
    ):
        print("Schema already installed; skipped.")
        return
    env = dict(
        line.split("=", 1)
        for line in (ROOT / ".env").read_text().splitlines()
        if "=" in line
    )
    query = "begin;\n" + (ROOT / "sql/001_library.sql").read_text()
    for table in ("names", "terms", "cities"):
        query += (
            f"\ncopy nominal.{table} from stdin with (format csv);\n"
            + (ROOT / "data" / f"{table}.csv").read_text()
            + "\\.\n"
        )
    query += "\ncall nominal.rebuild_locale('en_US'); call nominal.rebuild_locale('de_DE');\n"
    # Passwords are generated as hex by deployment; SQL literal quoted defensively.
    password = env["APP_PASSWORD"].replace("'", "''")
    query += f"create role nominal_app login password '{password}';\n"
    query += """revoke all on schema nominal from public;
revoke execute on all procedures in schema nominal from public;
grant usage on schema nominal to nominal_app;
grant select on all tables in schema nominal to nominal_app;
grant execute on all procedures in schema nominal to nominal_app;
revoke execute on procedure nominal.rebuild_locale(text) from nominal_app;
revoke execute on procedure nominal.benchmark(text,text,integer) from nominal_app;
alter role nominal_app set statement_timeout='8s';
alter role nominal_app set default_transaction_read_only=on;
commit;
"""
    sql(query)
    print(
        sql(
            "select locale, jsonb_array_length(dictionary->'last') as surnames from nominal.assets order by locale;"
        )
    )
    print(sql("call nominal.batch('en_US','42',0,1,null);"))


def benchmark():
    sql("call nominal.benchmark('en_US','warmup',100,null);")
    runs = []
    for locale in ("en_US", "de_DE"):
        for trial in range(1, 4):
            start = time.perf_counter()
            result = json.loads(
                sql(
                    f"call nominal.benchmark('{locale}','benchmark-v1-{trial}',100000,null);"
                )
            )
            result.update(trial=trial, client_seconds=time.perf_counter() - start)
            runs.append(result)
            print(
                f"{locale} trial {trial}: {result['users_per_second']:.1f} users/s, {result['seconds']:.1f}s",
                flush=True,
            )
            save_benchmark(runs)


def save_benchmark(runs):
    env = (
        subprocess.check_output(
            [
                "sh",
                "-c",
                "printf 'CPU: '; lscpu | sed -n 's/^Model name:[[:space:]]*//p'; printf 'vCPUs: '; nproc",
            ],
            text=True,
        )
        .strip()
        .replace("\n", " · ")
    )
    output = {
        "measured_at": datetime.now(UTC).isoformat(),
        "environment": env
        + " · shared VPS · database memory limit 384 MiB · PostgreSQL 18 Alpine container",
        "total_contacts": sum(r["count"] for r in runs),
        "overall_users_per_second": sum(r["count"] for r in runs)
        / sum(r["seconds"] for r in runs),
        "runs": runs,
    }
    (ROOT / "artifacts").mkdir(exist_ok=True)
    temporary = ROOT / "artifacts/benchmark.json.tmp"
    temporary.write_text(json.dumps(output, indent=2) + "\n")
    temporary.replace(ROOT / "artifacts/benchmark.json")


if __name__ == "__main__":
    {"install": install, "benchmark": benchmark}[sys.argv[1]]()
