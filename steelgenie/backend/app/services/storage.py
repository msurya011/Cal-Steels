"""
Storage adapter — abstracts local disk vs Cloudflare R2.
Switch with STORAGE_BACKEND=local (default) or r2 in .env.
"""
from __future__ import annotations

import logging
import mimetypes
import os
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class StorageAdapter(ABC):
    """Abstract file storage interface."""

    @abstractmethod
    async def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        """Store *data* under *key*. Returns the public/signed URL."""

    @abstractmethod
    async def get(self, key: str) -> bytes:
        """Retrieve file content by key."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete a file by key."""

    @abstractmethod
    async def signed_url(self, key: str, expires_in: int = 900) -> str:
        """Return a time-limited URL for *key*."""

    @abstractmethod
    def public_url(self, key: str) -> str:
        """Return the stable public URL for *key* (for non-sensitive assets)."""


# ---------------------------------------------------------------------------
# Local disk adapter
# ---------------------------------------------------------------------------

class LocalStorageAdapter(StorageAdapter):
    """
    Stores files on the local filesystem.
    Files are served by the FastAPI /files/{key} endpoint.
    """

    def __init__(self, base_dir: str, serve_base_url: str = "http://localhost:8000") -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)
        self._serve_base = serve_base_url.rstrip("/")

    def _path(self, key: str) -> Path:
        # Strip any leading slashes / path separators to prevent traversal
        safe_key = key.lstrip("/\\").replace("..", "")
        return self._base / safe_key

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        logger.debug("LocalStorage PUT %s (%d bytes)", key, len(data))
        return self.public_url(key)

    async def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    async def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            p.unlink()

    async def signed_url(self, key: str, expires_in: int = 900) -> str:
        # Local storage: no signing; just return the public URL
        return self.public_url(key)

    def public_url(self, key: str) -> str:
        return f"{self._serve_base}/api/v1/files/{key}"

    def local_path(self, key: str) -> str:
        """Return filesystem path — used when extraction engine needs the file."""
        return str(self._path(key))


# ---------------------------------------------------------------------------
# R2 adapter (Cloudflare R2 via boto3-compatible S3 API)
# ---------------------------------------------------------------------------

class R2StorageAdapter(StorageAdapter):
    """Cloudflare R2 via boto3."""

    def __init__(self) -> None:
        import boto3
        cfg = get_settings()
        endpoint = f"https://{cfg.r2_account_id}.r2.cloudflarestorage.com"
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=cfg.r2_access_key_id,
            aws_secret_access_key=cfg.r2_secret_access_key,
            region_name="auto",
        )
        self._bucket = cfg.r2_bucket_name
        self._public_url = cfg.r2_public_url.rstrip("/")

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self._client.put_object(
            Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
        )
        return self.public_url(key)

    async def get(self, key: str) -> bytes:
        resp = self._client.get_object(Bucket=self._bucket, Key=key)
        return resp["Body"].read()

    async def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    async def signed_url(self, key: str, expires_in: int = 900) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    def public_url(self, key: str) -> str:
        if self._public_url:
            return f"{self._public_url}/{key}"
        return f"https://{self._bucket}.r2.cloudflarestorage.com/{key}"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_adapter: Optional[StorageAdapter] = None


def get_storage() -> StorageAdapter:
    """Returns the configured storage adapter (singleton)."""
    global _adapter
    if _adapter is None:
        cfg = get_settings()
        if cfg.storage_backend == "r2":
            logger.info("Using R2 storage adapter")
            _adapter = R2StorageAdapter()
        else:
            logger.info("Using local storage adapter (dir=%s)", cfg.upload_dir)
            _adapter = LocalStorageAdapter(cfg.upload_dir)
    return _adapter


def generate_storage_key(prefix: str = "", ext: str = "") -> str:
    """Generate a UUID-based storage key.  Never uses user-provided filenames."""
    key = str(uuid.uuid4())
    if prefix:
        key = f"{prefix}/{key}"
    if ext:
        key = f"{key}{ext if ext.startswith('.') else '.' + ext}"
    return key
