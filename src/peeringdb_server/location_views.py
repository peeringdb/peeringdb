"""Session-authenticated location helpers for the website editor."""

import json
import math

import reversion
from django import forms
from django.conf import settings
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_protect
from django_grainy.exceptions import PermissionDenied as GrainyPermissionDenied
from grainy.const import PERM_CREATE, PERM_UPDATE
from rest_framework.exceptions import APIException, PermissionDenied, Throttled

from peeringdb_server import location
from peeringdb_server.models import Facility, Organization, ParentStatusException
from peeringdb_server.permissions import check_permissions
from peeringdb_server.renderers import JSONEncoder
from peeringdb_server.rest_throttles import LocationLookupThrottle, WriteRateThrottle
from peeringdb_server.serializers import FacilitySerializer


class LocationCoordinateField(forms.FloatField):
    def to_python(self, value):
        if isinstance(value, bool):
            raise forms.ValidationError("A coordinate must be a number.")
        return super().to_python(value)


class LocationRequest(forms.Form):
    ref_tag = forms.CharField(max_length=16)
    ref_id = forms.IntegerField(min_value=1, required=False)
    org_id = forms.IntegerField(min_value=1, required=False)
    location_version = forms.CharField(required=False, max_length=64)
    country = forms.CharField(max_length=2)
    input = forms.CharField(required=False, min_length=2, max_length=255)
    session_token = forms.UUIDField(required=False)
    place_id = forms.CharField(required=False, max_length=512)
    latitude = LocationCoordinateField(required=False)
    longitude = LocationCoordinateField(required=False)

    def clean_country(self):
        try:
            return location.country_code(self.cleaned_data["country"])
        except location.ValidationError as exc:
            raise forms.ValidationError(exc.detail["country"]) from None


class LocationSaveRequest(LocationRequest):
    location_confirmation = forms.CharField(max_length=8192)
    data = forms.JSONField()

    def clean_data(self):
        data = self.cleaned_data["data"]
        if not isinstance(data, dict):
            raise forms.ValidationError("Provide the facility fields as a JSON object.")
        return data


class FacilityLocationTarget:
    def resolve(self, request, data):
        if not settings.FACILITY_ADDRESS_SELECTION_ENABLED:
            raise location.ValidationError(
                {"location": "Facility location selection is not enabled."}
            )
        if not data.get("org_id"):
            raise location.ValidationError(
                {"org_id": "This field is required for facilities."}
            )
        org = get_object_or_404(Organization, pk=data["org_id"], status="ok")
        instance = None
        if data.get("ref_id"):
            instance = get_object_or_404(
                Facility, pk=data["ref_id"], org=org, status__in=["ok", "pending"]
            )
            namespace = instance.grainy_namespace
            flag = PERM_UPDATE
        else:
            namespace = Facility.Grainy.namespace_instance("*", org=org)
            flag = PERM_CREATE
        if not check_permissions(request.user, namespace, flag):
            raise PermissionDenied()
        return org.pk, instance

    @transaction.atomic
    def save(self, request, data, org_id, instance):
        fields = data["data"].copy()
        if "suggest" in fields and instance is None:
            fields["org_id"] = settings.SUGGEST_ENTITY_ORG
        try:
            supplied_org = int(fields.get("org_id", org_id))
        except (TypeError, ValueError):
            raise location.ValidationError(
                {"org_id": "Invalid organization."}
            ) from None
        if supplied_org != org_id:
            raise location.ValidationError(
                {"org_id": "The organization differs from the confirmed location."}
            )
        request.query_params = request.GET
        serializer = FacilitySerializer(
            instance,
            data=fields,
            context={
                "request": request,
                "location_confirmation": data["location_confirmation"],
            },
        )
        try:
            with reversion.create_revision():
                reversion.set_user(request.user)
                serializer.is_valid(raise_exception=True)
                serializer.save()
                result = dict(serializer.data)
                result.pop("_grainy", None)
                return {"data": [result]}
        finally:
            if instance is None:
                serializer.finalize_create(request)
            else:
                serializer.finalize_update(request)


