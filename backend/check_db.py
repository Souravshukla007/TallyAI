"""
Read-only connectivity check for BUSINESS_DATABASE_URL.

Connects with the configured (read-only) role, lists tables, runs a sample
SELECT, and confirms that a write is rejected — proving the role is safe.
Reads only; the write attempt is expected to fail.
"""
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")
import asyncpg


def _to_asyncpg_dsn(url: str) -> str:
    # asyncpg wants a plain postgresql:// DSN without the SQLAlchemy driver suffix
    # or the ssl query (we pass ssl explicitly).
    dsn = url.replace("postgresql+asyncpg://", "postgresql://")
    if "?" in dsn:
        dsn = dsn.split("?", 1)[0]
    return dsn


async def _try_connect(host, port, user, password, database):
    return await asyncpg.connect(
        host=host, port=port, user=user, password=password,
        database=database, ssl="require", timeout=30,
    )


async def main() -> None:
    from urllib.parse import urlparse, unquote

    raw = os.getenv("BUSINESS_DATABASE_URL")
    if not raw:
        print("BUSINESS_DATABASE_URL not set")
        return

    parsed = urlparse(_to_asyncpg_dsn(raw))
    user = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    host = parsed.hostname or ""
    port = parsed.port or 5432
    database = (parsed.path or "/").lstrip("/")

    print(f"user={user!r} host={host!r} db={database!r} pw_len={len(password)}")

    # Try the configured host first, then the direct (non-pooler) endpoint.
    hosts = [host]
    if "-pooler." in host:
        hosts.append(host.replace("-pooler.", ".", 1))

    conn = None
    for h in hosts:
        try:
            conn = await _try_connect(h, port, user, password, database)
            print(f"CONNECTED via host={h!r}")
            break
        except Exception as exc:
            print(f"  attempt host={h!r} -> {type(exc).__name__}: {str(exc).splitlines()[0]}")
    if conn is None:
        print("CONNECT_FAILED on all hosts")
        return

    try:
        ver = await conn.fetchval("SELECT version()")
        print("VERSION:", ver.split(",")[0])

        who = await conn.fetchval("SELECT current_user")
        print("ROLE:", who)

        rows = await conn.fetch(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' ORDER BY table_name
            """
        )
        tables = [r["table_name"] for r in rows]
        print(f"TABLES ({len(tables)}):", ", ".join(tables[:30]) or "(none)")

        if tables:
            t = tables[0]
            cnt = await conn.fetchval(f'SELECT COUNT(*) FROM "{t}"')
            print(f"SELECT_OK: \"{t}\" has {cnt} rows")

        # Prove read-only: a write must be rejected.
        try:
            await conn.execute("CREATE TABLE _tallyai_write_test (id int)")
            await conn.execute("DROP TABLE _tallyai_write_test")
            print("WRITE: !!! UNEXPECTEDLY ALLOWED — role is NOT read-only !!!")
        except Exception as exc:
            print("WRITE_BLOCKED (good):", str(exc).splitlines()[0])
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
