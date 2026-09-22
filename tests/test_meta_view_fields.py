"""
Net view field definitions for the registered `net` metadata keys (#1751).

The net view is built from field definitions in views.py rather than a
template, so the metadata keys are rendered from the serialized document and
edited through the flat write-only serializer fields.
"""

import datetime
import re

from django.conf import settings

from peeringdb_server import meta_registry
from peeringdb_server.models import (
    InternetExchange,
    IXLanPrefix,
    Network,
    NetworkContact,
    NetworkIXLan,
    Organization,
)

from .util import ClientCase


class TestNetworkMetaViewFields(ClientCase):
    @classmethod
    def setUpTestData(cls):
        # ClientCase sets up the guest group and the public-read grainy
        # permissions the view applicator needs -- without it the whole
        # serialized network is denied and never reaches the field defs
        super().setUpTestData()

        cls.org = Organization.objects.create(name="View Meta Org", status="ok")
        cls.net = Network.objects.create(
            name="View Meta Net",
            asn=64512,
            org=cls.org,
            status="ok",
            website="https://viewmeta.example.com",
            policy_general="Open",
        )
        NetworkContact.objects.create(
            network=cls.net,
            role="Technical",
            visible="Public",
            email="viewmeta@localhost",
            status="ok",
        )

    def find_field(self, response, name):
        for field in response.context["data"]["fields"]:
            if field.get("name") == name:
                return field
        return None

    def test_meta_keys_are_rendered_on_the_net_view(self):
        self.net.meta = {"rtbh_community": "65000:666", "preferred_ip_mtu": 9000}
        self.net.save()

        response = self.client.get(f"/net/{self.net.id}")
        assert response.status_code == 200

        rtbh = self.find_field(response, "rtbh_community")
        mtu = self.find_field(response, "preferred_ip_mtu")
        assert rtbh is not None
        assert rtbh["value"] == "65000:666"
        assert mtu is not None
        assert mtu["value"] == 9000

    def test_unset_meta_keys_render_without_error(self):
        # an empty document must not break the view or render a raw {}
        Network.objects.filter(id=self.net.id).update(meta={})

        response = self.client.get(f"/net/{self.net.id}")
        assert response.status_code == 200

        rtbh = self.find_field(response, "rtbh_community")
        assert rtbh is not None
        assert rtbh["value"] != {}

    def test_meta_keys_are_not_under_peering_policy_information(self):
        """
        The net view has no group_end marker, so a `sub` header owns every
        field after it -- and "Peering Policy Information" is the last one,
        which makes it a catch-all tail. Neither key is a condition of
        peering, so both belong in the technical block above it.
        """
        fields = self.client.get(f"/net/{self.net.id}").context["data"]["fields"]
        names = [f.get("name") or f.get("label") for f in fields]
        policy_header = next(
            i
            for i, f in enumerate(fields)
            if f.get("type") == "sub" and "Peering Policy" in str(f.get("label"))
        )
        for name in ("rtbh_community", "preferred_ip_mtu"):
            assert names.index(name) < policy_header, name

    def test_unset_meta_keys_still_reach_the_page(self):
        """
        A `DoNotRender` value drops the whole row in view.html, edit mode
        included -- so defaulting an absent key to `dismiss` would leave the
        field visible only once it already had a value, and unsettable from
        the UI. Asserted against the HTML, not the context: the field dict is
        present either way.
        """
        Network.objects.filter(id=self.net.id).update(meta={})
        content = self.client.get(f"/net/{self.net.id}").content.decode()

        for name, label in (
            ("rtbh_community", "RTBH Community"),
            ("preferred_ip_mtu", "Preferred IP MTU"),
        ):
            assert f'data-edit-name="{name}"' in content, name
            assert label in content, label