@method_decorator(csrf_protect, name="dispatch")
class LocationView(View):
    http_method_names = ["post"]
    action: str | None = None
    targets = {"fac": FacilityLocationTarget()}
    form_class = LocationRequest
    throttle_class = LocationLookupThrottle
    response_status = 200

    def post(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({"detail": "Authentication required."}, status=403)
        try:
            # Website helpers bind both permissions and throttling to the session.
            request._permission_holder = request.user
            throttle = self.throttle_class()
            if not throttle.allow_request(request, self):
                raise Throttled(wait=throttle.wait())
            try:
                payload = json.loads(request.body)
            except (ValueError, UnicodeDecodeError):
                raise location.ValidationError(
                    {"location": "Provide a valid JSON object."}
                ) from None
            if not isinstance(payload, dict):
                raise location.ValidationError(
                    {"location": "Provide a valid JSON object."}
                )
            form = self.form_class(payload)
            if not form.is_valid():
                return JsonResponse(dict(form.errors), status=400)
            data = form.cleaned_data
            target = self.targets.get(data["ref_tag"])
            if target is None:
                raise location.ValidationError(
                    {
                        "ref_tag": "Location selection is not supported for this entity type."
                    }
                )
            org_id, instance = target.resolve(request, data)
            if instance and data.get("location_version") != location.location_version(
                instance
            ):
                raise location.LocationConflict()
            result = getattr(self, f"location_{self.action}")(
                data, location.actor_id(request.user), org_id, instance
            )
            return JsonResponse(
                result, encoder=JSONEncoder, status=self.response_status
            )
        except Http404:
            return JsonResponse({"detail": "Not found."}, status=404)
        except GrainyPermissionDenied:
            return JsonResponse({"detail": "Permission denied."}, status=403)
        except ParentStatusException as exc:
            return JsonResponse({"detail": str(exc)}, status=400)
        except APIException as exc:
            detail = (
                exc.detail if isinstance(exc.detail, dict) else {"detail": exc.detail}
            )
            response = JsonResponse(detail, status=exc.status_code)
            if isinstance(exc, Throttled) and exc.wait is not None:
                response["Retry-After"] = str(math.ceil(exc.wait))
            return response

    def location_search(self, data, actor, org_id, instance):
        if not data.get("input") or not data.get("session_token"):
            raise location.ValidationError(
                {"location": "Provide search text and a session token."}
            )
        return {
            "suggestions": location.GoogleLocation().search(
                data["input"], data["country"], str(data["session_token"])
            )
        }

    def location_country(self, data, actor, org_id, instance):
        return {"viewport": location.GoogleLocation().country_viewport(data["country"])}

    def location_resolve(self, data, actor, org_id, instance):
        has_pin = data["latitude"] is not None or data["longitude"] is not None
        if bool(data.get("place_id")) == has_pin:
            raise location.ValidationError(
                {"location": "Select a place or a coordinate pair."}
            )
        pin = (
            location.coordinates(data["latitude"], data["longitude"])
            if has_pin
            else None
        )
        if pin is None and not data.get("session_token"):
            raise location.ValidationError(
                {"session_token": "A search session token is required."}
            )
        proposal = location.GoogleLocation().resolve(
            country=data["country"],
            place_id=data.get("place_id", ""),
            session_token=str(data.get("session_token") or ""),
            pin=pin,
        )
        proposal["location_confirmation"] = location.sign_selection(
            proposal, actor, org_id, instance, ref_tag=data["ref_tag"]
        )
        return proposal


class LocationSaveView(LocationView):
    http_method_names = ["post", "put"]
    form_class = LocationSaveRequest
    throttle_class = WriteRateThrottle
    action = "save"

    @transaction.atomic
    def post(self, request):
        return super().post(request)

    put = post

    def location_save(self, data, actor, org_id, instance):
        if (self.request.method == "PUT") != (instance is not None):
            raise location.ValidationError(
                {"ref_id": "Use POST to create a facility and PUT to update one."}
            )
        self.response_status = 200 if instance is not None else 201
        return self.targets[data["ref_tag"]].save(self.request, data, org_id, instance)
