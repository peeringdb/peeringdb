from django.conf import settings as dj_settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

User = get_user_model()


class Command(BaseCommand):
    help = "Manage UI Next feature flags for users"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()

        group.add_argument(
            "--opt-in-user", type=int, help="Opt in specific user ID to UI Next"
        )
        group.add_argument(
            "--opt-out-user", type=int, help="Opt out specific user ID from UI Next"
        )
        group.add_argument(
            "--opt-in-nth", type=int, help="Opt in every nth user to UI Next"
        )
        group.add_argument(
            "--opt-out-all", action="store_true", help="Opt out all users from UI Next"
        )
        group.add_argument(
            "--show-rejections",
            action="store_true",
            help="Show total count of users rejecting UI Next",
        )
        group.add_argument(
            "--list-rejections", type=int, help="List up to N users rejecting UI Next"
        )

    def handle(self, *args, **options):
        if options["opt_in_user"]:
            self.opt_in_user(options["opt_in_user"])

        elif options["opt_out_user"]:
            self.opt_out_user(options["opt_out_user"])

        elif options["opt_in_nth"]:
            self.opt_in_every_nth_user(options["opt_in_nth"])

        elif options["opt_out_all"]:
            self.opt_out_all_users()

        elif options["show_rejections"]:
            self.show_rejection_count()

        elif options["list_rejections"]:
            self.list_rejected_users(options["list_rejections"])

        else:
            self.stdout.write(self.style.ERROR("No valid option provided."))

    def opt_in_user(self, user_id):
        try:
            user = User.objects.get(id=user_id)
            user.set_opt_flag(dj_settings.USER_OPT_FLAG_UI_NEXT, True)
            user.set_opt_flag(dj_settings.USER_OPT_FLAG_UI_NEXT_REJECTED, False)
            user.save()
            self.stdout.write(self.style.SUCCESS(f"User {user_id} opted in to UI Next"))
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"User with id {user_id} not found"))

    def opt_out_user(self, user_id):
        try:
            user = User.objects.get(id=user_id)
            user.set_opt_flag(dj_settings.USER_OPT_FLAG_UI_NEXT, False)
            user.set_opt_flag(
                dj_settings.USER_OPT_FLAG_UI_NEXT_REJECTED,
                True if user.ui_next_enabled else False,
            )
            user.save()
            self.stdout.write(
                self.style.SUCCESS(f"User {user_id} opted out of UI Next")
            )
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"User with id {user_id} not found"))

    def opt_in_every_nth_user(self, n):
        users = User.objects.all().order_by("id")
        count = 0

        for i, user in enumerate(users):
            if i % n == 0:
                if not user.ui_next_rejected:
                    user.set_opt_flag(dj_settings.USER_OPT_FLAG_UI_NEXT, True)
                    user.save()
                    count += 1

        self.stdout.write(
            self.style.SUCCESS(f"Opted in {count} users (every {n}th user)")
        )

    def opt_out_all_users(self):
        users = User.objects.all()
        count = 0

        for user in users:
            user.set_opt_flag(dj_settings.USER_OPT_FLAG_UI_NEXT, False)
            user.set_opt_flag(dj_settings.USER_OPT_FLAG_UI_NEXT_REJECTED, False)
            user.save()
            count += 1

        self.stdout.write(self.style.SUCCESS(f"Opted out {count} users from UI Next"))

    def show_rejection_count(self):
        users = User.objects.all()
        rejected_count = sum(1 for u in users if u.ui_next_rejected)
        self.stdout.write(
            self.style.SUCCESS(f"{rejected_count} users have rejected the new UI")
        )

    def list_rejected_users(self, limit):
        users = User.objects.all()
        rejected_users = [user for user in users if user.ui_next_rejected][:limit]

        if not rejected_users:
            self.stdout.write("No users found rejecting the UI.")
            return

        for user in rejected_users:
            self.stdout.write(f"{user.id} - {user.username} - {user.email}")
