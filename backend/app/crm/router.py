from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.auth.dependencies import current_identity
from app.crm.models import Account, Contact
from app.crm.schemas import (
    AccountCreate,
    AccountListResponse,
    AccountPatch,
    AccountQuery,
    AccountResponse,
    ContactCreate,
    ContactListResponse,
    ContactPatch,
    ContactQuery,
    ContactResponse,
    ListQuery,
)
from app.crm.service import CRMService

router = APIRouter(tags=["CRM accounts and contacts"])


def service(request: Request):
    return CRMService(request.app.state.db)


def writer(request: Request, identity=Depends(current_identity)):
    request.app.state.auth.origin(request.headers.get("origin"))
    request.app.state.auth.check_csrf(identity, request.headers.get("x-csrf-token"))
    return identity


def result(request, data):
    return {"data": data, "request_id": request.state.request_id}


def listing(request, model, query, account_id=None):
    data, total = service(request).listing(model, query, account_id)
    return {
        **result(request, data),
        "page": {
            "number": query.page,
            "size": query.page_size,
            "total": total,
        },
    }


@router.get("/accounts", response_model=AccountListResponse)
def accounts(
    request: Request, query: Annotated[AccountQuery, Query()], _identity=Depends(current_identity)
):
    return listing(request, Account, query)


@router.post("/accounts", status_code=201, response_model=AccountResponse)
def create_account(body: AccountCreate, request: Request, identity=Depends(writer)):
    return result(
        request, service(request).create(Account, body, identity, request.state.request_id)
    )


@router.get("/accounts/{entity_id}", response_model=AccountResponse)
def account_detail(entity_id: UUID, request: Request, _identity=Depends(current_identity)):
    return result(request, service(request).detail(Account, str(entity_id)))


@router.patch("/accounts/{entity_id}", response_model=AccountResponse)
def patch_account(entity_id: UUID, body: AccountPatch, request: Request, identity=Depends(writer)):
    return result(
        request,
        service(request).patch(Account, str(entity_id), body, identity, request.state.request_id),
    )


@router.get("/accounts/{entity_id}/contacts", response_model=ContactListResponse)
def account_contacts(
    entity_id: UUID,
    request: Request,
    query: Annotated[ListQuery, Query()],
    _identity=Depends(current_identity),
):
    contacts_query = ContactQuery(**query.model_dump())
    return listing(request, Contact, contacts_query, str(entity_id))


@router.get("/contacts", response_model=ContactListResponse)
def contacts(
    request: Request, query: Annotated[ContactQuery, Query()], _identity=Depends(current_identity)
):
    return listing(request, Contact, query)


@router.post("/contacts", status_code=201, response_model=ContactResponse)
def create_contact(body: ContactCreate, request: Request, identity=Depends(writer)):
    return result(
        request, service(request).create(Contact, body, identity, request.state.request_id)
    )


@router.get("/contacts/{entity_id}", response_model=ContactResponse)
def contact_detail(entity_id: UUID, request: Request, _identity=Depends(current_identity)):
    return result(request, service(request).detail(Contact, str(entity_id)))


@router.patch("/contacts/{entity_id}", response_model=ContactResponse)
def patch_contact(entity_id: UUID, body: ContactPatch, request: Request, identity=Depends(writer)):
    return result(
        request,
        service(request).patch(Contact, str(entity_id), body, identity, request.state.request_id),
    )
