import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from rest_framework.response import Response
from rest_framework.test import APIClient, APIRequestFactory

from peeringdb_server import models
from peeringdb_server.rest import ModelViewSet
from peeringdb_server.rest_throttles import (
    APIAnonUserThrottle,
    APIUserThrottle,
    MelissaThrottle,
    ResponseSizeThrottle,
)


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
        cache.clear()

        self.factory = APIRequestFactory()
        env = models.EnvironmentSetting(
            setting="API_THROTTLE_RATE_ANON", value_str="10/minute"
        )
        env.save()
        env = models.EnvironmentSetting(
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

    def test_anon_requests_below_throttle_rate(self):
        """
        Test if request rate is limited for anonymous users
        """
        request = self.factory.get("/")
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
        request.user = user
        for dummy in range(10):
            response = MockView.as_view({"get": "get"})(request)
        assert response.status_code == 200

    def test_anon_requests_above_throttle_rate(self):
        """
        Ensure request rate is limited for anonymous users
        """

        request = self.factory.get("/")
        for dummy in range(11):
            response = MockView.as_view({"get": "get"})(request)
        assert response.status_code == 429
        assert "Rate limit exceeded (anon)" in response.data["message"]

    def test_authenticated_requests_above_throttle_rate(self):
        """
        Ensure request rate is not limited for authenticated users
        """

        user = models.User(username="test")
        user.save()
        request = self.factory.get("/")
        request.user = user
        for dummy in range(11):
            response = MockView.as_view({"get": "get"})(request)
        assert response.status_code == 429
        assert "Rate limit exceeded (user)" in response.data["message"]

    def test_response_size_ip_block(self):
        """
        Ensure request rate is limited based on response size
        for ip-block
        """

        request = self.factory.get("/")
        request.META.update({"REMOTE_ADDR": "10.10.10.10"})

        # by default ip-block response size rate limiting is disabled
        # ip 10.10.10.10 requesting 10 times (all should be ok)

        for dummy in range(10):
            response = ResponseSizeMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

        # turn on response size throttling for responses bigger than 500 bytes
        # for ip blocks

        thold = models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_RESPONSE_SIZE_THRESHOLD_CIDR", value_int=500
        )
        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_RESPONSE_SIZE_RATE_CIDR", value_str="3/minute"
        )
        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_RESPONSE_SIZE_ENABLED_CIDR", value_bool=True
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

    def test_response_size_ip(self):
        """
        Ensure request rate is limited based on response size
        for ip-address
        """

        request = self.factory.get("/")
        request.META.update({"REMOTE_ADDR": "10.10.10.10"})

        # by default ip-address response size rate limiting is disabled
        # ip 10.10.10.10 requesting 10 times (all should be ok)

        for dummy in range(10):
            response = ResponseSizeMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

        # turn on response size throttling for responses bigger than 500 bytes
        # for ip addresses

        thold = models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_RESPONSE_SIZE_THRESHOLD_IP", value_int=500
        )
        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_RESPONSE_SIZE_RATE_IP", value_str="3/minute"
        )
        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_RESPONSE_SIZE_ENABLED_IP", value_bool=True
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

        user = models.User.objects.create_user(username="test")
        user_b = models.User.objects.create_user(username="test_2")
        request = self.factory.get("/")
        request.user = user

        # by default user response size rate limiting is disabled
        # ip 10.10.10.10 requesting 10 times (all should be ok)

        for dummy in range(10):
            response = ResponseSizeMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

        # turn on response size throttling for responses bigger than 500 bytes
        # for ip addresses

        thold = models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_RESPONSE_SIZE_THRESHOLD_USER", value_int=500
        )
        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_RESPONSE_SIZE_RATE_USER", value_str="3/minute"
        )
        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_RESPONSE_SIZE_ENABLED_USER", value_bool=True
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
        request.META["HTTP_AUTHORIZATION"] = f"Api-Key {key}"

        # by default user response size rate limiting is disabled
        # requesting 10 times (all should be ok)

        for dummy in range(10):
            response = ResponseSizeMockView.as_view({"get": "get"})(request)
            assert response.status_code == 200

        # turn on response size throttling for responses bigger than 500 bytes
        # for ip addresses

        thold = models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_RESPONSE_SIZE_THRESHOLD_ORG", value_int=500
        )
        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_RESPONSE_SIZE_RATE_ORG", value_str="3/minute"
        )
        models.EnvironmentSetting.objects.create(
            setting="API_THROTTLE_RESPONSE_SIZE_ENABLED_ORG", value_bool=True
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

        user = models.User.objects.create_user(username="test")
        user_b = models.User.objects.create_user(username="test_2")
        request = self.factory.get("/api/fac", {"country": "US", "state": "IL"})
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
