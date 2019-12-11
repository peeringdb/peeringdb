#!/usr/bin/env python
# -*- coding: utf-8 -*-

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
        self.log("DESKPRO: {}".format(settings.DESKPRO_URL))
        ticket_qs = models.DeskProTicket.objects.filter(
            published__isnull=True
        ).order_by("created")

        if not ticket_qs.count():
            self.log("No tickets in queue")
            return

        for ticket in ticket_qs[:10]:
            self.log("Posting to Deskpro: #{}".format(ticket.id))

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
                ticket.subject = "[FAILED] {}".format(ticket.subject)
                ticket.body = "{}\nAPI Delivery Error: {}".format(
                    ticket.body, exc.data
                )
                ticket.save()
