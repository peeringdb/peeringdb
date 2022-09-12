#!/usr/bin/env python
"""
Process deskpro ticket queue.
"""

import datetime

from django.conf import settings
from django.core.management.base import BaseCommand
from django.template import loader

from peeringdb_server import models
from peeringdb_server.deskpro import APIClient, APIError
from peeringdb_server.mail import mail_admins_with_from


class Command(BaseCommand):
    help = "Process deskpro ticket queue"

    def log(self, msg):
        self.stdout.write(msg)

    def handle(self, *args, **options):
        client = APIClient(settings.DESKPRO_URL, settings.DESKPRO_KEY)
        self.log(f"DESKPRO: {settings.DESKPRO_URL}")

        # Per issue #858 we want to ignore the IX-F tickets
        ticket_qs = (
            models.DeskProTicket.objects.filter(published__isnull=True)
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
                ticket.published = datetime.datetime.now().replace(tzinfo=models.UTC())
                ticket.save()

            except APIError as exc:
                error_code = exc.data.get("code")
                if error_code:
                    if error_code == "duplicate_ticket":
                        self.log(f"Duplicate ticket #{ticket.id} - ignoring.")
                        return

                self.log(
                    f"!!!! Could not create ticket #{ticket.id} - code {error_code} - error data has been attached to ticket body."
                )

                ticket.published = datetime.datetime.now().replace(tzinfo=models.UTC())
                ticket.subject = f"[FAILED][{error_code}] {ticket.subject}"
                ticket.body = f"{ticket.body}\nAPI Delivery Error: {exc.data}"
                ticket.save()

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
