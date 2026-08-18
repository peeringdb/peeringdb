"""
Utility functions for emailing users and admin staff.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.mail.message import EmailMultiAlternatives
from django.template import loader
from django.utils.html import strip_tags
from django.utils.translation import gettext_lazy as _
from django.utils.translation import override

if TYPE_CHECKING:
    from django.core.mail.backends.base import BaseEmailBackend

    from peeringdb_server.models import Network, Organization, User

logger = logging.getLogger(__name__)


def mail_sponsorship_admin(subj: str, msg: str) -> None:
    mail = EmailMultiAlternatives(
        f"{settings.EMAIL_SUBJECT_PREFIX}{subj}",
        strip_tags(msg),
        settings.SERVER_EMAIL,
        [settings.SPONSORSHIPS_EMAIL],
    )

    mail.send(fail_silently=False)


def mail_sponsorship_admin_merge(
    source_orgs: list[Organization], target_org: Organization
) -> None:
    msg = loader.get_template("email/notify-sponsorship-merge.txt").render(
        {"source_orgs": source_orgs, "target_org": target_org}
    )

    return mail_sponsorship_admin("Organization merge - sponsorship transfered", msg)


def mail_sponsorship_admin_merge_conflict(
    conflicting_orgs: list[Organization], target_org: Organization
) -> None:
    if target_org in conflicting_orgs:
        conflicting_orgs.remove(target_org)

    msg = loader.get_template("email/notify-sponsorship-merge-conflict.txt").render(
        {"orgs": conflicting_orgs, "target_org": target_org}
    )

    return mail_sponsorship_admin("Organization merge - sponsorship conflict", msg)


def mail_admins_with_from(
    subj: str,
    msg: str,
    from_addr: str,
    fail_silently: bool = False,
    connection: BaseEmailBackend | None = None,
    html_message: str | None = None,
) -> None:
    """
    Mail admins but allow specifying of from address.
    """

    if not settings.ADMINS:
        return

    # set plain text message
    strip_tags(msg)
    mail = EmailMultiAlternatives(
        f"{settings.EMAIL_SUBJECT_PREFIX}{subj}",
        msg,
        from_addr,
        [a[1] for a in settings.ADMINS],
        connection=connection,
    )

    # attach html message
    mail.attach_alternative(msg.replace("\n", "<br />\n"), "text/html")
    mail.send(fail_silently=fail_silently)


def mail_users_entity_merge(
    users_source: Iterable[User],
    users_target: Iterable[User],
    entity_source: Organization,
    entity_target: Organization,
) -> None:
    """
    Notify the users specified in users_source that their entity (entity_source) has
    been merged with another entity (entity_target).

    Notify the users specified in users_target that an entity has ben merged into their
    entity (entity_target).

    Arguments:
        - users_source <list>: list of User objects
        - users_target <list>: list of User objects
        - entity_source <HandleRef>: handleref object, entity that was merged
        - entity_target <HandleRef>: handleref object, entity that was merged into
    """
    msg = loader.get_template("email/notify-org-admin-merge.txt").render(
        {
            "entity_type_name": entity_source._meta.verbose_name.capitalize(),
            "entity_source": entity_source,
            "entity_target": entity_target,
            "entity_target_url": f"{settings.BASE_URL}/{entity_target.ref_tag}/{entity_target.id}",
            "support_email": settings.DEFAULT_FROM_EMAIL,
        }
    )

    for user in set([u for u in users_source] + [u for u in users_target]):
        # FIXME: why not have the `override` call in email_user in the first place?
        with override(user.locale):
            user.email_user(
                _("{} Merge Notification: {} -> {}").format(
                    entity_source._meta.verbose_name.capitalize(),
                    entity_source.name,
                    entity_target.name,
                ),
                msg,
            )


def _mail_network_contacts(
    net: Network,
    recipients: list[str],
    subject: str,
    template: str,
    context: dict[str, object],
    debug_note: str,
) -> None:
    """
    Render `template` and mail it to a network's contacts.

    Shared body of the network-contact outreach mails (RIR status #1942, irr_as_set
    #1973/#1974) so the MAIL_DEBUG guard exists once: in non-prod environments we
    never put real operator notifications on the wire.

    Arguments:
        - net <Network>: the network being notified
        - recipients <list>: contact email addresses; no mail is sent when empty
        - subject <str>: subject line, EMAIL_SUBJECT_PREFIX is prepended
        - template <str>: template path to render
        - context <dict>: extra context; `net` and `support_email` are added here
        - debug_note <str>: what to log instead of sending under MAIL_DEBUG
    """

    if not recipients:
        return

    msg = loader.get_template(template).render(
        {
            "net": net,
            "support_email": settings.DEFAULT_FROM_EMAIL,
            **context,
        }
    )

    if getattr(settings, "MAIL_DEBUG", False):
        logger.info(
            "MAIL_DEBUG set; not sending %s for AS%s to %s",
            debug_note,
            net.asn,
            recipients,
        )
        return

    mail = EmailMultiAlternatives(
        f"{settings.EMAIL_SUBJECT_PREFIX}{subject}",
        strip_tags(msg),
        settings.DEFAULT_FROM_EMAIL,
        recipients,
    )
    mail.attach_alternative(msg.replace("\n", "<br />\n"), "text/html")
    mail.send(fail_silently=False)


def mail_network_rir_status_flagged(
    net: Network, recipients: list[str], days_until_deletion: int
) -> None:
    """
    Notify a network's contacts that the network has been flagged for
    automatic removal because its ASN is no longer registered as assigned by
    its RIR/NIR (GH #1942).

    Arguments:
        - net <Network>: the flagged network
        - recipients <list>: list of contact email addresses
        - days_until_deletion <int>: KEEP_RIR_STATUS, the number of days the
          network is kept after being flagged before it is removed
    """

    _mail_network_contacts(
        net,
        recipients,
        _("AS{} flagged for removal from PeeringDB (RIR status)").format(net.asn),
        "email/notify-net-rir-status.txt",
        {"days_until_deletion": days_until_deletion},
        "RIR removal notification",
    )


def mail_network_irr_as_set_flagged(
    net: Network,
    recipients: list[str],
    reason: str,
    deadline: str | None = None,
    previous: str | None = None,
    found_in: list[str] | None = None,
    remaining: str | None = None,
) -> None:
    """
    Notify a network's contacts about an irr_as_set data-quality problem, or about
    a value PeeringDB disambiguated on their behalf (#1973 / #1974).

    Arguments:
        - net <Network>: the network whose irr_as_set is flagged
        - recipients <list>: contact email addresses
        - reason <str>: one of "unresolved" (not found in any registry),
          "ambiguous" (found in several registries, needs a SOURCE:: prefix),
          "placeholder" (generic AS-SET/RS-SET value with no useful identity),
          "route_set" (a route-set RS-* name, not accepted), "invalid" (does not
          pass the field's format rules at all), "multi_set" (more than one
          set name, capped by #1974), "auto_prefixed" (the cleanup added the
          registry prefix itself because the name resolved to exactly one
          registry -- a disclosure, not a request), "moved" (the object is no
          longer in the registry the value names but does exist in another) or
          "gone" (the object has disappeared from every registry we check)
        - deadline <str|None>: human-readable enforcement date for the
          "multi_set" nudge; ignored for the other reasons
        - previous <str|None>: the value before PeeringDB changed it; only the
          "auto_prefixed" notice uses it, because the template renders
          net.irr_as_set, which by then is the new value
        - found_in <list|None>: registries that do hold the object; only the
          "moved" notice uses it, and it is what makes that mail actionable
          rather than alarming
        - remaining <str|None>: for "auto_prefixed" only -- the outreach reason
          for tokens the cleanup could NOT resolve -- it prefixes per token, so a
          mixed value comes back partly fixed. Set, it replaces the notice's "no
          action is needed" with what the operator still has to do, which is why
          a partly-fixed value needs no second mail. It is the highest-ranked
          reason, not a count: more than one token can be left over, so neither the
          subject nor the body claims there is exactly one
    """

    subjects = {
        "unresolved": _("AS{} IRR as-set not found in any registry").format(net.asn),
        "ambiguous": _("AS{} IRR as-set is ambiguous — add a source prefix").format(
            net.asn
        ),
        "placeholder": _("AS{} IRR as-set is a generic placeholder").format(net.asn),
        "route_set": _("AS{} IRR as-set uses a route-set name (not accepted)").format(
            net.asn
        ),
        "invalid": _("AS{} IRR as-set is improperly formatted").format(net.asn),
        "multi_set": _("AS{} lists multiple IRR as-sets").format(net.asn),
        "auto_prefixed": _(
            "AS{} IRR as-set updated by PeeringDB — source prefix added"
        ).format(net.asn),
        # a partly-fixed value is still the operator's to finish, so the subject
        # asks rather than merely informing. Not "one entry": several tokens can be
        # left over, and `remaining` carries only the highest-ranked reason.
        "auto_prefixed_partial": _(
            "AS{} IRR as-set partly updated by PeeringDB — an entry still needs you"
        ).format(net.asn),
        "moved": _("AS{} IRR as-set has moved to another registry").format(net.asn),
        "gone": _("AS{} IRR as-set no longer exists").format(net.asn),
    }

    # the partial auto-prefix notice is the same template branch with a different
    # ending, but a different subject -- it is a request, not just a disclosure
    subject_key = (
        "auto_prefixed_partial" if reason == "auto_prefixed" and remaining else reason
    )

    _mail_network_contacts(
        net,
        recipients,
        subjects.get(subject_key, _("AS{} IRR as-set needs attention").format(net.asn)),
        "email/notify-net-irr-as-set.txt",
        {
            "reason": reason,
            "deadline": deadline,
            "previous": previous,
            # pre-joined: the template's blocktrans cannot call a filter on a list
            "found_in": ", ".join(found_in) if found_in else "",
            "remaining": remaining,
        },
        f"irr_as_set notification ({subject_key})",
    )


def mail_username_retrieve(email: str, secret: str) -> None:
    """
    Send an email to the specified email address containing
    the url for username retrieval.

    Arguments:
        - email <str>
        - secret <str>: username retrieval secret in the user's session
    """

    msg = loader.get_template("email/username-retrieve.txt").render(
        {
            "email": email,
            "secret": secret,
            "username_retrieve_url": f"{settings.BASE_URL}/username-retrieve/complete?secret={secret}",
        }
    )

    subject = "PeeringDB username retrieval"

    mail = EmailMultiAlternatives(subject, msg, settings.DEFAULT_FROM_EMAIL, [email])
    mail.send(fail_silently=False)
