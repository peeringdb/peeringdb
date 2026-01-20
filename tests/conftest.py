import os

import elasticsearch as es_module
import pytest
import pytest_filedata
from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.core.management import call_command

from peeringdb_server.inet import RdapLookup

pytest_filedata.setup(os.path.dirname(__file__))


@pytest.fixture(scope="session")
def elasticsearch():
    """
    Elasticsearch client fixture.
    """
    es_url = os.environ.get("ELASTICSEARCH_URL", "http://elasticsearch:9200")

    try:
        client = es_module.Elasticsearch(es_url)
        info = client.info()
        print(f"Connected to Elasticsearch {info['version']['number']}")
        return client
    except Exception as e:
        pytest.fail(f"Failed to connect to Elasticsearch at {es_url}: {e}")


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
    user, created = get_user_model().objects.get_or_create(
        username="ixf_importer",
        email="ixf_importer@localhost",
    )
    return user


@pytest.fixture(scope="class")
def elasticsearch_index(elasticsearch, django_db_setup, django_db_blocker):
    """
    Indexing test data into Elasticsearch for search tests.
    """
    with django_db_blocker.unblock():
        call_command("pdb_search_index", "--rebuild", "-f")
        try:
            elasticsearch.indices.refresh(index="_all")
        except Exception:
            raise
    yield elasticsearch


@pytest.fixture(autouse=True)
def cleanup(request):
    """Cleanup a django cache after each test"""

    for name in caches:
        caches[name].clear()
