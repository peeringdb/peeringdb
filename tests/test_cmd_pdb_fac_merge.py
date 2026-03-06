import io

import pytest
import reversion
from django.core.management import call_command

from peeringdb_server.models import (
    Facility,
    InternetExchange,
    InternetExchangeFacility,
    Network,
    NetworkFacility,
    Organization,
)

from .util import ClientCase


class TestFacMerge(ClientCase):
    """Tests for the pdb_fac_merge management command."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        with reversion.create_revision():
            cls.org = Organization.objects.create(name="Test Org", status="ok")
            cls.org2 = Organization.objects.create(name="Test Org 2", status="ok")

            cls.net1 = Network.objects.create(
                name="Network 1",
                org=cls.org,
                asn=63311,
                status="ok",
                info_prefixes4=42,
                info_prefixes6=42,
                website="http://example1.com/",
                policy_general="Open",
                policy_url="https://example1.com/policy/",
            )
            cls.net2 = Network.objects.create(
                name="Network 2",
                org=cls.org,
                asn=63312,
                status="ok",
                info_prefixes4=42,
                info_prefixes6=42,
                website="http://example2.com/",
                policy_general="Open",
                policy_url="https://example2.com/policy/",
            )

    def _create_facilities(self, **kwargs):
        """Create source and target facilities for merging."""
        with reversion.create_revision():
            target = Facility.objects.create(
                name="Target Facility",
                org=self.org,
                country="US",
                city="New York",
                status="ok",
            )
            source = Facility.objects.create(
                name="Source Facility",
                org=self.org,
                country="US",
                city="Chicago",
                status="ok",
            )
        return target, source

    def test_merge_netfac_moved(self):
        """Test that netfacs are moved from source to target facility."""
        target, source = self._create_facilities()

        with reversion.create_revision():
            netfac = NetworkFacility.objects.create(
                network=self.net1,
                facility=source,
                status="ok",
            )

        out = io.StringIO()
        call_command(
            "pdb_fac_merge",
            target=str(target.id),
            ids=str(source.id),
            commit=True,
            stdout=out,
        )

        netfac.refresh_from_db()
        assert netfac.facility_id == target.id
        assert netfac.status == "ok"

    def test_merge_netfac_skip_existing(self):
        """Test that existing undeleted netfacs at target are skipped."""
        target, source = self._create_facilities()

        with reversion.create_revision():
            NetworkFacility.objects.create(
                network=self.net1,
                facility=target,
                status="ok",
            )
            netfac_source = NetworkFacility.objects.create(
                network=self.net1,
                facility=source,
                status="ok",
            )

        out = io.StringIO()
        call_command(
            "pdb_fac_merge",
            target=str(target.id),
            ids=str(source.id),
            commit=True,
            stdout=out,
        )

        # Source netfac should NOT have been moved (connection already exists at target)
        netfac_source.refresh_from_db()
        assert netfac_source.facility_id == source.id

        output = out.getvalue()
        assert "connection already exists at target, skipping" in output

    def test_merge_netfac_undelete(self):
        """
        Test that a deleted netfac at target is undeleted and updated
        during merge.

        This is the scenario fixed by b1d25aeb - the code previously
        tried to set local_asn which is now a read-only property.
        """
        target, source = self._create_facilities()

        with reversion.create_revision():
            # Create a deleted netfac at the target facility
            netfac_target = NetworkFacility.objects.create(
                network=self.net1,
                facility=target,
                status="ok",
            )
            netfac_target.status = "deleted"
            netfac_target.save()

            # Create an active netfac at the source facility
            netfac_source = NetworkFacility.objects.create(
                network=self.net1,
                facility=source,
                status="ok",
            )

        out = io.StringIO()
        call_command(
            "pdb_fac_merge",
            target=str(target.id),
            ids=str(source.id),
            commit=True,
            stdout=out,
        )

        netfac_target.refresh_from_db()
        assert netfac_target.status == "ok"
        assert netfac_target.facility_id == target.id

        output = out.getvalue()
        assert "undeleting and updating" in output

    def test_merge_ixfac_moved(self):
        """Test that ixfacs are moved from source to target facility."""
        target, source = self._create_facilities()

        with reversion.create_revision():
            ix = InternetExchange.objects.create(
                name="Test IX",
                org=self.org,
                status="ok",
                country="US",
                city="New York",
                media="Ethernet",
            )
            ixfac = InternetExchangeFacility.objects.create(
                ix=ix,
                facility=source,
                status="ok",
            )

        out = io.StringIO()
        call_command(
            "pdb_fac_merge",
            target=str(target.id),
            ids=str(source.id),
            commit=True,
            stdout=out,
        )

        ixfac.refresh_from_db()
        assert ixfac.facility_id == target.id
        assert ixfac.status == "ok"

    def test_merge_ixfac_undelete(self):
        """Test that a deleted ixfac at target is undeleted during merge."""
        target, source = self._create_facilities()

        with reversion.create_revision():
            ix = InternetExchange.objects.create(
                name="Test IX",
                org=self.org,
                status="ok",
                country="US",
                city="New York",
                media="Ethernet",
            )
            ixfac_target = InternetExchangeFacility.objects.create(
                ix=ix,
                facility=target,
                status="ok",
            )
            ixfac_target.status = "deleted"
            ixfac_target.save()

            InternetExchangeFacility.objects.create(
                ix=ix,
                facility=source,
                status="ok",
            )

        out = io.StringIO()
        call_command(
            "pdb_fac_merge",
            target=str(target.id),
            ids=str(source.id),
            commit=True,
            stdout=out,
        )

        ixfac_target.refresh_from_db()
        assert ixfac_target.status == "ok"

        output = out.getvalue()
        assert "undeleting and updating" in output

    def test_merge_source_soft_deleted(self):
        """Test that the source facility is soft-deleted after merge."""
        target, source = self._create_facilities()

        out = io.StringIO()
        call_command(
            "pdb_fac_merge",
            target=str(target.id),
            ids=str(source.id),
            commit=True,
            stdout=out,
        )

        source.refresh_from_db()
        assert source.status == "deleted"

        target.refresh_from_db()
        assert target.status == "ok"

    def test_merge_pretend_mode(self):
        """Test that pretend mode (no --commit) makes no changes."""
        target, source = self._create_facilities()

        with reversion.create_revision():
            netfac = NetworkFacility.objects.create(
                network=self.net1,
                facility=source,
                status="ok",
            )

        out = io.StringIO()
        call_command(
            "pdb_fac_merge",
            target=str(target.id),
            ids=str(source.id),
            stdout=out,
        )

        # Nothing should have changed
        netfac.refresh_from_db()
        assert netfac.facility_id == source.id

        source.refresh_from_db()
        assert source.status == "ok"

        output = out.getvalue()
        assert "[pretend]" in output

    def test_merge_multiple_sources(self):
        """Test merging multiple source facilities into target."""
        with reversion.create_revision():
            target = Facility.objects.create(
                name="Target Facility",
                org=self.org,
                country="US",
                city="New York",
                status="ok",
            )
            source1 = Facility.objects.create(
                name="Source Facility 1",
                org=self.org,
                country="US",
                city="Chicago",
                status="ok",
            )
            source2 = Facility.objects.create(
                name="Source Facility 2",
                org=self.org,
                country="US",
                city="Dallas",
                status="ok",
            )
            NetworkFacility.objects.create(
                network=self.net1,
                facility=source1,
                status="ok",
            )
            NetworkFacility.objects.create(
                network=self.net2,
                facility=source2,
                status="ok",
            )

        out = io.StringIO()
        call_command(
            "pdb_fac_merge",
            target=str(target.id),
            ids=f"{source1.id},{source2.id}",
            commit=True,
            stdout=out,
        )

        source1.refresh_from_db()
        source2.refresh_from_db()
        assert source1.status == "deleted"
        assert source2.status == "deleted"

        # Both networks should now be at target
        assert NetworkFacility.objects.filter(facility=target, status="ok").count() == 2

    def test_merge_deleted_target_undeleted(self):
        """Test that a deleted target facility is undeleted during merge."""
        with reversion.create_revision():
            target = Facility.objects.create(
                name="Target Facility",
                org=self.org,
                country="US",
                city="New York",
                status="deleted",
            )
            source = Facility.objects.create(
                name="Source Facility",
                org=self.org,
                country="US",
                city="Chicago",
                status="ok",
            )

        out = io.StringIO()
        call_command(
            "pdb_fac_merge",
            target=str(target.id),
            ids=str(source.id),
            commit=True,
            stdout=out,
        )

        target.refresh_from_db()
        assert target.status == "ok"
