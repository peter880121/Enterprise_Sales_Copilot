from datetime import date
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.crm.schemas import Version

TOPICS = ("needs", "budget", "contacts", "decision_maker", "close_date", "tasks", "risks")


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class MeetingCreate(Input):
    expected_opportunity_version: Version
    meeting_text: str = Field(min_length=1, max_length=50000, repr=False)
    meeting_date: date | None = None
    timezone: str = Field(default="Asia/Hong_Kong", max_length=64)
    request_token: UUID

    @field_validator("meeting_text")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("meeting text required")
        return value

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("known IANA timezone required") from None
        return value


class Evidence(Input):
    start: int = Field(ge=0, strict=True)
    end: int = Field(gt=0, strict=True)
    quote: str = Field(min_length=1, max_length=2000)


class Fact(Input):
    topic: Literal["needs", "budget", "contacts", "decision_maker", "close_date", "tasks", "risks"]
    kind: Literal["FACT", "INFERENCE", "UNKNOWN"]
    value: str | None = Field(default=None, max_length=2000)
    evidence: list[Evidence] = Field(max_length=10)

    @model_validator(mode="after")
    def supported(self):
        if self.kind == "UNKNOWN":
            if self.value is not None or self.evidence:
                raise ValueError("unknown information cannot carry invented values")
        elif not self.value or not self.value.strip() or not self.evidence:
            raise ValueError("facts and inferences require evidence")
        return self


class Extraction(Input):
    mode: Literal["MOCK"]
    schema_version: Literal["meeting-v1"]
    facts: list[Fact] = Field(min_length=7, max_length=7)
    proposed_changes: list = Field(default_factory=list, max_length=0)

    @model_validator(mode="after")
    def complete_topics(self):
        if {item.topic for item in self.facts} != set(TOPICS):
            raise ValueError("exactly one entry per topic required")
        return self

    def verify_source(self, text):
        for item in self.facts:
            for evidence in item.evidence:
                if (
                    not (evidence.start < evidence.end <= len(text))
                    or text[evidence.start : evidence.end] != evidence.quote
                ):
                    raise ValueError("source quote or Unicode code-point offsets do not match")
            if item.kind == "FACT" and not any(
                item.value in evidence.quote for evidence in item.evidence
            ):
                raise ValueError("a fact value must occur in its cited source")
        return self


class Review(Input):
    expected_version: Version
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("reason required")
        return value.strip()


class Regenerate(Input):
    expected_version: Version
    expected_opportunity_version: Version
    request_token: UUID
