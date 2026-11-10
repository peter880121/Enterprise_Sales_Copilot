import hashlib
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import and_, or_, select

from app.auth.models import User
from app.auth.service import now
from app.core.errors import AppError
from app.crm.service import SELLERS
from app.discovery.extraction import extract
from app.discovery.models import DiscoveryLead, DiscoveryRun, Material, RunMaterial
from app.discovery.service import DiscoveryService, audit


class DiscoveryProcessor:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings

    def claim(self):
        with self.db.transaction() as s:
            row = s.scalar(
                select(DiscoveryRun)
                .where(
                    or_(
                        DiscoveryRun.status == "QUEUED",
                        and_(DiscoveryRun.status == "RUNNING", DiscoveryRun.lease_until <= now()),
                    )
                )
                .order_by(DiscoveryRun.created_at, DiscoveryRun.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            if row.attempts >= 3:
                row.status = "FAILED"
                row.error_code = "RETRY_EXHAUSTED"
                row.version += 1
                row.updated_at = now()
                row.lease_token = row.lease_until = None
                audit(s, row, None, "DISCOVERY_RUN_FAILED", row.id)
                return None
            row.status = "RUNNING"
            row.attempts += 1
            row.version += 1
            row.updated_at = now()
            row.lease_until = now() + timedelta(seconds=60)
            row.lease_token = str(uuid4())
            return {
                "id": row.id,
                "token": row.lease_token,
                "creator": row.created_by,
                "profile_id": row.profile_id,
                "profile": row.profile_snapshot,
            }

    def process_one(self):
        claim = self.claim()
        if claim is None:
            return False
        result, error = [], None
        try:
            with self.db.transaction() as session:
                actor = session.get(User, claim["creator"], with_for_update=True)
                if not actor or not actor.is_active or actor.role not in SELLERS:
                    raise AppError(403, "SOURCE_ACCESS_REVOKED", "Permission changed")
                DiscoveryService(self.db, self.settings).access(
                    session, actor, claim["profile_id"], write=True
                )
                row = session.get(DiscoveryRun, claim["id"], with_for_update=True)
                if (
                    row.status != "RUNNING"
                    or row.lease_token != claim["token"]
                    or row.lease_until <= now()
                ):
                    return False
                materials = [
                    (m.id, m.content, hashlib.sha256(m.content.encode()).hexdigest())
                    for m in session.scalars(
                        select(Material)
                        .join(RunMaterial, RunMaterial.material_id == Material.id)
                        .where(RunMaterial.run_id == row.id)
                        .order_by(Material.id)
                    )
                ]
            result = [
                (uid, extract(content, claim["profile"], uid, sha))
                for uid, content, sha in materials
            ]
        except AppError as exc:
            error = exc.code
        except Exception:
            error = "EXTRACTION_FAILED"
        self.publish(claim, result, error)
        return True

    def publish(self, claim, results, error=None):
        with self.db.transaction() as s:
            # Match API lock order: user -> profile -> run/lead. The claim transaction has ended.
            actor = s.get(User, claim["creator"], with_for_update=True)
            service = DiscoveryService(self.db, self.settings)
            try:
                if not actor or not actor.is_active or actor.role not in SELLERS:
                    raise AppError(403, "FORBIDDEN", "Permission changed")
                service.access(s, actor, claim["profile_id"], write=True)
            except AppError:
                error = "SOURCE_ACCESS_REVOKED"
            row = s.get(DiscoveryRun, claim["id"], with_for_update=True)
            if (
                row.status != "RUNNING"
                or row.lease_token != claim["token"]
                or row.lease_until <= now()
            ):
                return False
            if not error:
                for uid, analysis in results:
                    prior = s.scalar(select(DiscoveryLead).where(DiscoveryLead.material_id == uid))
                    if prior:
                        continue
                    lead = DiscoveryLead(
                        id=str(uuid4()),
                        profile_id=row.profile_id,
                        run_id=row.id,
                        material_id=uid,
                        owner_id=actor.id,
                        buyer_name=analysis["facts"]["buyer"]["value"],
                        project_name=analysis["facts"]["project"]["value"],
                        notice_type=analysis["notice_type"],
                        analysis=analysis,
                        status="NEW",
                        summary_shared=False,
                        version=1,
                        created_at=now(),
                        updated_at=now(),
                    )
                    s.add(lead)
                    s.flush()
                    audit(s, lead, None, "DISCOVERY_LEAD_CREATED", row.id)
            row.status = "FAILED" if error else "SUCCEEDED"
            row.error_code = error
            row.result_count = 0 if error else len(results)
            row.version += 1
            row.updated_at = now()
            row.lease_token = row.lease_until = None
            audit(
                s, row, None, "DISCOVERY_RUN_FAILED" if error else "DISCOVERY_RUN_COMPLETED", row.id
            )
            return True
