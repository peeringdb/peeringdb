import os
import json
import datetime
import re
import uuid

from allauth.account.models import EmailAddress
from django.http import (
    JsonResponse,
    HttpResponse,
    HttpResponseRedirect,
    HttpResponseNotFound,
    HttpResponseBadRequest,
    HttpResponseForbidden,
)
from django.conf import settings as dj_settings
from django.shortcuts import render
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned
from django.contrib.auth import authenticate, logout, login
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from django.urls import resolve, Resolver404
from django.template import loader
from django.utils.crypto import constant_time_compare
from django_namespace_perms.util import (
    get_perms,
    has_perms,
    load_perms,
)
from django_namespace_perms.constants import (
    PERM_CRUD,
    PERM_CREATE,
    PERM_DELETE,
    PERM_WRITE,
)
import requests

from oauth2_provider.decorators import protected_resource
from oauth2_provider.oauth2_backends import get_oauthlib_core

from peeringdb_server import settings
from peeringdb_server.search import search
from peeringdb_server.stats import stats as global_stats
from peeringdb_server.org_admin_views import load_all_user_permissions
from peeringdb_server.data_views import BOOL_CHOICE
from peeringdb_server.models import (
    UserOrgAffiliationRequest,
    User,
    UserPasswordReset,
    Organization,
    Network,
    NetworkFacility,
    NetworkIXLan,
    InternetExchange,
    InternetExchangeFacility,
    Facility,
    Sponsorship,
    Partnership,
    PARTNERSHIP_LEVELS,
    REFTAG_MAP,
    UTC,
)
from peeringdb_server.forms import (
    UserCreationForm,
    PasswordResetForm,
    PasswordChangeForm,
    AffiliateToOrgForm,
    UsernameRetrieveForm,
    UserLocaleForm,
)
from peeringdb_server.serializers import (
    OrganizationSerializer,
    NetworkSerializer,
    InternetExchangeSerializer,
    FacilitySerializer,
)
from peeringdb_server.inet import RdapLookup, RdapException
from peeringdb_server.mail import mail_username_retrieve
from peeringdb_server.deskpro import ticket_queue_rdap_error

from peeringdb_server import maintenance

from ratelimit.decorators import ratelimit, is_ratelimited

RATELIMITS = dj_settings.RATELIMITS

from django.utils.translation import ugettext_lazy as _

# lazy init for translations
# _ = lambda s: s

BASE_ENV = {
    "RECAPTCHA_PUBLIC_KEY": dj_settings.RECAPTCHA_PUBLIC_KEY,
    "OAUTH_ENABLED": dj_settings.OAUTH_ENABLED,
    "PEERINGDB_VERSION": settings.PEERINGDB_VERSION,
    "TUTORIAL_MODE": settings.TUTORIAL_MODE,
}


def is_oauth_authorize(url):
    if url.find("/oauth2/authorize/") == 0:
        return True
    return False


def export_permissions(user, entity):
    """
    returns dict of permission bools for the specified user and entity

    to be used in template context
    """

    if entity.status == "deleted":
        return {}

    perms = {
        "can_write": has_perms(user, entity, PERM_WRITE),
        "can_create": has_perms(user, entity, PERM_CREATE),
        "can_delete": has_perms(user, entity, PERM_DELETE),
    }

    if entity.status == "pending":
        perms["can_create"] = False
        perms["can_delete"] = False

    if perms["can_write"] or perms["can_create"] or perms["can_delete"]:
        perms["can_edit"] = True

    if hasattr(entity, "nsp_namespace_manage"):
        perms["can_manage"] = has_perms(user, entity.nsp_namespace_manage, PERM_CRUD)
    else:
        perms["can_manage"] = False

    return perms


class DoNotRender(object):
    """
    Instance of this class is sent when a component attribute does not exist,
    this can then be type checked in the templates to remove non existant attribute
    rows while still allowing attributes with nonetype values to be rendered
    """

    def all(self):
        return []


def make_env(**data):
    env = {}
    env.update(**BASE_ENV)
    env.update(**{"global_stats": global_stats()})
    env.update(**data)
    return env


def view_http_error_404(request):
    template = loader.get_template("site/error_404.html")
    return HttpResponseNotFound(template.render(make_env(), request))


def view_http_error_403(request):
    template = loader.get_template("site/error_403.html")
    return HttpResponseForbidden(template.render(make_env(), request))


def view_http_error_csrf(request, reason):
    return JsonResponse({"non_field_errors": [reason]}, status=403)


def view_maintenance(request):
    template = loader.get_template("site/maintenance.html")
    return HttpResponse(template.render({}, request), status=503)


@login_required
@ratelimit(key="ip", rate=RATELIMITS["view_request_ownership_GET"], method="GET")
@ratelimit(key="ip", rate=RATELIMITS["view_request_ownership_POST"], method="POST")
def view_request_ownership(request):
    """
    Renders the form that allows users to request ownership
    to an unclaimed organization
    """

    was_limited = getattr(request, "limited", False)

    if request.method in ["GET", "HEAD"]:

        # check if reuqest was blocked by rate limiting
        if was_limited:
            return view_index(
                request,
                errors=[_("Please wait a bit before requesting ownership again.")],
            )

        org_id = request.GET.get("id")
        try:
            org = Organization.objects.get(id=org_id)
        except Organization.DoesNotExist:
            return view_index(request, errors=[_("Invalid organization")])

        if org.owned:
            return view_index(
                request,
                errors=[
                    _("Organization '%(org_name)s' is already under ownership")
                    % {"org_name": org.name}
                ],
            )

        template = loader.get_template("site/request-ownership.html")
        return HttpResponse(template.render(make_env(org=org), request))

    elif request.method == "POST":

        org_id = request.POST.get("id")

        # check if reuqest was blocked by rate limiting
        if was_limited:
            return JsonResponse(
                {
                    "non_field_errors": [
                        _("Please wait a bit before requesting ownership again.")
                    ]
                },
                status=400,
            )

        try:
            org = Organization.objects.get(id=org_id)
        except Organization.DoesNotExist:
            return JsonResponse(
                {"non_field_errors": [_("Organization does not exist")]}, status=400
            )

        if org.owned:
            return JsonResponse(
                {
                    "non_field_errors": [
                        _("Organization '%(org_name)s' is already under ownership")
                        % {"org_name": org.name}
                    ]
                },
                status=400,
            )

        if UserOrgAffiliationRequest.objects.filter(
            user=request.user, org=org
        ).exists():
            return JsonResponse(
                {
                    "non_field_errors": [
                        _(
                            "You already have an ownership request pending for this organization"
                        )
                    ]
                },
                status=400,
            )

        uoar = UserOrgAffiliationRequest.objects.create(
            user=request.user, org=org, status="pending"
        )
        return JsonResponse({"status": "ok", "ownership_status": uoar.status})


