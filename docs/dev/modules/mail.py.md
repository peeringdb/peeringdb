Generated from mail.py on 2026-08-15 04:17:12.049436

# peeringdb_server.mail

Utility functions for emailing users and admin staff.

# Functions
---

## _mail_network_contacts
`def _mail_network_contacts(net, recipients, subject, template, context, debug_note)`

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

---
## mail_admins_with_from
`def mail_admins_with_from(subj, msg, from_addr, fail_silently=False, connection=None, html_message=None)`

Mail admins but allow specifying of from address.

---
## mail_network_irr_as_set_flagged
`def mail_network_irr_as_set_flagged(net, recipients, reason, deadline=None, previous=None, found_in=None, remaining=None)`

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

---
## mail_network_rir_status_flagged
`def mail_network_rir_status_flagged(net, recipients, days_until_deletion)`

Notify a network's contacts that the network has been flagged for
automatic removal because its ASN is no longer registered as assigned by
its RIR/NIR (GH #1942).

Arguments:
    - net <Network>: the flagged network
    - recipients <list>: list of contact email addresses
    - days_until_deletion <int>: KEEP_RIR_STATUS, the number of days the
      network is kept after being flagged before it is removed

---
## mail_username_retrieve
`def mail_username_retrieve(email, secret)`

Send an email to the specified email address containing
the url for username retrieval.

Arguments:
    - email <str>
    - secret <str>: username retrieval secret in the user's session

---
## mail_users_entity_merge
`def mail_users_entity_merge(users_source, users_target, entity_source, entity_target)`

Notify the users specified in users_source that their entity (entity_source) has
been merged with another entity (entity_target).

Notify the users specified in users_target that an entity has ben merged into their
entity (entity_target).

Arguments:
    - users_source <list>: list of User objects
    - users_target <list>: list of User objects
    - entity_source <HandleRef>: handleref object, entity that was merged
    - entity_target <HandleRef>: handleref object, entity that was merged into

---
