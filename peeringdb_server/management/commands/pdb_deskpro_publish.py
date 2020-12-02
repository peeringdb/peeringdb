#!/usr/bin/env python

import datetime
from django.core.management.base import BaseCommand
from django.conf import settings

from peeringdb_server import models
from peeringdb_server.deskpro import APIClient, APIError


class Command(BaseCommand):
    help = "Process deskpro ticket queue"

    def add_arguments(self, parser):
        pass

    def log(self, msg):
        print(msg)

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
                self.log(
                    "!!!! Could not create ticket #{} - error data has been attached to ticket body.".format(
                        ticket.id
                    )
                )
                ticket.published = datetime.datetime.now().replace(tzinfo=models.UTC())
                ticket.subject = f"[FAILED] {ticket.subject}"
                ticket.body = f"{ticket.body}\nAPI Delivery Error: {exc.data}"
                ticket.save()
