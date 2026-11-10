import hashlib
import json

from sqlalchemy import select

from app.meetings.proposals import FIELDS
from app.sales.models import Activity
from app.sales.service import encode


def snapshot(opportunity):
    return encode(
        {
            name: getattr(opportunity, name)
            for name in sorted(FIELDS | {"id", "version", "owner_id", "account_id", "stage"})
        }
    )


def context_digest(session, opportunity):
    # Activity APIs serialize their changes on the same parent opportunity lock.
    activities = session.execute(
        select(Activity.id, Activity.version)
        .where(Activity.opportunity_id == opportunity.id)
        .order_by(Activity.id)
    ).all()
    data = {
        "opportunity": snapshot(opportunity),
        "activities": [(row.id, row.version) for row in activities],
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).digest()
