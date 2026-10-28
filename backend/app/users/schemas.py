from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.auth.models import Role
from app.crm.schemas import EMAIL_PATTERN, Version

Password = Annotated[str, Field(min_length=12, max_length=128, repr=False)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Registration(Input):
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=254)
    password: Password

    @field_validator("name")
    @classmethod
    def name_shape(cls, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("name required")
        return value.strip()

    @field_validator("email")
    @classmethod
    def email_shape(cls, value):
        if not isinstance(value, str):
            raise ValueError("email required")
        value = value.strip().lower()
        if not EMAIL_PATTERN.fullmatch(value):
            raise ValueError("valid email required")
        return value

    @field_validator("password")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("nonblank password required")
        return value


class UserCreate(Registration):
    role: Role
    is_active: bool = Field(default=True, strict=True)


class UserPatch(Input):
    expected_version: Version
    reason: str = Field(min_length=1, max_length=2000)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    email: str | None = Field(default=None, min_length=3, max_length=254)
    role: Role | None = None
    is_active: bool | None = Field(default=None, strict=True)

    _name = field_validator("name")(Registration.name_shape.__func__)
    _email = field_validator("email")(Registration.email_shape.__func__)

    @model_validator(mode="after")
    def changes(self):
        if not self.model_fields_set - {"expected_version", "reason"}:
            raise ValueError("at least one change required")
        if any(getattr(self, key) is None for key in self.model_fields_set):
            raise ValueError("fields cannot be cleared")
        if not self.reason.strip():
            raise ValueError("reason required")
        return self


class UserCommand(Input):
    expected_version: Version
    reason: str = Field(min_length=1, max_length=2000)

    @field_validator("reason")
    @classmethod
    def reason_shape(cls, value):
        if not value.strip():
            raise ValueError("reason required")
        return value.strip()


class Approval(UserCommand):
    role: Role


class PasswordReset(UserCommand):
    new_password: Password
    _password = field_validator("new_password")(Registration.not_blank.__func__)


class PasswordChange(Input):
    current_password: str = Field(min_length=1, max_length=128, repr=False)
    new_password: Password
    _password = field_validator("new_password")(Registration.not_blank.__func__)


class ProfilePatch(Input):
    expected_version: Version
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=254)
    current_password: str = Field(min_length=1, max_length=128, repr=False)
    _name = field_validator("name")(Registration.name_shape.__func__)
    _email = field_validator("email")(Registration.email_shape.__func__)


class UserQuery(Input):
    page: int = Field(default=1, ge=1, le=100000)
    page_size: int = Field(default=20, ge=1, le=100)
    q: str = Field(default="", max_length=100)
    role: Role | None = None
    status: Literal["PENDING", "ACTIVE", "DISABLED", "DELETED"] | None = None
    is_active: bool | None = None


class UserAuditView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    actor_id: str | None
    action: str
    reason: str | None
    before_state: dict | None
    after_state: dict | None
    expected_version: int | None
    resulting_version: int | None
    request_id: str
    created_at: datetime

    @field_serializer("created_at")
    def utc(self, value):
        return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")
