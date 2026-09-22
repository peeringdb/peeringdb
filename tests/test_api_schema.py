"""
Tests for api_schema.py — OpenAPI schema generation.
"""

import pathlib
import re

import pytest
from django.conf import settings as dj_settings
from rest_framework import serializers

from peeringdb_server import meta_registry
from peeringdb_server.api_schema import BaseSchema, CustomSchemaGenerator


class _FakeSerializer(serializers.Serializer):
    foo = serializers.SerializerMethodField()
    bar = serializers.SerializerMethodField()
    baz = serializers.SerializerMethodField()
    unannotated = serializers.SerializerMethodField()

    def get_foo(self, obj) -> int:
        return 0

    def get_bar(self, obj) -> bool:
        return False

    def get_baz(self, obj) -> float:
        return 0.0

    def get_unannotated(self, obj):
        return "something"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field_name,expected_type",
    [
        ("foo", "integer"),
        ("bar", "boolean"),
        ("baz", "number"),
    ],
)
def test_map_field_infers_type_from_annotation(field_name, expected_type):
    """
    map_field should return the correct OpenAPI type for SerializerMethodFields
    whose get_* methods have return type annotations.
    """
    schema = BaseSchema()
    serializer = _FakeSerializer()
    field = serializer.fields[field_name]

    result = schema.map_field(field)

    assert result == {"type": expected_type}


@pytest.mark.django_db
def test_map_field_fallthrough_without_annotation():
    """
    map_field should fall through to DRF default when get_* has no annotation.
    Current DRF returns {'type': 'string'} for unannotated SerializerMethodField.
    """
    schema = BaseSchema()
    serializer = _FakeSerializer()
    field = serializer.fields["unannotated"]

    result = schema.map_field(field)

    assert result == {"type": "string"}


@pytest.mark.django_db
def test_object_metadata_docs_are_rendered_into_the_schema():
    """
    #1751: docs/api/object_metadata.md has to reach API consumers.

    API_DOC_INCLUDES indexes every docs/api/*.md, but only `obj_<tag>` and
    `op_<type>` are ever looked up -- so a page named anything else is never
    rendered anywhere. The metadata reference is therefore appended to the
    description of the object types that carry a `meta` document.
    """
    generator = CustomSchemaGenerator(urlconf="mainsite.urls")
    schema = generator.get_schema(request=None, public=True)

    for tag in meta_registry.PARTICIPATING_MODELS:
        descriptions = [
            operation.get("description", "")
            for path, methods in schema["paths"].items()
            if path.rstrip("/").endswith(f"/{tag}")
            for operation in methods.values()
        ]
        assert descriptions, tag
        for description in descriptions:
            assert "## Object metadata" in description, tag
            # the whole page, not just its heading: the launch-key catalog
            # and the "a non-filterable key silently returns the unfiltered
            # list" warning are the parts written for API consumers
            assert "Registered keys only" in description, tag
            assert "unrecognized filter parameter is ignored" in description, tag

    # an object type that carries no `meta` document does not get the page
    fac_descriptions = [
        operation.get("description", "")
        for path, methods in schema["paths"].items()
        if path.rstrip("/").endswith("/fac")
        for operation in methods.values()
    ]
    assert fac_descriptions
    assert all("## Object metadata" not in d for d in fac_descriptions)


@pytest.mark.django_db
def test_api_docs_carry_no_relative_markdown_links():
    """
    A `[text](other.md)` link in docs/api/ resolves against the apidocs URL
    when the page is rendered into a schema description, so it 404s. Cross
    references have to be inlined instead.
    """
    for page in pathlib.Path(dj_settings.API_DOC_PATH).glob("*.md"):
        assert not re.search(r"\]\([^)]*\.md\)", page.read_text()), page.name
