from __future__ import annotations

import base64
import copy
import json
import os
import re
from collections.abc import Iterator
from typing import Any, cast

import jsonschema
import reversion
from django.conf import settings as dj_settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db import transaction
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseRedirect,
    JsonResponse,
    QueryDict,
)
from django.template import loader
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_exempt, csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from django_grainy.exceptions import PermissionDenied
from django_ratelimit.decorators import ratelimit
from grainy.const import PERM_UPDATE
from rest_framework import serializers
from rest_framework.exceptions import APIException
from rest_framework.exceptions import ValidationError as RestValidationError
from rest_framework.request import Request
from rest_framework.serializers import as_serializer_error
from rest_framework.settings import api_settings

from peeringdb_server import location
from peeringdb_server.forms import VerifiedUpdateForm
from peeringdb_server.models import REFTAG_MAP
from peeringdb_server.permissions import check_permissions
from peeringdb_server.serializers import REFTAG_MAP as SERIALIZER_REFTAG_MAP
from peeringdb_server.validators import validate_verified_update_data
from peeringdb_server.verified_update.const import MAX_UPDATES
from peeringdb_server.views import is_id, view_http_error_invalid

RATELIMITS: dict[str, str] = dj_settings.RATELIMITS

DATA_FIELD_RE = re.compile(r"data\[(\d{0,4})\]\[([^\[\]]+)\]")

# load json schema from file
schema_path: str = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), "schema.json"
)

# Any: an arbitrary JSON Schema document (open-ended structure loaded from schema.json)
JSON_SCHEMA: dict[str, Any] | None = None

with open(schema_path) as f:
    JSON_SCHEMA = json.load(f)


def get_api_request(request: HttpRequest) -> Request:
    """
    Returns `request` as the API serializers see an update, so a verified
    update is held to the same rules as a PUT to the API (#525)
    """
    put_request = copy.copy(request)
    put_request.method = "PUT"
    # the serializers read options such as depth from the query string
    put_request.GET = QueryDict()
    api_request = Request(put_request)
    api_request.user = request.user
    return api_request


def get_country_phone_error(ref_tag: str, data: dict[str, Any]) -> str | None:
    """
    Returns why a facility update that changes the country and a phone number
    together is refused: the country is applied outside the API serializer,
    which checks and formats the number against the stored country
    """
    if "country" not in get_location_fields(ref_tag, data):
        return None
    phones = get_phone_fields(data)
    if not phones:
        return None
    return _(
        "{fields}: Change the country and the phone numbers in separate updates"
    ).format(fields=", ".join(phones))


def get_phone_fields(data: dict[str, Any]) -> list[str]:
    return [field for field in data if field.endswith("_phone")]


def get_location_fields(ref_tag: str, data: dict[str, Any]) -> list[str]:
    """
    Returns the fields in `data` the API serializer only changes with a
    location selection from the facility editor, a verified update applies
    them to the model directly instead
    """
    if ref_tag != "fac" or not dj_settings.FACILITY_ADDRESS_SELECTION_ENABLED:
        return []
    return [field for field in data if field in location.LOCATION_FIELDS]


