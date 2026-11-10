from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.crm.schemas import Input, Version


class ProfileCreate(Input):
    name: str = Field(min_length=1, max_length=200)
    product: str = Field(min_length=1, max_length=200)
    keywords: list[str] = Field(min_length=1, max_length=20)
    regions: list[str] = Field(default_factory=list, max_length=20)
    visibility: Literal["PRIVATE", "TEAM"] = "PRIVATE"
    reviewer_ids: list[UUID] = Field(default_factory=list, max_length=10)

    @field_validator("name", "product")
    @classmethod
    def nonblank(cls, value):
        if not value.strip() or "\x00" in value:
            raise ValueError("nonblank value required")
        return value.strip()

    @field_validator("keywords", "regions")
    @classmethod
    def terms(cls, values):
        if any(not value.strip() or len(value.strip()) > 50 for value in values):
            raise ValueError("terms must contain 1..50 characters")
        return list(dict.fromkeys(value.strip() for value in values))


class ProfilePatch(ProfileCreate):
    expected_version: Version
    # Editing is an explicit complete snapshot; omitted ACL/regions must never revoke data.
    reviewer_ids: list[UUID] = Field(max_length=10)
    regions: list[str] = Field(max_length=20)
    visibility: Literal["PRIVATE", "TEAM"]


class MaterialCreate(Input):
    title: str = Field(min_length=1, max_length=200)
    purpose: Literal["SELLER_CAPABILITY", "BUYER_DEMAND"]
    content: str = Field(min_length=1, max_length=50000, repr=False)
    confirm_team_visibility: bool = Field(default=False, strict=True)
    confirm_no_patient_data: bool = Field(strict=True)

    @field_validator("confirm_no_patient_data")
    @classmethod
    def no_patient_data(cls, value):
        if value is not True:
            raise ValueError("patient records are outside discovery scope")
        return value

    @field_validator("title", "content")
    @classmethod
    def nonblank(cls, value):
        if not value.strip() or "\x00" in value:
            raise ValueError("nonblank value required")
        return value


class RunCreate(Input):
    expected_profile_version: Version
    material_ids: list[UUID] = Field(min_length=1, max_length=10)
    request_token: UUID

    @field_validator("material_ids")
    @classmethod
    def unique(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("duplicate material")
        return values


class PublicSearchPreview(Input):
    expected_profile_version: Version
    public_query: str = Field(min_length=3, max_length=200, repr=False)

    @field_validator("public_query")
    @classmethod
    def public_line(cls, value):
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("public query must be a single line")
        value = value.strip()
        if not 3 <= len(value) <= 200:
            raise ValueError("public query must contain 3..200 characters")
        return value


class SearchAccept(PublicSearchPreview):
    request_token: UUID
    preview_token: str = Field(pattern=r"^[0-9]{1,12}:[0-9a-f]{64}$")
    confirmed_public: bool = Field(strict=True)

    @field_validator("confirmed_public")
    @classmethod
    def confirm(cls, value):
        if value is not True:
            raise ValueError("explicit public-query confirmation required")
        return value


class Review(Input):
    expected_version: Version
    status: Literal["IN_REVIEW", "QUALIFIED", "DISQUALIFIED"]
    reason: str = Field(min_length=1, max_length=1000)
    publish_summary: bool = Field(default=False, strict=True)

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("reason required")
        return value.strip()


class AccountPreview(Input):
    expected_version: Version
    existing_account_id: UUID | None = None
    new_account_name: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def target(self):
        if bool(self.existing_account_id) == bool(self.new_account_name):
            raise ValueError("choose one existing account or a new account name")
        if self.new_account_name is not None:
            self.new_account_name = self.new_account_name.strip()
            if not self.new_account_name:
                raise ValueError("account name required")
        return self


class AccountConfirm(AccountPreview):
    preview_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirmed_shared_crm: bool = Field(strict=True)

    @field_validator("confirmed_shared_crm")
    @classmethod
    def explicit(cls, value):
        if value is not True:
            raise ValueError("explicit shared CRM confirmation required")
        return value
