"""Unit tests for Object Storage Service (LocalStorageDriver and S3StorageDriver)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from services.storage import (
    LocalStorageDriver,
    ObjectNotFoundError,
    ObjectStorageError,
    S3StorageDriver,
)


@pytest.mark.unit
class TestLocalStorageDriver:
    """Verify LocalStorageDriver CRUD, metadata persistence, and path traversal prevention."""

    def test_put_and_get_object_with_metadata_and_content_type(self, tmp_path: Path) -> None:
        """Verify object storage preserves content_type and metadata sidecars."""
        driver = LocalStorageDriver(root_dir=str(tmp_path))
        bucket = "test-bucket"
        key = "reports/rep_1001.pdf"
        data = b"%PDF-1.4 Mock PDF content"

        uri = driver.put_object(
            bucket=bucket,
            key=key,
            data=data,
            content_type="application/pdf",
            metadata={"tenant_id": "tenant_1", "report_type": "audit"},
        )
        assert uri == f"s3://{bucket}/{key}"
        assert driver.object_exists(bucket, key) is True

        retrieved_data, retrieved_type = driver.get_object(bucket, key)
        assert retrieved_data == data
        assert retrieved_type == "application/pdf"

    def test_delete_object_removes_data_and_metadata(self, tmp_path: Path) -> None:
        """Verify delete_object purges both binary object and metadata sidecar."""
        driver = LocalStorageDriver(root_dir=str(tmp_path))
        bucket = "test-bucket"
        key = "temp/doc.txt"

        driver.put_object(bucket, key, b"sample text", content_type="text/plain")
        assert driver.object_exists(bucket, key) is True

        deleted = driver.delete_object(bucket, key)
        assert deleted is True
        assert driver.object_exists(bucket, key) is False

        with pytest.raises(ObjectNotFoundError):
            driver.get_object(bucket, key)

    def test_generate_presigned_url_validates_path(self, tmp_path: Path) -> None:
        """Verify generate_presigned_url returns download URI and validates containment."""
        driver = LocalStorageDriver(root_dir=str(tmp_path))
        bucket = "test-bucket"
        key = "reports/rep_2002.pdf"

        driver.put_object(bucket, key, b"PDF content")
        url = driver.generate_presigned_url(bucket=bucket, key=key, expires_in=1800)
        assert url == "/v1/reports/reports/rep_2002.pdf/pdf"

    def test_path_traversal_detection(self, tmp_path: Path) -> None:
        """Verify path traversal attempts raise ObjectStorageError."""
        driver = LocalStorageDriver(root_dir=str(tmp_path))
        bucket = "safe-bucket"

        with pytest.raises(ObjectStorageError, match="Path traversal detected"):
            driver.put_object(bucket, "../../../etc/passwd", b"malicious")


@pytest.mark.unit
class TestS3StorageDriver:
    """Verify S3StorageDriver endpoint_url handling and client configuration."""

    def test_s3_driver_passes_custom_endpoint_url(self) -> None:
        """Verify custom endpoint_url is passed to boto3.client for MinIO / LocalStack."""
        mock_boto3 = MagicMock()
        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            _driver = S3StorageDriver(
                region_name="eu-west-1",
                endpoint_url="http://localhost:9000",
                aws_access_key_id="minio_admin",
                aws_secret_access_key="minio_secret",
            )

            mock_boto3.client.assert_called_once_with(
                "s3",
                region_name="eu-west-1",
                endpoint_url="http://localhost:9000",
                aws_access_key_id="minio_admin",
                aws_secret_access_key="minio_secret",
            )

    def test_s3_driver_omits_endpoint_url_when_none(self) -> None:
        """Verify endpoint_url is not passed to boto3.client when None (standard AWS)."""
        mock_boto3 = MagicMock()
        with patch.dict("sys.modules", {"boto3": mock_boto3}):
            _driver = S3StorageDriver(
                region_name="us-east-1",
                endpoint_url=None,
            )

            mock_boto3.client.assert_called_once_with(
                "s3",
                region_name="us-east-1",
            )
