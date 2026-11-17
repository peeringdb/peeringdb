"""
Emoji detection for entity name fields (#2018).

Which characters count as emoji, and which entity fields must not contain
them. The validator and the strip helper that use these live in validators.
"""

import re

from django.conf import settings

# emoji are not allowed in entity name fields (#2018). To extend the rule to
# another field (e.g. "notes"), add it here: the API serializers, the admin
# forms and the pdb_strip_name_emoji backfill all read it. The control
# character check (#533) applies to the same fields.
EMOJI_FREE_TAGS = ("org", "fac", "ix", "net", "carrier", "campus")
EMOJI_FREE_FIELDS = ("name", "aka", "name_long")

# pictographic code points (#2018): every supplementary-plane symbol block
# (U+1F000-1FAFF: emoticons, pictographs, flags, skin tones), the range
# reserved for future emoji (U+1FC00-1FFFD), the Misc Symbols and Dingbats
# blocks, and the remaining BMP characters Unicode marks as emoji.
# A superset of Unicode's Emoji property, except # * 0-9 and (c) (r) (tm);
# the last three are added by the EMOJI_INCLUDE_TRADEMARK_SIGNS setting.
#
# Ranges include unassigned code points, so emoji Unicode adds later inside
# them are rejected without a code change. U+1FC00-1FFFD holds no characters
# yet: Unicode pre-labels it Extended_Pictographic so future emoji can go
# there. U+1FB00-1FBFF (Symbols for Legacy Computing) is skipped on purpose,
# it is not pictographic. Source:
# https://www.unicode.org/Public/UCD/latest/ucd/emoji/emoji-data.txt
_EMOJI_CHARS = (
    "\U0001f000-\U0001faff\U0001fc00-\U0001fffd"
    "\u2600-\u27bf"
    "\u203c\u2049\u2139\u2194-\u2199\u21a9\u21aa\u231a\u231b\u2328\u23cf"
    "\u23e9-\u23f3\u23f8-\u23fa\u24c2\u25aa\u25ab\u25b6\u25c0\u25fb-\u25fe"
    "\u2934\u2935\u2b05-\u2b07\u2b1b\u2b1c\u2b50\u2b55\u3030\u303d\u3297\u3299"
    # combining keycap (digit + U+20E3) and tag characters (subdivision flags)
    "\u20e3\U000e0020-\U000e007f"
)
# the zero-width joiner and variation selectors glue multi-character emoji
# together (family sequences, red heart = U+2764 U+FE0F). They are only
# matched next to an emoji, since the joiner is also used in Indic scripts.
# At most one glue character may lead (the U+FE0F of a keycap): an unbounded
# lead makes every search quadratic on a long run of glue characters.
_EMOJI_GLUE = "\u200d\ufe0e\ufe0f"
_TRADEMARK_SIGNS = "\u00a9\u00ae\u2122"


def _emoji_pattern(chars: str) -> re.Pattern:
    return re.compile(f"[{_EMOJI_GLUE}]?(?:[{chars}][{_EMOJI_GLUE}]*)+")


EMOJI = _emoji_pattern(_EMOJI_CHARS)
EMOJI_WITH_TRADEMARK_SIGNS = _emoji_pattern(_EMOJI_CHARS + _TRADEMARK_SIGNS)


def emoji_regex() -> re.Pattern:
    """
    The emoji pattern in effect: EMOJI, plus (c) (r) (tm) when the
    EMOJI_INCLUDE_TRADEMARK_SIGNS setting is on.
    """
    if settings.EMOJI_INCLUDE_TRADEMARK_SIGNS:
        return EMOJI_WITH_TRADEMARK_SIGNS
    return EMOJI


def emoji_free_fields(model) -> list[str]:
    """
    The EMOJI_FREE_FIELDS that `model` has, or [] when the model is not one
    of the EMOJI_FREE_TAGS entities (#2018).
    """
    tag = getattr(getattr(model, "HandleRef", None), "tag", None)
    if tag not in EMOJI_FREE_TAGS:
        return []
    names = {field.name for field in model._meta.get_fields()}
    return [field for field in EMOJI_FREE_FIELDS if field in names]