class UpdateSerializer:
    """
    Binds verified update data for an object to its API serializer, on top
    of the object's current API representation, the way a client sends a
    full object with a PUT
    """

    def __init__(self, api_request: Request, ref_tag: str, obj: Any) -> None:
        self.serializer_class = SERIALIZER_REFTAG_MAP[ref_tag]
        self.context = {"request": api_request}
        self.obj = obj
        self.fields = self.serializer_class(context=self.context).fields
        self.payload = dict(self.serializer_class(obj, context=self.context).data)
        # the legacy field overwrites info_types when it is sent back
        self.payload.pop("info_type", None)
        # the representation fills in the organization's website, and adds
        # the website to social_media
        if "website" in self.payload:
            self.payload["website"] = obj.website
        if "social_media" in self.payload:
            social_media = obj.social_media
            self.payload["social_media"] = (
                social_media if isinstance(social_media, list) else []
            )
        # a field the API reads as blank is represented as null
        for field, value in self.payload.items():
            serializer_field = self.fields.get(field)
            if (
                value is None
                and serializer_field is not None
                and not serializer_field.allow_null
                and getattr(serializer_field, "allow_blank", False)
            ):
                self.payload[field] = ""

    def is_writable(self, field: str) -> bool:
        serializer_field = self.fields.get(field)
        return serializer_field is not None and not serializer_field.read_only

    def bind_payload(self, data: dict[str, Any]) -> dict[str, Any]:
        payload = dict(self.payload)
        for field, value in data.items():
            if isinstance(self.fields.get(field), serializers.MultipleChoiceField):
                # the preview posts multiple choices joined by commas
                if isinstance(value, str):
                    value = [item for item in value.split(",") if item]
            payload[field] = value
        return payload

    def validate(
        self, data: dict[str, Any]
    ) -> tuple[serializers.Serializer | None, list[str]]:
        """
        Returns a serializer for `data` that is ready to save, or the errors
        that refuse it.

        Only the fields in `data` are held to the API's field rules and saved
        (#525). The API's checks of the object as a whole apply in full.
        """
        proposed = set(data)
        if "info_type" in proposed:
            proposed.add("info_types")
        serializer_class = get_proposal_serializer_class(
            self.serializer_class, proposed
        )
        serializer = serializer_class(
            self.obj, data=self.bind_payload(data), context=self.context
        )
        if not serializer.is_valid():
            return None, list(flatten_error_detail(serializer.errors))

        check = getattr(serializer, "check_ixp_update_contact", None)
        if check and "allow_ixp_update" in proposed:
            try:
                check(self.obj, serializer.validated_data.get("allow_ixp_update"))
            except RestValidationError as exc:
                return None, list(flatten_error_detail(exc.detail))

        # other fields keep their stored value, the permission namespace is
        # built from them
        sources = {
            self.fields[field].source for field in proposed if field in self.fields
        }
        for key in list(serializer.validated_data):
            if key in sources:
                continue
            try:
                model_field = self.obj._meta.get_field(key)
            except FieldDoesNotExist:
                continue
            if not model_field.is_relation:
                serializer.validated_data[key] = getattr(self.obj, key)
        # the network update checks for a contact whenever this is sent
        if "allow_ixp_update" not in sources:
            serializer.validated_data.pop("allow_ixp_update", None)
        return serializer, []


def get_proposal_serializer_class(
    serializer_class: type[serializers.Serializer], proposed: set[str]
) -> type[serializers.Serializer]:
    """
    Returns a subclass of `serializer_class` that runs the field rules for the
    `proposed` fields only and takes every other field at its stored value.

    The serializer-wide checks still run. An error they report about a field
    nobody proposed doesn't refuse the proposal, any other error does.
    """

    class ProposalSerializer(serializer_class):  # type: ignore[valid-type,misc]
        @property
        def _writable_fields(self) -> Iterator[serializers.Field]:
            for field in super()._writable_fields:
                if field.field_name in proposed:
                    yield field

        def to_internal_value(self, data: Any) -> dict[str, Any]:
            attrs = super().to_internal_value(data)
            for field in self.fields.values():
                if field.read_only or field.field_name in proposed:
                    continue
                if self.get_model_field(field.source) is not None:
                    attrs.setdefault(field.source, getattr(self.instance, field.source))
            return attrs

        def get_model_field(self, source: str) -> Any:
            try:
                model_field = self.instance._meta.get_field(source)
            except FieldDoesNotExist:
                return None
            return model_field if model_field.concrete else None

        def only_unproposed_errors(
            self, errors: dict[str, Any], attrs: dict[str, Any]
        ) -> bool:
            """
            True when every error is about a field nobody proposed
            """
            return bool(errors) and all(
                key in attrs
                and key not in proposed
                and key != api_settings.NON_FIELD_ERRORS_KEY
                for key in errors
            )

        def run_validators(self, value: dict[str, Any]) -> None:
            # one by one, as DRF stops at a validator that refuses with a dict
            # and ignoring that refusal would skip the validators after it
            to_validate = self._read_only_defaults()
            to_validate.update(value)
            for validator in self.validators:
                try:
                    if getattr(validator, "requires_context", False):
                        validator(to_validate, self)
                    else:
                        validator(to_validate)
                except (RestValidationError, ValidationError) as exc:
                    if not self.only_unproposed_errors(as_serializer_error(exc), value):
                        raise

        def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
            # validate() stops at its first error. When that is about a stored
            # value nobody proposed, it runs again with a neutral value there,
            # so the checks after it run too. The result is only ever that of
            # a validate() that passed, and the stored values are put back.
            try:
                return super().validate(dict(attrs))
            except (RestValidationError, ValidationError) as exc:
                first = exc
                errors = as_serializer_error(exc)
            neutral: dict[str, Any] = {}
            tries: dict[str, list[Any]] = {}
            while True:
                if not self.only_unproposed_errors(errors, attrs):
                    # a later check refused a proposed field, otherwise the
                    # error may be about a neutral value
                    if neutral and any(key in proposed for key in errors):
                        raise RestValidationError(
                            {key: errors[key] for key in errors if key in proposed}
                        )
                    raise first
                for key in errors:
                    if key not in tries:
                        tries[key] = self.get_neutral_values(key, attrs[key])
                    if not tries[key]:
                        raise first
                    neutral[key] = tries[key].pop(0)
                # a neutral value is not what the checks expect of every
                # field, so a rerun that fails in any way refuses with the
                # errors the stored values got
                try:
                    validated = super().validate({**attrs, **neutral})
                except (RestValidationError, ValidationError) as exc:
                    errors = as_serializer_error(exc)
                except Exception:
                    raise first
                else:
                    validated.update({key: attrs[key] for key in neutral})
                    return validated

        def get_neutral_values(self, source: str, value: Any) -> list[Any]:
            if isinstance(value, (list, dict)):
                return [[]]
            values: list[Any] = [""]
            field = next(
                (field for field in self.fields.values() if field.source == source),
                None,
            )
            # a website is required where the organization has none either
            if isinstance(field, serializers.URLField):
                values.append("https://localhost")
            return values

    return ProposalSerializer


