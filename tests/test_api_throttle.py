import pytest
from django.core.cache import cache
from django.test import TestCase
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory

from peeringdb_server import models
from peeringdb_server.rest import ModelViewSet
from peeringdb_server.rest_throttles import APIAnonUserThrottle, APIUserThrottle


class MockView(ModelViewSet):
    """
    Dummy view for testing throttling
    """

    throttle_classes = (APIUserThrottle, APIAnonUserThrottle)

    def get(self, request):
        return Response("example")


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
