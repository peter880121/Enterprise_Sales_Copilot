import json
from itertools import product
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth.models import Role
from app.crm.schemas import AccountCreate, AccountPatch, ContactCreate, ContactPatch
from app.crm.service import can_write
from app.main import create_app

VALIDATION_CASES = json.loads(
    (Path(__file__).resolve().parents[2] / "tests/fixtures/crm-validation.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("case", VALIDATION_CASES["websites"])
@pytest.mark.parametrize("schema", [AccountCreate, AccountPatch])
def test_shared_website_validation(case, schema):
    # UI blank fields are serialized as null; direct API callers must send null to clear.
    value = (case["value"].strip() or None) if case["value"] is not None else None
    values = {"name": "Synthetic", "website": value}
    if schema is AccountPatch:
        values["expected_version"] = 1
    if case["valid"]:
        assert schema(**values).website == value
    else:
        with pytest.raises(ValidationError):
            schema(**values)


@pytest.mark.parametrize("case", VALIDATION_CASES["emails"])
@pytest.mark.parametrize("schema", [ContactCreate, ContactPatch])
def test_shared_email_validation(case, schema):
    value = (case["value"].strip() or None) if case["value"] is not None else None
    values = {"name": "Synthetic", "email": value}
    if schema is ContactCreate:
        values["account_id"] = str(uuid4())
    else:
        values["expected_version"] = 1
    if case["valid"]:
        assert schema(**values).email == value
    else:
        with pytest.raises(ValidationError):
            schema(**values)


def test_invalid_existing_values_can_be_corrected_or_cleared_without_data_rewrite():
    assert AccountPatch(expected_version=1, website=None).website is None
    assert ContactPatch(expected_version=1, email=None).email is None
    for schema, field in [(AccountPatch, "website"), (ContactPatch, "email")]:
        with pytest.raises(ValidationError):
            schema(expected_version=1, **{field: ""})


@pytest.mark.parametrize("role,own", list(product(list(Role), [True, False])))
def test_q03_write_matrix(role, own):
    assert can_write(role, "actor", "actor" if own else "other") == (
        role in {Role.ADMIN, Role.SALES_MANAGER} or (role == Role.SALES_REP and own)
    )


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"name": "  "},
        {"name": "x", "website": "javascript:alert(1)"},
        {"name": "x", "website": "https://user:password@example.test"},
        {"name": "x", "company_size": "INVALID"},
        {"name": "x", "is_active": False},
        {"name": "x", "description": "x" * 10001},
        {"name": "x", "unknown": "value"},
    ],
)
def test_account_invalid_input(values):
    with pytest.raises(ValidationError):
        AccountCreate(**values)


def test_nullable_patch_and_trim():
    assert AccountCreate(name="  Synthetic  ").name == "Synthetic"
    body = AccountPatch(expected_version=1, description=None)
    assert body.model_dump(exclude_unset=True) == {"expected_version": 1, "description": None}
    for values in (
        {"expected_version": 1},
        {"expected_version": 1, "name": None},
        {"expected_version": True, "name": "x"},
    ):
        with pytest.raises(ValidationError):
            AccountPatch(**values)


def test_contact_relationship_immutable_and_validation():
    account_id = str(uuid4())
    assert ContactCreate(account_id=account_id, name="Same name").decision_role == "UNKNOWN"
    for values in (
        {"account_id": "invalid", "name": "x"},
        {"account_id": account_id, "name": "x", "email": "invalid"},
        {"account_id": account_id, "name": "x", "decision_role": "CEO"},
    ):
        with pytest.raises(ValidationError):
            ContactCreate(**values)
    with pytest.raises(ValidationError):
        ContactPatch(expected_version=1, account_id=account_id)


def test_crm_auth_and_response_contract_without_database(settings):
    # No configured connection is used: unauthenticated requests reject before accessing DB.
    with TestClient(create_app(settings)) as client:
        for path in ("/accounts", "/contacts", f"/accounts/{uuid4()}/contacts"):
            response = client.get("/api/v1" + path)
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "SESSION_EXPIRED"
        schema = client.get("/openapi.json").json()
        assert schema["paths"]["/api/v1/accounts"]["post"]["responses"]["201"]
        assert "/api/v1/accounts/{entity_id}/activation" not in schema["paths"]
        assert "delete" not in schema["paths"]["/api/v1/contacts/{entity_id}"]
