from abc import ABC, abstractmethod


class ContentStore(ABC):
    """Content storage abstraction over the S3 content bucket (infra/modules/storage) —
    keys are always `{org_id}/...` (specs/02-architecture.md § Request lifecycle: "workers
    ... construct S3 keys as s3://{bucket}/{org_id}/... only from the message, never from
    payload-derived paths"). Callers pass org_id explicitly on every call; implementations
    must not accept a bare key that skips the org prefix.
    """

    @abstractmethod
    def put(self, org_id: str, key: str, data: bytes) -> str:
        """Returns the storage key actually written (== f"{org_id}/{key}")."""

    @abstractmethod
    def get(self, org_id: str, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, org_id: str, key: str) -> bool: ...

    @abstractmethod
    def delete(self, org_id: str, key: str) -> None: ...
