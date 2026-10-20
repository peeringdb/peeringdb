"""
Lists, migrates and notifies OAuth applications that cannot sign their HS256
ID tokens (#2055).

PeeringDB stores client secrets hashed (migration 0115), so an HS256 ID token
can no longer be signed and these applications fail every request that issues
one. HS256 applications that still hold a plaintext secret sign fine; they are
listed as skipped and left alone. Switching an application to RS256 changes how
its relying party has to verify ID tokens, so the command lets the operator
pick what to do:

  --migrate  switch the applications to RS256 (requires OIDC_RSA_PRIVATE_KEY)
  --notify   email the owner: the user for user-owned applications, the
             organization admins for organization-owned ones. The text says
             whether the application was switched or still needs switching.

Either flag, or both. Without either, the applications are only listed.
With both, the owner is mailed first and an application is switched only once
at least one owner mail went out; one that could not be notified (no active
owner with an email address, or every send failed) stays on HS256, so a re-run
finds it again.

Dry run by default; --commit applies the changes and sends the mail. Mail
honors MAIL_DEBUG. Applications nobody could be notified about, and failed
sends to individual owners of an application that was notified, are logged,
the run continues, and the command exits with an error listing them and what
to do next. A dry run lists the applications that would not be notified and
exits normally. Nothing records who was notified, so re-running --notify
without --migrate mails the same owners again.

Usage:
  manage pdb_oauth_hs256 [--migrate] [--notify] [--commit]
"""

import logging

from django.conf import settings
from django.core.management.base import CommandError
from django.db.models import Max
from django.template import loader
from django.urls import reverse
from oauth2_provider.models import (
    get_access_token_model,
    get_application_model,
    get_id_token_model,
)
from oauth2_provider.settings import oauth2_settings

from mainsite.oauth2.validators import hs256_signing_unavailable
from peeringdb_server.management.commands.pdb_base_command import PeeringDBBaseCommand

logger = logging.getLogger(__name__)


class Command(PeeringDBBaseCommand):
    help = "List, migrate to RS256 and/or notify owners of HS256 OAuth applications (#2055)."

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--migrate",
            action="store_true",
            help="Switch HS256 applications to RS256.",
        )
        parser.add_argument(
            "--notify",
            action="store_true",
            help="Email the owners of HS256 applications.",
        )

    def handle(self, *args, **options):
        self.commit = options.get("commit")
        migrate = options.get("migrate")
        notify = options.get("notify")
        unnotified = []
        missed = []

        Application = get_application_model()

        if migrate and not oauth2_settings.OIDC_RSA_PRIVATE_KEY:
            raise CommandError(
                "--migrate needs OIDC_RSA_PRIVATE_KEY, RS256 cannot sign without it."
            )

        applications = (
            Application.objects.filter(algorithm=Application.HS256_ALGORITHM)
            .select_related("org", "user")
            .order_by("id")
        )

        affected = 0
        for application in applications:
            self.log(
                f"OAuth application {application.id} '{application.name}' "
                f"client_id={application.client_id} owner={self.owner(application)} "
                f"last_access_token={self.last_created(get_access_token_model(), application)} "
                f"last_id_token={self.last_created(get_id_token_model(), application)}"
            )

            if not hs256_signing_unavailable(application):
                self.log("  skipped, its plaintext client secret can still sign HS256")
                continue

            affected += 1
            notified = True
            if notify:
                notified, failed_sends = self.notify(application, migrated=migrate)
                if not notified:
                    unnotified.append(str(application.id))
                missed.extend(failed_sends if notified else [])
            if migrate and notified:
                self.migrate(application)
            elif migrate:
                self.log("  not switched, no owner was notified")

        self.log(f"{affected} HS256 OAuth application(s) that cannot sign ID tokens")
        self.report(unnotified, missed, migrate)

    def report(self, unnotified, missed, migrate):
        """
        Tells the operator what was not notified and what to do about it;
        a committed run with anything to report exits with an error
        """

        problems = []
        if unnotified and not self.commit:
            problems.append(
                "Would not be notified (no active owner with an email address): "
                f"application(s) {', '.join(unnotified)}."
                + (" They would stay on HS256." if migrate else "")
                + " Fix the owner's email address (the user, or the "
                "organization's admins) before running with --commit, or switch "
                "the application to RS256 in /cp."
            )
        elif unnotified:
            problems.append(
                "Not notified (no active owner with an email address, or every send "
                f"failed): application(s) {', '.join(unnotified)}."
                + (" They were left on HS256." if migrate else "")
                + " Fix the owner's email address (the user, or the "
                "organization's admins) or the mail problem and "
                + (
                    "re-run, or switch the application to RS256 in /cp."
                    if migrate
                    else "contact them by hand or switch the application to RS256 "
                    "in /cp, a re-run mails every owner again."
                )
            )
        if missed:
            problems.append(
                f"Notified, but these sends failed: {', '.join(missed)}. "
                + (
                    "Those applications were switched to RS256, so a re-run "
                    "won't find them: contact these owners by hand."
                    if migrate
                    else "Contact these owners by hand, a re-run mails every "
                    "owner again."
                )
            )

        if not problems:
            return
        if not self.commit:
            for problem in problems:
                self.log(problem)
            return
        raise CommandError(" ".join(problems))

    def last_created(self, model, application):
        return model.objects.filter(application_id=application.id).aggregate(
            last=Max("created")
        )["last"]

    def owner(self, application):
        if application.org_id:
            return f"org {application.org_id} '{application.org.name}'"
        if application.user_id:
            return f"user {application.user_id} '{application.user.username}'"
        return "none"

    def recipients(self, application):
        if application.org_id:
            users = application.org.admin_usergroup.user_set.all()
        elif application.user_id:
            users = [application.user]
        else:
            users = []
        return [user for user in users if user.is_active and user.email]

    def migrate(self, application):
        self.log(f"  switch to {application.RS256_ALGORITHM}")
        if not self.commit:
            return
        application.algorithm = application.RS256_ALGORITHM
        application.save(update_fields=["algorithm"])

    def notify(self, application, migrated):
        """
        Mails the owners

        Returns whether at least one mail went out (or, in a dry run, would go
        out) and the recipients whose send failed
        """

        recipients = self.recipients(application)
        if not recipients:
            self.log("  no owner with an email address to notify")
            return False, []

        message = loader.get_template("email/notify-oauth-app-hs256.txt").render(
            {
                "application": application,
                "migrated": migrated,
                "application_url": settings.BASE_URL
                + reverse("oauth2_provider:detail", args=(application.id,)),
                "jwks_url": settings.BASE_URL + reverse("oauth2_provider:jwks-info"),
                "support_email": settings.DEFAULT_FROM_EMAIL,
            }
        )
        subject = "PeeringDB OAuth application: HS256 is no longer supported"

        sent = False
        failed_sends = []
        for user in recipients:
            self.log(f"  notify {user.username} <{user.email}>")
            if not self.commit:
                sent = True
                continue
            try:
                user.email_user(subject, message)
                sent = True
            except Exception:
                logger.exception(
                    "HS256 notification for OAuth application %s to %s failed",
                    application.id,
                    user.email,
                )
                failed_sends.append(f"application {application.id} -> {user.email}")
        return sent, failed_sends
