"""
#2040: hold the AS-SET editor's client-side name grammar to the server's.

This repo has no JS test coverage, which is how #2040 shipped: the editor
rejected ASN-first names (AS5405:AS-INTERDOTLINK) that validate_irr_as_set
has always accepted. The grammar is one regex literal per static bundle; these
tests extract it and assert it accepts exactly what the server accepts.
"""

import pathlib
import re

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import override_settings

import peeringdb_server
from peeringdb_server.validators import validate_irr_as_set

pytestmark = pytest.mark.django_db

STATIC = pathlib.Path(peeringdb_server.__file__).parent / "static"
BUNDLES = [STATIC / "peeringdb.js", STATIC / "peeringdb_ui_next.js"]

_GRAMMAR_RE = re.compile(r"^\s*const IRR_NAME_RE = /(?P<pattern>.+)/i;$", re.MULTILINE)

# The pre-#2040 literal. A second inline copy would still gate the editor while
# sailing past the parity check below, which only sees the named constant.
SUPERSEDED_LITERAL = "/^(AS-[a-zA-Z0-9_:-]+|AS[0-9]+)$/i"

# The malformed-value hint. Its examples are a save-path claim: #1973's
# IRR_AS_SET_REQUIRE_SOURCE rejects unprefixed tokens on a changed value, so a
# bare example here is #2040 again -- the editor endorsing what save refuses.
_HINT_RE = re.compile(r'gettext\("Not a valid AS-SET name\.(?P<body>[^"]*)"\)')

# Examples inside that hint. The SOURCE:: prefix must stay optional: a bare
# example is the bug, so a SOURCE::NAME-only pattern finds nothing to fail on.
_HINT_EXAMPLE_RE = re.compile(r"\b(?:[A-Za-z0-9-]+::)?AS[0-9A-Za-z_:-]*")

# RPSL class names ("use an AS-SET name such as ...") are nouns, not examples,
# but are shaped like unprefixed ones.
_HINT_PROSE_TERMS = {"AS-SET", "AS-SETS", "RS-SET", "RS-SETS"}

# Rather than guess at the JS/Python regex overlap, keep the pattern inside the
# subset with no divergence at all: no escapes (\d, \p{...}, \uXXXX) and no
# named groups ((?<x>) vs (?P<x>)). Widening it is fine, but deliberately.
UNTRANSLATABLE = {
    "\\": "escape sequences",
    "(?<": "named groups or lookbehind",
}

# Expected verdicts are deliberately absent: each name is put to
# validate_irr_as_set at run time. A hand-maintained expectation column would
# just be a third grammar to keep in sync.
NAMES = [
    # plain and hierarchical set names
    "AS-RIPENCC",
    "AS-FOO_BAR",
    "AS-FOO-AS-BAR",
    "AS-123",
    "AS-CUST:AS5405",
    "AS-FOO:AS-BAR",
    "AS-A:AS-B:AS-C",
    "AS-FOO:AS5406",
    "AS-FOO:AS-BAR:AS5405",
    # bare ASNs
    "AS5405",
    "AS0",
    # ASN-first hierarchical names -- the #2040 regression
    "AS5405:AS-INTERDOTLINK",
    "AS5405:AS-CUST:AS-SUB",
    "AS5405:AS-A:AS-B",
    "AS5405:AS5406:AS-X",
    # no component is a set name
    "AS5405:AS5406",
    # deeper than DATA_QUALITY_MAX_IRR_DEPTH
    "AS-A:AS-B:AS-C:AS-D",
    "AS5405:AS-A:AS-B:AS-C",
    # malformed
    "AS-FOO:",
    ":AS-FOO",
    "AS-FOO::AS-BAR",
    "AS-",
    "AS",
    "FOO",
    "AS-FOO BAR",
    "AS12x",
    "AS-FOO.BAR",
    "AS_FOO",
    # route-sets, which the editor refuses earlier and the server refuses on save
    "RS-FOO",
    "RS-A:RS-B",
    "AS-FOO:RS-BAR",
    "AS5405:RS-FOO",
    # case is normalized on both sides
    "as-ripencc",
    "as5405:as-interdotlink",
]

