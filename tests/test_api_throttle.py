import datetime
import json

import pytest
from django.core.cache import caches
from django.core.management import call_command
from django.test import TestCase
from freezegun import freeze_time
from rest_framework.response import Response
from rest_framework.test import APIClient, APIRequestFactory

from peeringdb_server import models
from peeringdb_server import settings as pdb_settings
from peeringdb_server.rest import ModelViewSet
from peeringdb_server.rest_throttles import (
    APIAnonUserThrottle,
    APIUserThrottle,
    MelissaThrottle,
    ResponseSizeThrottle,
)

from .util import mock_csrf_session


class MockView(ModelViewSet):
    """
    Dummy view for testing throttling
    """

    throttle_classes = (APIUserThrottle, APIAnonUserThrottle)

    def get(self, request):
        return Response("example")


class MelissaMockView(ModelViewSet):
    """
    Dummy view for testing melissa throttling
    """

    throttle_classes = (MelissaThrottle,)

    def get(self, request):
        return Response("example")


class ResponseSizeMockView(ModelViewSet):
    """
    Dummy view for testing thorttling based on expected response size (#1126)
    """

    size = 1000

    throttle_classes = (ResponseSizeThrottle,)

    def get(self, request):
        r = Response("x" * self.size)
        ResponseSizeThrottle.cache_response_size(request, self.size)
        return r


