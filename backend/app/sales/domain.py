from decimal import ROUND_HALF_UP, Decimal

from app.core.errors import AppError

PROBABILITY = {
    "PROPOSAL_SUBMITTED": 20,
    "NEGOTIATION": 60,
    "FOLLOW_UP": 40,
    "WON": 100,
    "LOST": 0,
}
OPEN = frozenset(PROBABILITY) - {"WON", "LOST"}
EDGES = {
    ("PROPOSAL_SUBMITTED", "NEGOTIATION"),
    ("PROPOSAL_SUBMITTED", "FOLLOW_UP"),
    ("NEGOTIATION", "FOLLOW_UP"),
    ("FOLLOW_UP", "NEGOTIATION"),
    ("NEGOTIATION", "WON"),
    ("NEGOTIATION", "LOST"),
    ("FOLLOW_UP", "WON"),
    ("FOLLOW_UP", "LOST"),
}


def weighted(amount, stage):
    if amount is None:
        return None
    return (amount * Decimal(PROBABILITY[stage]) / 100).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def transition(current, target):
    if current not in OPEN:
        raise AppError(422, "TERMINAL_OPPORTUNITY", "终态商机不能直接变更阶段。")
    if (current, target) not in EDGES:
        raise AppError(422, "INVALID_STAGE_TRANSITION", "不允许此阶段转换。")


def validate_evidence(evidence, opportunity):
    if (
        evidence is None
        or evidence.opportunity_id != opportunity.id
        or evidence.status != "VERIFIED"
        or evidence.amount <= 0
        or not evidence.reviewed_by
        or evidence.reviewed_by == evidence.submitted_by
        or evidence.type not in {"SIGNED_CONTRACT", "PURCHASE_ORDER", "OTHER_APPROVED"}
    ):
        raise AppError(422, "EVIDENCE_INVALID", "请选择有效且由另一位有权限用户核验的证据。")
    if evidence.currency != opportunity.currency:
        raise AppError(422, "EVIDENCE_CURRENCY_MISMATCH", "证据与商机币种必须一致。")
    if evidence.type == "OTHER_APPROVED":
        raise AppError(409, "OTHER_APPROVAL_POLICY_PENDING", "其他成交依据的审批责任仍待确认。")
