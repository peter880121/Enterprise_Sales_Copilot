import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.crm.schemas import Input, Version

Stage = Literal["PROPOSAL_SUBMITTED", "NEGOTIATION", "FOLLOW_UP", "WON", "LOST"]
Currency = Literal["CNY", "USD", "EUR", "HKD"]
Priority = Literal["LOW", "MEDIUM", "HIGH"]
Source = Literal[
    "WEBSITE",
    "PARTNER",
    "REFERRAL",
    "CAMPAIGN",
    "EVENT",
    "COLD_OUTREACH",
    "EXISTING_CUSTOMER",
    "OTHER",
    "UNKNOWN",
]
LossReason = Literal["BUDGET", "COMPETITOR", "NO_DECISION", "PRODUCT_FIT", "TIMING", "OTHER"]
Reason = Annotated[str, Field(min_length=1, max_length=2000)]


def money(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(
        r"(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,2})?", value
    ):
        raise ValueError("money requires a nonnegative decimal string with at most two decimals")
    return Decimal(value).quantize(Decimal("0.01"))


class OpportunityFields(Input):
    name: str = Field(min_length=1, max_length=200)
    primary_contact_id: UUID | None = None
    amount: Decimal | None = None
    currency: Currency = "CNY"
    source: Source = "UNKNOWN"
    priority: Priority = "MEDIUM"
    expected_close_date: date | None = None

    _money = field_validator("amount", mode="before")(money)


class OpportunityCreate(OpportunityFields):
    account_id: UUID
    owner_id: UUID | None = None


class OpportunityPatch(OpportunityFields):
    expected_version: Version
    name: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def changed(self):
        if not self.model_fields_set - {"expected_version"}:
            raise ValueError("at least one change required")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")
        return self


class Command(Input):
    expected_version: Version
    reason: Reason


class Transition(Command):
    target_stage: Stage
    evidence_id: UUID | None = None
    close_reason_code: LossReason | None = None
    close_reason: Reason | None = None


class Assignment(Command):
    owner_id: UUID


class Archive(Command):
    is_archived: bool = Field(strict=True)


class Completion(Input):
    expected_version: Version
    reason: Reason | None = None


class EvidenceCreate(Input):
    stored_object_id: UUID
    type: Literal["SIGNED_CONTRACT", "PURCHASE_ORDER", "OTHER_APPROVED"]
    reference_number: str = Field(min_length=1, max_length=100)
    customer_legal_name: str = Field(min_length=1, max_length=200)
    document_date: date
    amount: Decimal = Field(gt=0)
    currency: Currency = "CNY"
    approval_basis: str | None = Field(default=None, max_length=2000)

    _money = field_validator("amount", mode="before")(money)


class Review(Input):
    expected_version: Version
    decision: Literal["VERIFY", "REJECT"]
    note: Reason
    approval_basis: str | None = Field(default=None, max_length=2000)


class OpportunityQuery(Input):
    page: int = Field(default=1, ge=1, le=100000)
    page_size: int = Field(default=20, ge=1, le=100)
    q: str = Field(default="", max_length=100)
    stage: Stage | None = None
    owner_id: UUID | None = None
    account_id: UUID | None = None
    currency: Currency | None = None
    priority: Priority | None = None
    is_archived: bool = False
    sort: Literal["name", "created_at", "updated_at", "expected_close_date"] = "name"
    win_from: datetime | None = None
    win_to: datetime | None = None

    @model_validator(mode="after")
    def dates(self):
        if any(value and value.tzinfo is None for value in (self.win_from, self.win_to)):
            raise ValueError("report timestamps must include timezone")
        if self.win_from and self.win_to and self.win_from > self.win_to:
            raise ValueError("win_from must not exceed win_to")
        return self


class ActivityCreate(Input):
    account_id: UUID
    opportunity_id: UUID | None = None
    contact_id: UUID | None = None
    type: Literal["CALL", "MEETING", "EMAIL", "NOTE", "TASK"]
    subject: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=20000)
    occurred_at: datetime | None = None
    due_at: datetime | None = None
    assignee_id: UUID | None = None

    @model_validator(mode="after")
    def task(self):
        if self.type == "TASK":
            if not self.due_at or not self.assignee_id:
                raise ValueError("task requires due date and assignee")
        elif not self.occurred_at:
            raise ValueError("recorded activity requires occurred_at")
        for key in ("occurred_at", "due_at"):
            value = getattr(self, key)
            if value and value.tzinfo is None:
                raise ValueError("activity times must include timezone")
        return self


class ActivityPatch(Input):
    expected_version: Version
    reason: Reason
    subject: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, min_length=1, max_length=20000)
    due_at: datetime | None = None

    @model_validator(mode="after")
    def changed(self):
        if not self.model_fields_set - {"expected_version", "reason"}:
            raise ValueError("at least one change required")
        if any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("these activity fields cannot be cleared")
        if self.due_at and self.due_at.tzinfo is None:
            raise ValueError("timezone required")
        return self
