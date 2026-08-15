"""
Tests for the shared network-contact outreach mailer (mail._mail_network_contacts)
and the #1973/#1974 irr_as_set notification built on it.

The RIR-status mail (GH #1942) shares the same body; its own content tests live in
tests/test_pdb_rir_status.py and cover the other side of the extraction.
"""

import pytest
from django.core import mail as django_mail
from django.test import override_settings

from peeringdb_server.mail import (
    mail_network_irr_as_set_flagged,
    mail_network_rir_status_flagged,
)
from peeringdb_server.models import Network, Organization

pytestmark = pytest.mark.django_db


@pytest.fixture
def net(db):
    org = Organization.objects.create(name="Test Org", status="ok")
    return Network.objects.create(
        name="Test Network", asn=64496, irr_as_set="AS-FOO", status="ok", org=org
    )


@override_settings(MAIL_DEBUG=False)
@pytest.mark.parametrize(
    "reason,subject_fragment,body_fragment",
    [
        ("unresolved", "not found in any registry", "could not be found"),
        ("ambiguous", "ambiguous", "more than one IRR registry"),
        ("placeholder", "generic placeholder", "generic placeholder"),
        ("route_set", "route-set", "route-set"),
        ("invalid", "improperly formatted", "not a valid AS-SET reference"),
        ("multi_set", "lists multiple irr as-sets", "more than one IRR AS-SET"),
        (
            "auto_prefixed",
            "source prefix added",
            "PeeringDB has added the IRR source prefix",
        ),
        ("moved", "moved to another registry", "no longer in the IRR registry"),
        ("gone", "no longer exists", "could no longer be found"),
    ],
)
def test_irr_as_set_mail_renders_each_reason(
    net, reason, subject_fragment, body_fragment
):
    django_mail.outbox = []
    mail_network_irr_as_set_flagged(net, ["tech@example.com"], reason)

    assert len(django_mail.outbox) == 1
    message = django_mail.outbox[0]
    assert subject_fragment in message.subject.lower()
    assert body_fragment in message.body
    assert "AS64496" in message.subject
    assert net.view_url in message.body
    # every reason gets the HTML alternative the shared body attaches
    assert any(
        content_type == "text/html" for _content, content_type in message.alternatives
    )


@override_settings(MAIL_DEBUG=False)
def test_irr_as_set_mail_multi_set_cites_deadline(net):
    django_mail.outbox = []
    mail_network_irr_as_set_flagged(
        net, ["tech@example.com"], "multi_set", deadline="March 01, 2027"
    )
    assert "March 01, 2027" in django_mail.outbox[0].body


@override_settings(MAIL_DEBUG=False)
def test_irr_as_set_mail_auto_prefixed_cites_previous_value(net):
    # the template renders net.irr_as_set, which is already the NEW value by send
    # time, so the notice has to carry the old one explicitly to be intelligible
    django_mail.outbox = []
    mail_network_irr_as_set_flagged(
        net, ["tech@example.com"], "auto_prefixed", previous="AS-EXAMPLE"
    )
    body = django_mail.outbox[0].body
    assert "Previous value:" in body
    assert "AS-EXAMPLE" in body


@override_settings(MAIL_DEBUG=False)
@pytest.mark.parametrize(
    "remaining,fragment",
    [
        ("ambiguous", "exists in more than one IRR registry"),
        ("unresolved", "could not be found in any IRR registry"),
        ("placeholder", "generic placeholder such as AS-SET"),
        ("route_set", "route-set (an RS-... name)"),
    ],
)
def test_irr_as_set_mail_partial_auto_prefix_names_what_is_left(
    net, remaining, fragment
):
    """
    The cleanup prefixes per token, so a mixed value comes back partly fixed. The notice
    then has to drop "no action is needed" and say what the operator still owes —
    every reason a token can be left behind gets its own sentence.
    """
    django_mail.outbox = []
    mail_network_irr_as_set_flagged(
        net,
        ["tech@example.com"],
        "auto_prefixed",
        previous="AS-EXAMPLE AS-OTHER",
        remaining=remaining,
    )

    message = django_mail.outbox[0]
    assert "still needs you" in message.subject
    assert "No action is needed" not in message.body
    assert fragment in message.body
    # the disclosure half survives: what changed, and from what
    assert "PeeringDB has added the IRR source prefix" in message.body
    assert "AS-EXAMPLE AS-OTHER" in message.body


@override_settings(MAIL_DEBUG=False)
def test_irr_as_set_mail_full_auto_prefix_keeps_no_action_needed(net):
    """The fully-fixed case must not inherit the request wording."""
    django_mail.outbox = []
    mail_network_irr_as_set_flagged(
        net, ["tech@example.com"], "auto_prefixed", previous="AS-EXAMPLE"
    )

    message = django_mail.outbox[0]
    assert "No action is needed" in message.body
    assert "still needs you" not in message.subject
    assert "still needs you" not in message.body


@override_settings(MAIL_DEBUG=False)
def test_irr_as_set_mail_moved_names_the_registries_that_hold_it(net):
    # what makes the moved notice actionable instead of alarming: the operator is
    # told where the object actually is, not that it does not exist
    django_mail.outbox = []
    mail_network_irr_as_set_flagged(
        net, ["tech@example.com"], "moved", found_in=["RIPE", "RADB"]
    )
    body = django_mail.outbox[0].body
    assert "We did find it in: RIPE, RADB" in body
    assert "update the value in PeeringDB to name that registry" in body


@override_settings(MAIL_DEBUG=False)
def test_irr_as_set_mail_moved_without_found_in_still_reads(net):
    # the moved copy must not depend on found_in being populated -- a caller that
    # omits it should still get a sentence that tells the operator what to do
    django_mail.outbox = []
    mail_network_irr_as_set_flagged(net, ["tech@example.com"], "moved")
    body = django_mail.outbox[0].body
    assert "We did find it in" not in body
    assert "name the registry the object now belongs to" in body


@override_settings(MAIL_DEBUG=False)
def test_irr_as_set_mail_gone_does_not_claim_a_registry(net):
    # the gone notice must never render an empty "we did find it in:" clause
    django_mail.outbox = []
    mail_network_irr_as_set_flagged(net, ["tech@example.com"], "gone")
    body = django_mail.outbox[0].body
    assert "We did find it in" not in body
    assert "could no longer be found in any of the IRR registries" in body


@override_settings(MAIL_DEBUG=False)
def test_irr_as_set_mail_unknown_reason_falls_back(net):
    django_mail.outbox = []
    mail_network_irr_as_set_flagged(net, ["tech@example.com"], "something-new")
    assert "needs attention" in django_mail.outbox[0].subject.lower()


def test_irr_as_set_mail_no_recipients_is_a_noop(net):
    django_mail.outbox = []
    mail_network_irr_as_set_flagged(net, [], "ambiguous")
    assert django_mail.outbox == []


@override_settings(MAIL_DEBUG=True)
@pytest.mark.parametrize(
    "send",
    [
        lambda net: mail_network_irr_as_set_flagged(
            net, ["tech@example.com"], "ambiguous"
        ),
        lambda net: mail_network_rir_status_flagged(net, ["tech@example.com"], 1),
    ],
    ids=["irr_as_set", "rir_status"],
)
def test_mail_debug_guard_covers_every_outreach_path(net, send):
    # the guard lives once, in the shared body -- both outreach mails must honour
    # it so no real operator notification goes out on beta
    django_mail.outbox = []
    send(net)
    assert django_mail.outbox == []
