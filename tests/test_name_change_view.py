import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

User = get_user_model()


@pytest.mark.django_db
def test_view_name_change_success():
    user = User.objects.create_user(
        username="testuser",
        email="test@email.com",
        first_name="First",
        last_name="Last",
    )
    user.set_password("test1234")
    user.save()

    client = Client()
    client.login(username="testuser", password="test1234")

    change_name_url = reverse("change-name")
    profile_url = reverse("user-profile")

    response = client.get(profile_url)
    assert response.status_code == 200

    response = client.post(
        change_name_url,
        {"first_name": "NewFirst", "last_name": "NewLast"},
    )
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.first_name == "NewFirst"
    assert user.last_name == "NewLast"


@pytest.mark.django_db
def test_view_name_change_invalid_data(client, user):
    client.force_login(user)
    url = reverse("change-name")
    data = {"first_name": "", "last_name": "TooLong" * 100}
    response = client.post(url, data, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
    assert response.status_code == 400
    errors = response.json()
    assert isinstance(errors, dict)
    assert "first_name" in errors or "last_name" in errors


@pytest.mark.django_db
def test_view_profile_name_change(client, user):
    client.force_login(user)
    url = reverse("user-profile")
    response = client.get(url)
    assert response.status_code == 200
    assert b"<form" in response.content
    assert b'name="first_name"' in response.content
    assert b'name="last_name"' in response.content


@pytest.mark.django_db
def test_view_name_change_validation_error(client, user):
    client.force_login(user)
    url = reverse("change-name")
    data = {"first_name": "ExistingUniqueName", "last_name": "NewLast"}
    response = client.post(url, data)
    assert response.status_code == 400
    errors = response.json()
    assert isinstance(errors, dict)


@pytest.fixture
def user(db):
    """Fixture to create a test user."""
    user = User.objects.create_user(username="testuser", password="testpassword")
    return user


@pytest.fixture
def client():
    """Fixture to provide a Django test client."""
    return Client()
