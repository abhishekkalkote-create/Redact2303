from pathlib import Path

from app.storage.base import ContentStore


class LocalFilesystemStore(ContentStore):
    """Dev/test stand-in for the S3 content bucket — same `{org_id}/...` key layout, so
    swapping to `S3Store` later is a pure config change, not a code change."""

    def __init__(self, root: str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, org_id: str, key: str) -> Path:
        """Security self-review finding: the previous check compared `full` against the
        shared `self.root`, not the org's own subdirectory. Two gaps: (1) an absolute
        `key` (e.g. "/etc/passwd") makes `root / org_id / key` collapse to just `key` —
        `Path.__truediv__` discards everything to the left of an absolute right operand
        — landing outside `root` entirely, which the old check DID catch; but (2) a
        relative `key` of exactly ".." resolved to `root` itself (one level ABOVE any
        org's own directory) and slipped through, since `full == root` hit the check's
        own carve-out for "the root itself is fine." That's not fine — it's a different
        org's sibling territory. Every caller currently passes only server-generated
        keys (doc_id, page numbers, fixed prefixes), so this was unreachable in
        practice; fixed anyway by requiring `full` be under the org's OWN resolved
        prefix, not merely under the shared root."""
        org_root = (self.root / org_id).resolve()
        full = (org_root / key).resolve()
        if full != org_root and org_root not in full.parents:
            raise ValueError(f"Refusing to access outside org {org_id!r}'s storage prefix: {key!r}")
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
