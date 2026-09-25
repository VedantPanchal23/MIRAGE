"""Object Storage Abstraction Service adhering to ADR 0005.

Provides unified interface for storing compliance audit PDFs and reports
in S3 or local filesystem abstraction without exposing raw filesystem paths to route handlers.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from shared.config import get_settings
from shared.logging import get_logger

logger = get_logger("storage_service")


class ObjectStorageError(RuntimeError):
    """Base exception for object storage operations."""

    pass


class ObjectNotFoundError(ObjectStorageError):
    """Raised when an object key does not exist."""

    pass


class ObjectStorageService(ABC):
    """Abstract interface for object storage operations."""

    @abstractmethod
    def put_object(
        self,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Store an object and return its canonical storage URI."""
        pass

    @abstractmethod
    def get_object(self, bucket: str, key: str) -> tuple[bytes, str]:
        """Retrieve object bytes and content type."""
        pass

    @abstractmethod
    def delete_object(self, bucket: str, key: str) -> bool:
        """Delete an object if it exists."""
        pass

    @abstractmethod
    def object_exists(self, bucket: str, key: str) -> bool:
        """Check if an object exists."""
        pass

    @abstractmethod
    def generate_presigned_url(self, bucket: str, key: str, expires_in: int = 3600) -> str:
        """Generate download URL or presigned S3 link."""
        pass


class LocalStorageDriver(ObjectStorageService):
    """Local filesystem driver preserving exact bucket/key hierarchy."""

    def __init__(self, root_dir: str | Path = "tmp/storage"):
        self.root = Path(root_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, bucket: str, key: str) -> Path:
        # Prevent directory traversal
        clean_key = key.lstrip("/\\")
        parts = clean_key.replace("\\", "/").split("/")
        if ".." in parts:
            raise ObjectStorageError(f"Path traversal detected for key: {key}")

        bucket_root = (self.root / bucket).resolve()
        path = (self.root / bucket / clean_key).resolve()
        # Verify path falls strictly within bucket_root
        if not str(path).startswith(str(bucket_root)):
            raise ObjectStorageError(f"Path traversal detected for key: {key}")
        return path

    def put_object(
        self,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> str:
        target_path = self._resolve_path(bucket, key)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(data)
        logger.info("Stored object locally", bucket=bucket, key=key, size=len(data))
        return f"s3://{bucket}/{key}"

    def get_object(self, bucket: str, key: str) -> tuple[bytes, str]:
        target_path = self._resolve_path(bucket, key)
        if not target_path.exists():
            raise ObjectNotFoundError(f"Object s3://{bucket}/{key} not found")
        data = target_path.read_bytes()
        content_type = "application/pdf" if key.endswith(".pdf") else "application/octet-stream"
        return data, content_type

    def delete_object(self, bucket: str, key: str) -> bool:
        target_path = self._resolve_path(bucket, key)
        if target_path.exists():
            target_path.unlink()
            return True
        return False

    def object_exists(self, bucket: str, key: str) -> bool:
        target_path = self._resolve_path(bucket, key)
        return target_path.exists()

    def generate_presigned_url(self, bucket: str, key: str, expires_in: int = 3600) -> str:
        # For local driver, returns internal download URI
        clean_key = key.lstrip("/\\")
        return f"/v1/reports/{clean_key}/pdf"


class S3StorageDriver(ObjectStorageService):
    """Amazon S3 driver using boto3 with server-side encryption."""

    def __init__(
        self,
        region_name: str = "us-east-1",
        endpoint_url: str | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
    ):
        try:
            import boto3

            self.s3_client: Any = boto3.client(
                "s3",
                region_name=region_name,
                endpoint_url=endpoint_url,
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
            )
        except Exception as exc:
            logger.warning("Failed to initialize boto3 S3 client; falling back to uninitialized state", error=str(exc))
            self.s3_client = None

    def put_object(
        self,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> str:
        if not self.s3_client:
            raise ObjectStorageError("S3 client not initialized")
        clean_key = key.lstrip("/\\")
        params: dict[str, Any] = {
            "Bucket": bucket,
            "Key": clean_key,
            "Body": data,
            "ContentType": content_type,
            "ServerSideEncryption": "AES256",
        }
        if metadata:
            params["Metadata"] = metadata
        self.s3_client.put_object(**params)
        logger.info("Stored object in S3", bucket=bucket, key=clean_key, size=len(data))
        return f"s3://{bucket}/{clean_key}"

    def get_object(self, bucket: str, key: str) -> tuple[bytes, str]:
        if not self.s3_client:
            raise ObjectStorageError("S3 client not initialized")
        clean_key = key.lstrip("/\\")
        try:
            resp = self.s3_client.get_object(Bucket=bucket, Key=clean_key)
            data = resp["Body"].read()
            content_type = resp.get("ContentType", "application/octet-stream")
            return data, content_type
        except Exception as exc:
            raise ObjectNotFoundError(f"Object s3://{bucket}/{clean_key} not found: {exc}") from exc

    def delete_object(self, bucket: str, key: str) -> bool:
        if not self.s3_client:
            raise ObjectStorageError("S3 client not initialized")
        clean_key = key.lstrip("/\\")
        try:
            self.s3_client.delete_object(Bucket=bucket, Key=clean_key)
            return True
        except Exception:
            return False

    def object_exists(self, bucket: str, key: str) -> bool:
        if not self.s3_client:
            return False
        clean_key = key.lstrip("/\\")
        try:
            self.s3_client.head_object(Bucket=bucket, Key=clean_key)
            return True
        except Exception:
            return False

    def generate_presigned_url(self, bucket: str, key: str, expires_in: int = 3600) -> str:
        if not self.s3_client:
            raise ObjectStorageError("S3 client not initialized")
        clean_key = key.lstrip("/\\")
        return str(
            self.s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": clean_key},
                ExpiresIn=expires_in,
            )
        )


def get_storage_service() -> ObjectStorageService:
    """Factory function returning configured storage service."""
    settings = get_settings()
    if settings.storage_driver.lower() == "s3":
        return S3StorageDriver(
            region_name=settings.s3_region_name,
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
    return LocalStorageDriver(root_dir=settings.storage_local_root)


default_storage_service = get_storage_service()
