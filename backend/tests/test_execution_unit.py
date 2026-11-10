from datetime import date
from uuid import uuid4

import pytest

from app.meetings.execution import Apply
from app.meetings.proposals import FrozenChange, propose

BASE = {
    "amount": None,
    "currency": "CNY",
    "expected_close_date": None,
    "priority": "MEDIUM",
    "source": "UNKNOWN",
    "primary_contact_id": None,
}


def test_budget_and_missing_currency_never_invent_estimated_amount():
    changes, _ = propose("预算：1000 USD", BASE)
    assert not changes
    changes, limits = propose("预计金额：1000", BASE)
    assert not changes and limits
    changes, _ = propose("预计金额：0\n币种：USD", BASE)
    assert changes[0]["values"] == {"amount": "0.00", "currency": "USD"}
    assert set(changes[0]["before"]) == {"amount", "currency"}


@pytest.mark.parametrize(
    "field",
    [
        "stage",
        "owner_id",
        "account_id",
        "probability",
        "weighted_amount",
        "actual_amount",
        "close_evidence_id",
        "role",
    ],
)
def test_forbidden_fields_cannot_be_frozen(field):
    with pytest.raises(ValueError):
        FrozenChange(
            id=uuid4(),
            kind="FIELD",
            before={field: "before"},
            values={field: "after"},
            evidence=[{"start": 0, "end": 1, "quote": "x"}],
        )


def test_unknown_cannot_clear_known_data_or_split_money_group():
    for before, values in [
        ({"amount": "1.00", "currency": "CNY"}, {"amount": None, "currency": "CNY"}),
        ({"amount": "1.00"}, {"amount": "2.00"}),
    ]:
        with pytest.raises(ValueError):
            FrozenChange(
                id=uuid4(),
                kind="FIELD",
                before=before,
                values=values,
                evidence=[{"start": 0, "end": 1, "quote": "x"}],
            )


def test_relative_dates_need_anchor_and_show_conversion():
    changes, limits = propose("预计成交日期：明天", BASE)
    assert not changes and limits
    changes, _ = propose("预计成交日期：明天", BASE, date(2026, 10, 28), "Asia/Hong_Kong")
    assert changes[0]["values"] == {"expected_close_date": "2026-10-29"}
    assert changes[0]["evidence"][0]["quote"] == "明天" and changes[0]["normalization"]


def test_task_requires_explicit_owner_and_due_time_and_rejects_dst_ambiguity():
    changes, limits = propose("任务：Synthetic task", BASE)
    assert not changes and limits
    text = f"任务：Synthetic task\n任务负责人ID：{uuid4()}\n任务截止：明天 17:30"
    changes, _ = propose(text, BASE, date(2026, 10, 28), "Asia/Hong_Kong")
    assert (
        changes[0]["kind"] == "TASK"
        and changes[0]["values"]["due_at"] == "2026-10-29T17:30:00+08:00"
    )
    changes, limits = propose(
        text.replace("17:30", "01:30"), BASE, date(2026, 10, 31), "America/New_York"
    )
    assert not changes and limits


@pytest.mark.parametrize("confirmation", [False, 1, "true", None])
def test_apply_requires_real_explicit_boolean_confirmation(confirmation):
    with pytest.raises(ValueError):
        Apply(
            expected_version=2,
            expected_opportunity_version=1,
            selected_change_ids=[uuid4()],
            confirmed=confirmation,
        )


def test_apply_rejects_duplicate_or_empty_selection():
    selected = uuid4()
    for ids in [[], [selected, selected]]:
        with pytest.raises(ValueError):
            Apply(
                expected_version=2,
                expected_opportunity_version=1,
                selected_change_ids=ids,
                confirmed=True,
            )


def test_duplicate_amount_labels_are_not_silently_resolved():
    changes, limits = propose("预计金额：100\n预计金额：200\n币种：CNY", BASE)
    assert not changes and limits


@pytest.mark.parametrize("invalid", ["", "x" * 2001], ids=["empty", "too-long"])
@pytest.mark.parametrize("label", ["预计金额", "币种"])
def test_invalid_duplicate_money_labels_cannot_hide_an_ambiguous_group(invalid, label):
    changes, limits = propose(f"预计金额：100\n币种：USD\n{label}：{invalid}", BASE)
    assert not changes and limits


@pytest.mark.parametrize("label", ["预计成交日期", "任务截止"])
def test_relative_date_overflow_is_reported_without_losing_other_valid_items(label):
    text = "备注：Synthetic valid note\n"
    if label == "预计成交日期":
        text += "预计成交日期：明天"
    else:
        text += f"任务：Synthetic task\n任务负责人ID：{uuid4()}\n任务截止：明天 12:00"
    changes, limits = propose(text, BASE, date(9999, 12, 31), "Asia/Hong_Kong")
    assert len(changes) == 1 and changes[0]["kind"] == "NOTE" and limits
