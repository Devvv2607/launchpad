#!/usr/bin/env python3
"""Cross-platform task runner: the same tasks as the Makefile, with no `make` required.

    python scripts/tasks.py <task> [args]      # macOS / Linux
    py scripts\\tasks.py <task> [args]          # Windows

Run with no arguments to list tasks. Standard library only, so it works before `setup`.
The Makefile delegates here, so there is a single source of truth.
"""

from __future__ import annotations

import os
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
API, WORKER, WEB = ROOT / "api", ROOT / "worker", ROOT / "web"
DEVDB = ROOT / ".devdb"
DEVDB_PORT = 55432
IS_WINDOWS = os.name == "nt"
NPM = "npm.cmd" if IS_WINDOWS else "npm"
NPX = "npx.cmd" if IS_WINDOWS else "npx"

TASKS: dict[str, tuple[Callable[[list[str]], None], str]] = {}


def task(
    help_text: str, name: str | None = None
) -> Callable[[Callable[[list[str]], None]], Callable[[list[str]], None]]:
    def deco(fn: Callable[[list[str]], None]) -> Callable[[list[str]], None]:
        TASKS[name or fn.__name__.replace("_", "-")] = (fn, help_text)
        return fn

    return deco


# --------------------------------------------------------------------------- helpers


def venv_python() -> str:
    for candidate in (API / ".venv" / "Scripts" / "python.exe", API / ".venv" / "bin" / "python"):
        if candidate.exists():
            return str(candidate)
    sys.exit("api/.venv not found. Run the 'setup' task first.")


