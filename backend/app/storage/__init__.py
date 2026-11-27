from app.core.config import Settings
from app.storage.base import StorageBackend, StorageError
from app.storage.local import LocalStorage
from app.storage.object_storage import S3Storage


def create_storage(settings: Settings) -> StorageBackend:
    if settings.storage_backend == "s3":
        assert settings.s3_bucket
        return S3Storage.from_settings(
            bucket=settings.s3_bucket,
            prefix=settings.s3_prefix,
            endpoint_url=settings.s3_endpoint_url,
            region=settings.s3_region,
            access_key_id=(
                settings.s3_access_key_id.get_secret_value() if settings.s3_access_key_id else None
            ),
            secret_access_key=(
                settings.s3_secret_access_key.get_secret_value()
                if settings.s3_secret_access_key
                else None
            ),
        )
    return LocalStorage(settings.upload_dir)


__all__ = ["LocalStorage", "S3Storage", "StorageBackend", "StorageError", "create_storage"]
