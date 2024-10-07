"""
Augment REST API schema to use for open-api schema generation.

open-api schema generation leans heavily on automatic generation
implemented through the django-rest-framework.

Specify custom fields to be added to the generated open-api schema.
"""

import re

from django.conf import settings
from django.utils.translation import gettext as _
from rest_framework import serializers
from rest_framework.schemas.openapi import AutoSchema

from peeringdb_server.serializers import (
    CampusSerializer,
    CarrierSerializer,
    FacilitySerializer,
    InternetExchangeSerializer,
    IXLanSerializer,
    NetworkSerializer,
    OrganizationSerializer,
    RequestAwareListSerializer,
)


class CustomField:
    def __init__(self, typ, help_text=""):
        self.typ = typ
        self.help_text = help_text

    def get_internal_type(self):
        return self.typ


class BaseSchema(AutoSchema):
    """
    Augments the openapi schema generation for
    the peeringdb API docs.
    """

    # map django internal types to openapi types

    numeric_fields = [
        "IntegerField",
        "PositiveIntegerField",
        "DecimalField",
        "DateField",
        "DateTimeField",
        "ForeignKey",
        "AutoField",
    ]

    text_fields = [
        "TextField",
        "CharField",
    ]

    other_fields = [
        "BooleanField",
        "TextSearchField",
        "NumberSearchField",
    ]

    type_map = {
        "ForeignKey": "integer",
        "PositiveIntegerField": "integer",
        "IntegerField": "integer",
        "AutoField": "integer",
        "BooleanField": "boolean",
        "DecimalField": "number",
        "DateTimeField": "date-time",
        "DateField": "date",
        "NumberSearchField": "number",
    }

    serializer_method_field_map = {
        "org": OrganizationSerializer,
        "campus": CampusSerializer,
        "carrier": CarrierSerializer,
        "net": NetworkSerializer,
        "ix": InternetExchangeSerializer,
        "ixlan": IXLanSerializer,
        "fac": FacilitySerializer,
    }

    def map_field(self, field):
        if isinstance(field, serializers.SerializerMethodField):
            serializer = self.serializer_method_field_map.get(field.field_name)
            if serializer:
                serializer_instance = serializer()
                data = self.map_serializer(serializer_instance)
                data["type"] = "object"
                return data

        if isinstance(field, RequestAwareListSerializer):
            mapping = {
                "type": "array",
                "items": {"type": "integer"},
            }
            return mapping
        return super().map_field(field)

    def get_operation_type(self, *args):
        """
        Determine if this is a list retrieval operation.
        """

        method = args[1]

        if method == "GET" and "{id}" not in args[0]:
            return "list"
        elif method == "GET":
            return "retrieve"
        elif method == "POST":
            return "create"
        elif method == "PUT":
            return "update"
        elif method == "DELETE":
            return "delete"
        elif method == "PATCH":
            return "patch"

        return method.lower()

    def get_operation_id(self, path, method):
        """
        Override this so operation ids become "{op} {reftag}"
        """

        serializer, model = self.get_classes(path, method)
        op_type = self.get_operation_type(path, method)

        if model:
            # Overrides for duplicate operations ids

            if "request_ixf_import" in path:
                return f"{op_type} IX-F import request"
            elif "as_set/{asn}" in path:
                return f"{op_type} as-set by asn"
            elif "as_set" in path:
                return f"{op_type} as-set"
            elif "campus" in path and "add-facility" in path:
                return "add facility to campus"
            elif "campus" in path and "remove-facility" in path:
                return "remove facility from campus"
            elif "carrierfac" in path and "approve" in path:
                return "approve facility presence at carrier"
            elif "carrierfac" in path and "reject" in path:
                return "reject facility presence at carrier"
            elif "netixlan" in path and "set-net-side" in path:
                return "set network side"
            elif "netixlan" in path and "set-ix-side" in path:
                return "set ix side"

            return f"{op_type} {model.HandleRef.tag}"

        return super().get_operation_id(path, method)

    def get_operation(self, *args, **kwargs):
        """
        Override this so we can augment the operation dict
        for an openapi schema operation.
        """

        op_dict = super().get_operation(*args, **kwargs)

        op_type = self.get_operation_type(*args)

        # check if we have an augmentation method set for the
        # operation type, if so run it

        augment = getattr(self, f"augment_{op_type}_operation", None)

        if augment:
            augment(op_dict, args)

        # attempt to relate a serializer and a model class to the operation

        serializer, model = self.get_classes(*args)
        if args[0] == "/api/{var}/self":
            return {}

        # Override the the requestBody with components instead of using reference
        components = super().get_components(*args).get(model.__name__)

        content_types = [
            "application/json",
        ]
        # Override schema for create, update and patch operations
        if components and op_type in ["create", "update", "patch"]:
            for content_type in content_types:
                op_dict["requestBody"]["content"][content_type]["schema"] = components

        op_id = op_dict.get("operationId")

        if op_id in [
            "add facility to campus",
            "remove facility from campus",
            "approve facility presence at carrier",
            "reject facility presence at carrier",
        ]:
            op_dict["requestBody"]["content"][content_type]["schema"] = None
            return op_dict

        # if set net side or set ix side, schema expects a fac_id
        elif op_id in ["set network side", "set ix side"]:
            op_dict["requestBody"]["content"][content_type]["schema"] = {
                "type": "object",
                "properties": {
                    "fac_id": {"type": "integer"},
                },
                "required": ["fac_id"],
            }
            return op_dict

        # if we were able to get a model we want to include the markdown documentation
        # for the model type in the openapi description field (docs/api/obj_*.md)

        if model:
            obj_descr_file = settings.API_DOC_INCLUDES.get(
                f"obj_{model.HandleRef.tag}", ""
            )
            if obj_descr_file:
                with open(obj_descr_file) as fh:
                    op_dict["description"] += "\n\n" + fh.read()

            # check if we have an augmentation method set for the operation_type and object type
            # combination, if so run it
            augment = getattr(self, f"augment_{op_type}_{model.HandleRef.tag}", None)
            if augment:
                augment(serializer, model, op_dict)

        # include the markdown documentation for the operation type (docs/api/op_*.md)

        op_descr_file = settings.API_DOC_INCLUDES.get(f"op_{op_type}", "")
        if op_descr_file:
            with open(op_descr_file) as fh:
                op_dict["description"] += "\n\n" + fh.read()

        return op_dict

    def get_classes(self, *op_args):
        """
        Try to relate a serializer and model class to the openapi operation.

        Returns:

        - tuple(serializers.Serializer, models.Model)
        """

        serializer = self.get_serializer(*op_args)
        model = None
        if hasattr(serializer, "Meta"):
            if hasattr(serializer.Meta, "model"):
                model = serializer.Meta.model
        return (serializer, model)

    def augment_retrieve_operation(self, op_dict, op_args):
        """
        Augment openapi schema for single object retrieval.
        """

        parameters = op_dict.get("parameters")
        serializer, model = self.get_classes(*op_args)

        if not model:
            return

        op_dict["description"] = _(
            "Retrieves a single `{obj_type}` type object by id"
        ).format(obj_type=model.HandleRef.tag)

        parameters.append(
            {
                "name": "depth",
                "in": "query",
                "required": False,
                "description": _("Expand nested sets according to depth."),
                "schema": {"type": "integer", "default": 1, "minimum": 0, "maximum": 2},
            }
        )

    def augment_list_operation(self, op_dict, op_args):
        """
        Augment openapi schema for object listings.
        """
        parameters = op_dict.get("parameters")
        serializer, model = self.get_classes(*op_args)

        if not model:
            return

        op_dict["description"] = _(
            "Retrieves a list of `{obj_type}` type objects"
        ).format(obj_type=model.HandleRef.tag)

        parameters.extend(
            [
                {
                    "name": "depth",
                    "in": "query",
                    "required": False,
                    "description": _("Expand nested sets according to depth."),
                    "schema": {
                        "type": "integer",
                        "default": 0,
                        "minimum": 0,
                        "maximum": 2,
                    },
                },
                {
                    "name": "limit",
                    "in": "query",
                    "required": False,
                    "description": _(
                        "Limit the number of rows returned in the result set (use for pagination in combination with `skip`)"
                    ),
                    "schema": {
                        "type": "integer",
                    },
                },
                {
                    "name": "skip",
                    "in": "query",
                    "required": False,
                    "description": _(
                        "Skip n results in the result set (use for pagination in combination with `limit`)"
                    ),
                    "schema": {
                        "type": "integer",
                    },
                },
                {
                    "name": "since",
                    "in": "query",
                    "required": False,
                    "description": _(
                        "Unix epoch time stamp (seconds). Only return objects that have been updated since then"
                    ),
                    "schema": {"type": "integer"},
                },
            ]
        )

        self.augment_list_filters(model, serializer, parameters)
        op_dict.update(parameters=sorted(parameters, key=lambda x: x["name"]))

    def augment_list_filters(self, model, serializer, parameters):
        """
        Further augment openapi schema for object listing by filling
        the query parameter list with all the possible query filters
        for the object.
        """

        field_names = [
            (fld.name, fld) for fld in model._meta.get_fields()
        ] + serializer.queryable_relations()

        custom_filter_fields = getattr(
            self, f"{model.HandleRef.tag}_list_filter_fields", None
        )
        if custom_filter_fields:
            field_names.extend(custom_filter_fields())

        blocked_prefixes = []
        for field, fld in field_names:
            typ = fld.get_internal_type()

            supported_filters = []

            # while sending queries to nested set fields sort of works
            # it's currently not officially supported and results may not
            # be what is expected.
            #
            # hide these query possibilities from the documentation
            blocked = False
            for prefix in blocked_prefixes:
                if field.find(prefix) == 0:
                    blocked = True
                    break

            if blocked:
                continue
            elif typ == "ForeignKey" and (fld.one_to_many or hasattr(fld, "multiple")):
                # mark prefix of nested object as blocked so we
                # don't expose it's fields to the documentation

                blocked_prefixes.append(f"{field}__")
                continue
            elif typ in self.numeric_fields:
                supported_filters = ["`__lt`", "`__gt`", "`__lte`", "`__gte`", "`__in`"]
            elif typ in self.text_fields:
                supported_filters = ["`__startswith`", "`__contains`", "`__in`"]
            elif typ in self.other_fields:
                supported_filters = []
            else:
                continue

            description = [
                _("Filter results by matching a value against this field."),
            ]

            # if field has a help_text set, append it to description

            help_text = getattr(fld, "help_text", None)
            if help_text:
                description.insert(0, f"{help_text}")

            # if field has choices defined, append them to the description

            choices = getattr(fld, "choices", None)
            if choices:
                description.append(
                    "{}".format(", ".join([f"`{_id}`" for _id, label in choices]))
                )

            if supported_filters:
                description.append(
                    _("Supported filter suffixes: {}").format(
                        ", ".join(supported_filters)
                    )
                )

            parameters.append(
                {
                    "name": re.sub(
                        "^facility__", "fac__", re.sub("^network__", "net__", field)
                    ),
                    "in": "query",
                    "description": "\n\n".join(description),
                    "required": False,
                    "schema": {
                        "type": self.type_map.get(typ, "string"),
                    },
                }
            )

    def fac_list_filter_fields(self):
        return [
            (
                "net_count",
                CustomField(
                    "IntegerField", _("Number of networks present at this facility")
                ),
            ),
        ]

    def net_list_filter_fields(self):
        return [
            (
                "name_search",
                CustomField(
                    "TextSearchField",
                    _("Targets both AKA and name fields for filtering"),
                ),
            ),
            (
                "not_ix",
                CustomField(
                    "NumberSearchField",
                    _("Find networks not present at an exchange (exchange id)"),
                ),
            ),
            (
                "ix",
                CustomField(
                    "NumberSearchField",
                    _("Find networks present at exchange (exchange id)"),
                ),
            ),
            (
                "not_fac",
                CustomField(
                    "NumberSearchField",
                    _("Find networks not present at a facility (facility id)"),
                ),
            ),
            (
                "fac",
                CustomField(
                    "NumberSearchField",
                    _("Find networks present at a facility (facility id)"),
                ),
            ),
            (
                "ixlan",
                CustomField(
                    "NumberSearchField",
                    _("Find networks connected at ixlan (ixlan id)"),
                ),
            ),
            (
                "netixlan",
                CustomField(
                    "NumberSearchField",
                    _("Find the network that contains this netixlan (netixlan id)"),
                ),
            ),
            (
                "netfac",
                CustomField(
                    "NumberSearchField",
                    _("Find the network that this netfac belongs to (netfac id)"),
                ),
            ),
        ]

    def ix_list_filter_fields(self):
        return [
            (
                "fac",
                CustomField(
                    "NumberSearchField",
                    _("Find exchanges present at a facility (facility id)"),
                ),
            ),
            (
                "ixlan",
                CustomField(
                    "NumberSearchField",
                    _("Find the exchange that contains this ixlan (ixlan id)"),
                ),
            ),
            (
                "ixfac",
                CustomField(
                    "NumberSearchField",
                    _("Find the exchange that contains this ixfac (ixfac id)"),
                ),
            ),
            (
                "net_count",
                CustomField(
                    "IntegerField", _("Number of networks present at this exchange")
                ),
            ),
            (
                "net",
                CustomField(
                    "NumberSearchField",
                    _("Find exchanges where this network has a presence at (net id)"),
                ),
            ),
        ]

    def org_list_filter_fields(self):
        return [
            (
                "asn",
                CustomField(
                    "NumberSearchField",
                    _("Find organization that contains the network (network asn)"),
                ),
            ),
        ]

    def ixpfx_list_filter_fields(self):
        return [
            (
                "ix",
                CustomField(
                    "NumberSearchField", _("Find prefixes by exchange (exchange id)")
                ),
            ),
            (
                "whereis",
                CustomField("TextSearchField", _("Find prefixes by ip address")),
            ),
        ]

    def netixlan_list_filter_fields(self):
        return [
            ("name", CustomField("CharField", _("Exchange name"))),
        ]

    def netfac_list_filter_fields(self):
        return [
            ("name", CustomField("CharField", _("Facility name"))),
            ("country", CustomField("CharField", _("Facility country"))),
            ("city", CustomField("CharField", _("Facility city"))),
        ]

    def augment_create_operation(self, op_dict, op_args):
        """
        Augment openapi schema for object creation.
        """

        op_dict.get("parameters")
        serializer, model = self.get_classes(*op_args)

        if not model:
            return

        op_dict["description"] = _("Creates a new `{obj_type}` type object.").format(
            obj_type=model.HandleRef.tag
        )

    def request_body_schema(self, op_dict, content="application/json"):
        """
        Helper function that return the request body schema
        for the specified content type.
        """

        return (
            op_dict.get("requestBody", {})
            .get("content", {})
            .get(content, {})
            .get("schema", {})
        )

    def augment_create_ix(self, serializer, model, op_dict):
        """
        Augment openapi schema for create ix operation.
        """
        request_body_schema = self.request_body_schema(op_dict)

        # during creation the `prefix` field should be marked as required
        request_body_schema["required"].extend(["prefix"])

    def augment_update_ix(self, serializer, model, op_dict):
        """
        Augment openapi schema for update ix operation.
        """
        request_body_schema = self.request_body_schema(op_dict)
        properties = request_body_schema["properties"]

        # prefix on `update` will be ignored
        del properties["prefix"]

    def augment_update_fac(self, serializer, model, op_dict):
        """
        Augment openapi schema for update fac operation.
        """
        request_body_schema = self.request_body_schema(op_dict)
        properties = request_body_schema["properties"]

        # suggest on `update` will be ignored
        del properties["suggest"]

    def augment_update_net(self, serializer, model, op_dict):
        """
        Augment openapi schema for update net operation.
        """
        request_body_schema = self.request_body_schema(op_dict)
        properties = request_body_schema["properties"]

        # suggest on `update` will be ignored
        del properties["suggest"]

    def augment_update_operation(self, op_dict, op_args):
        """
        Augment openapi schema for update operation.
        """
        op_dict.get("parameters")
        serializer, model = self.get_classes(*op_args)

        if not model:
            return

        op_dict["description"] = _(
            "Updates an existing `{obj_type}` type object."
        ).format(obj_type=model.HandleRef.tag)

    def augment_delete_operation(self, op_dict, op_args):
        """
        Augment openapi schema for delete operation.
        """
        op_dict.get("parameters")
        serializer, model = self.get_classes(*op_args)

        if not model:
            return

        op_dict["description"] = _(
            "Marks an `{obj_type}` type object as `deleted`."
        ).format(obj_type=model.HandleRef.tag)