def run(cmd: list[str], cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    print(f"\n$ {' '.join(cmd)}   (in {cwd.relative_to(ROOT) if cwd != ROOT else '.'})", flush=True)
    result = subprocess.run(cmd, cwd=cwd, env=env, check=False)  # noqa: S603
    if result.returncode != 0:
        sys.exit(result.returncode)


def py(*args: str, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    run([venv_python(), *args], cwd=cwd, env=env)


def read_dotenv() -> dict[str, str]:
    """Minimal .env reader (KEY=VALUE lines) — enough to derive URLs; values never printed."""
    values: dict[str, str] = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def test_env() -> dict[str, str]:
    """Tests drop and recreate tables, so they always use a separate *_test database."""
    env = dict(os.environ)
    if not env.get("TEST_DATABASE_URL"):
        url = env.get("DATABASE_URL") or read_dotenv().get("DATABASE_URL")
        if not url:
            sys.exit("Set TEST_DATABASE_URL (or DATABASE_URL in .env) before running tests.")
        parts = urlsplit(url)
        db = parts.path.lstrip("/") or "launchpad"
        test_db = db if db.endswith("_test") else f"{db}_test"
        env["TEST_DATABASE_URL"] = urlunsplit(parts._replace(path=f"/{test_db}"))
    return env


def find_pg_bin() -> Path:
    """A Postgres bin dir whose install ships pgvector (PG_BIN overrides)."""
    if os.environ.get("PG_BIN"):
        return Path(os.environ["PG_BIN"])
    candidates: list[Path] = []
    if IS_WINDOWS:
        base = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "PostgreSQL"
        if base.exists():
            candidates = sorted((p / "bin" for p in base.iterdir()), reverse=True)
    else:
        pg_config = shutil.which("pg_config")
        if pg_config:
            out = subprocess.run([pg_config, "--bindir"], capture_output=True, text=True)  # noqa: S603
            candidates.append(Path(out.stdout.strip()))
    exe = ".exe" if IS_WINDOWS else ""
    for bindir in candidates:
        if not (bindir / f"initdb{exe}").exists():  # e.g. psqlODBC has no server binaries
            continue
        if (bindir.parent / "share" / "extension" / "vector.control").exists():
            return bindir
        sharedir = subprocess.run(  # noqa: S603
            [str(bindir / f"pg_config{exe}"), "--sharedir"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        if sharedir and (Path(sharedir) / "extension" / "vector.control").exists():
            return bindir
    sys.exit(
        "No local Postgres with pgvector found. Install pgvector "
        "(https://github.com/pgvector/pgvector#installation), set PG_BIN, or use Docker ('up')."
    )


def pg(tool: str) -> str:
    return str(find_pg_bin() / (f"{tool}.exe" if IS_WINDOWS else tool))


# --------------------------------------------------------------------------- tasks


@task("Create api/.venv, install API + worker + web deps, install git hooks")
def setup(_: list[str]) -> None:
    if sys.version_info < (3, 11):  # noqa: UP036 - may be launched by an older python
        sys.exit(f"Python 3.11+ required to create the venv (this is {sys.version.split()[0]}).")
    if not (API / ".venv").exists():
        run([sys.executable, "-m", "venv", str(API / ".venv")])
    py("-m", "pip", "install", "--upgrade", "pip")
    py("-m", "pip", "install", "-e", "./api[dev]", "-e", "./worker")
    run([NPM, "ci", "--no-audit", "--no-fund"], cwd=WEB)
    py("-m", "pre_commit", "install")
    if not (ROOT / ".env").exists():
        print("\nNext: copy .env.example to .env, then run the 'keys' task.")


@task("Print fresh JWT_SECRET and TOKEN_ENCRYPTION_KEYS for .env")
def keys(_: list[str]) -> None:
    print(f"JWT_SECRET={secrets.token_urlsafe(48)}")
    code = "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
    out = subprocess.run([venv_python(), "-c", code], capture_output=True, text=True, check=True)  # noqa: S603
    print(f"TOKEN_ENCRYPTION_KEYS={out.stdout.strip()}")


@task("Check toolchain, services and required env vars (names only, never values)")
def doctor(_: list[str]) -> None:
    py("-m", "launchpad.doctor", cwd=API)


@task("Create a project-local Postgres cluster with pgvector in .devdb/ (no Docker needed)")
def db_init(_: list[str]) -> None:
    data = DEVDB / "pgdata"
    if data.exists():
        print(f"{data} already exists; use 'db-start'.")
        return
    DEVDB.mkdir(exist_ok=True)
    run(
        [
            pg("initdb"),
            "-D",
            str(data),
            "-U",
            "launchpad",
            "--auth=trust",
            "-E",
            "UTF8",
            "--locale=C",
        ]
    )
    db_start([])
    for name in ("launchpad", "launchpad_test"):
        run([pg("createdb"), "-h", "localhost", "-p", str(DEVDB_PORT), "-U", "launchpad", name])
        run(
            [
                pg("psql"),
                "-h",
                "localhost",
                "-p",
                str(DEVDB_PORT),
                "-U",
                "launchpad",
                "-d",
                name,
                "-qc",
                "create extension if not exists vector",
            ]
        )
    print(
        "\nLocal cluster ready (trust auth, localhost only). Put this in .env:\n"
        f"DATABASE_URL=postgresql+asyncpg://launchpad@localhost:{DEVDB_PORT}/launchpad"
    )


@task("Start the .devdb Postgres cluster")
def db_start(_: list[str]) -> None:
    data = DEVDB / "pgdata"
    if not data.exists():
        sys.exit("No local cluster yet. Run the 'db-init' task first.")
    print(f"Starting Postgres on localhost:{DEVDB_PORT} (log: .devdb/postgres.log)", flush=True)
    # The server inherits pg_ctl's handles; detach them so callers reading our output
    # (pipes, CI, IDEs) don't block forever waiting for EOF. Logs go to the -l file.
    result = subprocess.run(  # noqa: S603
        [
            pg("pg_ctl"), "-D", str(data), "-l", str(DEVDB / "postgres.log"), "-w",
            "-o", f"-p {DEVDB_PORT} -c listen_addresses=localhost", "start",
        ],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        check=False,
    )  # fmt: skip
    if result.returncode != 0:
        status = subprocess.run([pg("pg_ctl"), "-D", str(data), "status"], capture_output=True)  # noqa: S603
        if status.returncode == 0:
            print("Already running.")
            return
        sys.exit(f"pg_ctl start failed (exit {result.returncode}); see .devdb/postgres.log")


@task("Stop the .devdb Postgres cluster")
def db_stop(_: list[str]) -> None:
    run([pg("pg_ctl"), "-D", str(DEVDB / "pgdata"), "-m", "fast", "stop"])


@task("Apply database migrations")
def migrate(_: list[str]) -> None:
    py("-m", "alembic", "upgrade", "head", cwd=API)


@task('Autogenerate a migration: migration "add foo"')
def migration(args: list[str]) -> None:
    if not args:
        sys.exit('Usage: tasks.py migration "message"')
    py("-m", "alembic", "revision", "--autogenerate", "-m", " ".join(args), cwd=API)


@task("Run the API with reload on :8000")
def dev_api(_: list[str]) -> None:
    py("-m", "uvicorn", "launchpad.main:app", "--reload", "--port", "8000", cwd=API)


@task("Run the background worker")
def dev_worker(_: list[str]) -> None:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    py("-m", "arq", "launchpad_worker.main.WorkerSettings", cwd=API, env=env)


@task("Run the web app with hot reload on :3000")
def dev_web(_: list[str]) -> None:
    run([NPM, "run", "dev"], cwd=WEB)


@task("Run API + worker + web together (Ctrl+C stops all)")
def dev(_: list[str]) -> None:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    procs = {
        "api": (
            [venv_python(), "-m", "uvicorn", "launchpad.main:app", "--reload", "--port", "8000"],
            API,
        ),
        "worker": ([venv_python(), "-m", "arq", "launchpad_worker.main.WorkerSettings"], API),
        "web": ([NPM, "run", "dev"], WEB),
    }
    running: list[subprocess.Popen[str]] = []

    def pump(name: str, proc: subprocess.Popen[str]) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            print(f"[{name:6}] {line}", end="", flush=True)

    for name, (cmd, cwd) in procs.items():
        p = subprocess.Popen(  # noqa: S603
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            # Own process group so Ctrl+Break can stop each child cleanly on Windows.
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0,
        )
        running.append(p)
        threading.Thread(target=pump, args=(name, p), daemon=True).start()
    try:
        while all(p.poll() is None for p in running):
            time.sleep(0.5)
        print("\nA process exited; stopping the others.")
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        for p in running:
            if p.poll() is None:
                p.send_signal(signal.CTRL_BREAK_EVENT if IS_WINDOWS else signal.SIGTERM)
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()


@task("Run backend tests (uses TEST_DATABASE_URL, else DATABASE_URL's *_test database)")
def test(args: list[str]) -> None:
    env = test_env()
    py("-m", "pytest", *args, cwd=API, env=env)
    py("-m", "pytest", *args, cwd=WORKER, env=env)
    run([NPM, "run", "-s", "test"], cwd=WEB)


@task("Lint and format-check everything")
def lint(_: list[str]) -> None:
    for pkg in (API, WORKER):
        py("-m", "ruff", "check", ".", cwd=pkg)
        py("-m", "ruff", "format", "--check", ".", cwd=pkg)
    run([NPM, "run", "-s", "lint"], cwd=WEB)
    run([NPM, "run", "-s", "format:check"], cwd=WEB)


@task("Auto-format everything")
def fmt(_: list[str]) -> None:
    for pkg in (API, WORKER):
        py("-m", "ruff", "check", "--fix", ".", cwd=pkg)
        py("-m", "ruff", "format", ".", cwd=pkg)
    run([NPM, "run", "-s", "format"], cwd=WEB)


@task("mypy (strict) + tsc")
def typecheck(_: list[str]) -> None:
    py("-m", "mypy", cwd=API)
    py("-m", "mypy", cwd=WORKER)
    run([NPM, "run", "-s", "typecheck"], cwd=WEB)


@task("Regenerate the OpenAPI spec and the typed TS client")
def gen_api(_: list[str]) -> None:
    out = subprocess.run(  # noqa: S603
        [venv_python(), "-m", "launchpad.openapi"], cwd=API, capture_output=True, check=True
    )
    (WEB / "openapi.json").write_bytes(out.stdout)
    run([NPM, "run", "-s", "gen:api"], cwd=WEB)


@task("Everything CI runs: lint, typecheck, test")
def check(args: list[str]) -> None:
    lint(args)
    typecheck(args)
    test([])


@task("Run the content-engine eval: eval gemini | eval groq [--model ...] | eval --fake", "eval")
def run_eval(args: list[str]) -> None:
    if not args:
        args = ["--provider", "gemini"]
    elif args[0] in ("gemini", "groq", "openai", "anthropic"):
        args = ["--provider", *args]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    py("-m", "evals.run", *args, cwd=API, env=env)


@task("Docker: build and start the full stack")
def up(_: list[str]) -> None:
    run(["docker", "compose", "up", "--build", "-d"])
    print("Web: http://localhost:3000  API docs: http://localhost:8000/docs")


@task("Docker: stop the stack")
def down(_: list[str]) -> None:
    run(["docker", "compose", "down"])


@task("Docker: tail logs")
def logs(_: list[str]) -> None:
    run(["docker", "compose", "logs", "-f", "--tail=100"])


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help", "help"}:
        print(__doc__)
        for name, (_, help_text) in TASKS.items():
            print(f"  {name:12} {help_text}")
        return
    name, args = sys.argv[1], sys.argv[2:]
    if name not in TASKS:
        sys.exit(f"Unknown task '{name}'. Run without arguments to list tasks.")
    TASKS[name][0](args)


if __name__ == "__main__":
    main()
