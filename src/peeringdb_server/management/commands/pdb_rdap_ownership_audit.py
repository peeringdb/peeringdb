"""Report retained affiliation evidence without modifying the selected database."""

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from peeringdb_server.rdap_audit import iter_affiliation_audit


class Command(BaseCommand):
    help = "Read-only affiliation approval and administrator evidence report (JSONL)"
    requires_system_checks: list[str] = []

    def add_arguments(self, parser):
        parser.add_argument("--database", default="default", choices=tuple(connections))

    def handle(self, *args, **options):
        try:
            for row in iter_affiliation_audit(options["database"]):
                self.stdout.write(json.dumps(row, sort_keys=True))
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
