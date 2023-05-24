from django_elasticsearch_dsl.management.commands.search_index import (
    Command as SearchIndexCommand,
)

from peeringdb_server.context import incremental_period


class Command(SearchIndexCommand):
    """
    Extends the django_elasticsearch_dsl search_index command to allow incremental updates based
    off of a max-age period
    """

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--max-age",
            type=int,
            default=3600,
            help="Only update records that have been updated in the last X seconds",
        )

    def handle(self, *args, **options):
        with incremental_period(options["max_age"]):
            super().handle(*args, **options)