class APIThrottleTests(TestCase):
    """
    API tests
    """

    @classmethod
    def setUp(self):
        """
        Reset the cache so that no throttles will be active
        """
        caches["default"].clear()
        caches["negative"].clear()

        self.factory = APIRequestFactory()
        self.rate_anon = env = models.EnvironmentSetting(
            setting="API_THROTTLE_RATE_ANON", value_str="10/minute"
        )
        env.save()
        self.rate_user = env = models.EnvironmentSetting(
            setting="API_THROTTLE_RATE_USER", value_str="10/minute"
        )
        env.save()

        env = models.EnvironmentSetting(
            setting="API_THROTTLE_RATE_ANON_MSG", value_str="Rate limit exceeded (anon)"
        )
        env.save()

        env = models.EnvironmentSetting(
            setting="API_THROTTLE_RATE_USER_MSG", value_str="Rate limit exceeded (user)"
        )
        env.save()

        env = models.EnvironmentSetting(
            setting="API_THROTTLE_RATE_WRITE", value_str="2/minute"
        )
        env.save()

        self.superuser = models.User.objects.create_user(
            "su", "neteng@20c.com", "su", is_superuser=True
        )
        self.org = models.REFTAG_MAP["org"].objects.create(name="Test Org", status="ok")

    def test_environment_throttle_setting(self):
        """
        Test if default throttle settings are overridden by environment settings
        """
        assert (
            models.EnvironmentSetting.get_setting_value("API_THROTTLE_RATE_ANON")
            == "10/minute"
        )
        assert (
            models.EnvironmentSetting.get_setting_value("API_THROTTLE_RATE_USER")
            == "10/minute"
        )
        assert (
            models.EnvironmentSetting.get_setting_value("API_THROTTLE_RATE_ANON_MSG")
            == "Rate limit exceeded (anon)"
        )
        assert (
            models.EnvironmentSetting.get_setting_value("API_THROTTLE_RATE_USER_MSG")
            == "Rate limit exceeded (user)"
        )
        assert (
            models.EnvironmentSetting.get_setting_value("API_THROTTLE_RATE_WRITE")
            == "2/minute"
        )

    def test_anon_requests_below_throttle_rate(self):
        """
        Test if request rate is limited for anonymous users
        """
        request = self.factory.get("/")
        mock_csrf_session(request)
        for dummy in range(10):
            response = MockView.as_view({"get": "get"})(request)
        assert response.status_code == 200

    def test_authenticated_requests_below_throttle_rate(self):
        """
        Test request rate is not limited for authenticated users
        """

        user = models.User(username="test")
        user.save()
        request = self.factory.get("/")
        mock_csrf_session(request)
        request.user = user
        for dummy in range(10):
            response = MockView.as_view({"get": "get"})(request)
        assert response.status_code == 200

    def test_admin_request_no_throttling(self):
        """
        admin users should not be throttled on generic api requests
        """

        user = models.User(username="test", is_superuser=True)
        user.save()
        request = self.factory.get("/")
        mock_csrf_session(request)
        request.user = user
        for dummy in range(20):
            response = MockView.as_view({"get": "get"})(request)
        assert response.status_code == 200

    def test_anon_requests_above_throttle_rate(self):
        """
        Ensure request rate is limited for anonymous users
        """

        request = self.factory.get("/")
        mock_csrf_session(request)
        for dummy in range(11):
            response = MockView.as_view({"get": "get"})(request)
        assert response.status_code == 429
        assert "Rate limit exceeded (anon)" in response.data["message"]

    def test_anon_requests_above_throttle_rate_dynamic_changes(self):
        """
        Ensure request rate is limited for anonymous users while
        changing the rate between requests
        """

        request = self.factory.get("/")
        mock_csrf_session(request)
        for dummy in range(11):
            response = MockView.as_view({"get": "get"})(request)
        assert response.status_code == 429
        assert "Rate limit exceeded (anon)" in response.data["message"]

        # adjust rate limit downwards

        self.rate_anon.value_str = "1/minute"
        self.rate_anon.save()

        # still rate limited, no error

        response = MockView.as_view({"get": "get"})(request)
        assert response.status_code == 429

        # adjust rate limit upwards

        self.rate_anon.value_str = "100/minute"
        self.rate_anon.save()

        # no longer rate limited, no error

        response = MockView.as_view({"get": "get"})(request)
        assert response.status_code == 200

        # adjust rate limit downwards (change duration)

        self.rate_anon.value_str = "1/hour"
        self.rate_anon.save()

        # rate limited again, no error

        response = MockView.as_view({"get": "get"})(request)
        assert response.status_code == 429

        # adjust rate limit upwards (change duration)

        self.rate_anon.value_str = "20/hour"
        self.rate_anon.save()

        # no longer rate limited (19 attempts), no error

        for idx in range(19):
            response = MockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

        # rate limited again, no error

        response = MockView.as_view({"get": "get"})(request)
        assert response.status_code == 429

    def test_authenticated_requests_above_throttle_rate(self):
        """
        Ensure request rate is not limited for authenticated users
        """

        user = models.User(username="test")
        user.save()
        request = self.factory.get("/")
        mock_csrf_session(request)
        request.user = user
        for dummy in range(11):
            response = MockView.as_view({"get": "get"})(request)
        assert response.status_code == 429
        assert "Rate limit exceeded (user)" in response.data["message"]

    def test_authenticated_requests_above_throttle_rate_dynamic_changes(self):
        """
        Ensure request rate is not limited for authenticated users
        """

        user = models.User(username="test")
        user.save()
        request = self.factory.get("/")
        mock_csrf_session(request)
        request.user = user
        for dummy in range(11):
            response = MockView.as_view({"get": "get"})(request)
        assert response.status_code == 429
        assert "Rate limit exceeded (user)" in response.data["message"]

        # adjust rate limit downwards

        self.rate_user.value_str = "1/minute"
        self.rate_user.save()

        # still rate limited, no error

        response = MockView.as_view({"get": "get"})(request)
        assert response.status_code == 429

        # adjust rate limit upwards

        self.rate_user.value_str = "100/minute"
        self.rate_user.save()

        # no longer rate limited, no error

        response = MockView.as_view({"get": "get"})(request)
        assert response.status_code == 200

        # adjust rate limit downwards (change duration)

        self.rate_user.value_str = "1/hour"
        self.rate_user.save()

        # rate limited again, no error

        response = MockView.as_view({"get": "get"})(request)
        assert response.status_code == 429

        # adjust rate limit upwards (change duration)

        self.rate_user.value_str = "20/hour"
        self.rate_user.save()

        # no longer rate limited (19 attempts), no error

        for idx in range(19):
            response = MockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

        # rate limited again, no error

        response = MockView.as_view({"get": "get"})(request)
        assert response.status_code == 429

    def test_response_size_ip_block(self):
        """
        Ensure request rate is limited based on response size
        for ip-block
        """

        request = self.factory.get("/")
        mock_csrf_session(request)
        request.META.update({"REMOTE_ADDR": "10.10.10.10"})

        # by default ip-block response size rate limiting is disabled
        # ip 10.10.10.10 requesting 10 times (all should be ok)

        for dummy in range(10):
            response = ResponseSizeMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

        # turn on response size throttling for responses bigger than 500 bytes
        # for ip blocks

        thold = models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_REPEATED_REQUEST_THRESHOLD_CIDR", value_int=500
        )
        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_REPEATED_REQUEST_RATE_CIDR", value_str="3/minute"
        )
        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_REPEATED_REQUEST_ENABLED_CIDR", value_bool=True
        )

        # ip 10.10.10.10 requesting 3 times (all should be ok)
        for dummy in range(3):
            response = ResponseSizeMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

        # ip 10.10.10.10 requesting 4th time (rate limited)
        response = ResponseSizeMockView.as_view({"get": "get"})(request)
        assert response.status_code == 429

        # ip 10.10.10.11 requesting 1st time (rate limited)
        request.META.update(REMOTE_ADDR="10.10.10.11")
        response = ResponseSizeMockView.as_view({"get": "get"})(request)
        assert response.status_code == 429

        # ip 20.10.10.10 requesting 1st time (ok)
        request.META.update(REMOTE_ADDR="20.10.10.10")
        response = ResponseSizeMockView.as_view({"get": "get"})(request)
        assert response.status_code == 200

        # increase threshold, no longer rate limited
        thold.value_int = 5000
        thold.save()

        # 10.10.10.10 requesting 3 times (all should be ok)
        request.META.update(REMOTE_ADDR="10.10.10.10")
        for dummy in range(3):
            response = ResponseSizeMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

    def test_response_size_ip_block_x_forwarded(self):
        """
        Ensure request rate is limited based on response size
        for ip-block with HTTP_X_FORWARDED_FOR set
        """

        request = self.factory.get("/")
        mock_csrf_session(request)
        request.META.update({"HTTP_X_FORWARDED_FOR": "10.10.10.10,77.77.77.77"})

        # by default ip-block response size rate limiting is disabled
        # ip 10.10.10.10 requesting 10 times (all should be ok)

        for dummy in range(10):
            response = ResponseSizeMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

        # turn on response size throttling for responses bigger than 500 bytes
        # for ip blocks

        thold = models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_REPEATED_REQUEST_THRESHOLD_CIDR", value_int=500
        )
        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_REPEATED_REQUEST_RATE_CIDR", value_str="3/minute"
        )
        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_REPEATED_REQUEST_ENABLED_CIDR", value_bool=True
        )

        # ip 10.10.10.10 requesting 3 times (all should be ok)
        for dummy in range(3):
            response = ResponseSizeMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

        # ip 10.10.10.10 requesting 4th time (rate limited)
        response = ResponseSizeMockView.as_view({"get": "get"})(request)
        assert response.status_code == 429

        # ip 10.10.10.11 requesting 1st time (rate limited)
        request.META.update(HTTP_X_FORWARDED_FOR="10.10.10.11,77.77.77.77")
        response = ResponseSizeMockView.as_view({"get": "get"})(request)
        assert response.status_code == 429

        # ip 20.10.10.10 requesting 1st time (ok)
        request.META.update(HTTP_X_FORWARDED_FOR="20.10.10.10,77.77.77.77")
        response = ResponseSizeMockView.as_view({"get": "get"})(request)
        assert response.status_code == 200

        # increase threshold, no longer rate limited
        thold.value_int = 5000
        thold.save()

        # 10.10.10.10 requesting 3 times (all should be ok)
        request.META.update(HTTP_X_FORWARDED_FOR="10.10.10.10,77.77.77.77")
        for dummy in range(3):
            response = ResponseSizeMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

    def test_response_size_ip(self):
        """
        Ensure request rate is limited based on response size
        for ip-address
        """

        request = self.factory.get("/")
        mock_csrf_session(request)
        request.META.update({"REMOTE_ADDR": "10.10.10.10"})

        # by default ip-address response size rate limiting is disabled
        # ip 10.10.10.10 requesting 10 times (all should be ok)

        for dummy in range(10):
            response = ResponseSizeMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

        # turn on response size throttling for responses bigger than 500 bytes
        # for ip addresses

        thold = models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_REPEATED_REQUEST_THRESHOLD_IP", value_int=500
        )
        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_REPEATED_REQUEST_RATE_IP", value_str="3/minute"
        )
        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_REPEATED_REQUEST_ENABLED_IP", value_bool=True
        )

        # ip 10.10.10.10 requesting 3 times (all should be ok)
        for dummy in range(3):
            response = ResponseSizeMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

        # ip 10.10.10.10 requesting 4th time (rate limited)
        response = ResponseSizeMockView.as_view({"get": "get"})(request)
        assert response.status_code == 429

        # ip 10.10.10.11 requesting 1st time (ok)
        request.META.update(REMOTE_ADDR="10.10.10.11")
        response = ResponseSizeMockView.as_view({"get": "get"})(request)
        assert response.status_code == 200

        # ip 20.10.10.10 requesting 1st time (ok)
        request.META.update(REMOTE_ADDR="20.10.10.10")
        response = ResponseSizeMockView.as_view({"get": "get"})(request)
        assert response.status_code == 200

        # increase threshold, no longer rate limited
        thold.value_int = 5000
        thold.save()

        # 10.10.10.10 requesting 3 times (all should be ok)
        request.META.update(REMOTE_ADDR="10.10.10.10")
        for dummy in range(3):
            response = ResponseSizeMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

    def test_response_size_user(self):
        """
        Ensure request rate is limited based on response size
        for authenticated users
        """

        user = models.User.objects.create_user(username="test", email="test@localhost")
        user_b = models.User.objects.create_user(
            username="test_2", email="test_2@localhost"
        )
        request = self.factory.get("/")
        mock_csrf_session(request)
        request.user = user

        # by default user response size rate limiting is disabled
        # ip 10.10.10.10 requesting 10 times (all should be ok)

        for dummy in range(10):
            response = ResponseSizeMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

        # turn on response size throttling for responses bigger than 500 bytes
        # for ip addresses

        thold = models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_REPEATED_REQUEST_THRESHOLD_USER", value_int=500
        )
        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_REPEATED_REQUEST_RATE_USER", value_str="3/minute"
        )
        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_REPEATED_REQUEST_ENABLED_USER", value_bool=True
        )

        # user requesting 3 times (all should be ok)
        for dummy in range(3):
            response = ResponseSizeMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

        # user requesting 4th time (rate limited)
        response = ResponseSizeMockView.as_view({"get": "get"})(request)
        assert response.status_code == 429

        # diff user requesting 1st time (ok)
        request.user = user_b
        response = ResponseSizeMockView.as_view({"get": "get"})(request)
        assert response.status_code == 200

        # increase threshold, no longer rate limited
        request.user = user
        thold.value_int = 5000
        thold.save()

        # user requesting 3 times (all should be ok)
        for dummy in range(3):
            response = ResponseSizeMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

    def test_response_size_admin(self):
        """
        Response size throttling should not be enabled for admins (#1172)
        """

        user = models.User.objects.create_user(username="test", is_superuser=True)
        request = self.factory.get("/")
        mock_csrf_session(request)
        request.user = user

        thold = models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_REPEATED_REQUEST_THRESHOLD_USER", value_int=500
        )
        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_REPEATED_REQUEST_RATE_USER", value_str="3/minute"
        )
        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_REPEATED_REQUEST_ENABLED_USER", value_bool=True
        )

        # no throttling since user is admin

        for dummy in range(100):
            response = ResponseSizeMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

    def test_response_size_org_key(self):
        """
        Ensure request rate is limited based on response size
        for organizations
        """

        org = models.Organization.objects.create(name="test", status="ok")
        org_b = models.Organization.objects.create(name="test b", status="ok")

        _, key = models.OrganizationAPIKey.objects.create_key(
            name="test", org=org, email="test@localhost"
        )
        _, key_b = models.OrganizationAPIKey.objects.create_key(
            name="test b", org=org_b, email="test@localhost"
        )

        request = self.factory.get("/")
        mock_csrf_session(request)
        request.META["HTTP_AUTHORIZATION"] = f"Api-Key {key}"

        # by default user response size rate limiting is disabled
        # requesting 10 times (all should be ok)

        for dummy in range(10):
            response = ResponseSizeMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

        # turn on response size throttling for responses bigger than 500 bytes
        # for ip addresses

        thold = models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_REPEATED_REQUEST_THRESHOLD_ORG", value_int=500
        )
        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_REPEATED_REQUEST_RATE_ORG", value_str="3/minute"
        )
        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_REPEATED_REQUEST_ENABLED_ORG", value_bool=True
        )

        # requesting 3 times (all should be ok)
        for dummy in range(3):
            response = ResponseSizeMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

        # requesting 4th time (rate limited)
        response = ResponseSizeMockView.as_view({"get": "get"})(request)
        assert response.status_code == 429

        # diff org requesting 1st time (ok)
        request.META.update(HTTP_AUTHORIZATION=f"Api-Key {key_b}")
        response = ResponseSizeMockView.as_view({"get": "get"})(request)
        assert response.status_code == 200

        # increase threshold, no longer rate limited
        thold.value_int = 5000
        thold.save()

        # requesting 3 times (all should be ok)
        request.META.update(HTTP_AUTHORIZATION=f"Api-Key {key}")
        for dummy in range(3):
            response = ResponseSizeMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

    def test_melissa_ip(self):
        """
        Ensure request rate is limited based on melissa enabled queries
        for unauthenticated queries
        """

        request = self.factory.get("/api/fac", {"country": "US", "state": "IL"})
        mock_csrf_session(request)
        request.META.update({"REMOTE_ADDR": "10.10.10.10"})

        # by default melissa rate limiting is disabled
        # requesting 10 times (all should be ok)

        for dummy in range(10):
            response = MelissaMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

        # turn on response size throttling for responses bigger than 500 bytes

        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_MELISSA_RATE_IP", value_str="3/minute"
        )
        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_MELISSA_ENABLED_IP", value_bool=True
        )

        # requesting 3 times (all should be ok)
        for dummy in range(3):
            response = MelissaMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

        # requesting 4th time (rate limited)
        response = MelissaMockView.as_view({"get": "get"})(request)
        assert response.status_code == 429
        assert "geo address normalization" in response.data["message"]

        # diff user requesting 1st time (ok)
        request.META.update({"REMOTE_ADDR": "10.10.10.11"})
        response = MelissaMockView.as_view({"get": "get"})(request)
        assert response.status_code == 200

    def test_melissa_user(self):
        """
        Ensure request rate is limited based on melissa enabled queries
        for authenticated users
        """

        user = models.User.objects.create_user(username="test", email="test@localhost")
        user_b = models.User.objects.create_user(
            username="test_2", email="test_2@localhost"
        )
        request = self.factory.get("/api/fac", {"country": "US", "state": "IL"})
        mock_csrf_session(request)
        request.user = user

        # by default melissa rate limiting is disabled
        # requesting 10 times (all should be ok)

        for dummy in range(10):
            response = MelissaMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

        # turn on response size throttling for responses bigger than 500 bytes

        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_MELISSA_RATE_USER", value_str="3/minute"
        )
        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_MELISSA_ENABLED_USER", value_bool=True
        )

        # requesting 3 times (all should be ok)
        for dummy in range(3):
            response = MelissaMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

        # requesting 4th time (rate limited)
        response = MelissaMockView.as_view({"get": "get"})(request)
        assert response.status_code == 429
        assert "geo address normalization" in response.data["message"]

        # diff user requesting 1st time (ok)
        request.user = user_b
        response = MelissaMockView.as_view({"get": "get"})(request)
        assert response.status_code == 200

    def test_melissa_admin(self):
        """
        Ensure request rate is limited based on melissa enabled queries
        for authenticated users with admin status
        """

        user = models.User.objects.create_user(
            username="test", email="test@localhost", is_superuser=True
        )
        user_b = models.User.objects.create_user(
            username="test_2", email="test_2@localhost", is_superuser=True
        )
        request = self.factory.get("/api/fac", {"country": "US", "state": "IL"})
        mock_csrf_session(request)
        request.user = user

        # by default melissa rate limiting is disabled
        # requesting 10 times (all should be ok)

        for dummy in range(10):
            response = MelissaMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

        # turn on response size throttling for responses bigger than 500 bytes

        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_MELISSA_RATE_ADMIN", value_str="3/minute"
        )
        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_MELISSA_ENABLED_ADMIN", value_bool=True
        )

        # also set up normal user throttling to test that it is ignored.

        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_MELISSA_RATE_USER", value_str="1/minute"
        )
        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_MELISSA_ENABLED_USER", value_bool=True
        )

        # requesting 3 times (all should be ok)
        for dummy in range(3):
            response = MelissaMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

        # requesting 4th time (rate limited)
        response = MelissaMockView.as_view({"get": "get"})(request)
        assert response.status_code == 429
        assert "geo address normalization" in response.data["message"]

        # diff user requesting 1st time (ok)
        request.user = user_b
        response = MelissaMockView.as_view({"get": "get"})(request)
        assert response.status_code == 200

    def test_melissa_org_key(self):
        """
        Ensure request rate is limited based on melissa enabled queries
        for organizations
        """

        org = models.Organization.objects.create(name="test", status="ok")
        org_b = models.Organization.objects.create(name="test b", status="ok")

        _, key = models.OrganizationAPIKey.objects.create_key(
            name="test", org=org, email="test@localhost"
        )
        _, key_b = models.OrganizationAPIKey.objects.create_key(
            name="test b", org=org_b, email="test@localhost"
        )

        request = self.factory.get("/api/fac", {"country": "US", "state": "IL"})
        mock_csrf_session(request)
        request.META["HTTP_AUTHORIZATION"] = f"Api-Key {key}"

        # by default melissa rate limiting is disabled
        # requesting 10 times (all should be ok)

        for dummy in range(10):
            response = MelissaMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

        # turn on response size throttling for responses bigger than 500 bytes

        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_MELISSA_RATE_ORG", value_str="3/minute"
        )
        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_MELISSA_ENABLED_ORG", value_bool=True
        )

        # requesting 3 times (all should be ok)
        for dummy in range(3):
            response = MelissaMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

        # requesting 4th time (rate limited)
        response = MelissaMockView.as_view({"get": "get"})(request)
        assert response.status_code == 429
        assert "geo address normalization" in response.data["message"]

        # diff org requesting 1st time (ok)
        request.META.update(HTTP_AUTHORIZATION=f"Api-Key {key_b}")
        response = MelissaMockView.as_view({"get": "get"})(request)
        assert response.status_code == 200

    def test_post_ratelimit(self):
        try:
            pdb_settings.TUTORIAL_MODE = True
            client = APIClient()
            client.force_authenticate(self.superuser)
            net = models.Network.objects.create(name="test", org=self.org, asn=9999999)
            for i in range(1, 5):
                # max post 2/minute
                r = client.post(
                    "/api/net",
                    {
                        "org_id": self.org.pk,
                        "name": f"Test net {i}",
                        "asn": 64496 + i,
                        "website": f"https://www.example{i}.com",
                    },
                    format="json",
                )
                content = json.loads(r.content)
                if i <= 2:
                    assert r.status_code == 201
                else:
                    # Block by django-ratelimit
                    assert content["meta"]["error"] == "Too Many Requests"
                    assert r.status_code == 429

            with freeze_time(datetime.datetime.now() + datetime.timedelta(minutes=1)):
                # Jump 1 minute for the block from django ratelimit to end
                r = client.post(
                    "/api/net",
                    {
                        "org_id": self.org.pk,
                        "name": "Test net",
                        "asn": 64496,
                        "website": "https://www.example.com",
                    },
                    format="json",
                )
                assert r.status_code == 201
        finally:
            pdb_settings.TUTORIAL_MODE = False
