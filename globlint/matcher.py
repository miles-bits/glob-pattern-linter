"""Compiles a parsed Pattern into something that can test paths against it.

The AST already has everything needed for this; the work here is just
translating it into `re`, one path segment at a time, plus the two bits
that don't map onto a single segment:

  - "{a,b}" expands into several alternative node lists before
    translation, since a brace can straddle a "/" and change how many
    segments a branch even has.
  - "**" spans a variable number of segments, so it can't be translated
    segment-by-segment like everything else; it's replaced with a
    placeholder first and turned into the right regex fragment once the
    segments are joined back together.

Matching is exact against the whole path: a pattern with no "/" only
matches a single path segment, the same way `fnmatch` or
`pathlib.PurePath.match` treat it. This module doesn't know about "!"
negation or how multiple patterns in a file should be combined - that's
a policy the caller applies using `Pattern.negated`.
"""

import re

from .parser import Brace, CharClass, Globstar, Literal, Pattern, Question, Star, _split_segments

_GLOBSTAR_TOKEN = '\x00'
_CLASS_SPECIAL = set(']^\\-')


class CompiledPattern:
    def __init__(self, regex: re.Pattern):
        self._regex = regex

    def match(self, path: str) -> bool:
        return self._regex.fullmatch(path) is not None


def compile_pattern(pattern: Pattern) -> CompiledPattern:
    """Turn a Pattern into something whose .match(path) tests it."""
    branches = [_translate_flat_parts(flat) for flat in _expand_braces(pattern.parts)]
    body = branches[0] if len(branches) == 1 else '(?:' + '|'.join(branches) + ')'
    return CompiledPattern(re.compile(body))


def match(pattern: Pattern, path: str) -> bool:
    """Convenience wrapper for one-off checks; prefer compile_pattern
    when testing many paths against the same pattern."""
    return compile_pattern(pattern).match(path)


def _expand_braces(parts):
    """Cross-product a parts list against any Brace nodes in it, so the
    result is a list of flat parts lists with no Brace nodes left."""
    branches = [[]]
    for node in parts:
        if isinstance(node, Brace):
            options = [option for alt in node.alternatives for option in _expand_braces(alt)]
            branches = [prefix + option for prefix in branches for option in options]
        else:
            branches = [prefix + [node] for prefix in branches]
    return branches


def _translate_flat_parts(parts) -> str:
    tokens = []
    for segment in _split_segments(parts):
        if len(segment) == 1 and isinstance(segment[0], Globstar):
            tokens.append(_GLOBSTAR_TOKEN)
        else:
            tokens.append(''.join(_translate_node(node) for node in segment))
    return _collapse_globstars('/'.join(tokens))


def _collapse_globstars(regex: str) -> str:
    regex = regex.replace(f'/{_GLOBSTAR_TOKEN}/', '/(?:.*/)?')
    if regex.startswith(f'{_GLOBSTAR_TOKEN}/'):
        regex = '(?:.*/)?' + regex[len(_GLOBSTAR_TOKEN) + 1:]
    if regex.endswith(f'/{_GLOBSTAR_TOKEN}'):
        regex = regex[:-(len(_GLOBSTAR_TOKEN) + 1)] + '(?:/.*)?'
    if regex == _GLOBSTAR_TOKEN:
        regex = '.*'
    return regex


def _translate_node(node) -> str:
    if isinstance(node, Literal):
        return re.escape(node.value)
    if isinstance(node, Star):
        return '[^/]*'
    if isinstance(node, Question):
        return '[^/]'
    if isinstance(node, Globstar):
        # Only reached when a "**" shares a segment with other nodes,
        # e.g. via brace expansion ("a{**,x}b"), which the parser's
        # placement check doesn't catch (it only looks inside each
        # brace alternative on its own). It can't span segments from
        # here, so it degrades to matching within the current one.
        return '[^/]*'
    if isinstance(node, CharClass):
        return _translate_charclass(node)
    raise TypeError(f'unknown node type: {type(node).__name__}')


def _translate_charclass(node: CharClass) -> str:
    pieces = []
    for item in node.items:
        if isinstance(item, tuple):
            lo, hi = item
            pieces.append(f'{_escape_class_char(lo)}-{_escape_class_char(hi)}')
        else:
            pieces.append(_escape_class_char(item))
    prefix = '^' if node.negated else ''
    return f'[{prefix}{"".join(pieces)}]'


def _escape_class_char(ch: str) -> str:
    return '\\' + ch if ch in _CLASS_SPECIAL else ch
