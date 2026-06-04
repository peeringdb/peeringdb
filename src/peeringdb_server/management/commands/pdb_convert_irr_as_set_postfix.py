"""
Convert irr_as_set @SOURCE postfix tokens to SOURCE:: prefix notation.

Finds all Network objects (status=ok) whose irr_as_set contains @SOURCE
tokens and rewrites each token to SOURCE::as-set format.

Usage:

    # Preview changes without modifying the database
    ./Ctl/dev/run.sh manage pdb_convert_irr_as_set_postfix

    # Apply changes
    ./Ctl/dev/run.sh manage pdb_convert_irr_as_set_postfix --commit
"""

import re

import reversion
from django.db import transaction

from peeringdb_server import models as pdb_models
from peeringdb_server.management.commands.pdb_base_command import PeeringDBBaseCommand


def convert_irr_as_set(value):
    """
    Convert any @SOURCE postfix tokens in value to SOURCE:: prefix format.

    Tokens already in SOURCE:: format are left unchanged.
    Returns the normalized, space-separated string.
    """
    # normalize comma/space separators to whitespace before splitting, in case
    # a row was written outside validate_irr_as_set (raw create, fixtures, legacy imports)
    normalized = value.upper().replace(",", " ")
    tokens = normalized.split()
    converted = []
    for token in tokens:
        m = re.match(r"^([A-Z0-9_:-]+)@([A-Z0-9-]+)$", token)
        if m:
            converted.append(f"{m.group(2)}::{m.group(1)}")
        else:
            converted.append(token)
    return " ".join(converted)


class Command(PeeringDBBaseCommand):
    help = "Convert irr_as_set @SOURCE postfix notation to SOURCE:: prefix notation."

    @reversion.create_revision()
    @transaction.atomic
    def handle(self, *args, **options):
        self.commit = options.get("commit")

        networks = pdb_models.Network.objects.filter(
            irr_as_set__contains="@", status="ok"
        )

        count = 0

        for net in networks:
            converted = convert_irr_as_set(net.irr_as_set)

            if converted == net.irr_as_set:
                continue

            self.log(
                f"Network id:{net.id} asn:{net.asn} - "
                f"irr_as_set '{net.irr_as_set}' -> '{converted}'"
            )
            count += 1

            if self.commit:
                net.irr_as_set = converted
                net.save()

        self.log(f"{count} network(s) converted.")
