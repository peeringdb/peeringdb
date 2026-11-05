from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from csp.constants import HEADER
from django.conf import settings
from django.test import Client

import peeringdb_server

from .util import ClientCase

APP_DIR = Path(peeringdb_server.__file__).parent

# hosts that served assets we now ship from static (#518). the two Google
# Fonts hosts stay in the policy because the Maps JS API loads its own fonts
# from them, but none of our templates or static files may reference them.
SELF_HOSTED_ASSET_HOSTS = [
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "cdn.redoc.ly",
    "unpkg.com",
]
REMOVED_POLICY_HOSTS = ["cdn.redoc.ly", "unpkg.com"]

# redoc's sidebar footer always renders its logo from cdn.redoc.ly; img-src
# blocks it and redoc hides the image on error
SELF_HOSTED_SCAN_EXCLUDE = {"static/redoc/redoc.standalone.js"}

PRELOAD_DIRECTIVES = {
    "font": "font-src",
    "script": "script-src",
    "style": "style-src",
}


class AssetTagParser(HTMLParser):
    """
    Collect (directive, host) for script and link tags that load a script,
    stylesheet or preloaded resource from another host.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.assets = []

    def handle_starttag(self, tag, attrs):
        attrs = {name: value or "" for name, value in attrs}
        if tag == "script":
            url, directive = attrs.get("src"), "script-src"
        elif tag == "link":
            rel = attrs.get("rel", "").lower().split()
            if "stylesheet" in rel:
                directive = "style-src"
            elif "modulepreload" in rel:
                directive = "script-src"
            elif "preload" in rel:
                directive = PRELOAD_DIRECTIVES.get(
                    attrs.get("as", "").lower(), "default-src"
                )
            else:
                return
            url = attrs.get("href")
        else:
            return
        host = urlsplit(url or "").hostname
        if host:
            self.assets.append((directive, host))


def offsite_assets(html):
    parser = AssetTagParser()
    parser.feed(html)
    parser.close()
    return parser.assets


class CSPTest(ClientCase):
    """
    django-csp only emits a policy for the settings format of the version
    installed -- the pre-4.0 CSP_* settings are silently ignored by 4.x, so a
    bad settings migration drops the header entirely without failing anything
    else (#1933).
    """

    def test_csp_header_present(self):
        resp = Client().get("/apidocs/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(HEADER, resp)

        policy = resp[HEADER]
        for directive, sources in settings.CONTENT_SECURITY_POLICY[
            "DIRECTIVES"
        ].items():
            self.assertIn(directive, policy)
            for source in sources:
                self.assertIn(source, policy)

    def test_csp_omits_removed_hosts(self):
        policy = Client().get("/apidocs/")[HEADER]
        for host in REMOVED_POLICY_HOSTS:
            self.assertNotIn(host, policy)

    def test_apidocs_load_local_assets(self):
        for url in ("/apidocs/", "/apidocs/swagger/"):
            resp = Client().get(url)
            self.assertEqual(resp.status_code, 200)
            content = resp.content.decode()
            self.assertEqual(offsite_assets(content), [])
            for host in SELF_HOSTED_ASSET_HOSTS:
                self.assertNotIn(host, content)
            self.assertIn(settings.STATIC_URL, content)

    def test_no_references_to_self_hosted_asset_hosts(self):
        """
        Catches the hosts however they are referenced -- tags, CSS @import,
        or URLs built in static JS.
        """
        for root in ("templates", "static"):
            for path in (APP_DIR / root).rglob("*"):
                name = path.relative_to(APP_DIR).as_posix()
                if not path.is_file() or name in SELF_HOSTED_SCAN_EXCLUDE:
                    continue
                content = path.read_bytes()
                for host in SELF_HOSTED_ASSET_HOSTS:
                    self.assertNotIn(host.encode(), content, name)

    def test_template_asset_tags_allowed_by_csp(self):
        """
        Off-site script src, stylesheet and preload link tags written in the
        project templates point at hosts the matching CSP directive allows.
        Loads injected from JS or CSS are not covered.
        """
        directives = settings.CONTENT_SECURITY_POLICY["DIRECTIVES"]
        for path in (APP_DIR / "templates").rglob("*.html"):
            name = path.relative_to(APP_DIR).as_posix()
            for directive, host in offsite_assets(path.read_text()):
                allowed = directives.get(directive, directives["default-src"])
                self.assertIn(host, allowed, f"{name}: {directive} {host}")

    def test_asset_tag_parser(self):
        html = """
        <script src = "https://a.example/x.js"></script>
        <script src=https://b.example/x.js></script>
        <link rel="alternate stylesheet" href="https://c.example/x.css">
        <link rel=preload as=font href="https://d.example/x.woff2">
        <link rel="canonical" href="https://e.example/">
        <img data-src="https://f.example/x.png">
        <!-- <script src="https://g.example/x.js"></script> -->
        <script src="{{ STATIC_URL }}local.js"></script>
        """
        self.assertEqual(
            offsite_assets(html),
            [
                ("script-src", "a.example"),
                ("script-src", "b.example"),
                ("style-src", "c.example"),
                ("font-src", "d.example"),
            ],
        )