@csrf_protect
@ensure_csrf_cookie
@ratelimit(key="ip", method="POST", rate=RATELIMITS["view_affiliate_to_org_POST"])
def view_affiliate_to_org(request):
    """
    Allows the user to request affiliation with an organization through
    an ASN they provide
    """

    if not request.user.is_authenticated:
        return view_login(request)

    if request.method == "POST":

        # check if request was blocked by rate limiting
        was_limited = getattr(request, "limited", False)
        if was_limited:
            return JsonResponse(
                {
                    "non_field_errors": [
                        _("Please wait a bit before requesting affiliation again.")
                    ]
                },
                status=400,
            )

        form = AffiliateToOrgForm(request.POST)
        if not form.is_valid():
            return JsonResponse(form.errors, status=400)

        if (
            not form.cleaned_data.get("org")
            and not form.cleaned_data.get("asn")
            and not form.cleaned_data.get("org_name")
        ):
            return JsonResponse(
                {
                    "asn": _("Either ASN or Organization required"),
                    "org": _("Either ASN or Organization required"),
                },
                status=400,
            )

        asn = form.cleaned_data.get("asn")

        # remove all deleted uoars for user
        UserOrgAffiliationRequest.objects.filter(
            user=request.user, status="denied"
        ).delete()

        try:

            uoar, created = UserOrgAffiliationRequest.objects.get_or_create(
                user=request.user,
                asn=form.cleaned_data.get("asn"),
                org_id=form.cleaned_data.get("org") or None,
                org_name=form.cleaned_data.get("org_name") or None,
                status="pending",
            )

        except RdapException as exc:
            ticket_queue_rdap_error(request.user, asn, exc)
            return JsonResponse(
                {"asn": _("RDAP Lookup Error: {}").format(exc)}, status=400
            )

        except MultipleObjectsReturned:
            pass

        return JsonResponse({"status": "ok"})

    return view_verify(request)


@csrf_protect
@ensure_csrf_cookie
@ratelimit(key="ip", rate=RATELIMITS["resend_confirmation_mail"])
def resend_confirmation_mail(request):
    was_limited = getattr(request, "limited", False)
    if was_limited:
        return view_index(
            request,
            errors=[
                _(
                    "Please wait a bit before trying to resend the confirmation email again"
                )
            ],
        )

    if not request.user.is_authenticated:
        return view_login(request)

    request.user.send_email_confirmation(request=request)
    return view_index(request, errors=[_("We have resent your confirmation email")])


@csrf_protect
@ensure_csrf_cookie
def view_profile(request):
    return view_verify(request)


@csrf_protect
@ensure_csrf_cookie
def view_set_user_locale(request):

    if not request.user.is_authenticated:
        return view_login(request)

    if request.method in ["GET", "HEAD"]:
        return view_verify(request)
    elif request.method == "POST":

        form = UserLocaleForm(request.POST)
        if not form.is_valid():
            return JsonResponse(form.errors, status=400)

        loc = form.cleaned_data.get("locale")
        request.user.set_locale(loc)

        from django.utils import translation

        translation.activate(loc)
        request.session[translation.LANGUAGE_SESSION_KEY] = loc

        return JsonResponse({"status": "ok"})


@protected_resource(scopes=["profile"])
def view_profile_v1(request):
    #    if not request.user.is_authenticated:
    #        return view_login(request)
    oauth = get_oauthlib_core()
    scope_email, _request = oauth.verify_request(request, scopes=["email"])
    scope_networks, _request = oauth.verify_request(request, scopes=["networks"])

    json_params = {}
    if "pretty" in request.GET:
        json_params["indent"] = 2

    user = request.user
    data = dict(
        id=request.user.id,
        given_name=request.user.first_name,
        family_name=request.user.last_name,
        name=request.user.full_name,
        verified_user=user.is_verified,
    )

    # only add email fields if email scope is present
    if scope_email:
        data.update(
            dict(email=request.user.email, verified_email=user.email_confirmed,)
        )

    # only add ddnetworks if networks scope is present
    if scope_networks:
        networks = []
        load_perms(user)
        for net in user.networks:
            crud = get_perms(user._nsp_perms_struct, net.nsp_namespace.split(".")).value
            networks.append(dict(id=net.id, name=net.name, asn=net.asn, perms=crud,))

        data["networks"] = networks

    return JsonResponse(data, json_dumps_params=json_params)


