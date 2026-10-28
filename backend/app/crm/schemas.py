import re
from datetime import UTC, datetime
from ipaddress import IPv6Address
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

Size = Literal["SOLO", "SMALL", "MEDIUM", "LARGE", "ENTERPRISE"]
DecisionRole = Literal["DECISION_MAKER", "CHAMPION", "INFLUENCER", "USER", "PROCUREMENT", "UNKNOWN"]
Version = Annotated[int, Field(strict=True, ge=1, le=18446744073709551614)]

# Keep this explicit input profile aligned with the frontend Zod refinements.
# Unicode domains must be supplied as Punycode; no DNS lookup or URL rewriting.
EMAIL_PATTERN = re.compile(
    r"(?:[A-Za-z0-9_'+\-]+\.)*[A-Za-z0-9_'+\-]*[A-Za-z0-9_+-]"
    r"@(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}"
)
WEBSITE_PATTERN = re.compile(
    r"https?://(\[[0-9a-f:]+\]|[a-z0-9][a-z0-9.\-]*)(?::([0-9]{1,5}))?"
    r"(?:[/?#][^\s\\]*)?",
    re.IGNORECASE | re.ASCII,
)
HOST_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?")


def valid_website(value: str) -> bool:
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 or char == "\\" for char in value):
        return False
    match = WEBSITE_PATTERN.fullmatch(value)
    if not match or (match[2] is not None and int(match[2]) > 65535):
        return False
    host = match[1]
    if host.startswith("["):
        try:
            IPv6Address(host[1:-1])
            return True
        except ValueError:
            return False
    host = host.removesuffix(".")
    labels = host.split(".")
    if len(host) > 253 or not all(HOST_LABEL.fullmatch(label) for label in labels):
        return False
    if labels[-1].isdigit():
        return len(labels) == 4 and all(
            label.isdigit() and str(int(label)) == label and int(label) <= 255 for label in labels
        )
    return True


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True)


class AccountFields(Input):
    name: str = Field(min_length=1, max_length=200)
    industry: str | None = Field(default=None, max_length=100)
    website: str | None = Field(default=None, max_length=2048)
    company_size: Size | None = None
    description: str | None = Field(default=None, max_length=10000)

    @field_validator("website")
    @classmethod
    def safe_website(cls, value):
        if value is not None and not valid_website(value):
            raise ValueError("valid http/https website without credentials required")
        return value


class AccountCreate(AccountFields):
    owner_id: UUID | None = None


class AccountPatch(AccountFields):
    expected_version: Version
    name: str | None = Field(default=None, min_length=1, max_length=200)
    owner_id: UUID | None = None

    @model_validator(mode="after")
    def patch_fields(self):
        if not self.model_fields_set - {"expected_version"}:
            raise ValueError("at least one change required")
        for key in ("name", "owner_id"):
            if key in self.model_fields_set and getattr(self, key) is None:
                raise ValueError("non-null field cannot be cleared")
        return self


class ContactFields(Input):
    name: str = Field(min_length=1, max_length=100)
    title: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=40)
    decision_role: DecisionRole = "UNKNOWN"

    @field_validator("email")
    @classmethod
    def email_shape(cls, value):
        if value is not None and not EMAIL_PATTERN.fullmatch(value):
            raise ValueError("valid email required")
        return value


class ContactCreate(ContactFields):
    account_id: UUID


class ContactPatch(ContactFields):
    expected_version: Version
    name: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def patch_fields(self):
        if not self.model_fields_set - {"expected_version"}:
            raise ValueError("at least one change required")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be cleared")
        return self


class EntityView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    version: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def utc_time(self, value):
        return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


class OwnerView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str


class AccountView(EntityView):
    owner_id: str
    owner: OwnerView
    name: str
    industry: str | None
    website: str | None
    company_size: Size | None
    description: str | None


class ContactView(EntityView):
    account_id: UUID
    name: str
    title: str | None
    email: str | None
    phone: str | None
    decision_role: DecisionRole


class ListQuery(Input):
    page: int = Field(default=1, ge=1, le=100000)
    page_size: int = Field(default=20, ge=1, le=100)
    q: str = Field(default="", max_length=100)
    is_active: bool | None = None


class AccountQuery(ListQuery):
    owner_id: UUID | None = None
    sort: Literal["name", "created_at"] = "name"


class ContactQuery(ListQuery):
    account_id: UUID | None = None


class Page(BaseModel):
    number: int
    size: int
    total: int


class AccountResponse(BaseModel):
    data: AccountView
    request_id: str


class ContactResponse(BaseModel):
    data: ContactView
    request_id: str


class AccountListResponse(BaseModel):
    data: list[AccountView]
    page: Page
    request_id: str


class ContactListResponse(BaseModel):
    data: list[ContactView]
    page: Page
    request_id: str
