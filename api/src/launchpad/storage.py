"""Object storage behind one interface: S3-compatible (MinIO, Supabase Storage, R2, S3)
or the local filesystem for docker-less development.

Keys are always workspace-scoped: `ws/<workspace_id>/<kind>/<uuid>.<ext>`.
Signed URLs expire; local "signed URLs" are HMAC-signed links served by the API.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

from launchpad.config import get_settings


class StorageError(Exception):
    pass


class ObjectNotFound(StorageError):
    pass


@dataclass(frozen=True)
class StoredObject:
    key: str
    content_type: str
    size: int


class Storage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> StoredObject: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...
    async def signed_url(self, key: str, expires_s: int = 3600) -> str: ...
    async def check(self) -> None: ...


def _sign(key: str, exp: int) -> str:
    secret = get_settings().require_jwt_secret().encode()
    return hmac.new(secret, f"{key}:{exp}".encode(), hashlib.sha256).hexdigest()


def verify_local_signature(key: str, exp: int, sig: str) -> bool:
    return exp >= int(time.time()) and hmac.compare_digest(_sign(key, exp), sig)


class LocalStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):  # no path traversal
            raise StorageError(f"Invalid storage key: {key}")
        return path

    async def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)
        return StoredObject(key=key, content_type=content_type, size=len(data))

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFound(key)
        return await asyncio.to_thread(path.read_bytes)

    async def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    async def signed_url(self, key: str, expires_s: int = 3600) -> str:
        exp = int(time.time()) + expires_s
        base = get_settings().api_public_url.rstrip("/")
        return f"{base}/api/v1/files/{quote(key)}?exp={exp}&sig={_sign(key, exp)}"

    async def check(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)


class S3Storage:
    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        s = get_settings()
        self.bucket = s.s3_bucket
        self.client: Any = boto3.client(  # Any: boto3 clients are dynamically typed
            "s3",
            endpoint_url=s.s3_endpoint_url,
            region_name=s.s3_region,
            aws_access_key_id=s.s3_access_key_id.get_secret_value() if s.s3_access_key_id else None,
            aws_secret_access_key=(
                s.s3_secret_access_key.get_secret_value() if s.s3_secret_access_key else None
            ),
            config=Config(signature_version="s3v4", retries={"mode": "standard"}),
        )

    async def put(self, key: str, data: bytes, content_type: str) -> StoredObject:
        await asyncio.to_thread(
            self.client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return StoredObject(key=key, content_type=content_type, size=len(data))

    async def get(self, key: str) -> bytes:
        from botocore.exceptions import ClientError

        try:
            obj = await asyncio.to_thread(self.client.get_object, Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                raise ObjectNotFound(key) from exc
            raise
        body: bytes = await asyncio.to_thread(obj["Body"].read)
        return body

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=key)

    async def signed_url(self, key: str, expires_s: int = 3600) -> str:
        url: str = await asyncio.to_thread(
            self.client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_s,
        )
        return url

    async def check(self) -> None:
        await asyncio.to_thread(self.client.head_bucket, Bucket=self.bucket)


@lru_cache
def get_storage() -> Storage:
    s = get_settings()
    if s.storage_backend == "s3":
        return S3Storage()
    return LocalStorage(s.storage_local_dir)
