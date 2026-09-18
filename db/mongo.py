"""MongoDB Trace Persistence Service for unstructured verification pipeline execution traces.

Governing Specifications:
- PRD.md §FR-AUD-01, §FR-AUD-04, §14
- Technical_Architecture.md §7.2, §8.3, §8.4
- Security_Access.md §1.3, §4.3, §5, §9.1
- Testing_Strategy.md §5.5, §5.9, §7.1
"""

import asyncio
import re
import time
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from shared.config import get_settings
from shared.logging import get_logger

logger = get_logger("mongo_persistence")
settings = get_settings()

_SAFE_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-]+$")


class MongoPersistenceError(RuntimeError):
    """Raised when authoritative MongoDB trace persistence fails."""

    pass


class MongoDuplicateTraceError(MongoPersistenceError):
    """Raised when a verification trace document already exists for the session."""

    pass


def _validate_identifier(name: str, value: Any, max_length: int = 64) -> str:
    """Validate that an identifier is a strict, non-empty, safe alphanumeric string.

    Guards against NoSQL injection, type juggling, and malformed namespace routing.
    Rejects dicts, lists, None, non-strings, and strings containing special characters.
    """
    if not isinstance(value, str):
        raise TypeError(f"Expected string for {name}, got {type(value).__name__}")
    value = value.strip()
    if not value:
        raise ValueError(f"{name} cannot be empty")
    if len(value) > max_length:
        raise ValueError(f"{name} exceeds maximum length of {max_length} characters")
    if not _SAFE_ID_REGEX.match(value):
        raise ValueError(f"{name} contains invalid characters; must match {_SAFE_ID_REGEX.pattern}")
    return str(value)


def _to_bson_compatible(val: Any) -> Any:
    """Recursively convert Pydantic models, dataclasses, enums, sets, and mappings to BSON-safe types."""
    if isinstance(val, Enum):
        return val.value
    if hasattr(val, "model_dump") and callable(val.model_dump):
        return _to_bson_compatible(val.model_dump())
    if hasattr(val, "dict") and callable(val.dict):
        return _to_bson_compatible(val.dict())
    if isinstance(val, dict):
        return {str(k): _to_bson_compatible(v) for k, v in val.items()}
    if isinstance(val, (list, tuple, set)):
        return [_to_bson_compatible(item) for item in val]
    if isinstance(val, (str, int, float, bool, bytes, datetime)) or val is None:
        return val
    if hasattr(val, "__dict__") and not isinstance(val, type):
        return {str(k): _to_bson_compatible(v) for k, v in val.__dict__.items() if not k.startswith("_")}
    return str(val)


