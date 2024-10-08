import json
import logging
from urllib.parse import parse_qsl, urlencode, urlparse

from django.contrib.auth.mixins import AccessMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.core.signing import BadSignature
from django.http import JsonResponse
from django.shortcuts import resolve_url
from django.urls import reverse
from django.utils import timezone
from django.views.generic import FormView, View
from oauth2_provider.exceptions import OAuthToolkitError
from oauth2_provider.forms import AllowForm
from oauth2_provider.http import OAuth2ResponseRedirect
from oauth2_provider.models import get_access_token_model, get_application_model
from oauth2_provider.scopes import get_scopes_backend
from oauth2_provider.settings import oauth2_settings
from oauth2_provider.views.mixins import OAuthLibMixin

log = logging.getLogger("oauth2_provider")


class LoginRequiredMixin(AccessMixin):
    """Verify that the current user is authenticated."""

    def dispatch(self, request, *args, **kwargs):
        try:
            request.get_signed_cookie("oauth_session")
        except (KeyError, BadSignature):
            return self.handle_no_permission()
        response = super().dispatch(request, *args, **kwargs)
        return response

    def handle_no_permission(self):
        if self.raise_exception:
            raise PermissionDenied(self.get_permission_denied_message())

        path = self.request.build_absolute_uri()
        resolved_login_url = resolve_url(self.get_login_url())
        # If the login url is the same scheme and net location then use the
        # path as the "next" url.
        login_scheme, login_netloc = urlparse(resolved_login_url)[:2]
        current_scheme, current_netloc = urlparse(path)[:2]
        if (not login_scheme or login_scheme == current_scheme) and (
            not login_netloc or login_netloc == current_netloc
        ):
            path = self.request.get_full_path()
        return redirect_to_login(
            path,
            resolved_login_url,
            self.get_redirect_field_name(),
        )


class BaseAuthorizationView(LoginRequiredMixin, OAuthLibMixin, View):
    """
    Implements a generic endpoint to handle *Authorization Requests* as in :rfc:`4.1.1`. The view
    does not implement any strategy to determine *authorize/do not authorize* logic.
    The endpoint is used in the following flows:

    * Authorization code
    * Implicit grant

    """

    def dispatch(self, request, *args, **kwargs):
        self.oauth2_data = {}
        return super().dispatch(request, *args, **kwargs)

    def error_response(self, error, application, **kwargs):
        """
        Handle errors either by redirecting to redirect_uri with a json in the body containing
        error details or providing an error response
        """
        redirect, error_response = super().error_response(error, **kwargs)

        if redirect:
            return self.redirect(error_response["url"], application)

        status = error_response["error"].status_code
        return self.render_to_response(error_response, status=status)

    def redirect(self, redirect_to, application):
        if application is None:
            # The application can be None in case of an error during app validation
            # In such cases, fall back to default ALLOWED_REDIRECT_URI_SCHEMES
            allowed_schemes = oauth2_settings.ALLOWED_REDIRECT_URI_SCHEMES
        else:
            allowed_schemes = application.get_allowed_schemes()
        return OAuth2ResponseRedirect(redirect_to, allowed_schemes)


RFC3339 = "%Y-%m-%dT%H:%M:%SZ"


