"""app/crypto/envelope.py's KmsEnvelopeCipher - found completely unimplemented while
sweeping for pilot-readiness gaps: get_cipher() unconditionally raised NotImplementedError
outside env=="local", meaning literally any redaction candidate creation (which encrypts
display_text on every single one) would crash in any deployed environment.

Uses moto's real KMS mock (not a hand-rolled fake) so this exercises actual KMS API
semantics - create_key/create_alias/generate_data_key/decrypt really wrap/unwrap a real
random key, not just a plausible-looking stub.
"""

import pytest
from moto import mock_aws

from app.crypto.envelope import KmsEnvelopeCipher


@pytest.fixture
def kms_cipher():
    with mock_aws():
        yield KmsEnvelopeCipher(region="us-east-1")


def test_encrypt_decrypt_roundtrip(kms_cipher: KmsEnvelopeCipher) -> None:
    ciphertext = kms_cipher.encrypt("org_abc", "452-88-3017")
    assert ciphertext != "452-88-3017"
    assert kms_cipher.decrypt("org_abc", ciphertext) == "452-88-3017"


def test_creates_a_real_per_org_key_and_alias(kms_cipher: KmsEnvelopeCipher) -> None:
    import boto3

    kms_cipher.encrypt("org_xyz", "some text")

    client = boto3.client("kms", region_name="us-east-1")
    aliases = client.list_aliases()["Aliases"]
    # org_id already carries the "org_" prefix (real ids are org_<ULID>) - the alias is
    # "alias/org-org_xyz", not "alias/org-xyz"; a bit redundant-looking but correct and
    # still matches the IAM policy's `kms:RequestAlias = "alias/org-*"` condition.
    assert any(a["AliasName"] == "alias/org-org_xyz" for a in aliases)


def test_reuses_the_same_key_across_multiple_calls(kms_cipher: KmsEnvelopeCipher) -> None:
    import boto3

    kms_cipher.encrypt("org_reuse", "first")
    kms_cipher.encrypt("org_reuse", "second")

    client = boto3.client("kms", region_name="us-east-1")
    matching = [a for a in client.list_aliases()["Aliases"] if a["AliasName"] == "alias/org-org_reuse"]
    assert len(matching) == 1


def test_encrypt_retries_past_a_transient_alias_not_found(
    kms_cipher: KmsEnvelopeCipher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Confirmed for real against the deployed app (2026-09-07): a brand-new org's very
    first upload failed with GenerateDataKey NotFoundException on the alias moments
    after _ensure_key()'s own create_alias call for that exact alias had already
    succeeded - real KMS alias-to-key resolution can lag slightly behind alias creation.
    Simulates that exact race: the first generate_data_key call raises NotFoundException
    (as if the alias hasn't propagated yet), the second call (against moto's real,
    already-created alias) succeeds."""
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    real_generate_data_key = kms_cipher._client.generate_data_key
    calls = {"count": 0}

    def flaky_generate_data_key(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise kms_cipher._client.exceptions.NotFoundException(
                {"Error": {"Code": "NotFoundException", "Message": "Alias not found"}}, "GenerateDataKey"
            )
        return real_generate_data_key(**kwargs)

    monkeypatch.setattr(kms_cipher._client, "generate_data_key", flaky_generate_data_key)

    ciphertext = kms_cipher.encrypt("org_race", "sensitive text")

    assert calls["count"] == 2
    assert kms_cipher.decrypt("org_race", ciphertext) == "sensitive text"


def test_different_orgs_get_different_keys(kms_cipher: KmsEnvelopeCipher) -> None:
    from botocore.exceptions import ClientError

    ct_a = kms_cipher.encrypt("org_a", "shared plaintext")
    ct_b = kms_cipher.encrypt("org_b", "shared plaintext")
    assert ct_a != ct_b

    # org_a's ciphertext must not decrypt under org_b's key
    with pytest.raises(ClientError, match="AccessDeniedException"):
        kms_cipher.decrypt("org_b", ct_a)
