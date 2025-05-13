from io import StringIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

User = get_user_model()


class PdbUIOptFlagsCommandTest(TestCase):
    def setUp(self):
        self.users = [User.objects.create(username=f"u{i}") for i in range(1, 6)]

    def test_opt_in_user(self):
        out = StringIO()
        call_command("pdb_ui_opt_flags", "--opt-in-user", self.users[0].id, stdout=out)
        self.users[0].refresh_from_db()
        self.assertTrue(self.users[0].ui_next_enabled)
        self.assertFalse(self.users[0].ui_next_rejected)

    def test_opt_out_user(self):
        self.users[1].set_opt_flag(settings.USER_OPT_FLAG_UI_NEXT, True)
        self.users[1].save()
        call_command("pdb_ui_opt_flags", "--opt-out-user", self.users[1].id)
        self.users[1].refresh_from_db()

        # reset user option
        self.assertFalse(self.users[1].ui_next_enabled)
        self.assertFalse(self.users[1].ui_next_rejected)

    def test_opt_in_every_nth(self):
        call_command("pdb_ui_opt_flags", "--opt-in-nth", 2)
        opted_in = [u for u in User.objects.all() if u.ui_next_enabled]
        self.assertGreaterEqual(len(opted_in), 2)

    def test_opt_out_all(self):
        for u in self.users:
            u.set_opt_flag(settings.USER_OPT_FLAG_UI_NEXT, True)
            u.save()
        call_command("pdb_ui_opt_flags", "--opt-out-all")
        for u in User.objects.all():
            # reset all users
            self.assertFalse(u.ui_next_enabled)
            self.assertFalse(u.ui_next_rejected)

    def test_show_rejections(self):
        self.users[0].set_opt_flag(settings.USER_OPT_FLAG_UI_NEXT_REJECTED, True)
        self.users[0].save()
        out = StringIO()
        call_command("pdb_ui_opt_flags", "--show-rejections", stdout=out)
        self.assertIn("1 users have rejected", out.getvalue())

    def test_list_rejections(self):
        self.users[2].set_opt_flag(settings.USER_OPT_FLAG_UI_NEXT_REJECTED, True)
        self.users[2].save()
        out = StringIO()
        call_command("pdb_ui_opt_flags", "--list-rejections", "2", stdout=out)
        self.assertIn(str(self.users[2].id), out.getvalue())
