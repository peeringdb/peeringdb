import os
import pytest
import pytest_filedata

import django_init
from peeringdb_server.inet import RdapLookup, RdapNotFoundError


pytest_filedata.setup(os.path.dirname(__file__))


def pytest_generate_tests(metafunc):
    for fixture in metafunc.fixturenames:
        if fixture.startswith('data_'):
            data = pytest_filedata.get_data(fixture)
            metafunc.parametrize(fixture, list(data.values()), ids=list(data.keys()))


@pytest.fixture
def rdap():
    return RdapLookup()
