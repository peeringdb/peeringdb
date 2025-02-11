Generated from mail.py on 2025-02-11 10:26:48.481231

# peeringdb_server.mail

Utility functions for emailing users and admin staff.

# Functions
---

## mail_admins_with_from
`def mail_admins_with_from(subj, msg, from_addr, fail_silently=False, connection=None, html_message=None)`

Mail admins but allow specifying of from address.

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