@csrf_protect
@ensure_csrf_cookie
@ratelimit(key="ip", rate=RATELIMITS["view_verify_POST"], method="POST")
def view_verify(request):

    if not request.user.is_authenticated:
        return view_login(request)

    if request.method in ["GET", "HEAD"]:
        template = loader.get_template("site/verify.html")
        env = BASE_ENV.copy()
        env.update(
            {
                "affiliation_request": request.user.affiliation_requests.order_by(
                    "-created"
                ).first(),
                "affiliations": request.user.organizations,
                "global_stats": global_stats(),
            }
        )
        return HttpResponse(template.render(env, request))
    elif request.method == "POST":

        # change email address

        password = request.POST.get("password")

        was_limited = getattr(request, "limited", False)

        if was_limited:
            return JsonResponse(
                {
                    "non_field_errors": [
                        _("Please wait a bit before requesting another email change")
                    ]
                },
                status=400,
            )

        if not request.user.has_oauth:
            if not authenticate(username=request.user.username, password=password):
                return JsonResponse({"status": "auth"}, status=401)

        if EmailAddress.objects.filter(user=request.user).exists():
            EmailAddress.objects.filter(user=request.user).delete()

        request.user.email = request.POST.get("email")

        if (
            User.objects.filter(email=request.user.email)
            .exclude(id=request.user.id)
            .exists()
        ):
            return JsonResponse(
                {"email": _("E-mail already exists in our system")}, status=400
            )
        request.user.clean()
        request.user.save()

        request.user.send_email_confirmation(request=request)

        return JsonResponse({"status": "ok"})


@csrf_protect
@ensure_csrf_cookie
def view_password_change(request):

    if not request.user.is_authenticated:
        return view_login(request)

    if request.method in ["GET", "HEAD"]:
        return view_verify(request)
    elif request.method == "POST":

        password_c = request.POST.get("password_c")

        if not request.user.has_oauth:
            if not authenticate(username=request.user.username, password=password_c):
                return JsonResponse(
                    {"status": "auth", "password_c": _("Wrong password")}, status=400
                )
        else:
            return JsonResponse({"status": "auth"}, status=401)

        form = PasswordChangeForm(request.POST)
        if not form.is_valid():
            return JsonResponse(form.errors, status=400)

        request.user.set_password(form.cleaned_data.get("password"))
        request.user.save()

        return JsonResponse({"status": "ok"})


@ensure_csrf_cookie
@require_http_methods(["GET"])
def view_username_retrieve(request):
    """
    username retrieval view
    """
    env = BASE_ENV.copy()
    env.update(
        {"global_stats": global_stats(),}
    )
    return render(request, "site/username-retrieve.html", env)


@csrf_protect
@ensure_csrf_cookie
@require_http_methods(["POST"])
@ratelimit(key="ip", rate=RATELIMITS["view_username_retrieve_initiate"])
def view_username_retrieve_initiate(request):
    """
    username retrieval initiate view
    """

    was_limited = getattr(request, "limited", False)
    if was_limited:
        return JsonResponse(
            {
                "non_field_errors": [
                    _("Please wait a bit before requesting your usernames again.")
                ]
            },
            status=400,
        )

    # clean form and get email address
    form = UsernameRetrieveForm(request.POST)
    if not form.is_valid():
        return JsonResponse(form.errors, status=400)

    email = form.cleaned_data.get("email")

    # generate secret and store in user's django sessions
    secret = str(uuid.uuid4())
    request.session["username_retrieve_secret"] = secret
    request.session["username_retrieve_email"] = email

    # send email
    if User.objects.filter(email=email).exists():
        mail_username_retrieve(email, secret)

    return JsonResponse({"status": "ok"})


@ensure_csrf_cookie
@require_http_methods(["GET"])
def view_username_retrieve_complete(request):
    """
    username retrieval completion view

    show the list of usernames associated to an email if
    the correct secret is provided
    """

    secret = request.GET.get("secret")
    secret_expected = request.session.get("username_retrieve_secret")
    email = request.session.get("username_retrieve_email")
    env = BASE_ENV.copy()
    env.update(
        {
            "secret": secret,
            "secret_expected": secret_expected,
            "users": User.objects.filter(email=email),
            "email": email,
        }
    )

    if secret_expected and constant_time_compare(secret, secret_expected):
        # invalidate the username retrieve session
        del request.session["username_retrieve_email"]
        del request.session["username_retrieve_secret"]
        request.session.modified = True

    return render(request, "site/username-retrieve-complete.html", env)


@csrf_protect
@ensure_csrf_cookie
def view_password_reset(request):
    """
    password reset initiation view
    """

    if request.method in ["GET", "HEAD"]:
        env = BASE_ENV.copy()
        env.update(
            {"global_stats": global_stats(),}
        )

        env["token"] = token = request.GET.get("token")
        env["target"] = target = request.GET.get("target")

        if token and target:
            pr = UserPasswordReset.objects.filter(user_id=target).first()
            env["pr"] = pr

            if pr and pr.match(token) and pr.is_valid():
                env["username"] = pr.user.username
                env["token_valid"] = True

        template = loader.get_template("site/password-reset.html")

        return HttpResponse(template.render(env, request))

    elif request.method == "POST":

        token = request.POST.get("token")
        target = request.POST.get("target")
        if token and target:
            form = PasswordChangeForm(request.POST)
            if not form.is_valid():
                return JsonResponse(form.errors, status=400)

            user = User.objects.filter(id=target).first()

            err_invalid_token_msg = _("Invalid Security Token")
            err_expired_msg = ('{} <a href="/reset-password">{}</a>').format(
                _("Password Reset Process has expired, please"), _("initiate again")
            )

            if user:
                try:
                    if not user.password_reset.match(token):
                        return JsonResponse(
                            {"non_field_errors": [err_invalid_token_msg]}, status=400
                        )

                    if not user.password_reset.is_valid():
                        return JsonResponse(
                            {"non_field_errors": [err_expired_msg]}, status=400
                        )

                except UserPasswordReset.DoesNotExist:
                    return JsonResponse(
                        {"non_field_errors": [err_expired_msg]}, status=400
                    )

                user.password_reset_complete(token, form.cleaned_data.get("password"))

            else:
                return JsonResponse({"non_field_errors": [err_expired_msg]}, status=400)

        else:
            form = PasswordResetForm(request.POST)

            if not form.is_valid():
                return JsonResponse(form.errors, status=400)

            user = User.objects.filter(email=form.cleaned_data["email"]).first()
            if user:
                user.password_reset_initiate()
        return JsonResponse({"status": "ok"})


