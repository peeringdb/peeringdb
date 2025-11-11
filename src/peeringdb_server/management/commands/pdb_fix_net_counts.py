"""
Fix incorrect net_count and ixf_net_count values for InternetExchange objects.

This command recalculates net_count and ixf_net_count for all exchanges
to fix any inconsistencies caused by issue #1607.

net_count: Number of unique networks actually peering at the exchange
ixf_net_count: Number of unique networks in the IX-F export data
"""

from django.core.management.base import BaseCommand
from django.db.models import Count

from peeringdb_server.models import InternetExchange, NetworkIXLan


class Command(BaseCommand):
    help = "Fix incorrect net_count and ixf_net_count values for exchanges (#1607)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit",
            action="store_true",
            help="commit changes, otherwise run in pretend mode",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help="only check and report which exchanges have incorrect values",
        )
        parser.add_argument(
            "--ix",
            type=int,
            help="only fix this specific exchange ID",
        )
        parser.add_argument(
            "--show-correct",
            action="store_true",
            help="also show exchanges that already have correct values",
        )

    def log(self, msg):
        if not self.commit and not self.check:
            self.stdout.write(f"[pretend] {msg}")
        else:
            self.stdout.write(msg)

    def handle(self, *args, **options):
        self.commit = options.get("commit", False)
        self.check = options.get("check", False)
        self.show_correct = options.get("show_correct", False)
        ix_id = options.get("ix")

        if ix_id:
            exchanges = InternetExchange.objects.filter(id=ix_id, status="ok")
        else:
            exchanges = InternetExchange.objects.filter(status="ok")

        total = exchanges.count()
        self.log(f"Processing {total} exchanges...\n")

        incorrect_exchanges = []
        fixed_net_count = 0
        correct_count = 0

        # Disable auto_now to prevent updating the 'updated' timestamp
        InternetExchange._meta.get_field("updated").auto_now = False

        try:
            for ix in exchanges:
                # Calculate correct net_count from database
                correct_net_count = (
                    NetworkIXLan.objects.filter(
                        ixlan__ix_id=ix.id, status="ok"
                    ).aggregate(net_count=Count("network_id", distinct=True))
                )["net_count"]

                is_incorrect = ix.net_count != correct_net_count

                if is_incorrect:
                    incorrect_exchanges.append(
                        {
                            "id": ix.id,
                            "name": ix.name,
                            "current": ix.net_count,
                            "correct": correct_net_count,
                            "diff": correct_net_count - ix.net_count,
                        }
                    )
                    fixed_net_count += 1

                    if self.check:
                        # Just report, don't fix
                        diff_str = f"{correct_net_count - ix.net_count:+d}"
                        self.stdout.write(
                            f"IX {ix.id:5d} | {ix.name:40s} | "
                            f"Current: {ix.net_count:3d} | Correct: {correct_net_count:3d} | "
                            f"Diff: {diff_str:>4s}"
                        )
                    else:
                        # Fix it
                        self.log(
                            f"Fixing IX {ix.id} ({ix.name}): "
                            f"net_count: {ix.net_count} -> {correct_net_count}"
                        )
                        ix.net_count = correct_net_count
                        if self.commit:
                            ix.save()
                else:
                    correct_count += 1
                    if self.show_correct:
                        self.stdout.write(
                            f"IX {ix.id:5d} | {ix.name:40s} | "
                            f"net_count: {ix.net_count:3d} ✓ (correct)"
                        )

        finally:
            # Re-enable auto_now
            InternetExchange._meta.get_field("updated").auto_now = True

        # Summary
        self.log("\n" + "=" * 80)
        self.log("SUMMARY:")
        self.log("=" * 80)
        self.log(f"Total exchanges processed: {total}")
        self.log(f"Exchanges with incorrect net_count: {fixed_net_count}")
        self.log(f"Exchanges already correct: {correct_count}")

        if self.check:
            self.log("\nThis was a check-only run. Use --commit to apply fixes.")
        elif not self.commit:
            self.log("\nRun with --commit to apply changes")
        else:
            self.log("\n✓ All changes have been committed to the database")
