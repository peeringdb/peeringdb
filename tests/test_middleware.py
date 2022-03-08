from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from peeringdb_server.middleware import PDBCommonMiddleware


def get_response_empty(request):
    return HttpResponse()


@override_settings(ROOT_URLCONF="middleware.urls")
class PDBCommonMiddlewareTest(SimpleTestCase):

    rf = RequestFactory()

    @override_settings(PDB_PREPEND_WWW=True)
    def test_prepend_www(self):
        request = self.rf.get("/path/")
        r = PDBCommonMiddleware(get_response_empty).process_request(request)
        self.assertEqual(r.status_code, 301)
        self.assertEqual(r.url, "http://www.testserver/path/")