@csrf_protect
@ensure_csrf_cookie
def view_registration(request):
    """
    user registration page view
    """
    if request.user.is_authenticated:
        return view_index(
            request,
            errors=[
                _(
                    "Please log out of your current session before trying to register. Notice, multiple accounts are no longer needed."
                )
            ],
        )

    if request.method in ["GET", "HEAD"]:
        template = loader.get_template("site/register.html")
        env = BASE_ENV.copy()
        env.update(
            {"global_stats": global_stats(), "register_form": UserCreationForm(),}
        )
        return HttpResponse(template.render(env, request))

    elif request.method == "POST":
        form = UserCreationForm(request.POST)
        form.request = request

        if not form.is_valid():
            errors = form.errors
            errors["non_field_errors"] = errors.get("__all__", [])
            return JsonResponse(errors, status=400)

        email = form.cleaned_data["email"]
        if EmailAddress.objects.filter(email=email).count() > 0:
            return JsonResponse(
                {"email": _("This email address has already been used")}, status=400
            )

        # require min password length
        # FIXME: impl password strength validation
        if len(form.cleaned_data["password1"]) < 10:
            return JsonResponse(
                {"password1": _("Needs to be at least 10 characters long")}, status=400
            )

        # create the user
        user = form.save()

        user.set_unverified()

        # log the user in
        login(
            request,
            authenticate(
                username=request.POST["username"], password=request.POST["password1"]
            ),
        )

        user.send_email_confirmation(signup=True, request=request)

        form.delete_captcha()

        return JsonResponse({"status": "ok"})


@ensure_csrf_cookie
def view_login(request, errors=None):
    """
    login page view
    """
    if not errors:
        errors = []

    if request.user.is_authenticated:
        return view_index(request, errors=[_("Already logged in")])

    template = loader.get_template("site/login.html")

    redir = request.GET.get("next", request.POST.get("next"))

    env = BASE_ENV.copy()
    env.update({"errors": errors, "next": redir})
    return HttpResponse(template.render(env, request))


@ensure_csrf_cookie
def view_index(request, errors=None):
    """
    landing page view
    """
    if not errors:
        errors = []

    template = loader.get_template("site/index.html")

    recent = {
        "net": Network.handleref.filter(status="ok").order_by("-updated")[:5],
        "fac": Facility.handleref.filter(status="ok").order_by("-updated")[:5],
        "ix": InternetExchange.handleref.filter(status="ok").order_by("-updated")[:5],
    }

    env = BASE_ENV.copy()
    env.update({"errors": errors, "global_stats": global_stats(), "recent": recent})
    return HttpResponse(template.render(env, request))


def view_component(
    request, component, data, title, perms=None, instance=None, **kwargs
):
    """
    Generic component view
    """
    if not perms:
        perms = {}

    template = loader.get_template("site/view.html")

    env = BASE_ENV.copy()
    env.update(
        {
            "data": data,
            "permissions": perms,
            "title": title,
            "component": component,
            "instance": instance,
            "ref_tag": instance._handleref.tag,
            "global_stats": global_stats(),
            "asset_template_name": "site/view_%s_assets.html" % component,
            "tools_template_name": "site/view_%s_tools.html" % component,
            "side_template_name": "site/view_%s_side.html" % component,
            "bottom_template_name": "site/view_%s_bottom.html" % component,
        }
    )
    env.update(**kwargs)
    return HttpResponse(template.render(env, request))


@ensure_csrf_cookie
def view_organization(request, id):
    """
    View organization data for org specified by id
    """

    try:
        org = OrganizationSerializer.prefetch_related(
            Organization.objects, request, depth=2
        ).get(id=id, status__in=["ok", "pending"])
    except ObjectDoesNotExist:
        return view_http_error_404(request)

    data = OrganizationSerializer(org, context={"user": request.user}).data

    if not data:
        return view_http_error_403(request)

    perms = export_permissions(request.user, org)

    tags = ["fac", "net", "ix"]
    for tag in tags:
        model = REFTAG_MAP.get(tag)
        perms["can_create_%s" % tag] = has_perms(
            request.user, model.nsp_namespace_from_id(org.id, "create"), PERM_CREATE
        )
        perms["can_delete_%s" % tag] = has_perms(
            request.user,
            model.nsp_namespace_from_id(org.id, "_").strip("_"),
            PERM_DELETE,
        )

    # if the organization being viewed is the one used
    # to store suggested entities, we dont want to show the editorial
    # tools
    if org.id == dj_settings.SUGGEST_ENTITY_ORG:
        perms["can_create"] = False
        perms["can_manage"] = False
        for tag in tags:
            perms["can_create_%s" % tag] = False
            perms["can_delete_%s" % tag] = False

    # if user has writing perms to entity, we want to load sub entities
    # that have status pending so we dont use the ones kicked back
    # by the serializer
    if perms.get("can_delete_ix") or perms.get("can_create_ix"):
        exchanges = org.ix_set.filter(status__in=["ok", "pending"])
    else:
        exchanges = data["ix_set"]

    if perms.get("can_delete_fac") or perms.get("can_create_fac"):
        facilities = org.fac_set.filter(status__in=["ok", "pending"])
    else:
        facilities = data["fac_set"]

    if perms.get("can_delete_net") or perms.get("can_create_net"):
        networks = org.net_set.filter(status__in=["ok", "pending"])
    else:
        networks = data["net_set"]

    dismiss = DoNotRender()

    data = {
        "title": data.get("name", dismiss),
        "exchanges": exchanges,
        "networks": networks,
        "facilities": facilities,
        "fields": [
            {
                "name": "website",
                "type": "url",
                "notify_incomplete": True,
                "value": data.get("website", dismiss),
                "label": _("Website"),
            },
            {
                "name": "address1",
                "label": _("Address 1"),
                "notify_incomplete": True,
                "value": data.get("address1", dismiss),
            },
            {
                "name": "address2",
                "label": _("Address 2"),
                "value": data.get("address2", dismiss),
            },
            {
                "name": "location",
                "label": _("Location"),
                "type": "location",
                "notify_incomplete": True,
                "value": data,
            },
            {
                "name": "country",
                "type": "list",
                "data": "countries_b",
                "label": _("Country Code"),
                "notify_incomplete": True,
                "value": data.get("country", dismiss),
            },
            {
                "name": "notes",
                "label": _("Notes"),
                "help_text": _("Markdown enabled"),
                "type": "fmt-text",
                "value": data.get("notes", dismiss),
            },
        ],
    }

    users = {}
    if perms.get("can_manage"):
        users.update(
            dict([(user.id, user) for user in org.admin_usergroup.user_set.all()])
        )
        users.update(dict([(user.id, user) for user in org.usergroup.user_set.all()]))
        users = sorted(list(users.values()), key=lambda x: x.full_name)

    # if user has rights to create sub entties or manage users, allow them
    # to view the tools
    if perms.get("can_manage") or perms.get("can_create"):
        perms["can_use_tools"] = True

    active_tab = None
    tab_init = {}
    for tag in tags:
        tab_init[tag] = "inactive"
        if perms.get("can_create_%s" % tag):
            perms["can_use_tools"] = True
            if not active_tab:
                tab_init[tag] = "active"
                active_tab = tag
        if perms.get("can_delete_%s" % tag):
            perms["can_edit"] = True

    if perms.get("can_manage") and org.pending_affiliations.count() > 0:
        tab_init = {"users": "active"}

    return view_component(
        request,
        "organization",
        data,
        "Organization",
        tab_init=tab_init,
        users=users,
        user_perms=load_all_user_permissions(org),
        instance=org,
        perms=perms,
    )


