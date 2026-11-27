"""S3-compatible object storage (AWS S3, Cloudflare R2, MinIO, Backblaze B2, ...).

Requires the optional `s3` extra (boto3). The client is injected so tests can pass a fake.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.storage.base import StorageError, validate_key


class S3Storage:
    name = "s3"

    def __init__(self, client: Any, bucket: str, prefix: str = "") -> None:
        self._client = client
        self._bucket = bucket
        self._prefix = prefix

    @classmethod
    def from_settings(
        cls,
        *,
        bucket: str,
        prefix: str,
        endpoint_url: str | None,
        region: str | None,
        access_key_id: str | None,
        secret_access_key: str | None,
    ) -> S3Storage:
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - depends on install extras
            raise RuntimeError("STORAGE_BACKEND=s3 requires the 's3' extra (boto3).") from exc
        client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )
        return cls(client, bucket, prefix)

    def _key(self, key: str) -> str:
        return f"{self._prefix}{validate_key(key)}"

    async def save(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=self._key(key),
            Body=data,
            ContentType=content_type,
        )

    async def read(self, key: str) -> bytes:
        try:
            response = await asyncio.to_thread(
                self._client.get_object, Bucket=self._bucket, Key=self._key(key)
            )
        except Exception as exc:
            raise StorageError("File not found.") from exc
        body: bytes = await asyncio.to_thread(response["Body"].read)
        return body

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=self._key(key))

    async def exists(self, key: str) -> bool:
        try:
            await asyncio.to_thread(
                self._client.head_object, Bucket=self._bucket, Key=self._key(key)
            )
        except Exception:
            return False
        return True
