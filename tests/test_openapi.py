"""openapi.yaml 0.2.0 (ARCH-02): the contract is valid OpenAPI, every example passes
as the request or response it documents, and the app serves exactly its routes.
The mock (ARCH-01) and spacey's unit tests are built from these examples, so each
one is checked with openapi-core, the validator the contract tests use."""

import json
import re
from pathlib import Path

import pytest
from openapi_core import OpenAPI
from openapi_core.testing import MockRequest, MockResponse
from openapi_core.validation.request.exceptions import SecurityValidationError
from openapi_core.validation.response.exceptions import InvalidData
from openapi_spec_validator import validate
from openapi_spec_validator.readers import read_from_filename

SPEC, _ = read_from_filename(str(Path(__file__).parent.parent / "openapi.yaml"))
CONTRACT = OpenAPI.from_dict(SPEC)

OPEN = {("GET", "/health"), ("GET", "/openapi.yaml")}
ACCESS_FUNCTIONS = {
    ("POST", "/bookings/{booking_id}/access"),
    ("GET", "/bookings/{booking_id}/access"),
    ("POST", "/bookings/{booking_id}/access/revoke"),
    ("POST", "/bookings/{booking_id}/check-in"),
    ("POST", "/bookings/{booking_id}/check-out"),
    ("POST", "/bookings/{booking_id}/access/expire"),
}
HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


def resolve(node):
    """Follow a local `$ref` ("#/components/...") to what it points at."""
    while "$ref" in node:
        target = SPEC
        for key in node["$ref"].removeprefix("#/").split("/"):
            target = target[key]
        node = target
    return node


def operations():
    for path, item in SPEC["paths"].items():
        for method, operation in item.items():
            if method in HTTP_METHODS:
                yield method.upper(), path, operation


def media_examples(media):
    """Every example of one media type, as (name, value)."""
    if "example" in media:
        yield "example", media["example"]
    for name, example in media.get("examples", {}).items():
        yield name, resolve(example)["value"]


def request_for(method, path, body=None, token=True):
    """The request the contract documents, with the booking id from its example."""
    booking_id = SPEC["components"]["parameters"]["BookingId"]["example"]
    return MockRequest(
        "http://localhost",
        method.lower(),
        path.replace("{booking_id}", str(booking_id)),
        headers={"Authorization": "Bearer test-token"} if token else {},
        data=None if body is None else json.dumps(body).encode(),
    )


def response_for(status, media_type, value):
    data = value if isinstance(value, str) else json.dumps(value)
    return MockResponse(data.encode(), status_code=status, content_type=media_type)


def request_examples():
    for method, path, operation in operations():
        bodies = [(None, None)]
        if "requestBody" in operation:
            content = resolve(operation["requestBody"])["content"]["application/json"]
            bodies = list(media_examples(content))
        for name, body in bodies:
            yield pytest.param(method, path, body, id=f"{method} {path} {name or 'no body'}")


def response_examples():
    for method, path, operation in operations():
        for status, response in operation["responses"].items():
            for media_type, media in resolve(response).get("content", {}).items():
                for name, value in media_examples(media):
                    yield pytest.param(
                        method, path, int(status), media_type, value,
                        id=f"{method} {path} {status} {name}",
                    )


def test_the_contract_is_valid_openapi_0_2_0():
    validate(SPEC)  # raises if it isn't

    assert SPEC["openapi"] == "3.0.3"
    assert SPEC["info"]["version"] == "0.2.0"


def test_it_has_the_6_access_functions_plus_health_and_the_contract():
    assert {(method, path) for method, path, _ in operations()} == ACCESS_FUNCTIONS | OPEN


def test_the_app_serves_exactly_the_contract(app):
    served = set()
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "static":
            continue
        path = re.sub(r"<(?:\w+:)?(\w+)>", r"{\1}", rule.rule)
        served |= {(method, path) for method in rule.methods - {"HEAD", "OPTIONS"}}

    assert served == {(method, path) for method, path, _ in operations()}


def test_the_6_functions_need_the_token_and_document_its_401():
    assert "security" not in SPEC  # no global default: each operation says it
    for method, path, operation in operations():
        if (method, path) in OPEN:
            assert "security" not in operation, (method, path)
        else:
            assert operation["security"] == [{"bearerAuth": []}], (method, path)
            assert "401" in operation["responses"], (method, path)


def test_every_response_has_an_example():
    for method, path, operation in operations():
        for status, response in operation["responses"].items():
            content = resolve(response).get("content")
            assert content, f"{method} {path} {status}: no content"
            for media_type, media in content.items():
                assert list(media_examples(media)), f"{method} {path} {status} {media_type}: no example"


@pytest.mark.parametrize(("method", "path", "body"), request_examples())
def test_every_example_request_is_valid(method, path, body):
    CONTRACT.validate_request(request_for(method, path, body))

    if (method, path) in ACCESS_FUNCTIONS:
        with pytest.raises(SecurityValidationError):
            CONTRACT.validate_request(request_for(method, path, body, token=False))


@pytest.mark.parametrize(("method", "path", "status", "media_type", "value"), response_examples())
def test_every_example_response_matches_its_schema(method, path, status, media_type, value):
    CONTRACT.validate_response(request_for(method, path), response_for(status, media_type, value))


def test_the_record_has_the_4_statuses_and_iso_times():
    schemas = SPEC["components"]["schemas"]
    record = schemas["AccessRecord"]["properties"]

    assert schemas["AccessStatus"]["enum"] == ["available", "used", "expired", "revoked"]
    for time in ("expires_at", "checked_in_at", "checked_out_at", "revoked_at", "expired_at"):
        assert record[time]["format"] == "date-time", time


def test_a_time_without_an_offset_is_refused():
    # Proves the format check runs, so the example tests above check times too.
    record = {**SPEC["components"]["examples"]["Available"]["value"], "expires_at": "2026-10-20T10:00:00"}

    with pytest.raises(InvalidData):
        CONTRACT.validate_response(
            request_for("GET", "/bookings/{booking_id}/access"),
            response_for(200, "application/json", record),
        )


@pytest.mark.parametrize(
    "path", [path for method, path, operation in operations() if "409" in operation["responses"]]
)
def test_every_409_must_carry_the_status(path):
    request = request_for("POST", path)

    with pytest.raises(InvalidData):
        CONTRACT.validate_response(request, response_for(409, "application/json", {"error": "not allowed"}))
