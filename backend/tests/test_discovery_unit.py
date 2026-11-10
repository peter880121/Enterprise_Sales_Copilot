from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.errors import AppError
from app.discovery.extraction import extract
from app.discovery.schemas import (
    AccountConfirm,
    MaterialCreate,
    ProfileCreate,
    ProfilePatch,
    RunCreate,
)

PROFILE = {"version": 1, "keywords": ["超声"], "regions": ["示例地区"]}


def test_medical_rules_keep_buyer_agency_budget_and_unicode_evidence_separate():
    text = (
        "采购人：示例医院😀\n采购代理：示例代理\n项目：超声设备\n"
        "公告类型：中标公告\n预算：120万元 人民币"
    )
    data = extract(text, PROFILE, "material", "hash")
    assert data["facts"]["buyer"]["value"] == "示例医院😀"
    assert data["facts"]["agency"]["value"] == "示例代理"
    assert data["notice_type"] == "AWARDED" and data["qualification"] == "NOT_VERIFIED"
    assert data["budget"] == {
        "value": "1200000.00",
        "currency": "CNY",
        "unit": "万元",
        "scope": "SOURCE_BUDGET_ONLY",
    }
    assert data["matched_keywords"] == ["超声"] and data["mode"] == "RULES"
    for field in data["facts"].values():
        evidence = field["evidence"]
        assert text[evidence["start"] : evidence["end"]] == evidence["quote"]


@pytest.mark.parametrize(
    "text",
    [
        "普通文章无标签",
        "采购人：A\n项目：X\n项目：Y",
        "采购人：A\n项目：",
        "采购人：A\n项目：" + "x" * 2001,
    ],
)
def test_rules_reject_missing_ambiguous_and_invalid_fields(text):
    with pytest.raises(AppError):
        extract(text, PROFILE, "material", "hash")


def test_missing_currency_or_timezone_is_not_invented():
    data = extract(
        "采购人：A\n项目：X\n预算：120万元\n截止时间：2026-12-01", PROFILE, "material", "hash"
    )
    assert data["budget"]["currency"] is None and data["deadline"] is None
    assert "agency" not in data["facts"]


@pytest.mark.parametrize(
    "extra",
    [
        {"confirmed_shared_crm": False},
        {"confirmed_shared_crm": 1},
        {"preview_hash": "bad"},
        {"new_account_name": None},
        {"owner_id": str(uuid4())},
    ],
)
def test_account_link_requires_explicit_valid_preview_and_no_client_actor(extra):
    with pytest.raises(ValidationError):
        AccountConfirm.model_validate(
            {
                "expected_version": 3,
                "new_account_name": "Synthetic",
                "preview_hash": "a" * 64,
                "confirmed_shared_crm": True,
                **extra,
            }
        )


def test_source_purpose_and_patient_confirmation_are_explicit():
    with pytest.raises(ValidationError):
        MaterialCreate(
            title="Synthetic",
            purpose="BUYER_DEMAND",
            content="Synthetic",
            confirm_no_patient_data=False,
        )
    with pytest.raises(ValidationError):
        ProfileCreate(name=" ", product="Synthetic", keywords=["test"])
    uid = uuid4()
    with pytest.raises(ValidationError):
        RunCreate(expected_profile_version=1, material_ids=[uid, uid], request_token=uuid4())


def test_profile_edit_cannot_silently_omit_authorization_snapshot():
    with pytest.raises(ValidationError):
        ProfilePatch(name="Synthetic", product="Synthetic", keywords=["test"], expected_version=1)
