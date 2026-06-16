#!/usr/bin/env python
"""
Process deskpro ticket queue.
"""

import datetime

from django.conf import settings
from django.core.management.base import BaseCommand
from django.template import loader

from peeringdb_server import deskpro, models
from peeringdb_server.deskpro import APIError
from peeringdb_server.mail import mail_admins_with_from


class Command(BaseCommand):
    help = "Process deskpro ticket queue"

    def log(self, msg):
        self.stdout.write(msg)

    def now(self):
        return datetime.datetime.now().replace(tzinfo=models.UTC())

    def handle(self, *args, **options):
        # look up APIClient on the module (not a bound import) so tests that
        # swap deskpro.APIClient take effect regardless of import order
        client = deskpro.APIClient(settings.DESKPRO_URL, settings.DESKPRO_KEY)
        self.log(f"DESKPRO: {settings.DESKPRO_URL}")

        self.publish_new_tickets(client)
        self.process_close_requests(client)

    def publish_new_tickets(self, client):
        # Per issue #858 we want to ignore the IX-F tickets.
        # Skip tickets already flagged for auto-close (#1948) - the related
        # object was deleted before publishing, so there is no point sending
        # them; process_close_requests will clean them up.
        ticket_qs = (
            models.DeskProTicket.objects.filter(
                published__isnull=True, close_requested=False
            )
            .exclude(subject__icontains="[IX-F]")
            .order_by("created")
        )

        if not ticket_qs.count():
            self.log("No tickets in queue")
            return

        for ticket in ticket_qs[:10]:
            self.log(f"Posting to Deskpro: #{ticket.id}")

            try:
                client.create_ticket(ticket)
                ticket.published = self.now()
                # Only write the fields we changed. The ticket instance was
                # loaded before the (slow) create_ticket call, so a concurrent
                # delete of the related object may have set close_requested=True
                # in the DB meanwhile (#1948). A full save() here would clobber
                # that flag back to False and orphan the ticket on DeskPro.
                ticket.save(update_fields=["published", "deskpro_id", "deskpro_ref"])

            except APIError as exc:
                error_code = exc.data.get("code")
                if error_code:
                    if error_code == "duplicate_ticket":
                        self.log(f"Duplicate ticket #{ticket.id} - ignoring.")
                        return

                self.log(
                    f"!!!! Could not create ticket #{ticket.id} - code {error_code} - error data has been attached to ticket body."
                )

                ticket.published = self.now()
                ticket.subject = f"[FAILED][{error_code}] {ticket.subject}"
                ticket.body = f"{ticket.body}\nAPI Delivery Error: {exc.data}"
                # see note above: scope the write so a concurrent close_requested
                # update is not overwritten. deskpro_id/deskpro_ref are included
                # because create_ticket may have already created the ticket on
                # DeskPro (first POST) before a later call failed — persisting
                # them keeps the partial-create result so the row isn't later
                # treated as unpublished and the real ticket isn't orphaned.
                # (Harmless when the first POST failed: both are still None.)
                ticket.save(
                    update_fields=[
                        "published",
                        "deskpro_id",
                        "deskpro_ref",
                        "subject",
                        "body",
                    ]
                )

                template = loader.get_template(
                    "email/notify-pdb-admin-deskpro-error.txt"
                )
                message = template.render({"ticket": ticket})

                if getattr(settings, "MAIL_DEBUG", False):
                    self.log(ticket.subject)
                    self.log(message)
                else:
                    mail_admins_with_from(
                        ticket.subject,
                        message,
                        settings.DEFAULT_FROM_EMAIL,
                    )

    def process_close_requests(self, client):
        """
        Process tickets flagged for auto-close when the related pending
        object was deleted (#1948). Only requests not yet processed
        (closed is null) are considered.

        Behavioral note: in the common case a flagged-but-unpublished ticket
        is never sent to DeskPro (publish_new_tickets excludes close_requested
        tickets) and is simply dropped here. In the rare interleave where the
        create pass had already picked up the ticket for publishing at the
        instant the object was deleted, the ticket is created on DeskPro and
        then auto-closed on a subsequent run — a brief create-then-close
        rather than never-created. Both outcomes mean the AC never has to
        touch the ticket; the latter just leaves an audit trail.

        The create-then-close outcome depends on close_requested surviving the
        create pass: publish_new_tickets MUST save with update_fields so it
        never overwrites a concurrently-set close_requested=True. Do not
        "simplify" those saves back to a bare ticket.save() — that reintroduces
        the race and orphans the ticket on DeskPro.
        """
        close_qs = models.DeskProTicket.objects.filter(
            close_requested=True,
            closed__isnull=True,
        ).order_by("created")

        for ticket in close_qs[:10]:
            # Never published to DeskPro - there is no ticket to close on
            # their side, so just drop the local record.
            if not ticket.deskpro_id:
                self.log(f"Dropping unpublished close request: #{ticket.id}")
                ticket.delete()
                continue

            self.log(f"Closing on Deskpro: #{ticket.id} (id {ticket.deskpro_id})")

            try:
                resolved = client.close_ticket(ticket.deskpro_id)
                if not resolved:
                    self.log(
                        f"Ticket #{ticket.id} not eligible for auto-close - skipped."
                    )

            except APIError as exc:
                error_code = exc.data.get("code")
                self.log(
                    f"!!!! Could not close ticket #{ticket.id} - code {error_code}."
                )

            # Mark processed regardless of outcome so we don't retry forever:
            # an ineligible status means an agent is already handling it, and
            # a persistent API error (e.g. the ticket was removed on DeskPro)
            # would otherwise block the queue head. AC can close manually if
            # a transient error happened to fall here.
            ticket.closed = self.now()
            ticket.save(update_fields=["closed"])
