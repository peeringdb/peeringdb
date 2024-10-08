from django.conf import settings
from django.core.management.commands.runserver import Command as RunServerBaseCommand


class Command(RunServerBaseCommand):
    """
    Custom migrate command that temporarily enables writes if DJANGO_READ_ONLY is enabled.
    """

    def inner_run(self, *args, **options):
        # Check if DJANGO_READ_ONLY is set to true
        if settings.DJANGO_READ_ONLY and "django_read_only" in settings.INSTALLED_APPS:
            self.stdout.write(
                self.style.WARNING(
                    "DJANGO_READ_ONLY is enabled. Temporarily enabling writes for runserver."
                )
            )
            import django_read_only

            with django_read_only.temp_writes():
                super().inner_run(*args, **options)
        else:
            super().inner_run(*args, **options)
