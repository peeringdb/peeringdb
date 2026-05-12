import os

import elasticsearch as es_module
import pytest
import pytest_filedata
from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.core.management import call_command
from django.db import connections
from django.test import TestCase, TransactionTestCase

from peeringdb_server.inet import RdapLookup

pytest_filedata.setup(os.path.dirname(__file__))

# Read-replica routing in test mode (see mainsite/settings/__init__.py)
# adds a "read" alias mirrored to default's connection. Allow Django's
# per-test DB-access guard to see queries against either alias.
TestCase.databases = {"default", "read"}
TransactionTestCase.databases = {"default", "read"}

# The connection-aliasing trick below reaches into Django's
# ConnectionHandler internals (`_connections`). If a future Django
# release renames this attribute, we want to fail loudly here at
# conftest-load time rather than silently routing tests at half
# coverage (separate connections, setUpTestData txns invisible across
# the alias).
assert hasattr(connections, "_connections"), (
    "django.db.connections._connections is missing — Django's internal "
    "layout changed. Update tests/conftest.py's connection-aliasing "
    "fixture before relying on it."
)


def pytest_collection_modifyitems(config, items):
    """
    Default the @pytest.mark.django_db marker's `databases` arg to both
    aliases when not explicitly set, so pytest-django-style tests get
    the same coverage as TestCase subclasses.
    """
    for item in items:
        for marker in item.iter_markers(name="django_db"):
            marker.kwargs.setdefault("databases", ["default", "read"])


@pytest.fixture(scope="session", autouse=True)
def _share_read_connection_with_default(django_db_setup):
    """
    The "read" alias is configured with TEST.MIRROR=default so it points
    at the same test database, but Django still hands out a separate
    DatabaseWrapper per alias. That separation means setUpTestData's
    class-level transaction on `default` is invisible to queries via
    `read` (uncommitted-txn isolation between connections), which would
    cause every TestCase that combines setUpTestData with a view-based
    request to fail under the production router.

    Alias the connection objects so reads via "read" share `default`'s
    connection — and therefore its transaction state — for the lifetime
    of the test session.
    """
    connections["read"]  # trigger lazy creation of the wrapper
    connections._connections.read = connections._connections.default
    yield


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