@ensure_csrf_cookie
def view_facility(request, id):
    """
    View facility data for facility specified by id
    """

    try:
        facility = Facility.objects.get(id=id, status__in=["ok", "pending"])
    except ObjectDoesNotExist:
        return view_http_error_404(request)

    data = FacilitySerializer(facility, context={"user": request.user}).data

    if not data:
        return view_http_error_403(request)

    perms = export_permissions(request.user, facility)

    org = OrganizationSerializer(facility.org, context={"user": request.user}).data

    exchanges = (
        InternetExchangeFacility.handleref.undeleted()
        .filter(facility=facility)
        .select_related("ix")
        .order_by("ix__name")
        .all()
    )
    peers = (
        NetworkFacility.handleref.undeleted()
        .filter(facility=facility)
        .select_related("network")
        .order_by("network__name")
    )

    dismiss = DoNotRender()

    data = {
        "title": data.get("name", dismiss),
        "exchanges": exchanges,
        "peers": peers,
        "fields": [
            {
                "name": "org",
                "label": _("Organization"),
                "value": org.get("name", dismiss),
                "type": "entity_link",
                "link": "/%s/%d" % (Organization._handleref.tag, org.get("id")),
            },
            {
                "name": "website",
                "type": "url",
                "value": data.get("website", dismiss),
                "label": _("Website"),
            },
            {
                "name": "address1",
                "label": _("Address 1"),
                "value": data.get("address1", dismiss),
            },
            {
                "name": "address2",
                "label": _("Address 2"),
                "value": data.get("address2", dismiss),
            },
            {
                "name": "location",
                "label": _("Location"),
                "type": "location",
                "value": data,
            },
            {
                "name": "country",
                "type": "list",
                "data": "countries_b",
                "label": _("Country Code"),
                "value": data.get("country", dismiss),
            },
            {
                "name": "geocode",
                "label": _("Geocode"),
                "type": "geocode",
                "value": data,
            },
            {
                "name": "clli",
                "label": _("CLLI Code"),
                "value": data.get("clli", dismiss),
            },
            {
                "name": "npanxx",
                "label": _("NPA-NXX"),
                "value": data.get("npanxx", dismiss),
            },
            {
                "name": "notes",
                "label": _("Notes"),
                "help_text": _("Markdown enabled"),
                "type": "fmt-text",
                "value": data.get("notes", dismiss),
            },
        ],
    }

    return view_component(
        request, "facility", data, "Facility", perms=perms, instance=facility
    )


