import os
import pytest

import django_init
from peeringdb_server.inet import RdapLookup, RdapNotFoundError

pytest.setup_filedata(os.path.dirname(__file__))


def pytest_generate_tests(metafunc):
    for fixture in metafunc.fixturenames:
        if fixture.startswith('data_'):
            data = pytest.get_filedata(fixture)
            metafunc.parametrize(fixture, data.values(), ids=data.keys())


@pytest.fixture
def rdap():
    return RdapLookup()
