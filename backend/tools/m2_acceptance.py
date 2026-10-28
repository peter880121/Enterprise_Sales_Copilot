"""Explicit isolated real-API acceptance. Never falls back to .env or creates a database."""

import io
import json
import os
import secrets
from pathlib import Path
from uuid import uuid4

import httpx
from minio import Minio
from minio.error import S3Error
from pypdf import PdfWriter
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from app.auth.models import User
from app.auth.security import hash_password
from app.auth.service import now
from app.core.config import Settings
from app.crm.models import AuditEvent
from app.db import Database
from app.sales.models import Opportunity, StoredObject


def pdf(pages=1, attachment=0):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=100, height=100)
    if attachment:
        writer.add_attachment("synthetic.txt", b"x" * attachment)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


class Acceptance:
    def __init__(self):
        self.directory = Path(os.environ["M2_EVIDENCE_DIR"])
        self.base = os.environ["M2_BASE_URL"]
        url = make_url(os.environ["TEST_DATABASE_URL"])
        if not (url.database or "").startswith("esc_m1_test_m2"):
            raise RuntimeError("Explicit isolated M2 test database required")
        self.db = Database(
            Settings(
                _env_file=None,
                app_env="test",
                database_url=str_url(url),
                csrf_signing_key=os.environ["SESSION_SECRET"],
                minio_endpoint="localhost",
                minio_access_key="synthetic",
                minio_secret_key="synthetic-secret",
            )
        )
        self.checks = []
        seed_url = make_url(os.environ["TEST_SEED_DATABASE_URL"])
        if (seed_url.host, seed_url.port, seed_url.database) != (
            url.host,
            url.port,
            url.database,
        ) or seed_url.username == url.username:
            raise RuntimeError("Separate fixture identity on the same isolated database required")
        self.seed = Database(Settings(_env_file=None, database_url=str_url(seed_url)))
        self.clients = {}
        self.users = {}
        self.password = secrets.token_urlsafe(28)
        self.resources = {
            "database": url.database,
            "opportunities": [],
            "evidence": [],
            "accounts": [],
        }

    def check(self, name, ok, details=None):
        item = {"check": name, "status": "PASS" if ok else "FAIL"}
        if details is not None:
            item["details"] = details
        self.checks.append(item)
        (self.directory / "api-checks.json").write_text(json.dumps(self.checks, indent=2))
        if not ok:
            raise AssertionError(name)

    def data(self, response, status=200):
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        self.check(
            "http_" + response.request.method + "_" + response.request.url.path,
            response.status_code == status,
            {
                "status": response.status_code,
                "error_code": payload.get("error", {}).get("code"),
            },
        )
        return payload["data"]

    def login(self, role):
        client = httpx.Client(base_url=self.base, timeout=45, trust_env=False)
        result = self.data(
            client.post(
                "/api/v1/auth/login",
                headers={"Origin": self.base},
                json={"email": self.users[role]["email"], "password": self.password},
            )
        )
        client.headers.update({"Origin": self.base, "X-CSRF-Token": result["csrf_token"]})
        self.clients[role] = client
        self.check("nginx_me_" + role, client.get("/api/v1/auth/me").status_code == 200)

    def setup(self):
        with self.seed.transaction() as session:
            version = str(session.scalar(text("SELECT VERSION()")))
            self.check("actual_mysql_8_4", version.startswith("8.4."), {"version": version})
            self.resources["mysql_version"] = version
            for role in ["SALES_REP", "OTHER_REP", "SALES_MANAGER", "ADMIN", "READ_ONLY"]:
                uid, current = (str(uuid4()), now())
                email = "accept-" + uuid4().hex + "@example.test"
                self.users[role] = {"id": uid, "email": email}
                session.add(
                    User(
                        id=uid,
                        email=email,
                        email_normalized=email,
                        name="Synthetic acceptance " + role,
                        password_hash=hash_password(self.password),
                        role="SALES_REP" if role == "OTHER_REP" else role,
                        is_active=True,
                        version=1,
                        password_changed_at=current,
                        created_at=current,
                        updated_at=current,
                    )
                )
        for role in self.users:
            self.login(role)
        private = {"users": self.users, "password": self.password}
        (self.directory / "browser-private.json").write_text(json.dumps(private))
        (self.directory / "browser-synthetic.pdf").write_bytes(pdf())
        self.account = self.data(
            self.clients["SALES_MANAGER"].post(
                "/api/v1/accounts", json={"name": "Acceptance synthetic account " + uuid4().hex[:8]}
            ),
            201,
        )
        self.resources["accounts"].append(self.account["id"])

    def opportunity(self, amount=None, currency="CNY", owner="SALES_REP"):
        item = self.data(
            self.clients["SALES_MANAGER"].post(
                "/api/v1/opportunities",
                json={
                    "name": "Acceptance synthetic deal " + uuid4().hex[:8],
                    "account_id": self.account["id"],
                    "owner_id": self.users[owner]["id"],
                    "amount": amount,
                    "currency": currency,
                },
            ),
            201,
        )
        self.resources["opportunities"].append(item["id"])
        return item

    def state(self, oid):
        with self.db.transaction() as session:
            o = session.get(Opportunity, oid)
            audits = session.scalar(
                select(func.count()).select_from(AuditEvent).where(AuditEvent.entity_id == oid)
            )
            return (
                o.version,
                o.stage,
                o.probability,
                str(o.amount),
                o.currency,
                o.close_evidence_id,
                audits,
            )

    def reject(self, name, oid, operation, status, code):
        before = self.state(oid)
        response = operation()
        self.check(
            name,
            response.status_code == status
            and response.json()["error"]["code"] == code
            and (before == self.state(oid)),
            {
                "status": response.status_code,
                "error_code": response.json().get("error", {}).get("code"),
                "business_audit_unchanged": before == self.state(oid),
            },
        )

    def transition(self, item, stage, role="SALES_MANAGER", key=None, **extra):
        return self.clients[role].post(
            f"/api/v1/opportunities/{item['id']}/transitions",
            headers={"Idempotency-Key": key or str(uuid4())},
            json={
                "expected_version": item["version"],
                "target_stage": stage,
                "reason": "Synthetic acceptance",
                **extra,
            },
        )

    def evidence(
        self, item, role="SALES_MANAGER", amount="230000.00", kind="SIGNED_CONTRACT", payload=None
    ):
        payload = pdf() if payload is None else payload
        client = self.clients[role]
        stored = self.data(
            client.post(
                f"/api/v1/opportunities/{item['id']}/evidence-files",
                data={"request_token": str(uuid4())},
                files={"file": ("synthetic.pdf", payload, "application/pdf")},
            ),
            201,
        )
        proof = self.data(
            client.post(
                f"/api/v1/opportunities/{item['id']}/evidence",
                json={
                    "stored_object_id": stored["stored_object_id"],
                    "type": kind,
                    "reference_number": "SYNTHETIC-" + uuid4().hex[:8],
                    "customer_legal_name": "Synthetic entity",
                    "document_date": "2026-10-27",
                    "amount": amount,
                    "currency": item["currency"],
                    **(
                        {"approval_basis": "Synthetic pending approval"}
                        if kind == "OTHER_APPROVED"
                        else {}
                    ),
                },
            ),
            201,
        )
        self.resources["evidence"].append(proof["id"])
        return (proof, stored, payload)

    def review(self, proof, role="ADMIN"):
        return self.clients[role].post(
            f"/api/v1/evidence/{proof['id']}/review",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "expected_version": proof["version"],
                "decision": "VERIFY",
                "note": "Synthetic original checked by another authorized reviewer",
            },
        )

    def permissions(self):
        item = self.opportunity()
        oid = item["id"]
        reader = self.clients["OTHER_REP"]
        for path in [
            f"/accounts/{self.account['id']}",
            f"/opportunities/{oid}",
            f"/opportunities?q={item['name']}",
            f"/pipeline/summary?owner_id={self.users['SALES_REP']['id']}",
            f"/accounts/{self.account['id']}/contacts",
        ]:
            self.check(
                "rep_global_read_" + path.split("?")[0],
                reader.get("/api/v1" + path).status_code == 200,
            )
        for role in ["OTHER_REP", "READ_ONLY"]:
            self.reject(
                "reject_foreign_or_readonly_" + role,
                oid,
                lambda role=role: self.clients[role].patch(
                    f"/api/v1/opportunities/{oid}", json={"expected_version": 1, "amount": "1.00"}
                ),
                403,
                "FORBIDDEN",
            )
        self.reject(
            "illegal_initial_won",
            oid,
            lambda item=item: self.transition(item, "WON"),
            422,
            "INVALID_STAGE_TRANSITION",
        )
        self.reject(
            "probability_direct_override",
            oid,
            lambda: self.clients["SALES_REP"].patch(
                f"/api/v1/opportunities/{oid}", json={"expected_version": 1, "probability": 20}
            ),
            422,
            "FIELD_NOT_EDITABLE",
        )

    def close_cases(self):
        for amount in [None, "0.00", "250000.00"]:
            item = self.opportunity(amount)
            item = self.data(self.transition(item, "NEGOTIATION"))
            proof, _, payload = self.evidence(item)
            self.reject(
                "unverified_close_rejected",
                item["id"],
                lambda item=item, proof=proof: self.transition(
                    item, "WON", evidence_id=proof["id"]
                ),
                422,
                "EVIDENCE_INVALID",
            )
            self.reject(
                "manager_self_review",
                item["id"],
                lambda proof=proof: self.review(proof, "SALES_MANAGER"),
                403,
                "EVIDENCE_REVIEWER_CONFLICT",
            )
            self.reject(
                "rep_review_forbidden",
                item["id"],
                lambda proof=proof: self.review(proof, "SALES_REP"),
                403,
                "FORBIDDEN",
            )
            checked = self.data(self.review(proof))
            self.check(
                "independent_review_fields",
                checked["submitted_by"] == self.users["SALES_MANAGER"]["id"]
                and checked["reviewed_by"] == self.users["ADMIN"]["id"]
                and bool(checked["reviewed_at"])
                and (checked["status"] == "VERIFIED")
                and bool(checked["verification_note"]),
            )
            second, _, _ = self.evidence(item, amount="999.00")
            self.data(self.review(second))
            key = str(uuid4())
            won = self.data(self.transition(item, "WON", key=key, evidence_id=proof["id"]))
            self.check(
                "won_unknown_zero_or_different",
                won["amount"] == amount
                and won["actual_amount"] == "230000.00"
                and (won["close_evidence_id"] == proof["id"])
                and (won["probability"] == 100),
            )
            before = self.state(item["id"])
            replay = self.data(self.transition(item, "WON", key=key, evidence_id=proof["id"]))
            self.check(
                "lost_response_then_replay_once", replay == won and before == self.state(item["id"])
            )
            self.reject(
                "terminal_reselection",
                item["id"],
                lambda second=second, won=won: self.transition(
                    won, "WON", evidence_id=second["id"]
                ),
                422,
                "TERMINAL_OPPORTUNITY",
            )
            self.reject(
                "won_reopen_rejected",
                item["id"],
                lambda item=item, won=won: self.clients["SALES_MANAGER"].post(
                    f"/api/v1/opportunities/{item['id']}/reopen",
                    headers={"Idempotency-Key": str(uuid4())},
                    json={"expected_version": won["version"], "reason": "Synthetic"},
                ),
                422,
                "WON_REOPEN_NOT_ALLOWED",
            )
            self.reject(
                "terminal_patch_rejected",
                item["id"],
                lambda item=item, won=won: self.clients["SALES_MANAGER"].patch(
                    f"/api/v1/opportunities/{item['id']}",
                    json={"expected_version": won["version"], "name": "Forbidden"},
                ),
                422,
                "TERMINAL_OPPORTUNITY",
            )
            download = self.clients["SALES_REP"].get(f"/api/v1/evidence/{proof['id']}/download")
            self.check(
                "nginx_real_pdf_download",
                download.status_code == 200 and download.content == payload,
            )
            anonymous = httpx.get(
                self.base + f"/api/v1/evidence/{proof['id']}/download", trust_env=False
            )
            self.check("anonymous_download_denied", anonymous.status_code == 401)
        item = self.data(self.transition(self.opportunity(), "NEGOTIATION"))
        proof, _, _ = self.evidence(item)
        self.data(self.review(proof))
        item = self.data(
            self.clients["SALES_MANAGER"].patch(
                f"/api/v1/opportunities/{item['id']}",
                json={"expected_version": item["version"], "currency": "USD"},
            )
        )
        self.reject(
            "currency_mismatch_close",
            item["id"],
            lambda item=item, proof=proof: self.transition(item, "WON", evidence_id=proof["id"]),
            422,
            "EVIDENCE_CURRENCY_MISMATCH",
        )
        lost = self.data(
            self.transition(
                item, "LOST", close_reason_code="BUDGET", close_reason="Synthetic budget"
            )
        )
        opened = self.data(
            self.clients["SALES_MANAGER"].post(
                f"/api/v1/opportunities/{item['id']}/reopen",
                headers={"Idempotency-Key": str(uuid4())},
                json={"expected_version": lost["version"], "reason": "Synthetic reopen"},
            )
        )
        self.check(
            "lost_reopen_60_and_audit",
            opened["stage"] == "NEGOTIATION"
            and opened["probability"] == 60
            and (opened["closed_at"] is None)
            and (self.state(item["id"])[-1] >= 5),
        )
        proof, _, _ = self.evidence(opened, kind="OTHER_APPROVED")
        self.reject(
            "other_pending_policy_not_bypassed",
            opened["id"],
            lambda proof=proof: self.review(proof),
            409,
            "OTHER_APPROVAL_POLICY_PENDING",
        )
        self.reject(
            "other_cannot_close",
            opened["id"],
            lambda proof=proof: self.transition(opened, "WON", evidence_id=proof["id"]),
            422,
            "EVIDENCE_INVALID",
        )
        proof, _, _ = self.evidence(opened, role="ADMIN")
        self.reject(
            "admin_self_review",
            opened["id"],
            lambda proof=proof: self.review(proof),
            403,
            "EVIDENCE_REVIEWER_CONFLICT",
        )

    def pdf_boundaries(self):
        item = self.opportunity()
        large = pdf(attachment=2 * 1024 * 1024)
        self.evidence(item, payload=large)
        self.check("nginx_valid_pdf_over_one_mib", len(large) > 1024 * 1024)
        client = self.clients["SALES_MANAGER"]
        for name, payload, mime, expected in [
            ("bad_type", b"synthetic", "text/plain", 422),
            ("bad_pdf", b"not a PDF", "application/pdf", 422),
            ("too_many_pages", pdf(101), "application/pdf", 422),
            ("file_over_20mib", pdf() + b"x" * (20 * 1024 * 1024), "application/pdf", 413),
            ("nginx_body_over_21mib", pdf() + b"x" * (22 * 1024 * 1024), "application/pdf", 413),
        ]:
            with self.db.transaction() as session:
                before = session.scalar(
                    select(func.count())
                    .select_from(StoredObject)
                    .where(StoredObject.opportunity_id == item["id"])
                )
            response = client.post(
                f"/api/v1/opportunities/{item['id']}/evidence-files",
                data={"request_token": str(uuid4())},
                files={"file": ("synthetic.pdf", payload, mime)},
            )
            with self.db.transaction() as session:
                after = session.scalar(
                    select(func.count())
                    .select_from(StoredObject)
                    .where(StoredObject.opportunity_id == item["id"])
                )
            self.check(
                "pdf_" + name,
                response.status_code == expected
                and before == after
                and (expected != 413 or response.json()["error"]["code"] == "FILE_TOO_LARGE"),
                {"status": response.status_code},
            )

    def storage_and_privileges(self):
        business = Minio(
            os.environ["MINIO_ENDPOINT"] + ":" + os.environ["MINIO_PORT"],
            access_key=os.environ["MINIO_ACCESS_KEY"],
            secret_key=os.environ["MINIO_SECRET_KEY"],
            secure=False,
        )
        try:
            business.make_bucket("forbidden-" + uuid4().hex[:8])
        except S3Error as exc:
            self.check(
                "real_minio_forbidden_create",
                exc.code == "AccessDenied" and exc.response.status == 403,
            )
        else:
            self.check("real_minio_forbidden_create", False)
        item = self.opportunity()
        proof, stored, payload = self.evidence(item)
        with self.db.transaction() as session:
            obj = session.get(StoredObject, stored["stored_object_id"])
            bucket, key = (obj.bucket, obj.object_key)
        root = Minio(
            os.environ["MINIO_ENDPOINT"] + ":" + os.environ["MINIO_PORT"],
            access_key=os.environ["ACCEPTANCE_MINIO_ROOT_USER"],
            secret_key=os.environ["ACCEPTANCE_MINIO_ROOT_PASSWORD"],
            secure=False,
        )
        root.put_object(
            bucket, key, io.BytesIO(b"synthetic corruption"), len(b"synthetic corruption")
        )
        try:
            response = self.clients["SALES_MANAGER"].get(f"/api/v1/evidence/{proof['id']}/download")
            self.check(
                "corrupted_original_integrity_failure",
                response.status_code == 503
                and response.json()["error"]["code"] == "STORAGE_UNAVAILABLE",
            )
        finally:
            root.put_object(
                bucket, key, io.BytesIO(payload), len(payload), content_type="application/pdf"
            )
        for operation in [
            "UPDATE audit_events SET reason='forbidden' WHERE entity_id=:id",
            "DELETE FROM audit_events WHERE entity_id=:id",
        ]:
            denied = False
            try:
                with self.db.transaction() as session:
                    session.execute(text(operation), {"id": item["id"]})
                    raise RuntimeError("AUDIT_MUTATION_UNEXPECTEDLY_ALLOWED")
            except OperationalError as exc:
                denied = getattr(exc.orig, "args", [None])[0] in {1142, 1143}
            self.check("runtime_audit_" + operation.split()[0].lower() + "_denied", denied)

    def run(self):
        try:
            self.setup()
            for name in ["permissions", "close_cases", "pdf_boundaries", "storage_and_privileges"]:
                try:
                    getattr(self, name)()
                except Exception as exc:
                    self.checks.append(
                        {"check": name, "status": "FAIL", "error_type": type(exc).__name__}
                    )
            self.resources["users"] = {k: v["id"] for k, v in self.users.items()}
            (self.directory / "api-resources.json").write_text(json.dumps(self.resources, indent=2))
            (self.directory / "api-checks.json").write_text(json.dumps(self.checks, indent=2))
            failed = [c for c in self.checks if c["status"] != "PASS"]
            print(
                json.dumps(
                    {
                        "api_checks": len(self.checks),
                        "failed": failed,
                        "mysql_version": self.resources.get("mysql_version"),
                    }
                )
            )
            return 1 if failed else 0
        finally:
            for client in self.clients.values():
                client.close()
            self.db.close()
            self.seed.close()


def str_url(url):
    return url.render_as_string(hide_password=False)


if __name__ == "__main__":
    raise SystemExit(Acceptance().run())
