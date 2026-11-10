"""Small labelled-text extractor, explicitly RULES, never a simulated Internet/LLM result."""

import re
from datetime import datetime
from decimal import Decimal

from app.core.errors import AppError

LABELS = {
    "采购人": "buyer",
    "采购单位": "buyer",
    "项目": "project",
    "项目名称": "project",
    "采购代理": "agency",
    "品类": "category",
    "需求": "need",
    "公告类型": "notice_type",
    "预算": "budget",
    "截止时间": "deadline",
    "地区": "region",
}
NOTICES = {
    "采购意向": "INTENT",
    "采购公告": "PROCUREMENT",
    "招标公告": "PROCUREMENT",
    "更正公告": "CORRECTION",
    "终止公告": "CANCELLED",
    "中标公告": "AWARDED",
    "企业动态": "NEWS",
}


def extract(text, profile, source_id, source_hash):
    facts, position = {}, 0
    for line in text.splitlines(keepends=True):
        for label, name in LABELS.items():
            match = re.match(re.escape(label) + r"[:：](.*)", line)
            if match:
                if name in facts:
                    raise AppError(422, "AMBIGUOUS_MATERIAL", "重复标签或多项目资料请拆分后核验。")
                value = match[1].strip()
                if not value or len(value) > 2000:
                    raise AppError(422, "INVALID_MATERIAL_FIELD", "标签值为空或超长，请核对。")
                start = position + line.index(value, len(label) + 1)
                facts[name] = {
                    "value": value,
                    "kind": "FACT",
                    "evidence": {
                        "material_id": source_id,
                        "sha256": source_hash,
                        "quote": value,
                        "start": start,
                        "end": start + len(value),
                    },
                }
        position += len(line)
    if any(name not in facts for name in ["buyer", "project"]):
        raise AppError(
            422,
            "MATERIAL_NEEDS_LABELS",
            "D1规则提取需要采购人和项目标签；不会根据普通文章补造事实。",
        )
    if any(len(facts[name]["value"]) > 200 for name in ["buyer", "project"]):
        raise AppError(422, "INVALID_MATERIAL_FIELD", "采购人或项目名称不能超过200字符。")
    notice = NOTICES.get(facts.get("notice_type", {}).get("value"), "UNKNOWN")
    budget = None
    if "budget" in facts:
        matched = re.fullmatch(
            r"([0-9]{1,12}(?:\.[0-9]{1,2})?)\s*(万元|元)\s*(CNY|人民币)?", facts["budget"]["value"]
        )
        if matched:
            amount = Decimal(matched[1]) * (10000 if matched[2] == "万元" else 1)
            budget = {
                "value": str(amount.quantize(Decimal("0.01"))),
                "currency": "CNY" if matched[3] else None,
                "unit": matched[2],
                "scope": "SOURCE_BUDGET_ONLY",
            }
    deadline = None
    if "deadline" in facts:
        try:
            parsed = datetime.fromisoformat(facts["deadline"]["value"])
            if parsed.tzinfo is not None:
                deadline = parsed.isoformat()
        except ValueError:
            pass
    demand = " ".join(
        facts.get(name, {}).get("value", "") for name in ["category", "need", "project"]
    )
    matched_keywords = [
        word for word in profile["keywords"] if word.casefold() in demand.casefold()
    ]
    return {
        "mode": "RULES",
        "rule_version": "medical-labelled-v1",
        "profile_version": profile["version"],
        "facts": facts,
        "notice_type": notice,
        "budget": budget,
        "deadline": deadline,
        "matched_keywords": matched_keywords,
        "qualification": "NOT_VERIFIED",
        "limitations": [
            "标签规则提取，不是互联网搜索或真实模型理解。",
            "关键词匹配不代表技术、资质或投标资格通过。",
            "公告预算不是商机预计金额或实际成交金额。",
        ],
    }
