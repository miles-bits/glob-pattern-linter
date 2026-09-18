"""Renders a parsed Pattern back to text.

This is not a no-op round trip: it drops escapes that were never
needed in the first place (``\\a`` becomes ``a``) so that two patterns
which mean the same thing tend to print the same way.
"""

from .parser import Brace, CharClass, Globstar, Literal, Pattern, Question, Star

_NEEDS_ESCAPE = set('*?[]{}\\')


def _render_node(node) -> str:
    if isinstance(node, Literal):
        return '\\' + node.value if node.value in _NEEDS_ESCAPE else node.value
    if isinstance(node, Star):
        return '*'
    if isinstance(node, Globstar):
        return '**'
    if isinstance(node, Question):
        return '?'
    if isinstance(node, CharClass):
        return _render_charclass(node)
    if isinstance(node, Brace):
        return _render_brace(node)
    raise TypeError(f'unknown node type: {type(node).__name__}')


def _render_parts(parts) -> str:
    return ''.join(_render_node(node) for node in parts)


def _render_charclass(node: CharClass) -> str:
    pieces = []
    for item in node.items:
        if isinstance(item, tuple):
            lo, hi = item
            pieces.append(f'{lo}-{hi}')
        else:
            pieces.append(item)
    body = ''.join(pieces)
    prefix = '!' if node.negated else ''
    return f'[{prefix}{body}]'


def _render_brace(node: Brace) -> str:
    return '{' + ','.join(_render_parts(alt) for alt in node.alternatives) + '}'


def pretty_print(pattern: Pattern) -> str:
    body = _render_parts(pattern.parts)
    if not pattern.negated and body[:1] in ('!', '#'):
        # would otherwise be misread as negation or a comment if written
        # back into a pattern file
        body = '\\' + body
    return ('!' if pattern.negated else '') + body
