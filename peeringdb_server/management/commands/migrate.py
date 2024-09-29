from django.conf import settings
from django.core.management.commands.migrate import Command as MigrateCommand


class Command(MigrateCommand):
    """
    Custom migrate command that temporarily enables writes if DJANGO_READ_ONLY is enabled.
    """

    def handle(self, *args, **options):
        # Check if DJANGO_READ_ONLY is set to true
        if settings.DJANGO_READ_ONLY:
            self.stdout.write(
                self.style.WARNING(
                    "DJANGO_READ_ONLY is enabled. Temporarily enabling writes for migrations."
                )
            )
            # Temporarily enable writes during migrations
            import django_read_only

            with django_read_only.temp_writes():
                super().handle(*args, **options)
        else:
            # Run the default migrate command
            super().handle(*args, **options)
