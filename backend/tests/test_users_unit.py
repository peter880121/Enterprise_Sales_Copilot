from datetime import datetime

import pytest
from pydantic import ValidationError

from app.auth.models import User
from app.users.schemas import ProfilePatch, Registration, UserCreate, UserPatch
from app.users.service import audit_snapshot

PASSWORD = "Synthetic user password 2026"


@pytest.mark.parametrize(
    "extra",
    [
        {"role": "ADMIN"},
        {"is_active": True},
        {"registration_status": "APPROVED"},
        {"deleted_at": None},
        {"password": "short"},
        {"name": "   "},
        {"email": "person@-invalid.example.test"},
    ],
)
def test_public_registration_rejects_privileged_or_invalid_input(extra):
    with pytest.raises(ValidationError):
        Registration(
            **{"name": "Synthetic", "email": "person@example.test", "password": PASSWORD, **extra}
        )


def test_password_not_trimmed_and_email_normalized():
    password = "  Synthetic exact password  "
    body = Registration(name="  Synthetic  ", email=" Person@Example.Test ", password=password)
    assert (
        body.password == password
        and body.name == "Synthetic"
        and body.email == "person@example.test"
    )


@pytest.mark.parametrize(
    "body",
    [
        {"name": None},
        {"email": None},
        {"role": None},
        {"is_active": None},
        {"is_active": "false"},
        {},
        {"registration_status": "APPROVED"},
        {"reason": "  ", "name": "Valid"},
    ],
)
def test_user_patch_rejects_hidden_empty_or_null_changes(body):
    with pytest.raises(ValidationError):
        UserPatch(**{"expected_version": 1, "reason": "Synthetic", **body})


def test_users_use_explicit_audit_allowlist_without_credentials_or_internal_fields():
    user = User(
        id="synthetic",
        name="Synthetic",
        email="person@example.test",
        role="ADMIN",
        is_active=True,
        registration_status="APPROVED",
        deleted_at=None,
        version=1,
        created_at=datetime(2026, 10, 27),
        updated_at=datetime(2026, 10, 27),
        password_hash="synthetic-internal-not-a-real-hash",
    )
    user.synthetic_internal = "synthetic-only-internal"
    snapshot = audit_snapshot(user)
    assert not {"password_hash", "password_changed_at", "synthetic_internal"} & snapshot.keys()
    assert snapshot["deleted_at"] is None and snapshot["created_at"] == "2026-10-27T00:00:00Z"


def test_admin_create_and_profile_do_not_accept_unapproved_fields():
    with pytest.raises(ValidationError):
        UserCreate(
            name="Synthetic", email="person@example.test", password=PASSWORD, role="SUPER_ADMIN"
        )
    with pytest.raises(ValidationError):
        ProfilePatch(
            expected_version=1,
            name="Synthetic",
            email="person@example.test",
            current_password=PASSWORD,
            role="ADMIN",
        )
