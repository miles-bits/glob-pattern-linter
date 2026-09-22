# globlint

A validating parser and pretty printer for glob patterns.

Most tools that accept glob patterns (`*.py`, `src/**/*.ts`, `logs/[0-9]*.log`)
either interpret them silently or reject bad ones with something like
`invalid pattern` and no indication of where the problem is. That's fine
for a one-off pattern typed at a prompt, but it's useless for a file full
of them — a `.gitignore`-style list, a bundler's include/exclude config,
anything checked into a repo and edited by more than one person over time.

globlint parses a glob pattern (or a whole file of them, one pattern per
line) into an AST, validates it against the mistakes that are actually
common — unbalanced `[` or `{`, a stray `**` glued to other text in the
same path segment, a trailing backslash with nothing to escape — and
reports every problem with the exact line and column, plus a caret
pointing at it. It also pretty-prints a pattern back to a minimal
canonical form, so `src/\a\b.py` (a backslash-escaped `a` and `b`,
neither of which needed escaping) normalizes to `src/ab.py`.

It can also compile a parsed pattern into something that tests whether
a given path matches it.

## Usage

Parse a single pattern:

```python
from globlint import parse_line, GlobSyntaxError

try:
    pattern = parse_line("src/**/*.py")
except GlobSyntaxError as exc:
    print(exc)
else:
    print(pattern.negated, len(pattern.parts))
```

A malformed pattern raises with a precise location:

```python
>>> from globlint import parse_line
>>> parse_line("logs/[0-9.log")
Traceback (most recent call last):
  ...
globlint.errors.GlobSyntaxError: line 1, column 6: unterminated character class, expected closing ']'
    logs/[0-9.log
         ^^^^^^^^
```

Parse a whole file of patterns and collect every error at once, instead
of stopping at the first one:

```python
from globlint import parse_file

text = """
# build artifacts
*.pyc
dist/**
node_modules/{js
!keep-this-one.log
""".strip()

result = parse_file(text)
for error in result.errors:
    print(error)
```

```
line 4, column 14: unterminated brace expansion, expected closing '}'
    node_modules/{js
                 ^^^
```


Pretty-print a pattern back to its minimal form:

```python
from globlint import parse_line, pretty_print

pattern = parse_line(r"src/\a\b\*.py")
print(pretty_print(pattern))  # src/ab\*.py
```

The unnecessary escapes on `a` and `b` are dropped; the escape on `*`
stays, because without it that character means "match anything" instead
of a literal asterisk.

Test whether a path matches a pattern:

```python
from globlint import parse_line, compile_pattern

pattern = parse_line("src/**/*.py")
matcher = compile_pattern(pattern)
matcher.match("src/a.py")        # True
matcher.match("src/pkg/b.py")    # True
matcher.match("src/a.txt")       # False
```

A pattern with no `/` only matches a single path segment (the same way
`fnmatch` does), not a file at any depth. `compile_pattern` says nothing
about a pattern's `!` negation - combining several patterns' results is
left to the caller, since the right precedence rules depend on what
they're being used for.

## Syntax supported

- `*` — any run of characters within one path segment
- `**` — any number of path segments (must be its own segment: `a/**/b`)
- `?` — any single character
- `[abc]`, `[a-z]`, `[!abc]` — character classes, with ranges and negation
- `{a,b,c}` — brace alternatives (at least two branches; `{single}` is
  flagged rather than treated as literal text, since it's almost always
  a missing comma)
- `\x` — escape any character, including to write a literal `*`, `?`,
  `[`, `{`, or `\`
- `!pattern` at the start of a line — negation, in the style of
  `.gitignore`
- `#` at the start of a line — a comment, ignored by `parse_file`

## Roadmap

- preserve comments and blank lines when pretty-printing a whole file
- a small CLI (`globlint check patterns.txt`)
- support POSIX class names like `[:alpha:]`
- collect more than one error per line instead of stopping at the first

## License

MIT, see [LICENSE](LICENSE).
