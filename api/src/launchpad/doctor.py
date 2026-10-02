"""Environment health check: `make doctor` / `python -m launchpad.doctor`.

Prints one line per check and exits non-zero if anything required is broken.
Never prints secret values — only the names of missing variables.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from launchpad.config import Settings, get_settings

OK, WARN, FAIL = "ok", "warn", "fail"
_SYMBOL = {OK: "✓", WARN: "!", FAIL: "✗"}


@dataclass
class Result:
    name: str
    status: str
    detail: str


def _redact_url(url: str) -> str:
    return re.sub(r"//([^:/@]+):[^@]+@", r"//\1:***@", url)


def check_python() -> Result:
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 11)
    return Result("Python", OK if ok else FAIL, f"{v.major}.{v.minor}.{v.micro} (need >= 3.11)")


def check_node() -> Result:
    node = shutil.which("node")
    if node is None:
        return Result("Node.js", FAIL, "not found on PATH (need >= 22)")
    out = subprocess.run([node, "--version"], capture_output=True, text=True, check=False)  # noqa: S603
    version = out.stdout.strip().lstrip("v")
    major = int(version.split(".")[0]) if version[:1].isdigit() else 0
    return Result("Node.js", OK if major >= 22 else FAIL, f"{version or 'unknown'} (need >= 22)")


async def check_postgres(s: Settings) -> list[Result]:
    import asyncpg

    dsn = s.database_url.replace("postgresql+asyncpg://", "postgresql://")
    where = _redact_url(dsn)
    try:
        conn = await asyncio.wait_for(asyncpg.connect(dsn), timeout=5)
    except Exception as exc:
        return [
            Result("Postgres", FAIL, f"cannot connect to {where}: {type(exc).__name__}: {exc}"),
            Result("pgvector", FAIL, "skipped (no database connection)"),
        ]
    try:
        server = await conn.fetchval("show server_version")
        installed = await conn.fetchval(
            "select extversion from pg_extension where extname = 'vector'"
        )
        available = await conn.fetchval(
            "select default_version from pg_available_extensions where name = 'vector'"
        )
    finally:
        await conn.close()
    pg = Result("Postgres", OK, f"{server} at {where}")
    if installed:
        vec = Result("pgvector", OK, f"extension installed (v{installed})")
    elif available:
        vec = Result(
            "pgvector", WARN, f"v{available} available but not installed; run make migrate"
        )
    else:
        vec = Result("pgvector", FAIL, "extension not available on this server; install pgvector")
    return [pg, vec]


async def check_redis(s: Settings) -> Result:
    from redis.asyncio import Redis

    client = Redis.from_url(s.redis_url, socket_timeout=3, socket_connect_timeout=3)
    try:
        info = await client.info("server")
        return Result("Redis", OK, f"{info.get('redis_version')} at {_redact_url(s.redis_url)}")
    except Exception as exc:
        return Result("Redis", FAIL, f"cannot reach {_redact_url(s.redis_url)}: {exc}")
    finally:
        await client.aclose()


async def check_storage(s: Settings) -> Result:
    if s.storage_backend == "local":
        from launchpad.storage import LocalStorage

        try:
            await LocalStorage(s.storage_local_dir).put(".doctor-probe", b"ok", "text/plain")
            await LocalStorage(s.storage_local_dir).delete(".doctor-probe")
        except OSError as exc:
            return Result("Storage", FAIL, f"local dir {s.storage_local_dir} not writable: {exc}")
        return Result("Storage", OK, f"local dir '{s.storage_local_dir}' is writable")

    from launchpad.storage import get_storage

    try:
        await get_storage().check()
    except Exception as exc:
        return Result("Storage", FAIL, f"S3 bucket '{s.s3_bucket}' at {s.s3_endpoint_url}: {exc}")
    return Result("Storage", OK, f"S3 bucket '{s.s3_bucket}' reachable at {s.s3_endpoint_url}")


def required_env(s: Settings) -> dict[str, bool]:
    """Variable name -> is it set. Requirements depend on the chosen providers."""
    # DATABASE_URL / REDIS_URL have dev defaults; the connectivity checks above cover them.
    req: dict[str, bool] = {
        "JWT_SECRET": len(s.jwt_secret.get_secret_value()) >= 32,
        "TOKEN_ENCRYPTION_KEYS": bool(s.token_encryption_keys.get_secret_value()),
        "LLM_PROVIDER": s.llm_provider is not None,
        "LLM_MODEL": bool(s.llm_model),
        "EMBEDDING_PROVIDER": s.embedding_provider is not None,
        "EMBEDDING_MODEL": bool(s.embedding_model),
    }
    providers = {p for p in (s.llm_provider, s.embedding_provider) if p}
    key_for = {
        "gemini": ("GEMINI_API_KEY", s.gemini_api_key),
        "groq": ("GROQ_API_KEY", s.groq_api_key),
        "openai": ("OPENAI_API_KEY", s.openai_api_key),
        "anthropic": ("ANTHROPIC_API_KEY", s.anthropic_api_key),
    }
    for p in sorted(providers):
        name, secret = key_for[p]
        req[name] = secret is not None and bool(secret.get_secret_value())
    if s.storage_backend == "s3":
        req["S3_ENDPOINT_URL"] = bool(s.s3_endpoint_url)
        req["S3_ACCESS_KEY_ID"] = s.s3_access_key_id is not None
        req["S3_SECRET_ACCESS_KEY"] = s.s3_secret_access_key is not None
    if s.auth_provider == "supabase":
        req["SUPABASE_URL"] = bool(s.supabase_url)
    return req


def check_embedding_dim(s: Settings) -> Result:
    from launchpad.models._types import EMBEDDING_DIM

    if s.embedding_dim != EMBEDDING_DIM:
        return Result(
            "Embeddings",
            FAIL,
            f"EMBEDDING_DIM={s.embedding_dim} but the database column is vector({EMBEDDING_DIM}); "
            "write a migration and re-index, or set EMBEDDING_DIM back",
        )
    model = s.embedding_model or "(EMBEDDING_MODEL unset)"
    return Result("Embeddings", OK, f"{model} at {EMBEDDING_DIM} dims matches the DB column")


def check_env(s: Settings) -> Result:
    missing = [name for name, present in required_env(s).items() if not present]
    if missing:
        return Result("Env vars", FAIL, "missing or invalid: " + ", ".join(missing))
    return Result("Env vars", OK, "all required variables are set")


async def run() -> int:
    s = get_settings()
    checks: list[Callable[[], Awaitable[Result | list[Result]]]] = [
        lambda: check_postgres(s),
        lambda: check_redis(s),
        lambda: check_storage(s),
    ]
    results = [check_python(), check_node()]
    for gathered in await asyncio.gather(*(c() for c in checks)):
        results.extend(gathered if isinstance(gathered, list) else [gathered])
    results.append(check_embedding_dim(s))
    results.append(check_env(s))

    width = max(len(r.name) for r in results)
    for r in results:
        print(f"  {_SYMBOL[r.status]} {r.name.ljust(width)}  {r.detail}")
    failed = [r for r in results if r.status == FAIL]
    print(f"\n{len(failed)} problem(s) found." if failed else "\nAll checks passed.")
    return 1 if failed else 0


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(asyncio.run(run()))


if __name__ == "__main__":
    main()