@ensure_csrf_cookie
def view_exchange(request, id):
    """
    View exchange data for exchange specified by id
    """

    try:
        exchange = InternetExchange.objects.get(id=id, status__in=["ok", "pending"])
    except ObjectDoesNotExist:
        return view_http_error_404(request)

    data = InternetExchangeSerializer(exchange, context={"user": request.user}).data

    # find out if user can write to object
    perms = export_permissions(request.user, exchange)

    if not data:
        return view_http_error_403(request)
    networks = (
        NetworkIXLan.handleref.undeleted()
        .select_related("network", "ixlan")
        .order_by("network__name")
        .filter(ixlan__ix=exchange)
    )
    dismiss = DoNotRender()

    facilities = (
        InternetExchangeFacility.handleref.undeleted()
        .select_related("ix", "facility")
        .filter(ix=exchange)
        .order_by("facility__name")
    )

    org = data.get("org")

    data = {
        "id": exchange.id,
        "title": data.get("name", dismiss),
        "facilities": facilities,
        "networks": networks,
        "ixlans": exchange.ixlan_set_active_or_pending,
        "fields": [
            {
                "name": "org",
                "label": _("Organization"),
                "value": org.get("name", dismiss),
                "type": "entity_link",
                "link": "/%s/%d" % (Organization._handleref.tag, org.get("id")),
            },
            {
                "name": "name_long",
                "label": _("Long Name"),
                "value": data.get("name_long", dismiss),
            },
            {"name": "city", "label": _("City"), "value": data.get("city", dismiss)},
            {
                "name": "country",
                "type": "list",
                "data": "countries_b",
                "label": _("Country"),
                "value": data.get("country", dismiss),
            },
            {
                "name": "region_continent",
                "type": "list",
                "data": "enum/regions",
                "label": _("Continental Region"),
                "value": data.get("region_continent", dismiss),
            },
            {
                "name": "media",
                "type": "list",
                "data": "enum/media",
                "label": _("Media Type"),
                "value": data.get("media", dismiss),
            },
            {
                "type": "flags",
                "label": _("Protocols Supported"),
                "value": [
                    {
                        "name": "proto_unicast",
                        "label": _("Unicast IPv4"),
                        "value": int(data.get("proto_unicast", False)),
                    },
                    {
                        "name": "proto_multicast",
                        "label": _("Multicast"),
                        "value": int(data.get("proto_multicast", False)),
                    },
                    {
                        "name": "proto_ipv6",
                        "label": _("IPv6"),
                        "value": int(data.get("proto_ipv6", False)),
                    },
                ],
            },
            {
                "name": "notes",
                "label": _("Notes"),
                "help_text": _("Markdown enabled"),
                "type": "fmt-text",
                "value": data.get("notes", dismiss),
            },
            {"type": "sub", "label": _("Contact Information")},
            {
                "type": "url",
                "name": "website",
                "label": _("Company Website"),
                "value": data.get("website", dismiss),
            },
            {
                "type": "url",
                "name": "url_stats",
                "label": _("Traffic Stats Website"),
                "value": data.get("url_stats", dismiss),
            },
            {
                "type": "email",
                "name": "tech_email",
                "label": _("Technical Email"),
                "value": data.get("tech_email", dismiss),
            },
            {
                "type": "string",
                "name": "tech_phone",
                "label": _("Technical Phone"),
                "value": data.get("tech_phone", dismiss),
            },
            {
                "type": "email",
                "name": "policy_email",
                "label": _("Policy Email"),
                "value": data.get("policy_email", dismiss),
            },
            {
                "type": "string",
                "name": "policy_phone",
                "label": _("Policy Phone"),
                "value": data.get("policy_phone", dismiss),
            },
        ],
    }

    ixlan_num = data["ixlans"].count()

    if ixlan_num < 2 and not perms.get("can_edit"):
        # if there is less than one LAN connected to this ix
        # we want to render a simplified view to read-only
        # viewers

        data["lan_simple_view"] = True

        if ixlan_num == 1:

            ixlan = data["ixlans"].first()

            data["fields"].extend(
                [
                    {"type": "sub", "label": _("LAN")},
                    {
                        "type": "number",
                        "name": "mtu",
                        "label": _("MTU"),
                        "value": ixlan.mtu or "",
                    },
                    {
                        "type": "bool",
                        "name": "dot1q_support",
                        "label": _("DOT1Q"),
                        "value": ixlan.dot1q_support,
                    },
                ]
            )

            data["fields"].extend(
                [
                    {
                        "type": "string",
                        "name": "prefix_%d" % prefix.id,
                        "label": _(prefix.protocol),
                        "value": prefix.prefix,
                    }
                    for prefix in ixlan.ixpfx_set_active
                ]
            )

    return view_component(
        request, "exchange", data, "Exchange", perms=perms, instance=exchange
    )


@ensure_csrf_cookie
def view_network_by_query(request):
    if "asn" in request.GET:
        try:
            return view_network_by_asn(request, request.GET.get("asn"))
        except ValueError:
            return view_http_error_404(request)
    else:
        return view_http_error_404(request)


@ensure_csrf_cookie
def view_network_by_asn(request, asn):
    try:
        network = Network.objects.get(asn=int(asn))
        # FIXME: should be able to just pass existing network object here to avoid
        # having to query again
        return view_network(request, network.id)
    except ObjectDoesNotExist:
        return view_http_error_404(request)


