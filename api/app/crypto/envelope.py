"""Application-layer envelope encryption for `redaction_candidates.display_text`
(specs/08-security-compliance.md § Encryption — "the most sensitive strings in the DB").

Prod: one CMK per org (`alias/org-<org_id>`, created at runtime — see
infra/modules/storage's per_org_kms_management IAM policy), used via `kms:GenerateDataKey`
+ local AES-GCM, the standard envelope pattern (never call kms:Decrypt on every read).

Local dev: no KMS/AWS account exists yet, so a single local Fernet key stands in — clearly
NOT per-org, NOT for any real deployment. Selected by `settings.env`, same seam as
app/auth/{cognito,dev_provider}.py.
"""

from cryptography.fernet import Fernet

from app.core.config import Settings, get_settings


class EnvelopeCipher:
    def encrypt(self, org_id: str, plaintext: str) -> str:
        raise NotImplementedError

    def decrypt(self, org_id: str, ciphertext: str) -> str:
        raise NotImplementedError


class LocalDevCipher(EnvelopeCipher):
    """Single static key for all orgs. Local dev / tests only — never prod."""

    def __init__(self, settings: Settings) -> None:
        self._fernet = Fernet(settings.local_dev_encryption_key.encode())

    def encrypt(self, org_id: str, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, org_id: str, ciphertext: str) -> str:
        return self._fernet.decrypt(ciphertext.encode()).decode()


class KmsEnvelopeCipher(EnvelopeCipher):
    """Per-org CMK via `alias/org-<org_id>` + AES-GCM data key (real envelope encryption).
    Not wired until an AWS account + per-org keys exist — see specs/08-security-compliance.md.
    """

    def __init__(self) -> None:
        raise NotImplementedError(
            "KMS envelope encryption requires an AWS account and per-org CMKs; "
            "not available until infra/modules/storage is applied. Use ENV=local until then."
        )


def get_cipher(settings: Settings | None = None) -> EnvelopeCipher:
    settings = settings or get_settings()
    if settings.env == "local":
        return LocalDevCipher(settings)
    return KmsEnvelopeCipher()
