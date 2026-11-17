Generated from emoji.py on 2026-11-17 18:01:18.661144

# peeringdb_server.emoji

Emoji detection for entity name fields (#2018).

Which characters count as emoji, and which entity fields must not contain
them. The validator and the strip helper that use these live in validators.

# Functions
---

## emoji_free_fields
`def emoji_free_fields(model)`

The EMOJI_FREE_FIELDS that `model` has, or [] when the model is not one
of the EMOJI_FREE_TAGS entities (#2018).

---
## emoji_regex
`def emoji_regex()`

The emoji pattern in effect: EMOJI, plus (c) (r) (tm) when the
EMOJI_INCLUDE_TRADEMARK_SIGNS setting is on.

---
