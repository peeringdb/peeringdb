from datetime import timedelta
from unittest.mock import PropertyMock, patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from peeringdb_server.models import User, UserAPIKey


class NotifyUsersMissingMfaAndApiKeysTest(TestCase):
    def create_user(self, username, email, api_key):
        user = User.objects.create_user(
            username=username,
            email=email,
            password="testpass",
        )
        if api_key:
            UserAPIKey.objects.create(user=user, name="my key", status="active")
        return user

    @override_settings(
        MFA_FORCE_SOFT_START=timezone.now() - timedelta(days=1),
        MFA_FORCE_HARD_START=timezone.now() - timedelta(days=1),
        DEFAULT_FROM_EMAIL="support@peeringdb.com",
        BASE_URL="https://example.com",
        USER_OPT_FLAG_NOTIFIED_MFA=0x08,
        USER_OPT_FLAG_NOTIFIED_API_KEY=0x10,
    )
    @patch.object(User, "has_2fa", new_callable=PropertyMock)
    @patch.object(User, "email_confirmed", new_callable=PropertyMock)
    @patch.object(User, "was_notified_mfa", new_callable=PropertyMock)
    @patch.object(User, "was_notified_api_key", new_callable=PropertyMock)
    @patch.object(User, "email_user")
    @patch.object(User, "set_opt_flag")
    def test_notify_user_missing_mfa_only(
        self,
        mock_set_opt_flag,
        mock_email_user,
        mock_notified_api_key,
        mock_notified_mfa,
        mock_email_confirmed,
        mock_has_2fa,
    ):
        user = self.create_user("testuser1", "user1@example.com", api_key=True)

        mock_email_confirmed.return_value = True
        mock_has_2fa.return_value = False
        mock_notified_mfa.return_value = False
        mock_notified_api_key.return_value = True

        call_command("pdb_mfa_notify", "--commit")

        mock_email_user.assert_called_once()
        mock_set_opt_flag.assert_called_once_with(0x08, True)

        subject = mock_email_user.call_args[1]["subject"]
        message = mock_email_user.call_args[1]["message"]

        self.assertIn("Set Up MFA", subject)
        self.assertIn("https://example.com/account/two_factor/", message)
        self.assertNotIn("API Key", subject)

    @override_settings(
        MFA_FORCE_SOFT_START=timezone.now() - timedelta(days=1),
        MFA_FORCE_HARD_START=timezone.now() - timedelta(days=1),
        DEFAULT_FROM_EMAIL="support@peeringdb.com",
        BASE_URL="https://example.com",
        USER_OPT_FLAG_NOTIFIED_MFA=0x08,
        USER_OPT_FLAG_NOTIFIED_API_KEY=0x10,
    )
    @patch.object(User, "has_2fa", new_callable=PropertyMock)
    @patch.object(User, "email_confirmed", new_callable=PropertyMock)
    @patch.object(User, "was_notified_mfa", new_callable=PropertyMock)
    @patch.object(User, "was_notified_api_key", new_callable=PropertyMock)
    @patch.object(User, "email_user")
    @patch.object(User, "set_opt_flag")
    def test_notify_user_missing_api_key_only(
        self,
        mock_set_opt_flag,
        mock_email_user,
        mock_notified_api_key,
        mock_notified_mfa,
        mock_email_confirmed,
        mock_has_2fa,
    ):
        user = self.create_user("testuser2", "user2@example.com", api_key=False)

        mock_email_confirmed.return_value = True
        mock_has_2fa.return_value = True
        mock_notified_mfa.return_value = True
        mock_notified_api_key.return_value = False

        call_command("pdb_mfa_notify", "--commit")

        mock_email_user.assert_called_once()
        mock_set_opt_flag.assert_called_once_with(0x10, True)

        subject = mock_email_user.call_args[1]["subject"]
        message = mock_email_user.call_args[1]["message"]

        self.assertIn("Create an API Key", subject)
        self.assertIn("https://example.com/profile/api_keys/", message)
        self.assertNotIn("MFA", subject)

    @override_settings(
        MFA_FORCE_SOFT_START=timezone.now() - timedelta(days=1),
        MFA_FORCE_HARD_START=timezone.now() - timedelta(days=1),
        DEFAULT_FROM_EMAIL="support@peeringdb.com",
        BASE_URL="https://example.com",
        USER_OPT_FLAG_NOTIFIED_MFA=0x08,
        USER_OPT_FLAG_NOTIFIED_API_KEY=0x10,
    )
    @patch.object(User, "has_2fa", new_callable=PropertyMock)
    @patch.object(User, "email_confirmed", new_callable=PropertyMock)
    @patch.object(User, "was_notified_mfa", new_callable=PropertyMock)
    @patch.object(User, "was_notified_api_key", new_callable=PropertyMock)
    @patch.object(User, "email_user")
    @patch.object(User, "set_opt_flag")
    def test_notify_user_missing_api_key_and_mfa(
        self,
        mock_set_opt_flag,
        mock_email_user,
        mock_notified_api_key,
        mock_notified_mfa,
        mock_email_confirmed,
        mock_has_2fa,
    ):
        user = self.create_user("testuser3", "user3@example.com", api_key=False)

        mock_email_confirmed.return_value = True
        mock_has_2fa.return_value = False
        mock_notified_mfa.return_value = False
        mock_notified_api_key.return_value = False

        call_command("pdb_mfa_notify", "--commit")

        mock_email_user.assert_called_once()
        mock_set_opt_flag.assert_any_call(0x08, True)
        mock_set_opt_flag.assert_any_call(0x10, True)
        self.assertEqual(mock_set_opt_flag.call_count, 2)

        subject = mock_email_user.call_args[1]["subject"]
        message = mock_email_user.call_args[1]["message"]

        self.assertIn("Set Up MFA and API Key", subject)
        self.assertIn("https://example.com/account/two_factor/", message)
        self.assertIn("https://example.com/profile/api_keys/", message)

    @override_settings(
        MFA_FORCE_SOFT_START=timezone.now() - timedelta(days=1),
        MFA_FORCE_HARD_START=timezone.now() - timedelta(days=1),
        DEFAULT_FROM_EMAIL="support@peeringdb.com",
        BASE_URL="https://example.com",
        USER_OPT_FLAG_NOTIFIED_MFA=0x08,
        USER_OPT_FLAG_NOTIFIED_API_KEY=0x10,
    )
    @patch.object(User, "has_2fa", new_callable=PropertyMock)
    @patch.object(User, "email_confirmed", new_callable=PropertyMock)
    @patch.object(User, "was_notified_mfa", new_callable=PropertyMock)
    @patch.object(User, "was_notified_api_key", new_callable=PropertyMock)
    @patch.object(User, "email_user")
    @patch.object(User, "set_opt_flag")
    def test_user_with_mfa_and_api_key_not_notified(
        self,
        mock_set_opt_flag,
        mock_email_user,
        mock_notified_api_key,
        mock_notified_mfa,
        mock_email_confirmed,
        mock_has_2fa,
    ):
        user = self.create_user("testuser4", "user4@example.com", api_key=True)

        mock_email_confirmed.return_value = True
        mock_has_2fa.return_value = True
        mock_notified_mfa.return_value = True
        mock_notified_api_key.return_value = True

        call_command("pdb_mfa_notify", "--commit")

        mock_email_user.assert_not_called()
        mock_set_opt_flag.assert_not_called()
