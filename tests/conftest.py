import os

import pytest
import pytest_filedata

from peeringdb_server.inet import RdapLookup, RdapNotFoundError

pytest_filedata.setup(os.path.dirname(__file__))


def pytest_generate_tests(metafunc):
    for fixture in metafunc.fixturenames:
        if fixture.startswith("data_"):
            data = pytest_filedata.get_data(fixture)
            metafunc.parametrize(fixture, list(data.values()), ids=list(data.keys()))


@pytest.fixture
def rdap():
    return RdapLookup()


@pytest.fixture
def ixf_importer_user():
    from django.contrib.auth import get_user_model

    user, created = get_user_model().objects.get_or_create(
        username="ixf_importer",
        email="ixf_importer@localhost",
    )
    return user


@pytest.fixture(autouse=True)
def cleanup(request):
    """Cleanup a django cache after each test"""

    from django.core.cache import caches

    for name in caches:
        caches[name].clear()