@ensure_csrf_cookie
def view_network(request, id):
    """
    View network data for network specified by id
    """

    try:
        network = NetworkSerializer.prefetch_related(
            Network.objects, request, depth=2
        ).get(id=id, status__in=["ok", "pending"])
    except ObjectDoesNotExist:
        return view_http_error_404(request)

    network_d = NetworkSerializer(network, context={"user": request.user}).data

    if not network_d:
        return view_http_error_403(request)

    perms = export_permissions(request.user, network)

    facilities = (
        NetworkFacility.handleref.undeleted()
        .select_related("facility")
        .filter(network=network)
        .order_by("facility__name")
    )

    exchanges = (
        NetworkIXLan.handleref.undeleted()
        .select_related("ixlan", "ixlan__ix", "network")
        .filter(network=network)
        .order_by("ixlan__ix__name")
    )

    # This will be passed as default value for keys that dont exist - causing
    # them not to be rendered in the template - also it is fairly
    # safe to assume that no existing keys have been dropped because permission
    # requirements to view them were not met.
    dismiss = DoNotRender()

    org = network_d.get("org")

    data = {
        "title": network_d.get("name", dismiss),
        "facilities": facilities,
        "exchanges": exchanges,
        "fields": [
            {
                "name": "org",
                "label": _("Organization"),
                "value": org.get("name", dismiss),
                "type": "entity_link",
                "link": "/%s/%d" % (Organization._handleref.tag, org.get("id")),
            },
            {
                "name": "aka",
                "label": _("Also Known As"),
                "notify_incomplete": True,
                "value": network_d.get("aka", dismiss),
            },
            {
                "name": "website",
                "label": _("Company Website"),
                "type": "url",
                "notify_incomplete": True,
                "value": network_d.get("website", dismiss),
            },
            {
                "name": "asn",
                "label": _("Primary ASN"),
                "notify_incomplete": True,
                "value": network_d.get("asn", dismiss),
            },
            {
                "name": "irr_as_set",
                "label": _("IRR as-set/route-set"),
                "notify_incomplete": True,
                "value": network_d.get("irr_as_set", dismiss),
            },
            {
                "name": "route_server",
                "type": "url",
                "label": _("Route Server URL"),
                "notify_incomplete": True,
                "value": network_d.get("route_server", dismiss),
            },
            {
                "name": "looking_glass",
                "type": "url",
                "label": _("Looking Glass URL"),
                "notify_incomplete": True,
                "value": network_d.get("looking_glass", dismiss),
            },
            {
                "name": "info_type",
                "type": "list",
                "data": "enum/net_types",
                "blank": _("Not Disclosed"),
                "label": _("Network Type"),
                "notify_incomplete": True,
                "value": network_d.get("info_type", dismiss),
            },
            {
                "name": "info_prefixes4",
                "label": _("IPv4 Prefixes"),
                "type": "number",
                "notify_incomplete": True,
                "value": int(network_d.get("info_prefixes4") or 0),
            },
            {
                "name": "info_prefixes6",
                "label": _("IPv6 Prefixes"),
                "type": "number",
                "notify_incomplete": True,
                "value": int(network_d.get("info_prefixes6") or 0),
            },
            {
                "name": "info_traffic",
                "type": "list",
                "data": "enum/traffic",
                "blank": _("Not Disclosed"),
                "label": _("Traffic Levels"),
                "value": network_d.get("info_traffic", dismiss),
            },
            {
                "name": "info_ratio",
                "type": "list",
                "data": "enum/ratios",
                "label": _("Traffic Ratios"),
                "blank": _("Not Disclosed"),
                "value": network_d.get("info_ratio", dismiss),
            },
            {
                "name": "info_scope",
                "type": "list",
                "data": "enum/scopes",
                "blank": _("Not Disclosed"),
                "label": _("Geographic Scope"),
                "value": network_d.get("info_scope", dismiss),
            },
            {
                "type": "flags",
                "label": _("Protocols Supported"),
                "value": [
                    {
                        "name": "info_unicast",
                        "label": _("Unicast IPv4"),
                        "value": network_d.get("info_unicast", False),
                    },
                    {
                        "name": "info_multicast",
                        "label": _("Multicast"),
                        "value": network_d.get("info_multicast", False),
                    },
                    {
                        "name": "info_ipv6",
                        "label": _("IPv6"),
                        "value": network_d.get("info_ipv6", False),
                    },
                ],
            },
            {
                "readonly": True,
                "name": "updated",
                "label": _("Last Updated"),
                "value": network_d.get("updated", dismiss),
            },
            {
                "name": "notes",
                "label": _("Notes"),
                "help_text": _("Markdown enabled"),
                "type": "fmt-text",
                "value": network_d.get("notes", dismiss),
            },
            {"type": "sub", "admin": True, "label": _("PeeringDB Configuration")},
            {
                "type": "flags",
                "admin": True,
                "label": _("Allow IXP Update"),
                "help_text": _(
                    "If enabled, an ixp may manage this network's entry in their peering list"
                ),
                "value": [
                    {
                        "name": "allow_ixp_update",
                        "label": "",
                        "value": network.allow_ixp_update,
                    }
                ],
            },
            {
                "type": "action",
                "admin": True,
                "label": _("IXP Update Tools"),
                "actions": [
                    {"label": _("Preview"), "action": "ixf_preview",},
                    {"label": _("Postmortem"), "action": "ixf_postmortem"},
                ],
            },
            {"type": "sub", "label": _("Peering Policy Information")},
            {
                "name": "policy_url",
                "label": _("Peering Policy"),
                "value": network_d.get("policy_url", dismiss),
                "notify_incomplete": True,
                "type": "url",
            },
            {
                "name": "policy_general",
                "type": "list",
                "data": "enum/policy_general",
                "label": _("General Policy"),
                "value": network_d.get("policy_general", dismiss),
            },
            {
                "name": "policy_locations",
                "type": "list",
                "data": "enum/policy_locations",
                "label": _("Multiple Locations"),
                "value": network_d.get("policy_locations", dismiss),
            },
            {
                "name": "policy_ratio",
                "type": "list",
                "data": "enum/bool_choice_str",
                "label": _("Ratio Requirement"),
                "value": network_d.get("policy_ratio", dismiss),
                "value_label": dict(BOOL_CHOICE).get(network_d.get("policy_ratio")),
            },
            {
                "name": "policy_contracts",
                "type": "list",
                "data": "enum/policy_contracts",
                "label": _("Contract Requirement"),
                "value": network_d.get("policy_contracts", dismiss),
            },
        ],
    }

    # Add POC data to dataset
    data["poc_set"] = network_d.get("poc_set")

    if not request.user.is_authenticated or not request.user.is_verified:
        cnt = network.poc_set.filter(status="ok", visible="Users").count()
        data["poc_hidden"] = cnt > 0
    else:
        data["poc_hidden"] = False

    return view_component(
        request, "network", data, "Network", perms=perms, instance=network
    )


def view_suggest(request, reftag):
    if reftag not in ["net", "ix", "fac"]:
        return HttpResponseRedirect("/")

    template = loader.get_template("site/view_suggest_{}.html".format(reftag))
    env = make_env()
    return HttpResponse(template.render(env, request))


def view_simple_content(request, content_name):
    """
    Renders the content in templates/{{ content_name }} inside
    the peeringdb layout
    """

    template = loader.get_template("site/simple_content.html")

    env = make_env(content_name=content_name)

    return HttpResponse(template.render(env, request))


def view_aup(request):
    """
    Render page containing acceptable use policy
    """

    return view_simple_content(request, "site/aup.html")


def view_about(request):
    """
    Render page containing about
    """

    return view_simple_content(request, "site/about.html")