def get_other_fields(obj: Any, fields: list[str]) -> list[str]:
    """
    Returns the names of the model fields of `obj` not in `fields`, so a
    stored value elsewhere does not refuse the update of `fields`
    """
    return [field.name for field in obj._meta.fields if field.name not in fields]


def validate_location_data(obj: Any, location_data: dict[str, Any]) -> None:
    """
    Validates the facility address fields in `location_data` on `obj`,
    leaving `obj` unchanged
    """
    stored = {field: getattr(obj, field) for field in location_data}
    for field, value in location_data.items():
        setattr(obj, field, value)
    try:
        obj.full_clean(exclude=get_other_fields(obj, list(location_data)))
    finally:
        for field, value in stored.items():
            setattr(obj, field, value)


def get_updates_error(pairs: list[tuple[Any, Any]]) -> str | None:
    """
    Returns why the (ref_tag, obj_id) pairs of one request are refused, as
    every update runs the API validators, some of which make lookups
    """
    if len(pairs) > MAX_UPDATES:
        return _("Too many proposed updates, at most {count} are allowed").format(
            count=MAX_UPDATES
        )
    if len(set(pairs)) != len(pairs):
        return _("Each object can only be proposed once")
    return None


def get_error_messages(exc: APIException | ValidationError) -> list[str]:
    """
    Flattens a validation error into messages
    """
    if isinstance(exc, ValidationError):
        return exc.messages
    return list(flatten_error_detail(exc.detail))


def flatten_error_detail(detail: Any, field: str | None = None) -> Iterator[str]:
    """
    Yields the messages in a serializer error detail, prefixed with the
    top-level field they belong to
    """
    if isinstance(detail, dict):
        for key, value in detail.items():
            yield from flatten_error_detail(
                value, field or (None if key == "non_field_errors" else key)
            )
    elif isinstance(detail, list):
        for item in detail:
            yield from flatten_error_detail(item, field)
    else:
        yield f"{field}: {detail}" if field else str(detail)


