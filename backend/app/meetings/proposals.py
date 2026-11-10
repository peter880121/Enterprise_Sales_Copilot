"""Explicit synthetic proposal grammar; never infer CRM amount from a customer budget."""

import re
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from app.meetings.schemas import Evidence, Input
from app.sales.schemas import OpportunityPatch

FIELDS = frozenset(
    {"amount", "currency", "expected_close_date", "priority", "source", "primary_contact_id"}
)


class FrozenChange(Input):
    id: UUID
    kind: Literal["FIELD", "NOTE", "TASK"]
    before: dict[str, Any]
    values: dict[str, Any]
    evidence: list[Evidence] = Field(min_length=1, max_length=10)
    basis: Literal["FACT"] = "FACT"
    normalization: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def whitelist(self):
        if self.kind == "FIELD":
            if (
                not self.values
                or not set(self.values) <= FIELDS
                or set(self.values) != set(self.before)
            ):
                raise ValueError("only approved fields may be frozen")
            if set(self.values) & {"amount", "currency"} and set(self.values) != {
                "amount",
                "currency",
            }:
                raise ValueError("amount and currency must be one indivisible change")
            if any(
                value is None and self.before.get(key) is not None
                for key, value in self.values.items()
            ):
                raise ValueError("missing information cannot clear existing fields")
            self.values = OpportunityPatch(expected_version=1, **self.values).model_dump(
                mode="json", exclude_unset=True, exclude={"expected_version"}
            )
        else:
            required = {"subject", "content"} | (
                {"due_at", "assignee_id"} if self.kind == "TASK" else set()
            )
            if set(self.values) != required or self.before:
                raise ValueError("activity proposal has unexpected fields")
            if (
                not isinstance(self.values["subject"], str)
                or not 1 <= len(self.values["subject"].strip()) <= 200
            ):
                raise ValueError("activity subject required")
            if (
                not isinstance(self.values["content"], str)
                or not 1 <= len(self.values["content"].strip()) <= 2000
            ):
                raise ValueError("activity content required")
            if self.kind == "TASK":
                due = datetime.fromisoformat(self.values["due_at"])
                if due.tzinfo is None:
                    raise ValueError("task due time must have explicit timezone")
                self.values["due_at"] = due.isoformat()
                self.values["assignee_id"] = str(UUID(self.values["assignee_id"]))
        return self

    def verify_source(self, text):
        for evidence in self.evidence:
            if (
                not evidence.start < evidence.end <= len(text)
                or text[evidence.start : evidence.end] != evidence.quote
            ):
                raise ValueError("proposal evidence does not match source")
        return self


def relative_day(value, meeting_date: date | None):
    days = {"明天": 1, "后天": 2}.get(value)
    match = re.fullmatch(r"([1-9][0-9]{0,2})天后", value)
    if match:
        days = int(match[1])
    if days is None:
        return None
    if meeting_date is None:
        raise ValueError("relative date needs a meeting date")
    try:
        return meeting_date + timedelta(days=days)
    except OverflowError:
        raise ValueError("relative date is outside the supported calendar") from None


def propose(text, base, meeting_date=None, timezone="Asia/Hong_Kong"):
    labels = {
        "预计金额": "amount",
        "币种": "currency",
        "预计成交日期": "expected_close_date",
        "优先级": "priority",
        "来源": "source",
        "主要联系人ID": "primary_contact_id",
        "备注": "note",
        "任务": "task",
        "任务截止": "due_at",
        "任务负责人ID": "assignee_id",
    }
    found, offset = {}, 0
    for line in text.splitlines(keepends=True):
        for label, name in labels.items():
            for separator in ("：", ":"):
                prefix = label + separator
                if line.startswith(prefix):
                    value = line[len(prefix) :].strip()
                    # Count every recognized label before validating its value. A blank or
                    # oversized duplicate must not silently make an ambiguous group executable.
                    start = offset + line.index(value, len(prefix))
                    found.setdefault(name, []).append(
                        (value, {"start": start, "end": start + len(value), "quote": value})
                    )
        offset += len(line)
    limitations, changes = [], []
    ambiguous = {name for name, values in found.items() if len(values) != 1}
    for name in ambiguous:
        limitations.append(f"重复标签 {name} 有歧义，未生成可执行项。")

    def value(name):
        return found[name][0][0]

    def evidence(names):
        return [found[name][0][1] for name in names]

    def add(kind, before, values, names, normalization=None):
        try:
            change = FrozenChange(
                id=uuid4(),
                kind=kind,
                before=before,
                values=values,
                evidence=evidence(names),
                normalization=normalization,
            )
            change.verify_source(text)
            if kind != "FIELD" or change.values != before:
                changes.append(change.model_dump(mode="json"))
        except (ValueError, TypeError, KeyError):
            limitations.append(f"{','.join(names)} 格式或必要信息不完整，未生成可执行项。")

    money = [name for name in ("amount", "currency") if name in found]
    if money:
        if any(name in ambiguous for name in money):
            limitations.append("金额/币种组合有歧义，整组不可执行。")
        elif "amount" in money and "currency" not in money:
            limitations.append("预计金额必须同时明确币种，未根据预算或默认值补齐。")
        else:
            before = {name: base[name] for name in ("amount", "currency")}
            add("FIELD", before, {**before, **{name: value(name) for name in money}}, money)
    for name in ("expected_close_date", "priority", "source", "primary_contact_id"):
        if name in found and name not in ambiguous:
            proposed = value(name)
            normalization = None
            if name == "expected_close_date":
                try:
                    ZoneInfo(timezone)
                    converted = relative_day(proposed, meeting_date)
                    if converted:
                        proposed = converted.isoformat()
                        normalization = (
                            f"依据会议日期 {meeting_date} 与时区 {timezone} 换算相对日期。"
                        )
                except (ValueError, KeyError):
                    limitations.append("相对日期缺少可靠会议日期/时区，不自动补齐。")
                    continue
            add("FIELD", {name: base[name]}, {name: proposed}, [name], normalization)
    if "note" in found and "note" not in ambiguous:
        add("NOTE", {}, {"subject": value("note")[:200], "content": value("note")}, ["note"])
    if "task" in found:
        names = ["task", "due_at", "assignee_id"]
        if all(name in found and name not in ambiguous for name in names):
            due = value("due_at")
            normalization = None
            relative = re.fullmatch(r"(明天|后天|[1-9][0-9]{0,2}天后)\s+(\d{2}:\d{2})", due)
            if relative:
                try:
                    zone = ZoneInfo(timezone)
                    converted = datetime.combine(
                        relative_day(relative[1], meeting_date), time.fromisoformat(relative[2])
                    ).replace(tzinfo=zone)
                    if converted.utcoffset() != converted.replace(
                        fold=1
                    ).utcoffset() or converted.astimezone(UTC).astimezone(zone).replace(
                        tzinfo=None
                    ) != converted.replace(tzinfo=None):
                        raise ValueError("ambiguous local time")
                    due = converted.isoformat()
                    normalization = (
                        f"依据会议日期 {meeting_date} 与时区 {timezone} 换算任务截止时间。"
                    )
                except (ValueError, TypeError, KeyError):
                    limitations.append("任务相对截止时间无可靠基准或存在时区歧义，未生成可执行项。")
                    return changes, limitations
            add(
                "TASK",
                {},
                {
                    "subject": value("task"),
                    "content": value("task"),
                    "due_at": due,
                    "assignee_id": value("assignee_id"),
                },
                names,
                normalization,
            )
        else:
            limitations.append("任务缺明确负责人、截止时间或存在歧义，不自动补齐。")
    return changes, limitations