class MongoTraceService:
    """Production MongoDB service managing verification traces and tenant isolation."""

    def __init__(
        self,
        uri: str | None = None,
        db_name: str | None = None,
    ) -> None:
        self._uri = uri
        self._db_name = db_name
        self._client: AsyncIOMotorClient[Any] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ensured_indexes: set[str] = set()

    @property
    def uri(self) -> str:
        return self._uri or settings.mongo_uri

    @property
    def db_name(self) -> str:
        return self._db_name or settings.mongo_db

    def get_client(self) -> AsyncIOMotorClient[Any]:
        """Return cached async Motor client, initializing or re-binding if the event loop changed."""
        current_loop: asyncio.AbstractEventLoop | None = None
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

        need_new_client = self._client is None or (
            self._loop is not None
            and (self._loop.is_closed() or (current_loop is not None and self._loop != current_loop))
        )

        if need_new_client:
            if self._client is not None:
                try:
                    self._client.close()
                except Exception:
                    pass
            self._client = AsyncIOMotorClient(
                self.uri,
                serverSelectionTimeoutMS=2000,
                connectTimeoutMS=2000,
                socketTimeoutMS=5000,
            )
            self._loop = current_loop
            self._ensured_indexes.clear()

        assert self._client is not None
        return self._client

    def get_database(self) -> AsyncIOMotorDatabase[Any]:
        """Return the target application database."""
        client = self.get_client()
        return client[self.db_name]

    def get_collection_name(self, tenant_id: str) -> str:
        """Derive the collection name enforcing strict identifier validation.

        Mandated physical architecture: `traces_{tenant_id}` per Security_Access.md §9.1
        and Testing_Strategy.md §5.9 (see docs/adr/0001_mongodb_trace_collection_architecture.md).
        """
        valid_tenant = _validate_identifier("tenant_id", tenant_id)
        return f"traces_{valid_tenant}"

    def get_tenant_collection(self, tenant_id: str) -> AsyncIOMotorCollection[Any]:
        """Return the collection for the tenant, applying physical namespace routing."""
        coll_name = self.get_collection_name(tenant_id)
        db = self.get_database()
        return db[coll_name]

    async def ensure_indexes(self, tenant_id: str) -> None:
        """Ensure required production indexes exist on the tenant collection."""
        valid_tenant = _validate_identifier("tenant_id", tenant_id)
        coll = self.get_tenant_collection(valid_tenant)
        coll_name = coll.name

        if coll_name in self._ensured_indexes:
            return

        ttl_seconds = settings.mongo_retention_days * 86400  # 90 days = 7776000s

        try:
            await coll.create_index([("session_id", 1)], unique=True, name="idx_session_id_unique")
            await coll.create_index([("trace_id", 1)], name="idx_trace_id")
            await coll.create_index([("created_at", 1)], expireAfterSeconds=ttl_seconds, name="idx_created_at_ttl")
            await coll.create_index([("created_at", -1)], name="idx_created_at_desc")

            self._ensured_indexes.add(coll_name)
            logger.info("Ensured MongoDB indexes on collection", collection=coll_name, tenant_id=valid_tenant)
        except Exception as exc:
            logger.error("Failed to ensure MongoDB indexes", collection=coll_name, error=str(exc))
            raise MongoPersistenceError(f"Failed to ensure MongoDB indexes for collection {coll_name}: {exc}") from exc

    async def persist_verification_trace(self, tenant_id: str, trace_data: dict[str, Any]) -> str:
        """Persist a deep, unstructured verification trace document.

        Server-owned fields (tenant_id, session_id, trace_id, created_at) are constructed
        explicitly from verified server state and cannot be spoofed by callers.
        """
        valid_tenant = _validate_identifier("tenant_id", tenant_id)
        raw_session_id = trace_data.get("session_id")
        session_id = _validate_identifier("session_id", raw_session_id)
        raw_trace_id = trace_data.get("trace_id", "unknown")
        trace_id = _validate_identifier("trace_id", raw_trace_id)

        await self.ensure_indexes(valid_tenant)
        coll = self.get_tenant_collection(valid_tenant)

        created_at = trace_data.get("created_at")
        if not isinstance(created_at, datetime):
            created_at = datetime.now(UTC)
        elif created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)

        document: dict[str, Any] = {
            "session_id": session_id,
            "tenant_id": valid_tenant,
            "trace_id": trace_id,
            "model_id": trace_data.get("model_id", "unknown"),
            "raw_prompt": trace_data.get("raw_prompt", ""),
            "raw_response": trace_data.get("raw_response", ""),
            "verified_response": trace_data.get("verified_response", ""),
            "hrs_result": trace_data.get("hrs_result", {}),
            "claims": trace_data.get("claims", []),
            "evidence_chunks": trace_data.get("evidence_chunks", []),
            "correction_metadata": trace_data.get("correction_metadata", {}),
            "execution_metadata": trace_data.get("execution_metadata", {}),
            "pii_metadata": trace_data.get("pii_metadata", {"pii_flagged": False, "detected_counts": {}}),
            "created_at": created_at,
        }

        bson_document = _to_bson_compatible(document)

        try:
            await coll.insert_one(bson_document)
            logger.info(
                "Persisted verification trace to MongoDB",
                session_id=session_id,
                tenant_id=valid_tenant,
                collection=coll.name,
            )
            return session_id
        except DuplicateKeyError as dup_exc:
            logger.warning(
                "MongoDB duplicate trace detected; document already exists for session",
                session_id=session_id,
                tenant_id=valid_tenant,
            )
            raise MongoDuplicateTraceError(
                f"MongoDB duplicate key / trace for session {session_id} in collection {coll.name}: "
                f"unique index violation ({dup_exc})"
            ) from dup_exc
        except Exception as exc:
            logger.error(
                "MongoDB trace insertion failed",
                session_id=session_id,
                tenant_id=valid_tenant,
                error=str(exc),
            )
            raise MongoPersistenceError(f"MongoDB persistence failed for session {session_id}: {exc}") from exc

    async def get_trace_by_session_id(self, tenant_id: str, session_id: str) -> dict[str, Any] | None:
        """Retrieve a trace by session_id with dual-layer tenant isolation."""
        valid_tenant = _validate_identifier("tenant_id", tenant_id)
        valid_session = _validate_identifier("session_id", session_id)

        coll = self.get_tenant_collection(valid_tenant)
        filter_query = {
            "session_id": {"$eq": valid_session},
            "tenant_id": {"$eq": valid_tenant},
        }

        try:
            doc = await coll.find_one(filter_query)
            if doc and "_id" in doc:
                doc["_id"] = str(doc["_id"])
            return doc
        except Exception as exc:
            logger.error("Failed to query MongoDB trace by session_id", session_id=valid_session, error=str(exc))
            raise MongoPersistenceError(f"MongoDB query failed: {exc}") from exc

    async def get_trace_by_trace_id(self, tenant_id: str, trace_id: str) -> dict[str, Any] | None:
        """Retrieve a trace by distributed trace_id with dual-layer tenant isolation."""
        valid_tenant = _validate_identifier("tenant_id", tenant_id)
        valid_trace = _validate_identifier("trace_id", trace_id)

        coll = self.get_tenant_collection(valid_tenant)
        filter_query = {
            "trace_id": {"$eq": valid_trace},
            "tenant_id": {"$eq": valid_tenant},
        }

        try:
            doc = await coll.find_one(filter_query)
            if doc and "_id" in doc:
                doc["_id"] = str(doc["_id"])
            return doc
        except Exception as exc:
            logger.error("Failed to query MongoDB trace by trace_id", trace_id=valid_trace, error=str(exc))
            raise MongoPersistenceError(f"MongoDB query failed: {exc}") from exc

    async def delete_trace(self, tenant_id: str, session_id: str) -> bool:
        """Compensating deletion of a trace document upon PostgreSQL commit failure."""
        valid_tenant = _validate_identifier("tenant_id", tenant_id)
        valid_session = _validate_identifier("session_id", session_id)

        coll = self.get_tenant_collection(valid_tenant)
        filter_query = {
            "session_id": {"$eq": valid_session},
            "tenant_id": {"$eq": valid_tenant},
        }

        try:
            result = await coll.delete_one(filter_query)
            deleted = bool(result.deleted_count > 0)
            logger.info(
                "Executed compensating delete on MongoDB trace",
                session_id=valid_session,
                tenant_id=valid_tenant,
                deleted=deleted,
            )
            return deleted
        except Exception as exc:
            logger.critical(
                "Compensating MongoDB delete failed! Potential orphaned document",
                session_id=valid_session,
                tenant_id=valid_tenant,
                error=str(exc),
            )
            raise MongoPersistenceError(f"Failed to delete MongoDB trace: {exc}") from exc

    async def check_health(self) -> dict[str, Any]:
        """Perform ping command to verify MongoDB connectivity and latency."""
        t0 = time.time()
        try:
            db = self.get_database()
            res = await db.command("ping")
            latency_ms = round((time.time() - t0) * 1000, 2)
            is_ok = bool(res.get("ok") == 1.0 or res.get("ok") == 1)
            return {
                "status": "pass" if is_ok else "fail",
                "latency_ms": latency_ms,
                "database": self.db_name,
            }
        except Exception as exc:
            latency_ms = round((time.time() - t0) * 1000, 2)
            return {
                "status": "fail",
                "latency_ms": latency_ms,
                "error": str(exc),
            }

    def close(self) -> None:
        """Close Motor client connection pool."""
        if self._client is not None:
            self._client.close()
            self._client = None
            self._loop = None
            self._ensured_indexes.clear()


default_mongo_trace_service = MongoTraceService()


def reset_default_mongo_service(uri: str | None = None, db_name: str | None = None) -> MongoTraceService:
    """Reset and reconfigure the global default_mongo_trace_service instance."""
    global default_mongo_trace_service
    default_mongo_trace_service.close()
    default_mongo_trace_service = MongoTraceService(uri=uri, db_name=db_name)
    return default_mongo_trace_service
