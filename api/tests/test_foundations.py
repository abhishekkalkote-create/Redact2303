import pytest

from app.core.config import Settings
from app.crypto.envelope import LocalDevCipher
from app.storage.local import LocalFilesystemStore


def test_envelope_cipher_roundtrip() -> None:
    settings = Settings(local_dev_encryption_key="qyhZRwVqQiUw1yI10p7u_P3YQQajwHwBzoT8Cmhkczk=")
    cipher = LocalDevCipher(settings)
    ciphertext = cipher.encrypt("org_a", "555-12-3456")
    assert ciphertext != "555-12-3456"
    assert cipher.decrypt("org_a", ciphertext) == "555-12-3456"


def test_local_filesystem_store_roundtrip(tmp_path) -> None:
    store = LocalFilesystemStore(str(tmp_path))
    key = store.put("org_a", "originals/doc_1.pdf", b"%PDF-1.4 fake content")
    assert key == "org_a/originals/doc_1.pdf"
    assert store.exists("org_a", "originals/doc_1.pdf")
    assert store.get("org_a", "originals/doc_1.pdf") == b"%PDF-1.4 fake content"
    store.delete("org_a", "originals/doc_1.pdf")
    assert not store.exists("org_a", "originals/doc_1.pdf")


def test_local_filesystem_store_blocks_path_traversal(tmp_path) -> None:
    store = LocalFilesystemStore(str(tmp_path))
    with pytest.raises(ValueError):
        store.put("org_a", "../../etc/passwd", b"pwned")
