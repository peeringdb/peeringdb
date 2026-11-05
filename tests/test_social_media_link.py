import pytest
from django.template import Context, Template
from django.test import Client, override_settings

from peeringdb_server.models import Organization

pytestmark = pytest.mark.django_db

PAYLOAD = '"><b>INJECTED</b>'


def render_link(identifier, service):
    template = Template("{% load util %}{{ identifier|social_media_link:service }}")
    return template.render(Context({"identifier": identifier, "service": service}))


@pytest.mark.parametrize(
    "identifier,service,expected",
    [
        (
            "peeringdb",
            "x",
            '<a href="https://x.com/peeringdb" target="_blank">peeringdb</a>',
        ),
        (
            "https://www.example.com",
            "website",
            '<a href="https://www.example.com" target="_blank">https://www.example.com</a>',
        ),
        ("peering_cn", "wechat", "peering_cn"),
    ],
)
def test_social_media_link(identifier, service, expected):
    assert render_link(identifier, service) == expected


@pytest.mark.parametrize(
    "identifier,service",
    [
        # service with a url format
        (f"peeringdb{PAYLOAD}", "x"),
        # url services, rendered as is
        (f"https://x.com/{PAYLOAD}", "website"),
        (f"https://x.com/{PAYLOAD}", "mastodon"),
        (f"https://x.com/{PAYLOAD}", "qq"),
        # no url format, rendered as a link if it looks like one
        (f"https://x.com/{PAYLOAD}", "wechat"),
        # no url format, rendered as text
        (f"peering{PAYLOAD}", "wechat"),
    ],
)
def test_social_media_link_escapes_identifier(identifier, service):
    html = render_link(identifier, service)
    assert "<b>" not in html
    assert "&lt;b&gt;INJECTED&lt;/b&gt;" in html
    assert '"><' not in html


@pytest.mark.parametrize("ui_next", [False, True])
def test_entity_view_escapes_social_media(ui_next):
    org = Organization.objects.create(name="Test org", status="ok")
    # bypass validation, existing rows may predate it
    Organization.objects.filter(id=org.id).update(
        social_media=[
            {"service": "website", "identifier": f"https://x.com/{PAYLOAD}"},
            {"service": "wechat", "identifier": f"https://x.com/{PAYLOAD}"},
        ]
    )

    with override_settings(DEFAULT_UI_NEXT_ENABLED=ui_next):
        response = Client().get(f"/org/{org.id}")

    assert response.status_code == 200
    content = response.content.decode()
    assert "<b>INJECTED</b>" not in content
    assert "&lt;b&gt;INJECTED&lt;/b&gt;" in content