class AuthorizationView(BaseAuthorizationView, FormView):
    """
    Implements an endpoint to handle *Authorization Requests* as in :rfc:`4.1.1` and prompting the
    user with a form to determine if she authorizes the client application to access her data.
    This endpoint is reached two times during the authorization process:
    * first receive a ``GET`` request from user asking authorization for a certain client
    application, a form is served possibly showing some useful info and prompting for
    *authorize/do not authorize*.

    * then receive a ``POST`` request possibly after user authorized the access

    Some informations contained in the ``GET`` request and needed to create a Grant token during
    the ``POST`` request would be lost between the two steps above, so they are temporarily stored in
    hidden fields on the form.
    A possible alternative could be keeping such informations in the session.

    The endpoint is used in the following flows:
    * Authorization code
    * Implicit grant
    """

    template_name = "oauth2_provider/authorize.html"
    form_class = AllowForm

    skip_authorization_completely = False

    def get_initial(self):
        # TODO: move this scopes conversion from and to string into a utils function
        scopes = self.oauth2_data.get("scope", self.oauth2_data.get("scopes", []))
        initial_data = {
            "redirect_uri": self.oauth2_data.get("redirect_uri", None),
            "scope": " ".join(scopes),
            "nonce": self.oauth2_data.get("nonce", None),
            "client_id": self.oauth2_data.get("client_id", None),
            "state": self.oauth2_data.get("state", None),
            "response_type": self.oauth2_data.get("response_type", None),
            "code_challenge": self.oauth2_data.get("code_challenge", None),
            "code_challenge_method": self.oauth2_data.get(
                "code_challenge_method", None
            ),
            "claims": self.oauth2_data.get("claims", None),
        }
        return initial_data

    def form_valid(self, form):
        client_id = form.cleaned_data["client_id"]
        application = get_application_model().objects.get(client_id=client_id)
        credentials = {
            "client_id": form.cleaned_data.get("client_id"),
            "redirect_uri": form.cleaned_data.get("redirect_uri"),
            "response_type": form.cleaned_data.get("response_type", None),
            "state": form.cleaned_data.get("state", None),
        }
        if form.cleaned_data.get("code_challenge", False):
            credentials["code_challenge"] = form.cleaned_data.get("code_challenge")
        if form.cleaned_data.get("code_challenge_method", False):
            credentials["code_challenge_method"] = form.cleaned_data.get(
                "code_challenge_method"
            )
        if form.cleaned_data.get("nonce", False):
            credentials["nonce"] = form.cleaned_data.get("nonce")
        if form.cleaned_data.get("claims", False):
            credentials["claims"] = form.cleaned_data.get("claims")

        scopes = form.cleaned_data.get("scope")
        allow = form.cleaned_data.get("allow")

        try:
            uri, headers, body, status = self.create_authorization_response(
                request=self.request,
                scopes=scopes,
                credentials=credentials,
                allow=allow,
            )
        except OAuthToolkitError as error:
            return self.error_response(error, application)

        self.success_url = uri
        log.debug(f"Success url for the request: {self.success_url}")
        return self.redirect(self.success_url, application)

    def get(self, request, *args, **kwargs):
        try:
            scopes, credentials = self.validate_authorization_request(request)
        except OAuthToolkitError as error:
            # Application is not available at this time.
            return self.error_response(error, application=None)

        prompt = request.GET.get("prompt")
        if prompt == "login" or not request.user.is_authenticated:
            return self.handle_prompt_login()

        all_scopes = get_scopes_backend().get_all_scopes()
        kwargs["scopes_descriptions"] = [all_scopes[scope] for scope in scopes]
        kwargs["scopes"] = scopes
        # at this point we know an Application instance with such client_id exists in the database

        # TODO: Cache this!
        application = get_application_model().objects.get(
            client_id=credentials["client_id"]
        )

        kwargs["application"] = application
        kwargs["client_id"] = credentials["client_id"]
        kwargs["redirect_uri"] = credentials["redirect_uri"]
        kwargs["response_type"] = credentials["response_type"]
        kwargs["state"] = credentials["state"]
        if "code_challenge" in credentials:
            kwargs["code_challenge"] = credentials["code_challenge"]
        if "code_challenge_method" in credentials:
            kwargs["code_challenge_method"] = credentials["code_challenge_method"]
        if "nonce" in credentials:
            kwargs["nonce"] = credentials["nonce"]
        if "claims" in credentials:
            kwargs["claims"] = json.dumps(credentials["claims"])

        self.oauth2_data = kwargs
        # following two loc are here only because of https://code.djangoproject.com/ticket/17795
        form = self.get_form(self.get_form_class())
        kwargs["form"] = form

        # Check to see if the user has already granted access and return
        # a successful response depending on "approval_prompt" url parameter
        require_approval = request.GET.get(
            "approval_prompt", oauth2_settings.REQUEST_APPROVAL_PROMPT
        )

        try:
            # If skip_authorization field is True, skip the authorization screen even
            # if this is the first use of the application and there was no previous authorization.
            # This is useful for in-house applications-> assume an in-house applications
            # are already approved.
            if application.skip_authorization:
                uri, headers, body, status = self.create_authorization_response(
                    request=self.request,
                    scopes=" ".join(scopes),
                    credentials=credentials,
                    allow=True,
                )
                return self.redirect(uri, application)

            elif require_approval == "auto":
                tokens = (
                    get_access_token_model()
                    .objects.filter(
                        user=request.user,
                        application=kwargs["application"],
                        expires__gt=timezone.now(),
                    )
                    .all()
                )

                # check past authorizations regarded the same scopes as the current one
                for token in tokens:
                    if token.allow_scopes(scopes):
                        uri, headers, body, status = self.create_authorization_response(
                            request=self.request,
                            scopes=" ".join(scopes),
                            credentials=credentials,
                            allow=True,
                        )
                        return self.redirect(uri, application)

        except OAuthToolkitError as error:
            return self.error_response(error, application)

        return self.render_to_response(self.get_context_data(**kwargs))

    def handle_prompt_login(self):
        path = self.request.build_absolute_uri()
        resolved_login_url = resolve_url(self.get_login_url())

        # If the login url is the same scheme and net location then use the
        # path as the "next" url.
        login_scheme, login_netloc = urlparse(resolved_login_url)[:2]
        current_scheme, current_netloc = urlparse(path)[:2]
        if (not login_scheme or login_scheme == current_scheme) and (
            not login_netloc or login_netloc == current_netloc
        ):
            path = self.request.get_full_path()

        parsed = urlparse(path)

        parsed_query = dict(parse_qsl(parsed.query))
        parsed_query.pop("prompt", None)

        parsed = parsed._replace(query=urlencode(parsed_query))

        return redirect_to_login(
            parsed.geturl(),
            resolved_login_url,
            self.get_redirect_field_name(),
        )


