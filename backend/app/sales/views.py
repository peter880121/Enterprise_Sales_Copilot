from typing import Any

from pydantic import BaseModel, Field

from app.crm.schemas import Page
from app.sales.schemas import Currency, Stage


class Envelope[T](BaseModel):
    data: T
    request_id: str


class Paged[T](Envelope[list[T]]):
    page: Page


class VersionedView(BaseModel):
    id: str
    version: int
    created_at: str
    updated_at: str


class OpportunityView(VersionedView):
    name: str
    account_id: str
    primary_contact_id: str | None
    owner_id: str
    stage: Stage
    amount: str | None
    currency: Currency
    probability: int = Field(json_schema_extra={"readOnly": True})
    weighted_amount: str | None = Field(json_schema_extra={"readOnly": True})
    actual_amount: str | None = Field(json_schema_extra={"readOnly": True})
    actual_currency: Currency | None = Field(json_schema_extra={"readOnly": True})
    source: str
    priority: str
    expected_close_date: str | None
    close_reason_code: str | None
    close_reason: str | None
    close_evidence_id: str | None
    close_evidence_type: str | None
    close_evidence_reference: str | None
    closed_at: str | None
    closed_by: str | None
    is_archived: bool
    archived_at: str | None
    archived_by: str | None
    account: dict[str, str]
    owner: dict[str, str]
    last_activity_at: str | None
    capabilities: dict[str, bool] | None = None


class EvidenceView(VersionedView):
    opportunity_id: str
    stored_object_id: str
    type: str
    reference_number: str
    customer_legal_name: str
    document_date: str
    amount: str
    currency: Currency
    status: str
    submitted_by: str
    reviewed_by: str | None
    reviewed_at: str | None
    verification_note: str | None
    approval_basis: str | None


class ActivityView(VersionedView):
    account_id: str
    opportunity_id: str | None
    contact_id: str | None
    type: str
    subject: str
    content: str
    occurred_at: str | None
    due_at: str | None
    assignee_id: str | None
    status: str
    completed_at: str | None
    created_by: str


class AuditView(BaseModel):
    id: str
    entity_type: str
    entity_id: str
    actor_kind: str
    actor_id: str | None
    action: str
    before_state: dict[str, Any] | None
    after_state: dict[str, Any] | None
    reason: str | None
    expected_version: int | None
    resulting_version: int | None
    request_id: str
    mutation_event_key: str | None
    created_at: str


class UploadedView(BaseModel):
    stored_object_id: str
    status: str
    sha256: str
    size_bytes: int
    pages: int