@csrf_exempt
@login_required
@transaction.atomic
# per user, behind the load balancer every request has the same address
@ratelimit(
    key="user",
    method="GET",
    rate=RATELIMITS["view_verified_update_POST"],
    block=False,
)
@require_http_methods(["GET"])
def view_verified_update(request: HttpRequest) -> HttpResponse | JsonResponse:
    """
    View verified update, to present all proposed updates data.
    """

    # check if request was blocked by rate limiting
    was_limited = getattr(request, "limited", False)
    if was_limited:
        return JsonResponse(
            {"error": _("Please wait a bit before proposing verified updates again.")},
            status=400,
        )

    # payload is a base64 encoded json string that contains
    # the following keys: `updates`, `source`, `reason`

    payload = request.GET.get("p")

    if not payload:
        return JsonResponse({"error": _("No payload provided")}, status=400)

    try:
        payload = json.loads(base64.b64decode(payload))
    except Exception:
        return JsonResponse({"error": _("Invalid JSON in payload")}, status=400)

    try:
        jsonschema.validate(payload, JSON_SCHEMA)
    except jsonschema.ValidationError as e:
        return JsonResponse({"error": e.message}, status=400)

    form = VerifiedUpdateForm(payload)
    if not form.is_valid():
        return JsonResponse(form.errors, status=400)
    updates = form.cleaned_data.get("updates")
    error = get_updates_error(
        [(update.get("ref_tag"), update.get("obj_id")) for update in updates]
    )
    if error:
        return JsonResponse({"error": error}, status=400)
    user = request.user
    api_request = get_api_request(request)
    diffs = []
    obj_types = {}
    invalid_permissions = {}
    for update in updates:
        status, data = validate_verified_update_data(
            ref_tag=update.get("ref_tag"),
            obj_id=update.get("obj_id"),
            data=update.get("data"),
        )
        if not status:
            return view_http_error_invalid(
                request,
                _(f"Proposed update contains invalid data: {data}"),
            )
        ref_tag = update.get("ref_tag")
        obj_id = update.get("obj_id")
        # status is truthy here (early-return above), so validate returned the dict
        data = cast("dict[str, Any]", data)
        # Any: model class resolves to type[object] without django-stubs,
        # hiding .objects/.DoesNotExist/._meta.
        model: Any = REFTAG_MAP[ref_tag]
        try:
            obj = model.objects.get(id=obj_id)
        except model.DoesNotExist:
            return JsonResponse(
                {"error": _(f"object {ref_tag}.{obj_id} not found")}, status=404
            )

        if not check_permissions(user, obj, PERM_UPDATE):
            invalid_permissions[obj] = obj._meta.verbose_name
            continue

        # backwards compatibility for network info_type
        if "info_type" in data:
            info_type = data.pop("info_type")
            if "info_types" not in data:
                data["info_types"] = [info_type]

        update_data = {}
        diff = {}
        update_data.update({"ref_tag": ref_tag, "obj_id": obj_id})
        update_serializer = UpdateSerializer(api_request, ref_tag, obj)
        location_fields = get_location_fields(ref_tag, data)
        for field, value in data.items():
            old = getattr(obj, field)

            if isinstance(value, list):
                # sort
                value = ",".join(sorted(str(item) for item in value))

            if isinstance(old, list):
                # sort
                old = ",".join(sorted(str(item) for item in old))

            if old == value:
                continue

            diff[field] = {
                "old": old,
                "new": value,
                "label": model._meta.get_field(field).verbose_name,
            }

            # leave out changes that would be refused
            if field in location_fields:
                try:
                    validate_location_data(obj, {field: data[field]})
                except ValidationError:
                    del diff[field]
            elif not update_serializer.is_writable(field):
                del diff[field]

        # a country and a phone number are proposed in separate updates
        if get_country_phone_error(ref_tag, {field: None for field in diff}):
            for field in get_phone_fields(diff):
                del diff[field]

        api_changes = {
            field: data[field] for field in diff if field not in location_fields
        }
        # changes can depend on each other, check them one by one only when
        # they don't validate together
        if api_changes and update_serializer.validate(api_changes)[1]:
            for field in api_changes:
                if update_serializer.validate({field: data[field]})[1]:
                    del diff[field]

        if not diff:
            continue

        update_data["diff"] = diff
        diffs.append(update_data)

        obj_types[obj] = obj._meta.verbose_name

    context = {
        "source": payload.get("source"),
        "reason": payload.get("reason"),
        "diffs": diffs,
        "objects": obj_types,
        "invalid_permissions": invalid_permissions,
        "referer": request.META.get("HTTP_REFERER"),
    }

    template = loader.get_template("site/verified_update/view.html")
    return HttpResponse(template.render(context, request), status=200)


# decroator


