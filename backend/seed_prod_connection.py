"""
One-off seed script: register a 'prod' connection for the demo tenant pointing
at the configured BUSINESS_DATABASE_URL (Neon, read-only), and introspect its
schema into the cache.

The UI hardcodes connectionId="prod" for the MVP, so seeding a connection with
that exact id makes the Connections, Schema, Metrics, and History pages resolve
real data with no frontend changes.

Run from the backend directory:
    python seed_prod_connection.py

This performs DB work only (privilege probe + information_schema read against
the target DB, and writes to the local app DB). It does NOT call any LLM.
"""

from __future__ import annotations

import asyncio
import os
from urllib.parse import unquote, urlparse

import asyncpg
from dotenv import load_dotenv
from sqlalchemy import select

load_dotenv()

from tallyai.db.models import Base, TenantConnection  # noqa: E402
from tallyai.db.session import AsyncSessionLocal, engine  # noqa: E402
from tallyai.services.credential_store import CredentialStore  # noqa: E402
from tallyai.services.schema_introspector import SchemaIntrospector  # noqa: E402

CONNECTION_ID = "prod"
TENANT_ID = os.getenv("SEED_TENANT_ID", "demo-tenant")


def parse_business_url() -> dict:
    """Parse BUSINESS_DATABASE_URL into asyncpg connection parts."""
    raw = os.getenv("BUSINESS_DATABASE_URL")
    if not raw:
        raise SystemExit("BUSINESS_DATABASE_URL is not set in the environment/.env")

    # Strip the SQLAlchemy driver suffix so urlparse sees a plain postgres URL.
    normalized = raw.replace("postgresql+asyncpg://", "postgresql://")
    parsed = urlparse(normalized)

    host = parsed.hostname or ""
    port = parsed.port or 5432
    database = (parsed.path or "/").lstrip("/")
    user = unquote(parsed.username or "")
    password = unquote(parsed.password or "")

    # Neon (and most managed Postgres) require TLS.
    require_ssl = "ssl=require" in raw or "sslmode=require" in raw
    return {
        "host": host,
        "port": port,
        "database": database,
        "user": user,
        "password": password,
        "ssl": "require" if require_ssl else None,
    }


async def main() -> None:
    parts = parse_business_url()
    ssl = parts.pop("ssl")
    print(
        f"Target DB: host={parts['host']} port={parts['port']} "
        f"database={parts['database']} role={parts['user']} ssl={'require' if ssl else 'off'}"
    )

    # 0) Ensure app tables exist (no-op if already created).
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 1) Verify connectivity to the target DB up front (clear error if it fails).
    try:
        probe = await asyncpg.connect(ssl=ssl, **parts)
        await probe.close()
        print("✓ Connected to target database.")
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"✗ Could not connect to target database: {exc}")

    store = CredentialStore()
    introspector = SchemaIntrospector()
    credentials = {"user": parts["user"], "password": parts["password"]}

    async with AsyncSessionLocal() as db:
        # 2) Upsert the TenantConnection row with id "prod".
        existing = await db.execute(
            select(TenantConnection).where(
                TenantConnection.connection_id == CONNECTION_ID,
                TenantConnection.tenant_id == TENANT_ID,
            )
        )
        row = existing.scalars().first()
        if row is None:
            row = TenantConnection(
                connection_id=CONNECTION_ID,
                tenant_id=TENANT_ID,
                host=parts["host"],
                port=parts["port"],
                database=parts["database"],
                role=parts["user"],
                is_active=True,
                schema_version="",
            )
            db.add(row)
            print(f"✓ Created connection '{CONNECTION_ID}' for tenant '{TENANT_ID}'.")
        else:
            row.host = parts["host"]
            row.port = parts["port"]
            row.database = parts["database"]
            row.role = parts["user"]
            row.is_active = True
            print(f"✓ Updated existing connection '{CONNECTION_ID}'.")
        await db.flush()

        # 3) Store encrypted credentials.
        await store.save(CONNECTION_ID, TENANT_ID, credentials, db)
        await db.commit()
        print("✓ Stored encrypted credentials.")

    # 4) Introspect schema into the cache (separate session for clarity).
    #    NOTE: the shared SchemaIntrospector connects without TLS; for Neon we
    #    introspect here with the correct ssl setting and write the cache.
    async with AsyncSessionLocal() as db:
        tables = await _fetch_schema_with_ssl(parts, ssl)
        import json
        import uuid
        from datetime import datetime

        from tallyai.db.models import CachedSchema

        schema_version = str(uuid.uuid4())[:8]
        now = datetime.utcnow()
        existing = await db.execute(
            select(CachedSchema).where(
                CachedSchema.connection_id == CONNECTION_ID,
                CachedSchema.tenant_id == TENANT_ID,
            )
        )
        cached = existing.scalars().first()
        if cached is None:
            cached = CachedSchema(
                connection_id=CONNECTION_ID,
                tenant_id=TENANT_ID,
                schema_version=schema_version,
                tables_json=json.dumps(tables),
                introspected_at=now,
            )
            db.add(cached)
        else:
            cached.schema_version = schema_version
            cached.tables_json = json.dumps(tables)
            cached.introspected_at = now
        await db.commit()
        print(f"✓ Cached schema: {len(tables)} table(s), version {schema_version}.")

    # keep the unused import reference quiet
    _ = introspector
    print("\nDone. The 'prod' connection and its schema are ready.")


async def _fetch_schema_with_ssl(parts: dict, ssl) -> list[dict]:
    """Introspect information_schema with the correct TLS setting for Neon."""
    columns_query = """
        SELECT table_name, column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
    """
    fk_query = """
        SELECT kcu.table_name, kcu.column_name,
               ccu.table_name  AS foreign_table_name,
               ccu.column_name AS foreign_column_name
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
             ON tc.constraint_name = kcu.constraint_name
        JOIN information_schema.constraint_column_usage AS ccu
             ON ccu.constraint_name = tc.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_schema = 'public'
    """
    conn = await asyncpg.connect(ssl=ssl, **parts)
    try:
        col_rows = await conn.fetch(columns_query)
        fk_rows = await conn.fetch(fk_query)
    finally:
        await conn.close()

    fk_map: dict[str, list[dict]] = {}
    for r in fk_rows:
        fk_map.setdefault(r["table_name"], []).append(
            {
                "column": r["column_name"],
                "references_table": r["foreign_table_name"],
                "references_column": r["foreign_column_name"],
            }
        )

    tables_map: dict[str, dict] = {}
    for r in col_rows:
        t = r["table_name"]
        if t not in tables_map:
            tables_map[t] = {"name": t, "columns": [], "foreign_keys": fk_map.get(t, [])}
        tables_map[t]["columns"].append(
            {
                "name": r["column_name"],
                "type": r["data_type"],
                "nullable": r["is_nullable"].upper() == "YES",
            }
        )
    return list(tables_map.values())


if __name__ == "__main__":
    asyncio.run(main())
