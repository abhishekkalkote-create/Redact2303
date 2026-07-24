from functools import lru_cache

from app.core.config import Settings, get_settings
from app.storage.base import ContentStore
from app.storage.local import LocalFilesystemStore

__all__ = ["ContentStore", "get_store"]


@lru_cache
def get_store(settings: Settings | None = None) -> ContentStore:
    settings = settings or get_settings()
    if settings.env == "local":
        return LocalFilesystemStore(settings.local_storage_root)

    from app.storage.s3 import S3Store

    if not settings.s3_content_bucket:
        raise RuntimeError("S3_CONTENT_BUCKET is not configured for a non-local environment")
    return S3Store(settings.s3_content_bucket, settings.aws_region)