class TestNetixlanMetaWidgets(ClientCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.org = Organization.objects.create(name="Widget Org", status="ok")
        cls.net = Network.objects.create(
            name="Widget Net",
            asn=64513,
            org=cls.org,
            status="ok",
            website="https://widget.example.com",
            policy_general="Open",
        )
        NetworkContact.objects.create(
            network=cls.net,
            role="Technical",
            visible="Public",
            email="widget@localhost",
            status="ok",
        )
        cls.ix = InternetExchange.objects.create(
            name="Widget IX", org=cls.org, status="ok"
        )
        IXLanPrefix.objects.create(
            ixlan=cls.ix.ixlan,
            protocol="IPv4",
            prefix="195.69.152.0/22",
            status="ok",
        )
        cls.netixlan = NetworkIXLan.objects.create(
            network=cls.net,
            ixlan=cls.ix.ixlan,
            asn=cls.net.asn,
            speed=1000,
            status="ok",
            ipaddr4="195.69.152.10",
        )

    def set_plan(self, status="deleted"):
        date = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
        NetworkIXLan.objects.filter(id=self.netixlan.id).update(
            meta={"planned_status_change": {"status": status, "date": date}}
        )
        return date

    def test_operational_widget_writes_status_not_the_boolean(self):
        # the deprecation window can only close once the dashboard stops
        # sending `operational`
        response = self.client.get(f"/net/{self.net.id}")
        assert response.status_code == 200
        content = response.content.decode()
        assert 'data-edit-name="status"' in content
        assert 'data-edit-type="netixlan_status"' in content
        assert 'data-edit-name="operational"' not in content

    def test_metadata_widgets_are_rendered_on_the_netixlan_row(self):
        response = self.client.get(f"/net/{self.net.id}")
        content = response.content.decode()
        assert 'data-edit-name="rfc8950"' in content
        assert 'data-edit-name="planned_status_change_status"' in content
        assert 'data-edit-name="planned_status_change_date"' in content
        assert 'data-edit-data="enum/meta_planned_status_change"' in content

    def test_planned_removal_badge_on_the_network_view(self):
        date = self.set_plan("deleted")
        response = self.client.get(f"/net/{self.net.id}")
        content = response.content.decode()
        assert "planned removal" in content
        assert date in content

    def test_planned_activation_badge_on_the_exchange_view(self):
        date = self.set_plan("ok")
        response = self.client.get(f"/ix/{self.ix.id}")
        assert response.status_code == 200
        content = response.content.decode()
        assert "planned activation" in content
        assert date in content

    def test_no_badge_when_no_plan_is_set(self):
        response = self.client.get(f"/net/{self.net.id}")
        content = response.content.decode()
        assert "planned removal" not in content
        assert "planned activation" not in content

    def test_plan_status_enum_is_served_from_the_registry(self):
        # the vocabulary must not require a django-peeringdb release
        response = self.client.get("/data/enum/meta_planned_status_change")
        assert response.status_code == 200
        rows = response.json()["enum/meta_planned_status_change"]
        # every registry value is offered (order is a UI choice: removal first)
        assert set(row["id"] for row in rows) == {""} | set(
            meta_registry.PLANNED_STATUS_CHANGE_STATUSES
        )
        # labels are user-facing wording, not the raw status values
        assert [row["name"] for row in rows] == [
            "None",
            "Planned Removal",
            "Planned Activation",
        ]


class TestNetixlanMetaLayout(ClientCase):
    """
    The metadata editors must not sit inside `.netixlan-extra`.

    That block is `white-space: nowrap` inside a col-md-3, and the five data
    columns of the netixlan grid already sum to 12, so extra controls there
    push the row out of the table. They belong in their own full-width
    sub-row, next to the existing `ip-addr` one.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.org = Organization.objects.create(name="Layout Org", status="ok")
        cls.net = Network.objects.create(
            name="Layout Net",
            asn=64514,
            org=cls.org,
            status="ok",
            website="https://layout.example.com",
            policy_general="Open",
        )
        NetworkContact.objects.create(
            network=cls.net,
            role="Technical",
            visible="Public",
            email="layout@localhost",
            status="ok",
        )
        cls.ix = InternetExchange.objects.create(
            name="Layout IX", org=cls.org, status="ok"
        )
        IXLanPrefix.objects.create(
            ixlan=cls.ix.ixlan,
            protocol="IPv4",
            prefix="195.69.156.0/22",
            status="ok",
        )
        NetworkIXLan.objects.create(
            network=cls.net,
            ixlan=cls.ix.ixlan,
            asn=cls.net.asn,
            speed=1000,
            status="ok",
            ipaddr4="195.69.156.10",
        )

    def content(self):
        response = self.client.get(f"/net/{self.net.id}")
        assert response.status_code == 200
        return response.content.decode()

    def test_netixlan_extra_holds_only_the_status_widget(self):
        content = self.content()
        start = content.index("netixlan-extra")
        # the block ends at the enclosing column's close; take a generous
        # window and assert the metadata controls are not inside it
        window = content[start : start + 900]
        assert 'data-edit-name="status"' in window
        assert 'data-edit-name="rfc8950"' not in window
        assert 'data-edit-name="planned_status_change_status"' not in window

    def test_metadata_fields_live_in_their_own_sub_row(self):
        content = self.content()
        assert 'class="netixlan-meta row' in content
        # and after the existing ip-addr sub-row, not inside the data grid
        assert content.index('class="ip-addr row') < content.index(
            'class="netixlan-meta row'
        )
        block = self.meta_block(content)
        assert 'data-edit-name="rfc8950"' in block
        assert 'data-edit-name="planned_status_change_date"' in block

    def test_sub_row_is_present_in_view_mode(self):
        """
        These are columns, not an editing affordance: a visitor who cannot
        edit still sees the values, the same way is_rs_peer and bfd_support
        work on this table. Nothing in the sub-row may be edit-toggled --
        20c-edit swaps a cell's content on toggle, so the view value and the
        control are the same element.
        """
        block = self.meta_block(self.content())
        assert "data-edit-toggled" not in block

    def test_metadata_labels_live_in_the_column_header(self):
        """
        The netixlan list is a table: its column headings carry the keys and
        the rows carry only values. The headings also drive sorting and the
        CSV/JSON export, both of which read `data-sort-target` off the header
        (`extractFromTableForExport` in peeringdb.js) -- so a heading without
        one is not a column, just text.
        """
        content = self.content()
        # the page carries several listings; anchor on this one's
        listing = content[content.index('id="api-listing-netixlan"') :]
        header = listing[listing.index('class="row header"') :]
        header = header[: header.index('class="scrollable"')]

        # #1742: the plan's status and date are one column to the user -- a
        # single "Planned change" heading over a `.planned-change` cell that
        # holds both editors; there is no separate "Change date" column
        expected = {
            "RFC8950": ".rfc8950",
            "Planned change": ".planned-change",
        }
        for label, target in expected.items():
            i = header.index(f">{label}<")
            line = header[header.rindex("<div", 0, i) : i]
            assert f'data-sort-target="{target}"' in line, label
            assert "data-edit-toggled" not in line, label

        # and the cell each one points at exists in the sub-row
        block = self.meta_block(content)
        for target in expected.values():
            assert f'class="{target.lstrip(".")}"' in block, target

        assert "<label" not in block
        assert ">Change date<" not in header
        # the merged cell wraps both editors
        cell = block[block.index('class="planned-change"') :]
        assert 'data-edit-name="planned_status_change_status"' in cell
        assert 'data-edit-name="planned_status_change_date"' in cell

    def test_plan_date_uses_the_native_date_input_with_bounds(self):
        """
        `type="date"` always yields YYYY-MM-DD, which is what the registry
        validates -- the free-text field it replaced could not. min/max are a
        hint only: the page is CDN-cached, so a boundary can go stale and the
        server stays the authority.
        """
        content = self.content()
        block = self.meta_block(content)
        i = block.index('data-edit-name="planned_status_change_date"')
        cell = block[block.rindex("<div", 0, i) : block.index(">", i) + 1]

        assert 'data-edit-type="date"' in cell
        today = datetime.date.today()
        assert f'data-edit-min="{today + datetime.timedelta(days=1)}"' in cell
        assert 'data-edit-max="' in cell
        # the window is the registry's, not a number repeated here
        window = settings.META_PLANNED_STATUS_CHANGE_WINDOW_DAYS
        assert f'data-edit-max="{today + datetime.timedelta(days=window)}"' in cell

    def test_metadata_cells_align_with_the_ip_addr_sub_row(self):
        """
        Alignment under the header is what makes the headings readable as
        this sub-row's labels, and the `ip-addr` row above it already spans
        the same header columns -- so every cell boundary of this sub-row
        must fall on a boundary of the `ip-addr` row. The sub-row may be
        coarser (#1742: the planned-change cell spans two header columns),
        never offset.
        """
        content = self.content()
        ip_addr = content[content.index('class="ip-addr row') :]
        ip_addr = ip_addr[: ip_addr.index('class="netixlan-meta row')]

        ip_bounds = self.column_boundaries(ip_addr)
        meta_bounds = self.column_boundaries(self.meta_block(content))
        assert meta_bounds and meta_bounds[-1] == ip_bounds[-1] == 12
        assert set(meta_bounds) <= set(ip_bounds), (meta_bounds, ip_bounds)

    def test_row_template_carries_the_same_sub_row(self):
        """
        Newly added rows are cloned from `#netixlan-item`; without the sub-row
        they would render three columns short until the page is reloaded.
        """
        content = self.content()
        template = content[content.index('id="netixlan-item"') :]
        template = template[: template.index('id="netfac-item"')]
        for name in (
            "rfc8950",
            "planned_status_change_status",
            "planned_status_change_date",
        ):
            assert f'data-edit-name="{name}"' in template, name

    @staticmethod
    def meta_block(content):
        start = content.index('class="netixlan-meta row')
        return content[start : content.index("</div>\n      </div>", start)]

    @staticmethod
    def column_widths(block):
        """The `col-sm-*` width of each grid cell, in document order."""
        return re.findall(r'class="col-\d+ (col-sm-\d+)', block)

    @classmethod
    def column_boundaries(cls, block):
        """Cumulative right edges (in grid units) of each cell, in order."""
        edges, total = [], 0
        for width in cls.column_widths(block):
            total += int(width.rsplit("-", 1)[1])
            edges.append(total)
        return edges


class TestNetixlanPublicSignals(ClientCase):
    """
    Metadata that is only visible while editing is pointless -- the whole
    point of publishing an RTBH community or a departure date is that peers
    can see it.

    The two lists render it differently because they already render their
    other per-connection booleans differently: the exchange side shows
    is_rs_peer and bfd_support as when-true badges, so rfc8950 is a chip
    there; the network side shows them as on/off checkmark columns, so
    rfc8950 is a column there -- and unlike those two it is tri-state, so
    the column has to distinguish false from unset in view mode as well as
    in the editor.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.org = Organization.objects.create(name="Signal Org", status="ok")
        cls.net = Network.objects.create(
            name="Signal Net",
            asn=64515,
            org=cls.org,
            status="ok",
            website="https://signal.example.com",
            policy_general="Open",
        )
        NetworkContact.objects.create(
            network=cls.net,
            role="Technical",
            visible="Public",
            email="signal@localhost",
            status="ok",
        )
        cls.ix = InternetExchange.objects.create(
            name="Signal IX", org=cls.org, status="ok"
        )
        IXLanPrefix.objects.create(
            ixlan=cls.ix.ixlan,
            protocol="IPv4",
            prefix="195.69.160.0/22",
            status="ok",
        )
        cls.netixlan = NetworkIXLan.objects.create(
            network=cls.net,
            ixlan=cls.ix.ixlan,
            asn=cls.net.asn,
            speed=1000,
            status="ok",
            ipaddr4="195.69.160.10",
        )

    def set_meta(self, **meta):
        NetworkIXLan.objects.filter(id=self.netixlan.id).update(meta=meta)

    def pages(self):
        return (f"/net/{self.net.id}", f"/ix/{self.ix.id}")

    def net_page(self):
        return self.client.get(f"/net/{self.net.id}").content.decode()

    def ix_page(self):
        return self.client.get(f"/ix/{self.ix.id}").content.decode()

    def test_rfc8950_chip_is_public_on_the_exchange_view(self):
        self.set_meta(rfc8950=True)
        content = self.ix_page()
        i = content.index("netixlan-capability")
        widget = content[content.rindex("<span", 0, i) : content.index(">", i) + 1]
        # public: rendered in view mode, not only while editing
        assert 'data-edit-toggled="view"' in widget
        assert "RFC8950" in content[i : i + 400]

    def test_no_chip_when_rfc8950_is_absent_or_false_on_the_exchange_view(self):
        for meta in ({}, {"rfc8950": False}):
            self.set_meta(**meta)
            assert "netixlan-capability" not in self.ix_page(), meta

    def test_rfc8950_column_distinguishes_false_from_unset(self):
        """
        A column says something a when-true chip cannot: that the network was
        asked and the answer is no. is_rs_peer and bfd_support on this same
        table read the same way -- but those two are plain booleans, and this
        one is tri-state, so "never declared" has to render as neither
        checkmark rather than borrowing the false one.

        The editor is a select for the same reason: an unchecked checkbox
        cannot submit "unset", and since a row save submits every field in
        the row that would stamp an explicit false onto connections whose
        owner never made an RFC8950 statement.
        """
        for meta, expected, unexpected in (
            ({"rfc8950": True}, "checkmark.png", "checkmark-off.png"),
            ({"rfc8950": False}, "checkmark-off.png", None),
            ({}, None, "checkmark"),
        ):
            self.set_meta(**meta)
            content = self.net_page()
            i = content.index('class="rfc8950"')
            cell = content[i : content.index("</div>", i)]
            # tri-state editor rather than a checkbox
            assert 'data-edit-type="select"' in cell, (meta, cell)
            assert 'data-edit-data="enum/bool_choice_with_opt_out_str"' in cell, meta
            if expected:
                assert expected in cell, (meta, cell)
            if unexpected:
                assert unexpected not in cell, (meta, cell)

    def test_plan_badge_is_public_on_both_views(self):
        self.set_meta(planned_status_change={"status": "deleted", "date": "2099-01-01"})

        # exchange side: a badge beside the not-operational indicator
        content = self.ix_page()
        assert content.index('class="not-operational"') < content.index(
            "planned-status-change"
        )
        assert "2099-01-01" in content

        # network side: the view-mode content of its own two columns
        content = self.net_page()
        status_cell = content[content.index('class="planned-status"') :]
        assert "planned-status-change" in status_cell[:800]
        date_cell = content[content.index('class="planned-date"') :]
        assert "2099-01-01" in date_cell[:800]
