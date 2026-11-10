from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.errors import AppError
from app.discovery.schemas import SearchAccept
from app.discovery.search_service import preview_signature, verify_preview


def body(settings, *, timestamp=1000):
    signature = preview_signature(
        settings, "actor", "profile", 7, "Synthetic public query", timestamp
    )
    return SearchAccept(
        expected_profile_version=7,
        public_query="Synthetic public query",
        request_token=uuid4(),
        preview_token=f"{timestamp}:{signature}",
        confirmed_public=True,
    )


def test_public_confirmation_is_strict_and_cannot_add_provider_parameters(settings):
    original = body(settings).model_dump()
    for value in [False, 1, "true"]:
        with pytest.raises(ValidationError):
            SearchAccept(**(original | {"confirmed_public": value}))
    with pytest.raises(ValidationError):
        SearchAccept(**(original | {"search_depth": "advanced"}))


@pytest.mark.parametrize(
    "changed", ["actor", "profile", "query", "version", "timestamp", "endpoint"]
)
def test_signed_preview_binds_identity_version_query_endpoint_and_finite_lifetime(
    settings, changed
):
    request = body(settings)
    actor, profile, clock = "actor", "profile", 1001
    if changed == "actor":
        actor = "another-actor"
    elif changed == "profile":
        profile = "another-profile"
    elif changed == "query":
        request.public_query = "Different public query"
    elif changed == "version":
        request.expected_profile_version = 8
    elif changed == "timestamp":
        clock = 1601
    else:
        settings.tavily_base_url = "https://api.tavily.com"
    with pytest.raises(AppError) as failure:
        verify_preview(settings, actor, profile, request, clock=clock)
    assert failure.value.code == "SEARCH_PREVIEW_STALE"


def test_preview_accepts_valid_boundary_and_rejects_future_clock(settings):
    request = body(settings)
    verify_preview(settings, "actor", "profile", request, clock=1600)
    with pytest.raises(AppError):
        verify_preview(settings, "actor", "profile", request, clock=980)


def test_worker_fencing_rejects_expired_and_superseded_claims():
    from datetime import timedelta

    from app.auth.service import now
    from app.discovery.search_processor import SearchProcessor

    row = SimpleNamespace(
        status="RUNNING", lease_token="token", lease_until=now() + timedelta(seconds=30)
    )
    assert SearchProcessor.valid(row, {"token": "token"})
    assert not SearchProcessor.valid(row, {"token": "other"})
    row.lease_until = now() - timedelta(seconds=1)
    assert not SearchProcessor.valid(row, {"token": "token"})
