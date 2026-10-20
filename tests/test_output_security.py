import json
from html.parser import HTMLParser
from types import SimpleNamespace

import pytest
from django.contrib.admin.sites import AdminSite
from django.template.loader import get_template, render_to_string
from django.utils.html import escape

from peeringdb_server import admin, models
from peeringdb_server.admin_commandline_tools import CommandLineToolWrapper

pytestmark = pytest.mark.django_db

PAYLOAD = '</script><img src=x onerror="alert(478)"> O\'Reilly &    end'


class ScriptParser(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.scripts = []
        self.current = None
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.current = {"attrs": dict(attrs), "text": ""}
            self.scripts.append(self.current)

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"] += data

    def handle_endtag(self, tag):
        if tag == "script":
            self.current = None


@pytest.mark.django_db
def test_admin_escapes_stored_import_text_and_names():
    org = models.Organization.objects.create(name="Output security", status="ok")
    ix = models.InternetExchange.objects.create(name=PAYLOAD, org=org, status="ok")
    ixlan = ix.ixlan
    ixlan.name = PAYLOAD
    ixlan.save(update_fields=["name"])
    models.IXLanIXFMemberImportAttempt.objects.create(ixlan=ixlan, info=PAYLOAD)
    log = models.IXLanIXFMemberImportLog.objects.create(ixlan=ixlan)
    site = AdminSite()
    inline = admin.IXLanInline(models.InternetExchange, site)
    log_admin = admin.IXLanIXFMemberImportLogAdmin(models.IXLanIXFMemberImportLog, site)

    rendered = [
        inline.ixf_import_attempt_info(ix.ixlan),
        log_admin.ix(log),
        log_admin.ixlan_name(log),
    ]
    for output in rendered:
        assert PAYLOAD not in output
        assert escape(PAYLOAD) in output
    assert rendered[0] == f"<pre>{escape(PAYLOAD)}</pre>"
    assert f"/cp/peeringdb_server/internetexchange/{ix.id}/change/" in rendered[1]
    assert f"/cp/peeringdb_server/ixlan/{ix.ixlan.id}/change/" in rendered[2]


@pytest.mark.django_db
def test_admin_escapes_stored_username():
    user = models.User.objects.create_user(username=PAYLOAD)
    output = admin.UserPermissionAdmin(models.User, AdminSite()).user(user)
    assert escape(PAYLOAD) in output
    assert PAYLOAD not in output
    assert f"/cp/peeringdb_server/user/{user.pk}/change/" in output


def test_admin_escapes_requirement_label_and_action():
    class Requirement:
        id = 478
        action = PAYLOAD

        def __str__(self):
            return PAYLOAD

    model_admin = admin.IXFMemberDataAdmin(models.IXFMemberData, AdminSite())
    obj = SimpleNamespace(requirements=[Requirement(), Requirement()])
    output = model_admin.requirement_detail(obj)
    assert output.count(escape(PAYLOAD)) == 4
    assert PAYLOAD not in output
    assert output.count("<br>") == 1
    assert (
        output.count('<a href="/cp/peeringdb_server/ixfmemberdata/478/change/">') == 2
    )
    assert (
        model_admin.requirement_detail(SimpleNamespace(requirements=[]))
        == "No requirements"
    )


def test_command_log_preserves_styles_and_escapes_each_line():
    tool = CommandLineToolWrapper(SimpleNamespace(cleaned_data={}))
    assert tool.pretty_result == ""
    tool.result = f"[error] {PAYLOAD}\n[warning] {PAYLOAD}\n{PAYLOAD}"
    output = tool.pretty_result
    assert PAYLOAD not in output
    assert output.count(escape(PAYLOAD)) == 3
    for level in ("error", "warning", "info"):
        assert f'<div class="{level}">' in output


@pytest.mark.parametrize("name", ["preview_command", "run_command"])
def test_command_templates_do_not_trust_plain_output(name):
    output = render_to_string(
        f"admin/peeringdb_server/commandlinetool/{name}.html",
        {
            "tool": SimpleNamespace(pretty_result=PAYLOAD),
            "opts": models.CommandLineTool._meta,
            "action": "run",
        },
    )
    assert escape(PAYLOAD) in output
    assert PAYLOAD not in output


@pytest.mark.parametrize(
    "template,keys",
    [
        ("site/view_facility_side.html", ["networks"]),
        ("site/view_facility_bottom.html", ["exchanges", "carriers"]),
        ("site/view_exchange_side.html", ["networks"]),
        ("site_next/view_facility_side.html", ["networks", "exchanges", "carriers"]),
        ("site_next/view_exchange_side.html", ["networks"]),
    ],
)
def test_add_entity_lists_are_inert_json_and_round_trip(template, keys):
    entries = [{"id": 478, "name": PAYLOAD}]
    context = {f"user_{key}": entries for key in keys}
    context["instance"] = SimpleNamespace(id=478)
    output = render_to_string(template, context)
    scripts = ScriptParser(output).scripts
    for key in keys:
        matches = [s for s in scripts if s["attrs"].get("id") == f"user-{key}-data"]
        assert len(matches) == 1
        assert matches[0]["attrs"]["type"] == "application/json"
        assert "<" not in matches[0]["text"]
        assert json.loads(matches[0]["text"]) == entries
    assert PAYLOAD not in output
    for script in scripts:
        if script["attrs"].get("type") != "application/json":
            assert "alert(478)" not in script["text"]


@pytest.mark.parametrize("family", ["site", "site_next"])
def test_generic_safe_row_still_escapes_plain_text(family):
    empty = get_template("site/stats.html")
    output = render_to_string(
        f"{family}/view.html",
        {
            "instance": SimpleNamespace(id=478),
            "ref_tag": "org",
            "data": {"fields": [{"name": "unsafe", "type": "safe", "value": PAYLOAD}]},
            "bottom_template_name": empty,
            "side_template_name": empty,
            "tools_template_name": empty,
            "asset_template_name": empty,
        },
    )
    assert escape(PAYLOAD) in output
    assert PAYLOAD not in output