@csrf_protect
@login_required
@ensure_csrf_cookie
@transaction.atomic
@reversion.create_revision()
@ratelimit(
    key="user",
    method="POST",
    rate=RATELIMITS["view_verified_update_accept_POST"],
    block=False,
)
@require_http_methods(["POST"])
def view_verified_update_accept(
    request: HttpRequest,
) -> HttpResponse | HttpResponseRedirect | JsonResponse:
    """
    View verified update accept, to update the objects from proposed updates.
    """

    source = request.POST.get("source")
    reason = request.POST.get("reason")
    referer = request.POST.get("referer")

    comment = f"Verified update accepted from {source} for reason: {reason} - Referer: {referer}"

    reversion.set_comment(comment)
    reversion.set_user(request.user)

    # check if request was blocked by rate limiting
    was_limited = getattr(request, "limited", False)
    if was_limited:
        return JsonResponse(
            {
                "error": _(
                    "Please wait a bit before requesting accept verified updates again."
                )
            },
            status=400,
        )

    data_list = request.POST.getlist("data[]")
    user = request.user

    # the ORM resolves forms such as "+1" or " 1" to the same id
    pairs = [
        (ref_tag, int(obj_id) if is_id(obj_id) else None)
        for ref_tag, obj_id in zip(data_list[::2], data_list[1::2])
    ]
    if any(obj_id is None for _, obj_id in pairs):
        error_message = _("Invalid object id")
    else:
        error_message = get_updates_error(pairs)
    if error_message:
        pairs = []

    # the preview names a field data[<n>][<field>] for the n-th object, a
    # page rendered before that names it data[][<field>] for every object
    shared: dict[str, str] = {}
    indexed: dict[int, dict[str, str]] = {}
    for key, value in request.POST.items():
        match = DATA_FIELD_RE.fullmatch(key)
        if not match:
            continue
        index, field_name = match.groups()
        if index:
            indexed.setdefault(int(index), {})[field_name] = value
        else:
            shared[field_name] = value

    payloads = [
        {
            "ref_tag": ref_tag,
            "obj_id": obj_id,
            "updates": {**shared, **indexed.get(index, {})},
        }
        for index, (ref_tag, obj_id) in enumerate(pairs)
    ]

    updated_obj = []
    invalid_permissions = {}
    errors = {}
    api_request = get_api_request(request)

    for payload in payloads:
        ref_tag = cast("str", payload.get("ref_tag"))
        obj_id = cast("int", payload.get("obj_id"))
        updates = json.loads(json.dumps(payload.get("updates")))
        status, data = validate_verified_update_data(
            ref_tag=ref_tag,
            obj_id=obj_id,
            data=updates,
        )

        if status:
            if data:
                # Any: model class resolves to type[object] without django-stubs,
                # hiding .objects/._meta.
                model: Any = REFTAG_MAP[ref_tag]
                obj = model.objects.get(id=obj_id)
                if check_permissions(user, obj, PERM_UPDATE):
                    # status is truthy here, so validate returned the dict
                    data = cast("dict[str, Any]", data)
                    country_phone_error = get_country_phone_error(ref_tag, data)
                    location_data = {
                        field: data.pop(field)
                        for field in get_location_fields(ref_tag, data)
                    }
                    try:
                        update_serializer = UpdateSerializer(api_request, ref_tag, obj)
                        read_only = [
                            field
                            for field in data
                            if not update_serializer.is_writable(field)
                        ]
                        if read_only:
                            raise ValidationError(
                                [
                                    _("{field}: This field can't be changed").format(
                                        field=field
                                    )
                                    for field in read_only
                                ]
                            )
                        if country_phone_error:
                            raise ValidationError(country_phone_error)
                        # everything is validated before the first save, the
                        # serializer against the stored address
                        serializer = None
                        if data:
                            serializer, messages = update_serializer.validate(data)
                            if messages:
                                raise RestValidationError(messages)
                        if location_data:
                            validate_location_data(obj, location_data)
                        with transaction.atomic():
                            if serializer:
                                serializer.save()
                                obj = serializer.instance
                            if location_data:
                                for field, value in location_data.items():
                                    setattr(obj, field, value)
                                obj.save()
                    except (APIException, ValidationError) as exc:
                        errors[obj] = get_error_messages(exc)
                    except PermissionDenied:
                        invalid_permissions[obj] = obj._meta.verbose_name
                    else:
                        updated_obj.append(obj)
                else:
                    invalid_permissions[obj] = obj._meta.verbose_name
        else:
            error_message = "Please select one or more data"

    # a netixlan has no page of its own
    if len(updated_obj) == 1 and not errors and hasattr(updated_obj[0], "view_url"):
        return HttpResponseRedirect(updated_obj[0].view_url)
    template = loader.get_template("site/verified_update/list.html")
    return HttpResponse(
        template.render(
            {
                "updated_obj": updated_obj,
                "invalid_permissions": invalid_permissions,
                "errors": errors,
                "error_message": error_message,
            },
            request,
        ),
        status=200,
    )
