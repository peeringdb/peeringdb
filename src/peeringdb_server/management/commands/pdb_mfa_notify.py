from django.conf import settings
from django.core.management.base import BaseCommand
from django.template import loader
from django.utils import timezone

from peeringdb_server.models import User


class Command(BaseCommand):
    help = "Notify users who need to set up MFA and/or API keys."

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Actually send emails (otherwise dry run)",
        )
        parser.add_argument("--limit", type=int, default=100)

    def get_setting_time(self, setting_name):
        value = getattr(settings, setting_name, None)
        if value and timezone.is_naive(value):
            try:
                return timezone.make_aware(value)
            except Exception:
                return None
        return value

    def build_subject(self, needs_mfa=False, needs_api_key=False):
        if needs_mfa and needs_api_key:
            return "Action Required: Set Up MFA and API Key for Your PeeringDB Account"
        elif needs_mfa:
            return "Action Required: Set Up MFA for Your PeeringDB Account"
        elif needs_api_key:
            return "Action Required: Create an API Key for Your PeeringDB Account"
        else:
            return "PeeringDB Account Notification"

    def handle(self, *args, **options):
        now = timezone.now()
        start_request = self.get_setting_time("MFA_FORCE_SOFT_START")
        start_force = self.get_setting_time("MFA_FORCE_HARD_START")

        if not (start_request or start_force):
            self.stdout.write("No MFA enforcement settings found. Exiting.")
            return

        users = (
            User.objects.filter(is_active=True)
            .prefetch_related("api_keys")
            .only("id", "username", "email")
        )

        notified = 0
        # notify_needs = []
        for user in users.iterator(chunk_size=1000):
            if not user.email_confirmed:
                continue

            needs_mfa = False
            needs_api_key = False

            if not user.has_2fa and not user.was_notified_mfa:
                if (start_force and now >= start_force) or (
                    start_request and now >= start_request
                ):
                    needs_mfa = True

            if (
                not user.api_keys.filter(status="active").exists()
                and not user.was_notified_api_key
            ):
                if start_force and now >= start_force:
                    needs_api_key = True

            if not needs_mfa and not needs_api_key:
                continue

            if options["limit"] and notified >= options["limit"]:
                break

            if options["commit"]:
                self.send_email(user, needs_mfa=needs_mfa, needs_api_key=needs_api_key)
            else:
                notify_needs = []
                if needs_mfa:
                    notify_needs.append("MFA")
                if needs_api_key:
                    notify_needs.append("API Key")
                self.stdout.write(
                    f"Would notify {user.username} ({user.email}) - notify needs: {', '.join(notify_needs)}"
                )

            notified += 1

        if notified == 0:
            self.stdout.write("[INFO] No users need to be notified.")
        elif not options["commit"]:
            self.stdout.write("\n[INFO] Run with --commit to send actual emails.")

    def send_email(self, user, needs_mfa=False, needs_api_key=False):
        if not (needs_mfa or needs_api_key):
            return

        subject = self.build_subject(needs_mfa=needs_mfa, needs_api_key=needs_api_key)
        context = {
            "user": user,
            "deadline": settings.MFA_FORCE_HARD_START.strftime("%B %d, %Y")
            if settings.MFA_FORCE_HARD_START
            else "soon",
            "support_email": settings.DEFAULT_FROM_EMAIL,
            "enable_mfa_url": f"{settings.BASE_URL}/account/two_factor/",
            "create_api_key_url": f"{settings.BASE_URL}/profile/api_keys/",
            "needs_mfa": needs_mfa,
            "needs_api_key": needs_api_key,
        }

        message = loader.get_template(
            "email/notify-user-missing-mfa-and-api-key.txt"
        ).render(context)

        if needs_mfa:
            user.set_opt_flag(settings.USER_OPT_FLAG_NOTIFIED_MFA, True)
        if needs_api_key:
            user.set_opt_flag(settings.USER_OPT_FLAG_NOTIFIED_API_KEY, True)

        user.save()

        user.email_user(subject=subject, message=message)

        self.stdout.write(
            f"Sent email to {user.username} ({user.email}) [MFA: {needs_mfa}, API Key: {needs_api_key}]"
        )
