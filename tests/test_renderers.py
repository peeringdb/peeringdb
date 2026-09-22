"""API response envelopes must preserve object metadata validation errors."""

import json

import pytest
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from peeringdb_server.meta_registry import validate_meta
from peeringdb_server.renderers import MetaJSONRenderer

pytestmark = pytest.mark.django_db


def render(data, status=400, **kwargs):
    return json.loads(
        MetaJSONRenderer().render(
            data, renderer_context={"response": Response(status=status)}, **kwargs
        )
    )


@pytest.mark.parametrize(
    "tag,document",
    [
        ("net", {"unregistered_key": True}),
        ("net", {"rtbh_community": "not-a-community"}),
        ("netixlan", {"rfc8950": "not-a-boolean"}),
        ("net", "not-an-object"),
    ],
)
def test_metadata_validation_details_survive_rendering(tag, document):
    with pytest.raises(ValidationError) as error:
        validate_meta(tag, document)
    expected = error.value.detail["meta"]

    result = render(error.value.detail)

    assert result == {
        "meta": {"error": "Bad Request", "field_errors": {"meta": expected}}
    }


def test_metadata_errors_preserve_other_errors_and_response_metadata():
    result = render(
        {
            "meta": ["Invalid JSON."],
            "name": ["This field is required."],
            "non_field_errors": ["Another validation error."],
            "detail": "Invalid input.",
            "__meta": {"request_id": "test-request"},
        }
    )

    assert result == {
        "name": ["This field is required."],
        "non_field_errors": ["Another validation error."],
        "meta": {
            "request_id": "test-request",
            "error": "Invalid input.",
            "field_errors": {"meta": ["Invalid JSON."]},
        },
    }


def test_ordinary_field_errors_keep_the_existing_response_shape():
    assert render({"name": ["This field is required."]}) == {
        "name": ["This field is required."],
        "meta": {"error": "Bad Request"},
    }


def test_successful_object_metadata_stays_in_data():
    document = {"id": 1, "meta": {"rtbh_community": "65000:666"}}
    assert render(document, status=200) == {"data": [document], "meta": {}}
