from decimal import Decimal
from itertools import product

import pytest
from pydantic import ValidationError

from app.core.errors import AppError
from app.sales.domain import EDGES, OPEN, PROBABILITY, transition, weighted
from app.sales.files import MAX_BYTES, inspect_pdf
from app.sales.schemas import EvidenceCreate, OpportunityCreate, OpportunityPatch


@pytest.mark.parametrize("current,target", list(product(PROBABILITY, repeat=2)))
def test_all_twenty_five_stage_pairs(current, target):
    if (current, target) in EDGES:
        transition(current, target)
    else:
        with pytest.raises(AppError) as error:
            transition(current, target)
        assert error.value.code == (
            "INVALID_STAGE_TRANSITION" if current in OPEN else "TERMINAL_OPPORTUNITY"
        )


@pytest.mark.parametrize("stage,probability", PROBABILITY.items())
def test_q06_probability_and_unknown_weight(stage, probability):
    assert weighted(None, stage) is None
    assert weighted(Decimal("0.00"), stage) == Decimal("0.00")
    assert weighted(Decimal("100.00"), stage) == Decimal(probability)
    assert weighted(Decimal("0.01"), "NEGOTIATION") == Decimal("0.01")


@pytest.mark.parametrize("value", [0, 1.5, "-1", "1.001", "1e2", "NaN", "", "10000000000000000.00"])
def test_money_rejects_binary_and_invalid_strings(value):
    with pytest.raises(ValidationError):
        OpportunityCreate(
            name="Synthetic", account_id="00000000-0000-0000-0000-000000000001", amount=value
        )


def test_expected_unknown_zero_and_readonly_probability():
    base = {"name": "Synthetic", "account_id": "00000000-0000-0000-0000-000000000001"}
    assert OpportunityCreate(**base).amount is None
    assert OpportunityCreate(**base).currency == "CNY"
    assert OpportunityCreate(**base, amount="0.00").amount == Decimal(0)
    with pytest.raises(ValidationError):
        OpportunityCreate(**base, probability=20)
    with pytest.raises(ValidationError):
        OpportunityPatch(expected_version=1, probability=20)
    with pytest.raises(ValidationError):
        EvidenceCreate(
            stored_object_id=base["account_id"],
            type="SIGNED_CONTRACT",
            reference_number="S",
            customer_legal_name="Synthetic",
            document_date="2026-10-27",
            amount="0.00",
        )


def test_pdf_bytes_limit_and_real_page_validation():
    import io

    from pypdf import PdfWriter

    with pytest.raises(AppError) as invalid:
        inspect_pdf(b"not a PDF")
    assert invalid.value.code == "FILE_TYPE_INVALID"
    with pytest.raises(AppError) as too_big:
        inspect_pdf(b"%PDF-" + b"0" * MAX_BYTES)
    assert too_big.value.status == 413
    writer = PdfWriter()
    for _ in range(101):
        writer.add_blank_page(width=100, height=100)
    buffer = io.BytesIO()
    writer.write(buffer)
    with pytest.raises(AppError) as too_many_pages:
        inspect_pdf(buffer.getvalue())
    assert too_many_pages.value.code == "FILE_TYPE_INVALID"


def test_oversized_chunk_body_uses_the_same_request_id(settings):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/opportunities/00000000-0000-0000-0000-000000000001/evidence-files",
            content=b"x" * (MAX_BYTES + 65537),
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert response.json()["request_id"] == response.headers["x-request-id"]