# Asserted explicitly so the parity check cannot pass by having both sides
# reject everything.
REGRESSION_NAMES = [
    "AS5405:AS-INTERDOTLINK",
    "AS5405:AS-CUST:AS-SUB",
    "AS5405:AS-A:AS-B",
]


def js_grammar(path):
    """The IRR_NAME_RE literal's pattern, as written in path."""
    match = _GRAMMAR_RE.search(path.read_text())
    assert match, f"no const IRR_NAME_RE = /.../i; line in {path.name}"
    return match.group("pattern")


def server_accepts_value(value):
    """Whether validate_irr_as_set accepts value exactly as written."""
    try:
        validate_irr_as_set(value, strict=True)
    except (ValidationError, ValueError):
        return False
    return True


def server_accepts(name):
    """
    Whether validate_irr_as_set accepts name as a set name.

    The RIPE:: prefix satisfies the #1973 source-prefix rule so it cannot be
    what rejects the value, leaving the per-name shape rules -- all the editor's
    grammar models -- as the only things under test.

    IRR_AS_SET_REQUIRE_SOURCE is pinned True by the callers rather than taken
    from the test settings: IRR_NAME_RE has no RS- alternative, so the route-set
    rows in NAMES only agree with the server because the RS- rejection at
    validators.py is gated on that setting. Flipped off, this would fail as a
    grammar mismatch with the grammar unchanged, pointing at the regex instead
    of at hasRouteSet(), which is the editor's actual route-set gate.
    """
    return server_accepts_value(f"RIPE::{name}")


def hint_examples(path):
    """The example values the malformed-value hint recommends, in path."""
    match = _HINT_RE.search(path.read_text())
    assert match, f"no malformed-value hint gettext() call in {path.name}"
    return [
        example
        for example in _HINT_EXAMPLE_RE.findall(match.group("body"))
        if example.upper() not in _HINT_PROSE_TERMS
    ]


@pytest.fixture(scope="module")
def grammar():
    return re.compile(js_grammar(BUNDLES[0]), re.IGNORECASE)


def test_bundles_carry_the_same_grammar():
    patterns = {path.name: js_grammar(path) for path in BUNDLES}
    assert len(set(patterns.values())) == 1, patterns


@pytest.mark.parametrize("path", BUNDLES, ids=lambda p: p.name)
def test_grammar_has_no_second_copy(path):
    source = path.read_text()
    assert SUPERSEDED_LITERAL not in source
    assert source.count("IRR_NAME_RE.test(") == 2, (
        "completionToken and completionTokens are the two call sites"
    )


@pytest.mark.parametrize("path", BUNDLES, ids=lambda p: p.name)
def test_grammar_stays_in_the_shared_regex_subset(path):
    pattern = js_grammar(path)
    for token, what in UNTRANSLATABLE.items():
        assert token not in pattern, (
            f"{path.name}: {what} do not read identically in JS and Python"
        )


def test_grammar_caps_depth_at_the_configured_maximum(grammar):
    quantifiers = re.findall(r"\{0,(\d+)\}", grammar.pattern)
    assert len(quantifiers) == 1, quantifiers
    assert int(quantifiers[0]) + 1 == settings.DATA_QUALITY_MAX_IRR_DEPTH


@override_settings(IRR_AS_SET_VERIFY_EXISTENCE=False, IRR_AS_SET_REQUIRE_SOURCE=True)
@pytest.mark.parametrize("name", NAMES)
def test_grammar_agrees_with_validate_irr_as_set(grammar, name):
    assert bool(grammar.match(name)) is server_accepts(name)


@override_settings(IRR_AS_SET_VERIFY_EXISTENCE=False, IRR_AS_SET_REQUIRE_SOURCE=True)
@pytest.mark.parametrize("name", REGRESSION_NAMES)
def test_asn_first_hierarchical_names_are_accepted(grammar, name):
    assert grammar.match(name)
    assert server_accepts(name)


@override_settings(IRR_AS_SET_VERIFY_EXISTENCE=False, IRR_AS_SET_REQUIRE_SOURCE=True)
@pytest.mark.parametrize("path", BUNDLES, ids=lambda p: p.name)
def test_hint_examples_are_saveable(path):
    examples = hint_examples(path)
    assert examples, "the hint must recommend at least one example value"
    for example in examples:
        assert server_accepts_value(example), (
            f"{path.name}: hint recommends {example}, which the save path rejects"
        )
