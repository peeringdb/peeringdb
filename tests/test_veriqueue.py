import json

import pytest
import reversion
from django.conf import settings
from django.contrib.auth.models import Group
from django.db import IntegrityError
from django.test import TestCase

import peeringdb_server.models as models


class VeriQueueTests(TestCase):
    """
    Test VerificationQueue creation and resolve
    """

    @classmethod
    def setUpTestData(cls):
        """
        Test that verification queue items are created for all entities
        for which it is enabled
        """

        cls.guest_group = Group.objects.create(name="guest", id=settings.GUEST_GROUP_ID)
        cls.user_group = Group.objects.create(name="user", id=settings.USER_GROUP_ID)

        settings.USER_GROUP_ID = cls.user_group.id
        settings.GUEST_GROUP_ID = cls.guest_group.id

        cls.inst = {}
        org = models.Organization.objects.create(name="Test", status="ok")
        for model in models.QUEUE_ENABLED:
            if model == models.Organization:
                continue
            if model == models.User:
                cls.inst["user"] = model.objects.create_user(
                    "test", "test@localhost", "test"
                )
                cls.inst["user"].set_unverified()
            else:
                kwargs = {
                    "org": org,
                    "name": "Test %s" % model.handleref.tag,
                    "status": "pending",
                }
                if model.handleref.tag == "net":
                    kwargs.update(asn=1)
                cls.inst[model.handleref.tag] = model.objects.create(**kwargs)

    def test_get_for_entity(self):
        """
        Test VerificationQueueItem.get_for_entity
        """

        # test verification queue items were created for all queue enabled
        # entities
        for k, v in list(self.inst.items()):
            vqi = models.VerificationQueueItem.get_for_entity(v)
            self.assertEqual(vqi.item, v)

    def test_deskpro_tickets(self):
        """
        Test that tickets were created for the facility and ix
        """
        user = self.inst["user"]
        qs = models.DeskProTicket.objects

        for tag in ["fac", "ix"]:
            inst = self.inst[tag]
            vqi = models.VerificationQueueItem.get_for_entity(inst)
            vqi.user = user
            vqi.save()
            self.assertEqual(
                qs.filter(
                    subject=f"[{settings.RELEASE_ENV}] {vqi.content_type.model_class()._meta.verbose_name} - {inst}"
                ).exists(),
                True,
            )

    def test_approve(self):
        """
        Test VerificationqueueItem.approve
        """
        ix = self.inst.get("ix")
        vqi = models.VerificationQueueItem.get_for_entity(ix)

        vqi.approve()

        # after approval ix should be status 'ok'
        ix.refresh_from_db()
        self.assertEqual(ix.status, "ok")

        # check that the status in the archive is correct (#558)

        version = (
            reversion.models.Version.objects.get_for_object(ix)
            .order_by("-revision_id")
            .first()
        )
        self.assertEqual(
            json.loads(version.serialized_data)[0]["fields"]["status"], "ok"
        )

        # after approval vqi should no longer exist
        with pytest.raises(models.VerificationQueueItem.DoesNotExist):
            vqi.refresh_from_db()

    def test_user_approve(self):
        """
        Test VerificationqueueItem.approve when approving users
        """

        # test that approving a user also moves them in the correct usergroup

        user = self.inst.get("user")
        vqi = models.VerificationQueueItem.get_for_entity(user)

        vqi.approve()

        # after approval user should be status 'ok'

        user.refresh_from_db()
        self.assertEqual(user.status, "ok")

        # after approval user should be in 'users' group
        self.assertEqual(user.groups.filter(name="user").exists(), True)
        self.assertEqual(user.groups.filter(name="guest").exists(), False)

    def test_deny(self):
        """
        Test VerificationqueueItem.deny
        """

        fac = self.inst.get("fac")
        vqi = models.VerificationQueueItem.get_for_entity(fac)

        vqi.deny()

        # after denial fac should no longer exist
        with pytest.raises(models.Facility.DoesNotExist):
            fac.refresh_from_db()

        # after denial vqi should no longer exist
        with pytest.raises(models.VerificationQueueItem.DoesNotExist):
            vqi.refresh_from_db()

    def test_unique(self):
        """
        Test that only one verification queue item can exist for an entity
        """

        fac = self.inst.get("fac")
        models.VerificationQueueItem.get_for_entity(fac)

        with pytest.raises(IntegrityError):
            models.VerificationQueueItem.objects.create(
                content_type=models.ContentType.objects.get_for_model(type(fac)),
                object_id=fac.id,
            )

    def test_pending_deleted_flags_unpublished_ticket_for_close(self):
        """
        When a pending object is deleted and its DeskPro ticket has not yet
        been published (deskpro_id is None), the signal only flags it
        (close_requested=True). The row is not deleted here — pdb_deskpro_publish
        is the single writer of DeskPro state and drops it later (#1948).
        """
        org = models.Organization.objects.create(name="CloseTest Org", status="ok")
        ix = models.InternetExchange.objects.create(
            org=org, name="CloseTest IX", status="pending"
        )

        vqi = models.VerificationQueueItem.get_for_entity(ix)

        ticket = models.DeskProTicket.objects.create(
            subject="test unpublished", body="", user=None, email="test@example.com"
        )
        vqi.deskpro_ticket = ticket
        vqi.save()

        ix.status = "deleted"
        ix.save()

        ticket.refresh_from_db()
        assert ticket.close_requested is True
        assert ticket.closed is None
        assert ticket.deskpro_id is None
        with pytest.raises(models.VerificationQueueItem.DoesNotExist):
            vqi.refresh_from_db()

    def test_pending_deleted_flags_published_ticket_for_close(self):
        """
        When a pending object is deleted and its DeskPro ticket has already
        been published (deskpro_id is set), the ticket is flagged for async
        auto-close (close_requested=True). The actual API call is performed
        by pdb_deskpro_publish (#1948).
        """
        org = models.Organization.objects.create(name="CloseTest2 Org", status="ok")
        fac = models.Facility.objects.create(
            org=org, name="CloseTest2 Fac", status="pending"
        )

        vqi = models.VerificationQueueItem.get_for_entity(fac)

        ticket = models.DeskProTicket.objects.create(
            subject="test published",
            body="",
            user=None,
            email="test@example.com",
            deskpro_id=42,
            deskpro_ref="REF-42",
        )
        vqi.deskpro_ticket = ticket
        vqi.save()

        fac.status = "deleted"
        fac.save()

        ticket.refresh_from_db()
        assert ticket.close_requested is True
        assert ticket.closed is None
        with pytest.raises(models.VerificationQueueItem.DoesNotExist):
            vqi.refresh_from_db()

    def test_pending_approved_does_not_flag_ticket_for_close(self):
        """
        When a pending object is approved (status -> ok), the linked DeskPro
        ticket should NOT be flagged for close — AC may still need to respond
        (#1948).
        """
        org = models.Organization.objects.create(name="CloseTest3 Org", status="ok")
        carrier = models.Carrier.objects.create(
            org=org, name="CloseTest3 Carrier", status="pending"
        )

        vqi = models.VerificationQueueItem.get_for_entity(carrier)

        ticket = models.DeskProTicket.objects.create(
            subject="test approved",
            body="",
            user=None,
            email="test@example.com",
            deskpro_id=99,
            deskpro_ref="REF-99",
        )
        vqi.deskpro_ticket = ticket
        vqi.save()

        carrier.status = "ok"
        carrier.save()

        ticket.refresh_from_db()
        assert ticket.close_requested is False

    def test_pending_deleted_no_ticket_does_not_crash(self):
        """
        When a pending object is deleted but has no linked DeskPro ticket,
        the deletion should proceed without error (#1948).
        """
        org = models.Organization.objects.create(name="CloseTest4 Org", status="ok")
        ix = models.InternetExchange.objects.create(
            org=org, name="CloseTest4 IX", status="pending"
        )

        vqi = models.VerificationQueueItem.get_for_entity(ix)
        assert vqi.deskpro_ticket is None

        ix.status = "deleted"
        ix.save()

        with pytest.raises(models.VerificationQueueItem.DoesNotExist):
            vqi.refresh_from_db()

    def test_pending_hard_deleted_flags_ticket_for_close(self):
        """
        Hard-deleting a pending object (the pre_delete path used by AC deny
        and admin purges, not just the user soft-delete path) also flags the
        linked DeskPro ticket for auto-close (#1948). Locks in the behavior
        documented in the SCOPE NOTE in signals.verification_queue_delete.
        """
        org = models.Organization.objects.create(name="CloseTest5 Org", status="ok")
        fac = models.Facility.objects.create(
            org=org, name="CloseTest5 Fac", status="pending"
        )

        vqi = models.VerificationQueueItem.get_for_entity(fac)

        ticket = models.DeskProTicket.objects.create(
            subject="test hard delete",
            body="",
            user=None,
            email="test@example.com",
            deskpro_id=77,
            deskpro_ref="REF-77",
        )
        vqi.deskpro_ticket = ticket
        vqi.save()

        # hard delete -> fires pre_delete -> verification_queue_delete
        fac.delete(hard=True)

        ticket.refresh_from_db()
        assert ticket.close_requested is True
        with pytest.raises(models.VerificationQueueItem.DoesNotExist):
            vqi.refresh_from_db()
