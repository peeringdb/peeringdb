"""
Replace a value in a field across several entities.
"""

import re

import reversion
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

import peeringdb_server.models as pdbm


class Command(BaseCommand):
    help = "Replace a value in a field across several entities"
    pretend = False

    # this defines which ref_tag field_name combinations may
    # be targeted by this command, this is a safety measure
    # extend as needed
    valid_targets = {"fac": ["name", "org_id"]}

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit", action="store_true", help="will commit the fac merge"
        )
        parser.add_argument("--search", help="<ref_tag>.<field_name>:<search_value>")
        parser.add_argument(
            "--replace", help="<field_name>:<search_value>:<replacement_value>"
        )

    def log(self, msg):
        if not self.commit:
            print(f"[{self.target}] {msg} [pretend]")
        else:
            print(f"[{self.target}] {msg}")

    @reversion.create_revision()
    @transaction.atomic()
    def handle(self, *args, **options):
        self.commit = options.get("commit", False)
        self.search = options.get("search")
        self.replace = options.get("replace")

        if not self.search:
            raise CommandError("Specify search parameters using the --search option")

        if not self.replace:
            raise CommandError(
                "Specify replacement parameters using the --replace option"
            )

        try:
            search_field, search_value = self.search.split(":")
            ref_tag, search_field = search_field.split(".")
        except Exception:
            raise CommandError(
                "Format for --search: <ref_tag>.<field_name>:<search_value>"
            )

        try:
            m = re.match("^([^:]+):([^:]+):(.+)$", self.replace)
            replace_field = m.group(1)
            replace_search_value = m.group(2)
            replace_value = m.group(3)
        except Exception:
            raise CommandError(
                "Format for --replace: <field_name>:<search_value>:<replacement_value>"
            )

        # if replace_field not in self.valid_targets.get(ref_tag,[]):
        #    raise CommandError("%s.%s is not a valid target for this script at this point, please add it to the valid_targets map" % (ref_tag, replace_field))

        self.target = f"{ref_tag}.{search_field}"

        self.log(
            "Searching for %s where %s matches '%s' ..."
            % (ref_tag, search_field, search_value)
        )

        q = pdbm.REFTAG_MAP[ref_tag].objects.filter(status="ok")
        c = 0

        for e in q:
            val = getattr(e, search_field)
            if re.search(search_value, val) is not None:
                t_val = getattr(e, replace_field)
                r_val = None
                if replace_search_value == "*":
                    r_val = replace_value
                elif isinstance(t_val, str):
                    r_val = re.sub(replace_search_value, replace_value, t_val)
                elif isinstance(t_val, int):
                    if t_val == int(replace_search_value or 0):
                        r_val = replace_value
                else:
                    if t_val == replace_search_value:
                        r_val = replace_value
                if r_val is None:
                    continue
                self.log(
                    "(<%s> id:%s) Changing %s from '%s' to '%s'"
                    % (e, e.id, replace_field, t_val, r_val)
                )
                c += 1
                if self.commit:
                    setattr(e, replace_field, r_val)
                    e.save()

        self.log("%d objects were changed." % c)
