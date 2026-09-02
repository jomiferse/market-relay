"""Automatic validation of the v1 contract's OpenAPI schema (tasks.md 5.1).

`specs/consumer-api/spec.md` requires a versioned contract with structured
errors. This module checks that the generated OpenAPI document is valid
and that real API responses comply with the published `schema` for each
operation — so a change that breaks the contract (a renamed field, an
altered type) fails in CI before reaching Holdria.
"""

from __future__ import annotations

from datetime import date
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from jsonschema import RefResolver
from jsonschema.validators import Draft202012Validator

from tests.factories import approve_publication, create_equity_listing, record_observation


def _auth(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


@pytest.fixture
def openapi_schema(api_client: TestClient) -> dict[str, Any]:
    response = api_client.get("/openapi.json")
    assert response.status_code == 200
    return cast("dict[str, Any]", response.json())


def test_openapi_document_has_required_top_level_fields(openapi_schema: dict[str, Any]) -> None:
    assert openapi_schema["openapi"].startswith("3.")
    assert openapi_schema["info"]["title"] == "MarketRelay"
    assert openapi_schema["info"]["version"] == "1.0.0"
    assert "/v1/instruments/search" in openapi_schema["paths"]
    assert "/v1/listings/{listing_id}/observations/latest" in openapi_schema["paths"]
    assert "/v1/listings/{listing_id}/observations" in openapi_schema["paths"]
    assert "/v1/status/operations" in openapi_schema["paths"]


def test_openapi_document_documents_auth_error_responses(openapi_schema: dict[str, Any]) -> None:
    search_get = openapi_schema["paths"]["/v1/instruments/search"]["get"]
    assert "401" in search_get["responses"]
    assert "403" in search_get["responses"]


def _validator_for(
    openapi_schema: dict[str, Any], path: str, method: str, status_code: str
) -> Draft202012Validator:
    """Extracts the `schema` of an OpenAPI operation/status and returns a
    validator able to resolve its `$ref`s from `#/components/schemas/...`
    against the document itself.
    """

    operation = openapi_schema["paths"][path][method]
    schema = operation["responses"][status_code]["content"]["application/json"]["schema"]
    resolver = RefResolver.from_schema(openapi_schema)
    return Draft202012Validator(schema, resolver=resolver)


def test_search_response_body_validates_against_its_openapi_schema(
    openapi_schema: dict[str, Any], api_client: TestClient, db_session, holdria_api_key: str
) -> None:
    create_equity_listing(db_session)

    response = api_client.get("/v1/instruments/search", headers=_auth(holdria_api_key))
    assert response.status_code == 200

    validator = _validator_for(openapi_schema, "/v1/instruments/search", "get", "200")
    validator.validate(response.json())


def test_latest_observation_response_body_validates_against_its_openapi_schema(
    openapi_schema: dict[str, Any], api_client: TestClient, db_session, holdria_api_key: str
) -> None:
    listing = create_equity_listing(db_session)
    approve_publication(db_session, "fake")
    record_observation(db_session, listing, session_date=date(2026, 1, 5))

    response = api_client.get(
        f"/v1/listings/{listing.id}/observations/latest", headers=_auth(holdria_api_key)
    )
    assert response.status_code == 200

    validator = _validator_for(
        openapi_schema, "/v1/listings/{listing_id}/observations/latest", "get", "200"
    )
    validator.validate(response.json())


def test_unauthenticated_error_response_body_validates_against_its_openapi_schema(
    openapi_schema: dict[str, Any], api_client: TestClient
) -> None:
    response = api_client.get("/v1/instruments/search")
    assert response.status_code == 401

    validator = _validator_for(openapi_schema, "/v1/instruments/search", "get", "401")
    validator.validate(response.json())
