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
from peeringdb_server.rest import REFTAG_MAP

# Components that legitimately expose no properties at all. `ASSet` is generated
# from ASSetSerializer, whose Meta.fields is empty, so there is nothing to document.
EMPTY_COMPONENTS = {"ASSet"}

# Properties knowingly shipped without a description. Keep this empty -- an entry
# here is a documentation gap, not a fix. Format: "Component.property".
UNDOCUMENTED_ALLOWLIST: set[str] = set()


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


@pytest.fixture(scope="module")
def generated_schema():
    """
    The real openapi schema, built through the same generator the
    `generateschema` management command uses.
    """
    return CustomSchemaGenerator().get_schema()


@pytest.mark.django_db
def test_every_schema_property_is_documented(generated_schema):
    """
    Every property of every component must carry a non-empty `description`.

    The description comes from a field's `help_text` and nothing else, so a new
    field without help_text lands in the public API docs as a bare type. Adding
    help_text on the model or the serializer field is the fix; see #1981.
    """
    schemas = generated_schema["components"]["schemas"]

    undocumented = sorted(
        f"{component}.{name}"
        for component, definition in schemas.items()
        for name, prop in (definition.get("properties") or {}).items()
        if not (isinstance(prop, dict) and prop.get("description"))
    )
    undocumented = [u for u in undocumented if u not in UNDOCUMENTED_ALLOWLIST]

    assert not undocumented, (
        f"{len(undocumented)} openapi properties have no description.\n"
        "Add help_text to the model field, or to the serializer field when it is "
        "declared explicitly:\n  " + "\n  ".join(undocumented)
    )


@pytest.mark.django_db
def test_schema_components_are_not_empty(generated_schema):
    """
    Guards the test above: a component that loses all of its properties would
    otherwise pass the documentation check by having nothing left to check.
    """
    schemas = generated_schema["components"]["schemas"]

    empty = {name for name, d in schemas.items() if not (d.get("properties") or {})}

    assert empty == EMPTY_COMPONENTS, (
        f"components with no properties changed: expected {sorted(EMPTY_COMPONENTS)}, "
        f"got {sorted(empty)}"
    )


@pytest.mark.django_db
def test_non_filtering_views_advertise_no_query_params(generated_schema):
    """
    A list endpoint that builds its own queryset and ignores `request.query_params`
    must not advertise filter/pagination parameters.

    Documenting them tells API consumers a filter exists when the view silently
    drops it, which is worse than documenting nothing. Viewsets opt in by
    inheriting `peeringdb_server.rest.ModelViewSet`, which sets
    `supports_query_filters` and applies the params in get_queryset().
    """
    generator = CustomSchemaGenerator()
    generator._initialise_endpoints()
    _, endpoints = generator._get_paths_and_endpoints(None)

    offenders = []
    for path, method, view in endpoints:
        if getattr(view, "supports_query_filters", False):
            continue

        operation = generated_schema["paths"].get(path, {}).get(method.lower())
        if not operation:
            continue

        params = [
            p["name"] for p in operation.get("parameters", []) if p.get("in") == "query"
        ]
        if params:
            offenders.append(f"{method} {path} -> {', '.join(sorted(params))}")

    assert not offenders, (
        "these views ignore query params but the schema advertises them:\n  "
        + "\n  ".join(sorted(offenders))
        + "\n\nEither the view should apply them, or it should not inherit "
        "`supports_query_filters`."
    )


@pytest.mark.django_db
def test_relation_filters_only_traverse_api_models(generated_schema):
    """
    `<relation>__<field>` query params must only reach models that are exposed
    as their own endpoint.

    Traversing into an internal model documents every one of its columns as a
    filter -- `ix` reaches the user table through `ixf_import_request_user`,
    which put the password hash column in the public API docs.
    """
    api_tags = set(REFTAG_MAP)

    # relation filters whose target model is not itself an API endpoint
    internal = set()
    for viewset in REFTAG_MAP.values():
        serializer = viewset.serializer_class
        for name, fld in serializer.queryable_relations():
            model = getattr(fld, "model", None)
            tag = getattr(getattr(model, "HandleRef", None), "tag", None)
            if tag not in api_tags:
                internal.add(name)

    assert internal, (
        "expected some internal relations to exist, test is not exercising anything"
    )

    documented = {
        param["name"]
        for operations in generated_schema["paths"].values()
        for operation in operations.values()
        if isinstance(operation, dict)
        for param in operation.get("parameters", [])
        if param.get("in") == "query"
    }

    leaked = sorted(documented & internal)
    assert not leaked, (
        "these query params traverse into models that are not part of the API "
        "and must not be documented:\n  " + "\n  ".join(leaked)
    )
