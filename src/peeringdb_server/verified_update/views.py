import base64
import json
import os

import jsonschema
import reversion
from django.conf import settings as dj_settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.template import loader
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_exempt, csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit
from grainy.const import PERM_UPDATE

from peeringdb_server.forms import VerifiedUpdateForm
from peeringdb_server.models import REFTAG_MAP
from peeringdb_server.permissions import check_permissions
from peeringdb_server.validators import validate_verified_update_data
from peeringdb_server.views import view_http_error_invalid

RATELIMITS = dj_settings.RATELIMITS

# load json schema from file
schema_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "schema.json")

JSON_SCHEMA = None

with open(schema_path) as f:
    JSON_SCHEMA = json.load(f)


@csrf_exempt
@login_required
@transaction.atomic
@ratelimit(
    key="ip",
    method="POST",
    rate=RATELIMITS["view_verified_update_POST"],
    block=False,
)
@require_http_methods(["GET"])
def view_verified_update(request):
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
    user = request.user
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
        data = data
        model = REFTAG_MAP[ref_tag]
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
        for field, value in data.items():
            old = getattr(obj, field)

            if isinstance(value, list):
                # sort
                value = sorted(value)
                value = ",".join(value)

            if isinstance(old, list):
                # sort
                old = sorted(old)
                old = ",".join(old)

            if old == value:
                continue

            diff[field] = {
                "old": old,
                "new": value,
                "label": model._meta.get_field(field).verbose_name,
            }

            # setattr on obj and validate
            setattr(obj, field, value)
            print(diff[field], getattr(obj, field))

            try:
                obj.full_clean()
            except ValidationError as e:
                # if validation fails, remove field from diff
                del diff[field]
                print(e)
            # reset field value
            setattr(obj, field, old)

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
    key="ip",
    method="POST",
    rate=RATELIMITS["view_verified_update_accept_POST"],
    block=False,
)
@require_http_methods(["POST"])
def view_verified_update_accept(request):
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

    payloads = []

    for i in range(0, len(data_list), 2):
        ref_tag = data_list[i]
        obj_id = data_list[i + 1]
        updates = {}

        for field, value in request.POST.items():
            if field.startswith("data[][") and field.endswith("]"):
                field_name = field.split("data[][")[1]
                field_name = field_name.rstrip("]")
                updates[field_name] = value

        payloads.append({"ref_tag": ref_tag, "obj_id": obj_id, "updates": updates})

    updated_obj = []
    error_message = None
    invalid_permissions = {}

    for payload in payloads:
        ref_tag = payload.get("ref_tag")
        obj_id = payload.get("obj_id")
        updates = json.loads(json.dumps(payload.get("updates")))
        status, data = validate_verified_update_data(
            ref_tag=ref_tag,
            obj_id=obj_id,
            data=updates,
        )

        if status:
            if data:
                model = REFTAG_MAP[ref_tag]
                obj = model.objects.get(id=obj_id)
                if check_permissions(user, obj, PERM_UPDATE):
                    for field, value in data.items():
                        setattr(obj, field, value)
                    obj.full_clean()
                    obj.save()
                    updated_obj.append(obj)
                else:
                    invalid_permissions[obj] = obj._meta.verbose_name
        else:
            error_message = "Please select one or more data"

    if len(updated_obj) == 1:
        return HttpResponseRedirect(updated_obj[0].view_url)
    template = loader.get_template("site/verified_update/list.html")
    return HttpResponse(
        template.render(
            {
                "updated_obj": updated_obj,
                "invalid_permissions": invalid_permissions,
                "error_message": error_message,
            },
            request,
        ),
        status=200,
    )