def view_sponsorships(request):
    """
    View current sponsorships
    """

    template = loader.get_template("site/sponsorships.html")
    now = datetime.datetime.now().replace(tzinfo=UTC())

    qset = Sponsorship.objects.filter(start_date__lte=now, end_date__gte=now)

    sponsorships = {
        "diamond": qset.filter(level=4),
        "platinum": qset.filter(level=3),
        "gold": qset.filter(level=2),
        "silver": qset.filter(level=1),
    }

    env = make_env(sponsorships=sponsorships)
    return HttpResponse(template.render(env, request))


def view_partnerships(request):
    """
    View current partners
    """

    template = loader.get_template("site/partnerships.html")
    qset = Partnership.objects.filter(logo__isnull=False)

    partnerships = {}
    for row in qset:
        if row.level not in partnerships:
            partnerships[row.level] = []
        partnerships[row.level].append(row)

    env = make_env(
        partnership_levels=dict(PARTNERSHIP_LEVELS), partnerships=partnerships
    )
    return HttpResponse(template.render(env, request))


def view_advanced_search(request):
    """
    View for advanced search
    """

    template = loader.get_template("site/advanced-search.html")
    env = make_env(row_limit=getattr(dj_settings, "API_DEPTH_ROW_LIMIT", 250))

    reftag = request.GET.get("reftag")

    if reftag == "net":
        try:
            env["ix_name"] = InternetExchange.objects.get(id=request.GET.get("ix")).name
        except (ObjectDoesNotExist, ValueError):
            env["ix_name"] = ""

        try:
            env["not_ix_name"] = InternetExchange.objects.get(
                id=request.GET.get("not_ix")
            ).name
        except (ObjectDoesNotExist, ValueError):
            env["not_ix_name"] = ""

        try:
            env["fac_name"] = Facility.objects.get(id=request.GET.get("fac")).name
        except (ObjectDoesNotExist, ValueError):
            env["fac_name"] = ""

        try:
            env["not_fac_name"] = Facility.objects.get(
                id=request.GET.get("not_fac")
            ).name
        except (ObjectDoesNotExist, ValueError):
            env["not_fac_name"] = ""

    return HttpResponse(template.render(env, request))


def request_api_search(request):
    q = request.GET.get("q")

    if not q:
        return HttpResponseBadRequest()

    result = search(q)

    return HttpResponse(json.dumps(result), content_type="application/json")


def request_search(request):
    """
    XHR search request goes here
    """
    q = request.GET.get("q")

    if not q:
        return HttpResponseRedirect("/")

    # if the user queried for an asn directly via AS*** or ASN***
    # redirect to the result
    m = re.match(r"(asn|as)(\d+)", q.lower())
    if m:
        net = Network.objects.filter(asn=m.group(2), status="ok")
        if net.exists() and net.count() == 1:
            return HttpResponseRedirect("/net/{}".format(net.first().id))

    result = search(q)

    sponsors = dict(
        [
            (org.id, sponsorship.label.lower())
            for org, sponsorship in Sponsorship.active_by_org()
        ]
    )

    for tag, rows in list(result.items()):
        for item in rows:
            item["sponsorship"] = sponsors.get(item["org_id"])

    template = loader.get_template("site/search_result.html")
    env = make_env(
        **{
            "search_ixp": result.get(InternetExchange._handleref.tag),
            "search_net": result.get(Network._handleref.tag),
            "search_fac": result.get(Facility._handleref.tag),
            "count_ixp": len(result.get(InternetExchange._handleref.tag, [])),
            "count_net": len(result.get(Network._handleref.tag, [])),
            "count_fac": len(result.get(Facility._handleref.tag, [])),
        }
    )
    return HttpResponse(template.render(env, request))


def request_logout(request):
    logout(request)
    return view_index(request)


@csrf_protect
@ensure_csrf_cookie
@ratelimit(key="ip", rate=RATELIMITS["request_login_POST"], method="POST")
def request_login(request):

    if request.user.is_authenticated:
        return view_index(request)

    if request.method in ["GET", "HEAD"]:
        return view_login(request)

    was_limited = getattr(request, "limited", False)
    if was_limited:
        return view_login(
            request, errors=[_("Please wait a bit before trying to login again.")]
        )

    username = request.POST["username"]
    password = request.POST["password"]
    redir = request.POST.get("next") or "/"
    if redir == "/logout":
        redir = "/"

    try:
        resolve(redir)
    except Resolver404:
        if not is_oauth_authorize(redir):
            redir = "/"

    user = authenticate(username=username, password=password)
    if user is not None:
        if user.is_active:
            login(request, user)

            from django.utils import translation

            user_language = user.get_locale()
            translation.activate(user_language)
            request.session[translation.LANGUAGE_SESSION_KEY] = user_language

            return HttpResponseRedirect(redir)
        return view_login(request, errors=[_("Account disabled.")])
    return view_login(request, errors=[_("Invalid username/password.")])


@require_http_methods(["POST"])
@ratelimit(key="ip", rate=RATELIMITS["request_translation"], method="POST")
def request_translation(request, data_type):

    if not request.user.is_authenticated:
        return JsonResponse(
            {"status": "error", "error": "Please login to use translation service"}
        )

    user_language = request.user.get_locale()
    if not user_language:
        user_language = "en"

    note = request.POST.get("note")
    target = user_language

    if note and target:

        translationURL = "https://translation.googleapis.com/language/translate/v2"
        call_params = {
            "key": dj_settings.GOOGLE_GEOLOC_API_KEY,
            "q": note,
            "target": target,
        }
        reply = requests.post(translationURL, params=call_params).json()

        if not "data" in reply:
            return JsonResponse({"status": request.POST, "error": reply})

        return JsonResponse(
            {"status": request.POST, "translation": reply["data"]["translations"][0]}
        )

    return JsonResponse(
        {"status": "error", "error": "No text or no language specified"}
    )
