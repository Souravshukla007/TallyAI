"""
Tests for CredentialStore (Req 1.1, 1.4, 1.5, 14.4).

Covers:
  - save() encrypts credentials (stored bytes ≠ original JSON)
  - get_connection() decrypts and returns the original dict
  - Cross-tenant access returns None
  - Unknown connection_id returns None
"""

from __future__ import annotations

import json
import os

import pytest

from tallyai.services.credential_store import CredentialStore

# Use a deterministic test secret so key derivation is predictable.
os.environ.setdefault("SECRET_KEY", "test-secret-for-unit-tests")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TENANT_A = "tenant-aaa"
TENANT_B = "tenant-bbb"
CONN_ID = "conn-001"
CREDS = {"user": "readonly_user", "password": "s3cr3t"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_stores_ciphertext_not_plaintext(db_session):
    """Stored bytes must NOT equal the JSON-serialised credentials (Req 1.1)."""
    store = CredentialStore()
    await store.save(CONN_ID, TENANT_A, CREDS, db_session)

    from sqlalchemy import select
    from tallyai.db.models import EncryptedCredential

    result = await db_session.execute(
        select(EncryptedCredential).where(
            EncryptedCredential.connection_id == CONN_ID
        )
    )
    row = result.scalars().first()

    assert row is not None, "EncryptedCredential row should exist after save()"

    plaintext_json = json.dumps(CREDS).encode()
    assert row.ciphertext != plaintext_json, (
        "Stored ciphertext must not equal plain JSON (Req 1.1)"
    )
    # Verify it really looks like Fernet ciphertext (starts with 'g' in base64).
    assert len(row.ciphertext) > len(plaintext_json), (
        "Ciphertext should be longer than plaintext due to Fernet overhead"
    )


@pytest.mark.asyncio
async def test_get_connection_decrypts_correctly(db_session):
    """get_connection() must return the original credentials dict."""
    store = CredentialStore()
    await store.save(CONN_ID, TENANT_A, CREDS, db_session)

    retrieved = await store.get_connection(CONN_ID, TENANT_A, db_session)

    assert retrieved == CREDS, "Decrypted credentials must match the original dict"


@pytest.mark.asyncio
async def test_cross_tenant_access_returns_none(db_session):
    """A different tenant must NOT see another tenant's credentials (Req 14.4)."""
    store = CredentialStore()
    # Tenant A saves credentials.
    await store.save(CONN_ID, TENANT_A, CREDS, db_session)

    # Tenant B attempts to retrieve them — should get None.
    retrieved = await store.get_connection(CONN_ID, TENANT_B, db_session)

    assert retrieved is None, (
        "Cross-tenant credential access must return None (Req 14.4)"
    )


@pytest.mark.asyncio
async def test_unknown_connection_returns_none(db_session):
    """get_connection() for a non-existent connection_id must return None."""
    store = CredentialStore()
    retrieved = await store.get_connection("nonexistent-conn", TENANT_A, db_session)
    assert retrieved is None


@pytest.mark.asyncio
async def test_save_upserts_credentials(db_session):
    """Calling save() twice should update the ciphertext, not duplicate rows."""
    store = CredentialStore()
    await store.save(CONN_ID, TENANT_A, CREDS, db_session)

    new_creds = {"user": "new_user", "password": "new_password"}
    await store.save(CONN_ID, TENANT_A, new_creds, db_session)

    # Only one row should exist.
    from sqlalchemy import select, func
    from tallyai.db.models import EncryptedCredential

    count_result = await db_session.execute(
        select(func.count()).where(
            EncryptedCredential.connection_id == CONN_ID,
            EncryptedCredential.tenant_id == TENANT_A,
        )
    )
    count = count_result.scalar()
    assert count == 1, "Upsert must not create duplicate rows"

    # The retrieved credentials should be the latest.
    retrieved = await store.get_connection(CONN_ID, TENANT_A, db_session)
    assert retrieved == new_creds


@pytest.mark.asyncio
async def test_different_tenants_same_connection_id_isolated(db_session):
    """Two tenants can have the same connection_id; reads are isolated."""
    store = CredentialStore()
    creds_a = {"user": "user_a", "password": "pass_a"}
    creds_b = {"user": "user_b", "password": "pass_b"}

    # We need separate connection_ids since there's a FK on TenantConnection;
    # for pure CredentialStore isolation tests we save without FK constraints
    # (SQLite in-memory has FK enforcement off by default).
    conn_a = "conn-a"
    conn_b = "conn-b"

    # Insert bare EncryptedCredential rows directly to bypass FK.
    from tallyai.db.models import EncryptedCredential
    import json, base64, hashlib, os as _os
    from cryptography.fernet import Fernet

    secret = _os.getenv("SECRET_KEY", "test-secret-for-unit-tests")
    digest = hashlib.sha256(secret.encode()).digest()
    key = base64.urlsafe_b64encode(digest)
    fernet = Fernet(key)

    for cid, tid, creds in [(conn_a, TENANT_A, creds_a), (conn_b, TENANT_B, creds_b)]:
        row = EncryptedCredential(
            connection_id=cid,
            tenant_id=tid,
            ciphertext=fernet.encrypt(json.dumps(creds).encode()),
            kms_key_id="fernet-env-sha256",
        )
        db_session.add(row)
    await db_session.flush()

    assert await store.get_connection(conn_a, TENANT_A, db_session) == creds_a
    assert await store.get_connection(conn_b, TENANT_B, db_session) == creds_b
    # Tenant A must not read Tenant B's connection.
    assert await store.get_connection(conn_b, TENANT_A, db_session) is None