Application = get_application_model()


class OAuthMetadataView(View):
    def get(self, request, *args, **kwargs):
        issuer_url = oauth2_settings.OIDC_ISS_ENDPOINT

        if not issuer_url:
            issuer_url = oauth2_settings.oidc_issuer(request)
            authorization_endpoint = request.build_absolute_uri(
                reverse("oauth2_provider:authorize")
            )
            token_endpoint = request.build_absolute_uri(
                reverse("oauth2_provider:token")
            )
            jwks_uri = request.build_absolute_uri(reverse("oauth2_provider:jwks-info"))
            revocation_endpoint = request.build_absolute_uri(
                reverse("oauth2_provider:revoke-token")
            )
            introspection_endpoint = request.build_absolute_uri(
                reverse("oauth2_provider:introspect")
            )
        else:
            parsed_url = urlparse(oauth2_settings.OIDC_ISS_ENDPOINT)
            host = parsed_url.scheme + "://" + parsed_url.netloc
            authorization_endpoint = "{}{}".format(
                host, reverse("oauth2_provider:authorize")
            )
            token_endpoint = "{}{}".format(host, reverse("oauth2_provider:token"))
            jwks_uri = "{}{}".format(host, reverse("oauth2_provider:jwks-info"))
            revocation_endpoint = "{}{}".format(
                host, reverse("oauth2_provider:revoke-token")
            )
            introspection_endpoint = "{}{}".format(
                host, reverse("oauth2_provider:introspect")
            )
        signing_algorithms = [Application.HS256_ALGORITHM]
        if oauth2_settings.OIDC_RSA_PRIVATE_KEY:
            signing_algorithms = [
                Application.RS256_ALGORITHM,
                Application.HS256_ALGORITHM,
            ]

        validator_class = oauth2_settings.OAUTH2_VALIDATOR_CLASS
        validator = validator_class()
        oidc_claims = list(set(validator.get_discovery_claims(request)))
        scopes_class = oauth2_settings.SCOPES_BACKEND_CLASS
        scopes = scopes_class()
        scopes_supported = [scope for scope in scopes.get_available_scopes()]

        # OAuth 2.0 and OpenID Connect Metadata
        data = {
            "issuer": issuer_url,
            "authorization_endpoint": authorization_endpoint,
            "token_endpoint": token_endpoint,
            "jwks_uri": jwks_uri,
            "response_types_supported": oauth2_settings.OIDC_RESPONSE_TYPES_SUPPORTED,
            "subject_types_supported": oauth2_settings.OIDC_SUBJECT_TYPES_SUPPORTED,
            "grant_types_supported": [
                "authorization_code",
                "implicit",
                "password",
                "client_credentials",
                "openid hybrid",
            ],
            "token_endpoint_auth_methods_supported": [
                "client_secret_basic",
                "client_secret_post",
            ],
            "revocation_endpoint": revocation_endpoint,
            "introspection_endpoint": introspection_endpoint,
            "oidc_claims_supported": oidc_claims,
            "scopes_supported": scopes_supported,
            "signing_algorithms_supported": signing_algorithms,
        }

        response = JsonResponse(data)
        return response
