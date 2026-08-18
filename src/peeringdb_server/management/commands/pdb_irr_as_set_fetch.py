"""
Download and refresh the local IRR dump cache used by batch AS-SET jobs.

The interactive editor and save path use the live IRR lookup pool. This command
maintains the separate bulk cache used by pdb_irr_as_set_cleanup and the periodic
checker so those jobs do not issue tens of thousands of per-object mirror queries.

Dry-run by default, --commit to download, like every other command in this suite.
A dry run reports what each source would do and touches nothing: it makes no
request, and the dump directory and its staging area are left alone, so it also
answers on a cold host. That offline rule is why any *usable* cache is reported
conditionally, however old it is: once the cache is valid the real run decides on
the published serial and ignores file age, so only the reason string can say what
that source's outcome actually turns on.

Under --commit every source is attempted independently: a refresh that failed but
kept a usable cache is "stale", one with no usable dump at all is "failed", and the
remaining sources are refreshed either way. The command then exits non-zero,
because the run otherwise looks successful while a registry silently stops
refreshing and pdb_irr_as_set_cleanup --commit auto-prefixes from an ageing index.

Usage:
  manage pdb_irr_as_set_fetch [--source SOURCE] [--force] [--commit]
                              [--dump-dir PATH] [--max-age-hours HOURS]
"""

from django.core.management.base import CommandError

from peeringdb_server import irr_bulk
from peeringdb_server.management.commands.pdb_base_command import PeeringDBBaseCommand


class Command(PeeringDBBaseCommand):
    help = "Download and refresh the local IRR dump cache (#1973)."

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--source",
            action="append",
            help="Refresh only this IRR source (repeatable; default: all).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Download even when the serial or cache age is current.",
        )
        parser.add_argument(
            "--dump-dir",
            default=None,
            help="Dump cache directory (overrides IRR_BULK_DUMP_DIR).",
        )
        parser.add_argument(
            "--max-age-hours",
            type=float,
            default=None,
            help="Maximum cache age for sources without serial markers.",
        )

    def handle(self, *args, **options):
        self.commit = options.get("commit")
        fetch = irr_bulk.fetch_dumps if self.commit else irr_bulk.plan_fetch

        try:
            outcomes = fetch(
                dump_dir=options["dump_dir"],
                source_names=options["source"],
                force=options["force"],
                max_age_hours=options["max_age_hours"],
            )
        except irr_bulk.BulkFetchError as exc:
            raise CommandError(str(exc)) from exc

        for outcome in outcomes:
            filenames = ", ".join(path.rsplit("/", 1)[-1] for path in outcome.files)
            # log(), not stdout.write: the base class marks dry-run lines
            # [pretend], which is how the sibling commands distinguish the two
            # modes at a glance
            self.log(
                f"[{outcome.status}] {outcome.source}: {filenames} ({outcome.reason})"
            )

        if not self.commit:
            downloads = sum(1 for o in outcomes if o.status == "would-download")
            conditional = sum(1 for o in outcomes if o.status == "serial-decides")
            self.stdout.write(
                f"dry run of {len(outcomes)} source(s): {downloads} would download, "
                f"{conditional} download only if the published serial moved. "
                "Nothing was requested and nothing was written. Pass --commit to "
                "refresh."
            )
            return

        # both mean this registry is no longer refreshing, and one such line among 17
        # is too quiet to notice -- raise so cron sees a non-zero exit
        unhealthy = [
            outcome for outcome in outcomes if outcome.status in ("stale", "failed")
        ]
        if unhealthy:
            raise CommandError(
                "IRR dump refresh failed for "
                + ", ".join(
                    f"{outcome.source} [{outcome.status}] ({outcome.reason})"
                    for outcome in unhealthy
                )
                + " -- pdb_irr_as_set_cleanup --commit will refuse the resulting "
                "index while any source is stale or missing."
            )
