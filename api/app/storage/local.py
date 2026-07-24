from pathlib import Path

from app.storage.base import ContentStore


class LocalFilesystemStore(ContentStore):
    """Dev/test stand-in for the S3 content bucket — same `{org_id}/...` key layout, so
    swapping to `S3Store` later is a pure config change, not a code change."""

    def __init__(self, root: str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, org_id: str, key: str) -> Path:
        full = (self.root / org_id / key).resolve()
        if self.root.resolve() not in full.parents and full != self.root.resolve():
            raise ValueError(f"Refusing to write outside storage root: {key!r}")
        return full

    def put(self, org_id: str, key: str, data: bytes) -> str:
        path = self._path(org_id, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return f"{org_id}/{key}"

    def get(self, org_id: str, key: str) -> bytes:
        return self._path(org_id, key).read_bytes()

    def exists(self, org_id: str, key: str) -> bool:
        return self._path(org_id, key).exists()

    def delete(self, org_id: str, key: str) -> None:
        path = self._path(org_id, key)
        if path.exists():
            path.unlink()
