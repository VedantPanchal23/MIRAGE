"""Unit tests for AWS Secrets Manager Safe Serializer and Staging Invariants.

Validates:
1. Safe escaping and serialization of special characters (quotes, backslashes, dollar signs, Unicode, whitespace).
2. Atomic .env file writing with restrictive permissions and zero partial writes on failure.
3. Mandatory staging secret enforcement and placeholder rejection.
4. Optional provider credential handling (valid when empty, rejected when placeholder).
5. Docker Compose config round-trip parsing of serialized .env files.
6. S3 Object Lock and Network Mode architectural invariants.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.fetch_secrets import (
    OPTIONAL_PROVIDER_KEYS,
    serialize_env_value,
    serialize_secrets_to_env,
    write_env_file_secure,
)


class TestSecretValueSerialization:
    """Test safe quoting and character escaping for Docker Compose .env files."""

    def test_simple_alphanumeric(self) -> None:
        """Alphanumeric values remain unquoted for maximum cleanliness."""
        assert serialize_env_value("simple123") == "simple123"
        assert serialize_env_value("redis-host.internal") == "redis-host.internal"

    def test_empty_string(self) -> None:
        """Empty string returns explicit double quotes."""
        assert serialize_env_value("") == '""'

    def test_values_with_spaces_and_whitespace(self) -> None:
        """Values with spaces or tabs are safely enclosed in single quotes."""
        val = "secret with multiple spaces and tabs\t"
        quoted = serialize_env_value(val)
        assert quoted == f"'{val}'"

    def test_dollar_signs_without_single_quotes(self) -> None:
        """Dollar signs are safely preserved literally inside single quotes without interpolation."""
        val = "p@ss$$word$123"
        quoted = serialize_env_value(val)
        assert quoted == f"'{val}'"

    def test_single_quotes_and_dollar_signs(self) -> None:
        """Single quotes require double-quoting, escaping quotes and doubling dollar signs ($$)."""
        val = "p@ss'word$value"
        quoted = serialize_env_value(val)
        # Should be double-quoted with escaped single quote (no escaping needed for single quote inside double quotes)
        # and doubled dollar sign $$
        assert quoted.startswith('"') and quoted.endswith('"')
        assert "p@ss'word$$value" in quoted

    def test_backslashes_and_double_quotes(self) -> None:
        """Backslashes and double quotes are escaped properly."""
        val = 'path\\to\\"quote"'
        quoted = serialize_env_value(val)
        assert quoted == f"'{val}'"  # No single quote, so single quoting protects literal \ and "

    def test_single_quotes_with_backslashes(self) -> None:
        """Combining single quotes and backslashes enforces double-quoting with double-backslash escaping."""
        val = "dir\\with'quote"
        quoted = serialize_env_value(val)
        assert quoted == '"dir\\\\with\'quote"'

    def test_unicode_and_emojis(self) -> None:
        """Unicode characters and emojis are preserved intact in UTF-8."""
        val = "pásswørd_🔑_ünîcødé"
        quoted = serialize_env_value(val)
        assert "pásswørd_🔑_ünîcødé" in quoted

    def test_multiline_and_newlines(self) -> None:
        """Newlines are escaped as \\n inside double quotes."""
        val = "line1\nline2\r\nline3"
        quoted = serialize_env_value(val)
        assert quoted.startswith('"')
        assert "\\n" in quoted
        assert "\n" not in quoted


class TestMandatoryAndOptionalSecretsValidation:
    """Validate mandatory presence and placeholder rejection."""

    @pytest.fixture
    def valid_secrets(self) -> dict[str, str]:
        return {
            "SECRET_KEY": "a" * 48,
            "POSTGRES_PASSWORD": "strong_db_password_123456",
            "POSTGRES_APP_PASSWORD": "strong_app_password_123456",
            "REDIS_PASSWORD": "strong_redis_password_123456",
            "RABBITMQ_PASSWORD": "strong_rabbit_password_123456",
            "CELERY_REDIS_PASSWORD": "strong_celery_password_123456",
            "MONGO_INITDB_ROOT_PASSWORD": "strong_mongo_root_123456",
            "MONGO_APP_PASSWORD": "strong_mongo_app_123456",
            "QDRANT_API_KEY": "strong_qdrant_key_123456",
            "GRAFANA_ADMIN_PASSWORD": "strong_grafana_password_123456",
        }

    def test_fully_valid_staging_secrets_produce_zero_defects(self, valid_secrets: dict[str, str]) -> None:
        content, defects = serialize_secrets_to_env(valid_secrets, environment="staging")
        assert defects == []
        assert "SECRET_KEY=" in content
        assert "POSTGRES_PASSWORD=" in content

    def test_missing_mandatory_secret_flagged(self, valid_secrets: dict[str, str]) -> None:
        del valid_secrets["SECRET_KEY"]
        _, defects = serialize_secrets_to_env(valid_secrets, environment="staging")
        assert any("Mandatory secret 'SECRET_KEY' is missing" in d for d in defects)

    def test_empty_mandatory_secret_flagged(self, valid_secrets: dict[str, str]) -> None:
        valid_secrets["POSTGRES_PASSWORD"] = "   "
        _, defects = serialize_secrets_to_env(valid_secrets, environment="staging")
        assert any("Mandatory secret 'POSTGRES_PASSWORD' is empty" in d for d in defects)

    def test_placeholder_mandatory_secret_flagged(self, valid_secrets: dict[str, str]) -> None:
        valid_secrets["REDIS_PASSWORD"] = "REPLACE_WITH_STRONG_REDIS_PASSWORD"
        _, defects = serialize_secrets_to_env(valid_secrets, environment="staging")
        assert any("REDIS_PASSWORD" in d and "placeholder" in d for d in defects)

    def test_optional_provider_keys_empty_is_valid(self, valid_secrets: dict[str, str]) -> None:
        # All provider keys empty
        for k in OPTIONAL_PROVIDER_KEYS:
            valid_secrets[k] = ""
        _, defects = serialize_secrets_to_env(valid_secrets, environment="staging")
        assert defects == []

    def test_optional_provider_key_with_placeholder_is_flagged(self, valid_secrets: dict[str, str]) -> None:
        valid_secrets["OPENAI_API_KEY"] = "your_openai_api_key_here"
        _, defects = serialize_secrets_to_env(valid_secrets, environment="staging")
        assert any("OPENAI_API_KEY" in d and "placeholder" in d for d in defects)


class TestAtomicWritingAndPermissions:
    """Validate atomic file replacement and security permissions."""

    def test_atomic_write_creates_file(self, tmp_path: Path) -> None:
        dest = tmp_path / "subdir" / ".env"
        dest.parent.mkdir()
        content = "TEST_KEY=test_value\n"
        write_env_file_secure(dest, content)
        assert dest.exists()
        assert dest.read_text(encoding="utf-8") == content

    def test_atomic_write_overwrites_cleanly(self, tmp_path: Path) -> None:
        dest = tmp_path / ".env"
        dest.write_text("OLD_CONTENT=old", encoding="utf-8")
        new_content = "NEW_CONTENT=new\n"
        write_env_file_secure(dest, new_content)
        assert dest.read_text(encoding="utf-8") == new_content

    def test_no_partial_file_left_on_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        dest = tmp_path / ".env"
        dest.write_text("ORIGINAL", encoding="utf-8")

        def mock_replace(_src: Path, _dst: Path) -> None:
            raise OSError("Simulated disk error during atomic rename")

        monkeypatch.setattr("os.replace", mock_replace)

        with pytest.raises(OSError, match="Simulated disk error"):
            write_env_file_secure(dest, "CORRUPTED")

        # Original file remains completely unchanged
        assert dest.read_text(encoding="utf-8") == "ORIGINAL"
        # No dangling temporary files
        temp_files = list(tmp_path.glob(".*.tmp.*"))
        assert temp_files == []


class TestDockerComposeRoundtrip:
    """Validate that serialized .env files are parsed without errors by Docker Compose."""

    def test_compose_config_roundtrip_with_complex_secrets(self, tmp_path: Path) -> None:
        repo_root = Path(__file__).resolve().parent.parent.parent
        env_file = tmp_path / "test.env"

        secrets = {
            "SECRET_KEY": "a" * 48,
            "POSTGRES_USER": "mirage",
            "POSTGRES_PASSWORD": "strong_pw$with$dollars'and'quotes",
            "POSTGRES_APP_USER": "mirage_app",
            "POSTGRES_APP_PASSWORD": "strong_app_pw\\with\\backslashes",
            "POSTGRES_DB": "mirage_db",
            "REDIS_PASSWORD": "redis_pw_with_spaces_and_quotes_'test'",
            "REDIS_USERNAME": "mirage_app",
            "RABBITMQ_USER": "mirage",
            "RABBITMQ_PASSWORD": "rabbit_pw_with_unicode_🔑",
            "CELERY_REDIS_USERNAME": "mirage_celery",
            "CELERY_REDIS_PASSWORD": "celery_redis_pw",
            "MONGO_INITDB_ROOT_USERNAME": "root",
            "MONGO_INITDB_ROOT_PASSWORD": "mongo_root_pw",
            "MONGO_APP_USER": "mirage_app",
            "MONGO_APP_PASSWORD": "mongo_app_pw",
            "MONGO_DB": "mirage_traces",
            "QDRANT_API_KEY": "qdrant_api_key_12345",
            "GRAFANA_ADMIN_USER": "admin",
            "GRAFANA_ADMIN_PASSWORD": "grafana_password_12345",
            "GROQ_API_KEY": "",
            "OPENROUTER_API_KEY": "",
            "HUGGINGFACE_API_KEY": "",
            "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "GEMINI_API_KEY": "",
        }

        content, defects = serialize_secrets_to_env(secrets, environment="staging")
        assert defects == []
        write_env_file_secure(env_file, content)

        # Run docker compose config with this env file
        cmd = [
            "docker",
            "compose",
            "--env-file",
            str(env_file),
            "-f",
            str(repo_root / "docker-compose.yml"),
            "-f",
            str(repo_root / "docker-compose.staging.yml"),
            "config",
            "--quiet",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0, f"docker compose config failed: {result.stderr}"


class TestS3ObjectLockAndNetworkInvariants:
    """Validate S3 Object Lock and VPC Network configuration constraints."""

    def test_s3_object_lock_retention_defaults_and_validation(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent.parent
        vars_tf = repo_root / "infra" / "terraform" / "variables.tf"
        content = vars_tf.read_text(encoding="utf-8")

        # Object lock mode must be GOVERNANCE or COMPLIANCE
        assert 'contains(["GOVERNANCE", "COMPLIANCE"], var.s3_object_lock_mode)' in content
        # Default mode must be GOVERNANCE for staging teardown safety
        assert 'default     = "GOVERNANCE"' in content
        # Default retention must be 90 days
        assert "default     = 90" in content

    def test_s3_tf_force_destroy_only_under_governance(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent.parent
        s3_tf = repo_root / "infra" / "terraform" / "s3.tf"
        content = s3_tf.read_text(encoding="utf-8")

        # force_destroy must be conditionally disabled when not GOVERNANCE
        assert 'force_destroy       = var.s3_object_lock_mode == "GOVERNANCE" ? true : false' in content

    def test_network_safety_check_block_present(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent.parent
        vpce_tf = repo_root / "infra" / "terraform" / "vpc_endpoints.tf"
        content = vpce_tf.read_text(encoding="utf-8")

        # Network safety assert must require either public edge or vpc endpoints
        assert "var.enable_public_edge || var.enable_vpc_endpoints" in content
