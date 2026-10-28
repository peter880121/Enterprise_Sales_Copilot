from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.auth.models import Role


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128, repr=False)

    @field_validator("email")
    @classmethod
    def email_shape(cls, value):
        value = value.strip().lower()
        if "@" not in value or any(c.isspace() for c in value):
            raise ValueError("valid email required")
        return value


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    email: str
    role: Role
    is_active: bool
    registration_status: str = "APPROVED"
    deleted_at: datetime | None = None
    version: int
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at", "deleted_at")
    def utc_datetime(self, value: datetime | None):
        if value is None:
            return None
        return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")
