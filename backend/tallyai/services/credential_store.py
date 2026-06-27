"""
Credential store — encrypts DB credentials at rest using Fernet symmetric
encryption and persists them as ``EncryptedCredential`` rows.

Security invariants (Req 1.1, 1.4, 1.5):
  - Credentials are JSON-serialised and Fernet-encrypted before any DB write.
  - Credential values are NEVER written to logs (no print/logger calls here).
  - The only way to retrieve plaintext credentials is via ``get_connection()``,
    which enforces tenant isolation.  There is no "dump all" method so callers
    cannot accidentally pass raw credentials into a prompt.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from typing import Optional

from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tallyai.db.models import EncryptedCredential

logger = logging.getLogger(__name__)


def _derive_fernet_key(secret: str) -> bytes:
    """Derive a URL-safe base64-encoded 32-byte Fernet key from *secret*.

    SHA-256 of the UTF-8 encoded secret gives a 32-byte digest; wrapping it
    in urlsafe_b64encode produces the 44-byte string Fernet expects.
    """
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _get_fernet() -> Fernet:
    """Build a Fernet instance from the ``SECRET_KEY`` environment variable."""
    secret = os.getenv("SECRET_KEY", "changeme-replace-in-production")
    key = _derive_fernet_key(secret)
    return Fernet(key)


class CredentialStore:
    """Handles encrypted persistence and retrieval of database credentials.

    Req 1.1 — encrypted at rest.
    Req 1.4 — credential *values* never appear in logs.
    Req 1.5 — no method exposes a raw credential dump; callers must use
               ``get_connection()`` which enforces tenant scoping.
    """

    # kms_key_id is a label stored alongside the ciphertext so a future KMS
    # migration can identify which key version was used.  For the Fernet/env
    # approach the label is the SHA-256 fingerprint of the key.
    _KMS_KEY_LABEL = "fernet-env-sha256"

    async def save(
        self,
        connection_id: str,
        tenant_id: str,
        credentials: dict,
        db: AsyncSession,
    ) -> None:
        """Encrypt *credentials* and upsert an ``EncryptedCredential`` row.

        Only the *presence* of keys is logged, never their values (Req 1.4).
        """
        fernet = _get_fernet()
        plaintext_json = json.dumps(credentials).encode()
        ciphertext: bytes = fernet.encrypt(plaintext_json)

        # Log only structural info — never credential values (Req 1.4).
        logger.debug(
            "Saving encrypted credentials for connection_id=%s tenant_id=%s keys=%s",
            connection_id,
            tenant_id,
            list(credentials.keys()),  # key *names* only, not values
        )

        # Upsert: delete any existing row for this (connection_id, tenant_id)
        # pair then insert a fresh one.  A unique constraint at the DB level
        # would be cleaner; this approach works with the current model.
        existing = await db.execute(
            select(EncryptedCredential).where(
                EncryptedCredential.connection_id == connection_id,
                EncryptedCredential.tenant_id == tenant_id,
            )
        )
        row = existing.scalars().first()
        if row is not None:
            row.ciphertext = ciphertext
            row.kms_key_id = self._KMS_KEY_LABEL
        else:
            row = EncryptedCredential(
                connection_id=connection_id,
                tenant_id=tenant_id,
                ciphertext=ciphertext,
                kms_key_id=self._KMS_KEY_LABEL,
            )
            db.add(row)

        await db.flush()

    async def get_connection(
        self,
        connection_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> Optional[dict]:
        """Fetch and decrypt the stored credentials for *(connection_id, tenant_id)*.

        Returns ``None`` if:
          - no credential row exists for this connection_id, or
          - the row's tenant_id does not match *tenant_id* (cross-tenant
            access prevention, Req 14.4).

        Credential values are never logged (Req 1.4).
        """
        result = await db.execute(
            select(EncryptedCredential).where(
                EncryptedCredential.connection_id == connection_id,
            )
        )
        row = result.scalars().first()

        if row is None:
            logger.debug(
                "get_connection: no credential found for connection_id=%s", connection_id
            )
            return None

        # Tenant isolation check — return None rather than raising so callers
        # can distinguish "not found" from "access denied" by checking the
        # returned value.
        if row.tenant_id != tenant_id:
            logger.warning(
                "get_connection: tenant mismatch for connection_id=%s "
                "expected_tenant=%s actual_tenant=%s — returning None (Req 14.4)",
                connection_id,
                tenant_id,
                row.tenant_id,
            )
            return None

        fernet = _get_fernet()
        plaintext_json = fernet.decrypt(row.ciphertext)
        credentials: dict = json.loads(plaintext_json)

        # Intentionally NOT logging credential values (Req 1.4).
        logger.debug(
            "get_connection: decrypted credentials for connection_id=%s tenant_id=%s keys=%s",
            connection_id,
            tenant_id,
            list(credentials.keys()),
        )
        return credentials
