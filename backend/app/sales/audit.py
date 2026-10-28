"""Explicit audit allowlists, independent of API response serialization and ORM columns."""

from app.sales.models import Activity, CloseEvidence, Opportunity

COMMON = ("id", "version", "created_at", "updated_at")
AUDIT_FIELDS = {
    Opportunity: COMMON
    + (
        "name",
        "account_id",
        "primary_contact_id",
        "owner_id",
        "stage",
        "amount",
        "currency",
        "probability",
        "weighted_amount",
        "source",
        "priority",
        "expected_close_date",
        "close_reason_code",
        "close_reason",
        "close_evidence_id",
        "closed_at",
        "closed_by",
        "is_archived",
        "archived_at",
        "archived_by",
    ),
    Activity: COMMON
    + (
        "account_id",
        "opportunity_id",
        "contact_id",
        "type",
        "subject",
        "content",
        "occurred_at",
        "due_at",
        "assignee_id",
        "status",
        "completed_at",
        "created_by",
    ),
    CloseEvidence: COMMON
    + (
        "opportunity_id",
        "stored_object_id",
        "type",
        "reference_number",
        "customer_legal_name",
        "document_date",
        "amount",
        "currency",
        "status",
        "submitted_by",
        "reviewed_by",
        "reviewed_at",
        "verification_note",
        "approval_basis",
    ),
}


def audit_values(entity):
    # Unknown audited entity types fail closed rather than exposing all mapped columns.
    return {field: getattr(entity, field) for field in AUDIT_FIELDS[type(entity)]}
