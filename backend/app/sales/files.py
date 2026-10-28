import hashlib
import io
import json
import logging
import subprocess
import sys
from uuid import uuid4

from sqlalchemy import select

from app.auth.models import User
from app.auth.service import now
from app.core.errors import AppError
from app.crm.repository import CRMRepository
from app.sales.models import CloseEvidence, Opportunity, StoredObject
from app.sales.service import SalesService

MAX_BYTES = 20 * 1024 * 1024


def inspect_pdf(payload):
    if not payload or len(payload) > MAX_BYTES:
        raise AppError(413, "FILE_TOO_LARGE", "PDF必须非空且不超过20 MiB。")
    if not payload.startswith(b"%PDF-"):
        raise AppError(422, "FILE_TYPE_INVALID", "仅接受有效PDF原件。")
    # Isolate malformed/untrusted PDF parsing and bound its wall-clock time.
    probe = (
        "import io,sys,logging; logging.disable(100); from pypdf import PdfReader; "
        "r=PdfReader(io.BytesIO(sys.stdin.buffer.read()), strict=True); "
        "assert not r.is_encrypted; n=len(r.pages); assert 1<=n<=100; print(n)"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-c", probe],
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=8,
            check=False,
        )
        if result.returncode:
            raise ValueError
        return int(result.stdout.strip())
    except (ValueError, subprocess.TimeoutExpired):
        raise AppError(422, "FILE_TYPE_INVALID", "PDF无效、加密、超过100页或解析超时。") from None


def public_object(entity):
    return {
        "stored_object_id": entity.id,
        "status": entity.status,
        "sha256": entity.sha256,
        "size_bytes": entity.size_bytes,
        "pages": entity.pages,
    }


class EvidenceFiles(SalesService):
    def upload(self, entity_id, payload, filename, request_token, identity, storage):
        pages = inspect_pdf(payload)
        digest = hashlib.sha256(payload).hexdigest()
        with self.db.transaction() as session:
            repository = CRMRepository(session)
            actor = self.users(repository, identity)
            _, opportunity = self.locked(repository, entity_id)
            self.authorize(actor, opportunity)
            self.open(opportunity)
            stored = session.scalar(
                select(StoredObject)
                .where(
                    StoredObject.uploaded_by == actor.id,
                    StoredObject.request_token == request_token,
                )
                .with_for_update()
            )
            if stored:
                if stored.sha256 != digest or stored.opportunity_id != entity_id:
                    raise AppError(409, "IDEMPOTENCY_KEY_REUSED", "上传请求标识已用于不同文件。")
                if stored.status == "AVAILABLE":
                    return public_object(stored)
                raise AppError(
                    409, "UPLOAD_INCOMPLETE", "此前上传尚未完成，请保留该标识并联系管理员核对。"
                )
            stored = StoredObject(
                id=str(uuid4()),
                opportunity_id=entity_id,
                bucket=storage.bucket,
                object_key=f"evidence/{uuid4().hex}.pdf",
                original_name=filename[:255],
                mime_type="application/pdf",
                size_bytes=len(payload),
                sha256=digest,
                pages=pages,
                purpose="CLOSE_EVIDENCE",
                status="UPLOADING",
                uploaded_by=actor.id,
                request_token=request_token,
                created_at=now(),
            )
            session.add(stored)
            session.flush()
            stored_id, bucket, object_key = stored.id, stored.bucket, stored.object_key
        # External I/O occurs after reservation commit, outside every DB transaction.
        try:
            uploaded = storage.client.put_object(
                bucket,
                object_key,
                io.BytesIO(payload),
                len(payload),
                content_type="application/pdf",
                metadata={"sha256": digest},
            )
            stat = storage.client.stat_object(bucket, object_key, version_id=uploaded.version_id)
            if stat.size != len(payload):
                raise ValueError("storage size mismatch")
        except Exception as exc:
            logging.getLogger("esc").warning(
                "evidence_storage_failed_%s_%s", type(exc).__name__, getattr(exc, "code", "unknown")
            )
            raise AppError(
                503, "STORAGE_UNAVAILABLE", "原件上传失败，不能作为成交证据。", True
            ) from None
        with self.db.transaction() as session:
            repository = CRMRepository(session)
            actor = self.users(repository, identity)
            _, opportunity = self.locked(repository, entity_id)
            self.authorize(actor, opportunity)
            self.open(opportunity)
            stored = self.required(repository, StoredObject, stored_id, lock=True)
            stored.status = "AVAILABLE"
            stored.storage_version_id = uploaded.version_id
            session.flush()
            return public_object(stored)

    def download(self, evidence_id, identity, storage):
        # Full CRM visibility per Q03; the protected route authenticates each request.
        with self.db.transaction() as session:
            repository = CRMRepository(session)
            user = self.required(repository, User, identity.user.id)
            if not user.is_active:
                raise AppError(401, "SESSION_EXPIRED", "会话已失效。")
            evidence = self.required(repository, CloseEvidence, evidence_id)
            self.required(
                repository,
                Opportunity,
                evidence.opportunity_id,
            )
            stored = self.required(repository, StoredObject, evidence.stored_object_id)
            if stored.status != "AVAILABLE":
                raise AppError(404, "SOURCE_UNAVAILABLE", "原件不可用。")
            bucket, object_key, version_id, expected = (
                stored.bucket,
                stored.object_key,
                stored.storage_version_id,
                stored.sha256,
            )
        try:
            response = storage.client.get_object(bucket, object_key, version_id=version_id)
            try:
                payload = response.read(MAX_BYTES + 1)
            finally:
                response.close()
                response.release_conn()
            if len(payload) > MAX_BYTES or hashlib.sha256(payload).hexdigest() != expected:
                raise ValueError("integrity mismatch")
            return payload
        except Exception:
            raise AppError(
                503, "STORAGE_UNAVAILABLE", "原件暂不可用或完整性校验失败。", True
            ) from None


class UploadBodyLimit:
    """Bound multipart bodies, including chunked transfer, before parser spooling."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").endswith("/evidence-files"):
            return await self.app(scope, receive, send)
        messages, total = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            total += len(message.get("body", b""))
            if total > MAX_BYTES + 65536:
                body = json.dumps(
                    {
                        "error": {
                            "code": "FILE_TOO_LARGE",
                            "message": "PDF upload exceeds limit",
                            "retryable": False,
                        },
                        "request_id": scope.get("state", {}).get("request_id", str(uuid4())),
                    }
                ).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"cache-control", b"no-store"),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
            messages.append(message)
            if not message.get("more_body", False):
                break
        cursor = 0

        async def replay():
            nonlocal cursor
            if cursor < len(messages):
                message = messages[cursor]
                cursor += 1
                return message
            return await receive()

        await self.app(scope, replay, send)
