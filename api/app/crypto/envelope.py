"""Application-layer envelope encryption for `redaction_candidates.display_text`
(specs/08-security-compliance.md § Encryption — "the most sensitive strings in the DB").

Prod: one CMK per org (`alias/org-<org_id>`, created at runtime — see
infra/modules/storage's per_org_kms_management IAM policy), used via `kms:GenerateDataKey`
+ local AES-GCM, the standard envelope pattern (never call kms:Decrypt on every read).

Local dev: no KMS/AWS account exists yet, so a single local Fernet key stands in — clearly
NOT per-org, NOT for any real deployment. Selected by `settings.env`, same seam as
app/auth/{cognito,dev_provider}.py.
"""

import base64
import json
import os

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

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
    infra/modules/storage's per_org_kms_management IAM policy scopes Encrypt/Decrypt/
    GenerateDataKey/CreateKey/CreateAlias to exactly this alias pattern (condition:
    `kms:RequestAlias = "alias/org-*"`) - every KMS call here must pass `KeyId=<alias>`,
    an actual key ARN/id would silently fail that condition.

    Ciphertext format: base64(json({"k": b64(kms-encrypted data key), "n": b64(12-byte
    AES-GCM nonce), "c": b64(AES-GCM ciphertext+tag)})) - self-contained per value, so
    decrypt never needs anything beyond the stored string + this org's CMK.
    """

    def __init__(self, region: str) -> None:
        import boto3

        self._client = boto3.client("kms", region_name=region)

    def _alias(self, org_id: str) -> str:
        return f"alias/org-{org_id}"

    def _ensure_key(self, org_id: str) -> None:
        alias = self._alias(org_id)
        try:
            self._client.describe_key(KeyId=alias)
            return
        except self._client.exceptions.NotFoundException:
            pass

        created = self._client.create_key(
            Description=f"RedactProof per-org content key ({org_id})",
            KeyUsage="ENCRYPT_DECRYPT",
            Tags=[{"TagKey": "org_id", "TagValue": org_id}],
        )
        key_id = created["KeyMetadata"]["KeyId"]
        try:
            self._client.create_alias(AliasName=alias, TargetKeyId=key_id)
        except self._client.exceptions.AlreadyExistsException:
            pass  # another concurrent request already created it for this org
        self._client.enable_key_rotation(KeyId=key_id)

    def encrypt(self, org_id: str, plaintext: str) -> str:
        self._ensure_key(org_id)
        alias = self._alias(org_id)
        data_key = self._client.generate_data_key(KeyId=alias, KeySpec="AES_256")
        nonce = os.urandom(12)
        aesgcm = AESGCM(data_key["Plaintext"])
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
        envelope = {
            "k": base64.b64encode(data_key["CiphertextBlob"]).decode(),
            "n": base64.b64encode(nonce).decode(),
            "c": base64.b64encode(ciphertext).decode(),
        }
        return base64.b64encode(json.dumps(envelope).encode()).decode()

    def decrypt(self, org_id: str, ciphertext: str) -> str:
        envelope = json.loads(base64.b64decode(ciphertext))
        encrypted_key = base64.b64decode(envelope["k"])
        nonce = base64.b64decode(envelope["n"])
        ct = base64.b64decode(envelope["c"])

        response = self._client.decrypt(CiphertextBlob=encrypted_key, KeyId=self._alias(org_id))
        aesgcm = AESGCM(response["Plaintext"])
        return aesgcm.decrypt(nonce, ct, None).decode()


def get_cipher(settings: Settings | None = None) -> EnvelopeCipher:
    settings = settings or get_settings()
    if settings.env == "local":
        return LocalDevCipher(settings)
    return KmsEnvelopeCipher(settings.aws_region)
