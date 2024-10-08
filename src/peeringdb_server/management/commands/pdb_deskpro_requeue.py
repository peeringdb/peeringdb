"""
Reset a deskpro ticket and requeue for publishing.
"""

import re

from django.core.management.base import BaseCommand

from peeringdb_server.models import DeskProTicket


class Command(BaseCommand):
    help = "Reset a deskpro ticket and queue again for publish"

    def add_arguments(self, parser):
        parser.add_argument("id", nargs="?", help="ticket id")
        parser.add_argument(
            "--commit", action="store_true", help="will commit the changes"
        )
        parser.add_argument(
            "--only-failed", action="store_true", help="only requeue failed tickets"
        )

    def log(self, msg):
        if self.commit:
            self.stdout.write(msg)
        else:
            self.stdout.write(f"[pretend] {msg}")

    def handle(self, *args, **options):
        _id = options.get("id")
        self.commit = options.get("commit")
        self.only_failed = options.get("only_failed")

        qset = DeskProTicket.objects
        if _id[0] == "g":
            self.log(f"Requeuing tickets with id greater than {_id[1:]}")
            qset = qset.filter(pk__gt=_id[1:])
        elif _id[0] == "l":
            self.log(f"Requeuing tickets with id smaller than {_id[1:]}")
            qset = qset.filter(pk__lt=_id[1:])
        else:
            qset = qset.filter(pk=_id)

        for ticket in qset:
            if self.only_failed and ticket.subject.find("[FAILED]") == -1:
                continue
            self.log(f"Requeuing ticket with id {ticket.id}")
            ticket.subject = ticket.subject.replace("[FAILED]", "")
            ticket.subject = re.sub(r"^\[.+\]", "", ticket.subject)
            ticket.subject = ticket.subject.strip(" ")
            ticket.body = re.sub(r"API Delivery Error(.+)$", "", ticket.body)
            ticket.published = None
            if self.commit:
                ticket.save()
