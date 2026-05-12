"""
Tests for api_schema.py — OpenAPI schema generation.
"""

import pytest
from rest_framework import serializers

from peeringdb_server.api_schema import BaseSchema


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
