"""A validating recursive-descent parser for glob patterns.

Grammar, informally:

    pattern    := "!"? sequence
    sequence   := atom*
    atom       := literal | "*" | "**" | "?" | charclass | brace
    charclass  := "[" "!"? item+ "]"
    item       := char | char "-" char
    brace      := "{" sequence ("," sequence){2,} "}"

A couple of rules are deliberately stricter than a shell would enforce,
because this is meant to catch mistakes, not just accept whatever a
shell happens to tolerate:

  - "**" must be its own path segment ("a/**/b" is fine, "a/**b" is not).
  - a brace expansion needs at least two comma-separated alternatives;
    "{foo}" is almost always a missing comma, not intentional literal text.

Every raised error is a GlobSyntaxError with the exact line/column of
the problem, and every AST node records the column it started at so
that later passes (like the globstar check) can point at the right
place too.
"""

from dataclasses import dataclass

from .errors import GlobSyntaxError

LITERAL_ESCAPE_CHARS = set('*?[]{}\\')


@dataclass
class Literal:
    value: str
    pos: int


@dataclass
class Star:
    pos: int


@dataclass
class Globstar:
    pos: int


@dataclass
class Question:
    pos: int


@dataclass
class CharClass:
    negated: bool
    items: list  # each item is a one-char str, or a (low, high) tuple for a range
    pos: int


@dataclass
class Brace:
    alternatives: list  # list of list[node]
    pos: int


@dataclass
class Pattern:
    raw: str
    negated: bool
    parts: list  # flat list of nodes; Literal('/') marks a path separator
    line: int


@dataclass
class FileParseResult:
    patterns: list  # list[Pattern]
    errors: list  # list[GlobSyntaxError]


def _parse_sequence(text: str, pos: int, line: int, in_brace: bool):
    length = len(text)
    parts = []
    while pos < length:
        ch = text[pos]
        if in_brace and ch in ',}':
            break
        if ch == '\\':
            if pos + 1 >= length:
                raise GlobSyntaxError(
                    "escape character '\\' at end of pattern with nothing to escape",
                    line, pos + 1, text,
                )
            parts.append(Literal(text[pos + 1], pos))
            pos += 2
        elif ch == '*':
            if pos + 1 < length and text[pos + 1] == '*':
                parts.append(Globstar(pos))
                pos += 2
            else:
                parts.append(Star(pos))
                pos += 1
        elif ch == '?':
            parts.append(Question(pos))
            pos += 1
        elif ch == '[':
            node, pos = _parse_charclass(text, pos, line)
            parts.append(node)
        elif ch == '{':
            node, pos = _parse_brace(text, pos, line)
            parts.append(node)
        elif ch == ']':
            raise GlobSyntaxError("unmatched ']' with no opening '['", line, pos + 1, text)
        elif ch == '}':
            raise GlobSyntaxError("unmatched '}' with no opening '{'", line, pos + 1, text)
        else:
            parts.append(Literal(ch, pos))
            pos += 1
    return parts, pos


def _parse_charclass(text: str, pos: int, line: int):
    start = pos
    length = len(text)
    pos += 1  # skip '['
    negated = False
    if pos < length and text[pos] in '!^':
        negated = True
        pos += 1

    items = []
    while pos < length and text[pos] != ']':
        ch = text[pos]
        if pos + 2 < length and text[pos + 1] == '-' and text[pos + 2] != ']':
            lo, hi = ch, text[pos + 2]
            if lo > hi:
                raise GlobSyntaxError(
                    f"invalid character range '{lo}-{hi}': start is after end",
                    line, pos + 1, text, 3,
                )
            items.append((lo, hi))
            pos += 3
        else:
            items.append(ch)
            pos += 1

    if pos >= length:
        raise GlobSyntaxError(
            "unterminated character class, expected closing ']'",
            line, start + 1, text, pos - start,
        )
    if not items:
        raise GlobSyntaxError(
            "empty character class '[]' matches nothing",
            line, start + 1, text, pos - start + 1,
        )

    pos += 1  # skip ']'
    return CharClass(negated, items, start), pos


def _parse_brace(text: str, pos: int, line: int):
    start = pos
    length = len(text)
    pos += 1  # skip '{'
    alternatives = []
    alt_start = pos
    while True:
        parts, pos = _parse_sequence(text, pos, line, in_brace=True)
        if pos >= length:
            raise GlobSyntaxError(
                "unterminated brace expansion, expected closing '}'",
                line, start + 1, text, pos - start,
            )
        if not parts:
            raise GlobSyntaxError(
                "empty alternative inside brace expansion",
                line, alt_start + 1, text, max(1, pos - alt_start),
            )
        alternatives.append(parts)
        ch = text[pos]
        if ch == ',':
            pos += 1
            alt_start = pos
            continue
        pos += 1  # skip '}'
        break

    if len(alternatives) < 2:
        raise GlobSyntaxError(
            "brace expansion needs at least two comma-separated alternatives "
            "(a single one is almost always a missing comma)",
            line, start + 1, text, pos - start,
        )
    return Brace(alternatives, start), pos


def _split_segments(parts):
    segments = []
    current = []
    for node in parts:
        if isinstance(node, Literal) and node.value == '/':
            segments.append(current)
            current = []
        else:
            current.append(node)
    segments.append(current)
    return segments


def _check_globstar_placement(parts, line: int, text: str):
    for segment in _split_segments(parts):
        globstars = [node for node in segment if isinstance(node, Globstar)]
        if globstars and len(segment) != 1:
            bad = globstars[0]
            raise GlobSyntaxError(
                "'**' must occupy its whole path segment, e.g. 'a/**/b' not 'a/**b'",
                line, bad.pos + 1, text, 2,
            )
    for node in parts:
        if isinstance(node, Brace):
            for alternative in node.alternatives:
                _check_globstar_placement(alternative, line, text)


def parse_line(raw_line: str, line_no: int = 1):
    """Parse one line of a pattern file.

    Returns a Pattern, or None if the line is blank or a '#' comment.
    Raises GlobSyntaxError on malformed input.
    """
    text = raw_line.rstrip('\r\n')
    if text.strip() == '' or text.strip().startswith('#'):
        return None

    negated = text.startswith('!')
    body_start = 1 if negated else 0
    if negated and len(text) == 1:
        raise GlobSyntaxError("negation '!' with no pattern after it", line_no, 1, text)

    parts, _ = _parse_sequence(text, body_start, line_no, in_brace=False)
    if not parts:
        raise GlobSyntaxError("pattern is empty", line_no, body_start + 1, text)

    _check_globstar_placement(parts, line_no, text)
    return Pattern(raw=text, negated=negated, parts=parts, line=line_no)


def parse_file(text: str) -> FileParseResult:
    """Parse a whole file of patterns, one per line.

    Unlike parse_line, this does not stop at the first bad line: it
    collects every error so a caller can report them all at once.
    """
    patterns = []
    errors = []
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        try:
            pattern = parse_line(raw_line, line_no)
        except GlobSyntaxError as exc:
            errors.append(exc)
            continue
        if pattern is not None:
            patterns.append(pattern)
    return FileParseResult(patterns=patterns, errors=errors)
