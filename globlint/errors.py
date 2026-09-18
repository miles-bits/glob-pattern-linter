"""The error type raised by the parser.

The whole point of this project is that these errors are worth reading:
every one of them carries the exact line and column of the problem, plus
a snippet of the source line with a caret pointing at it, the way a
compiler would report it.
"""


class GlobSyntaxError(Exception):
    def __init__(self, message: str, line: int, column: int, text: str, length: int = 1):
        self.message = message
        self.line = line
        self.column = column
        self.text = text
        self.length = max(1, length)
        super().__init__(self._render())

    def _render(self) -> str:
        caret_line = ' ' * (self.column - 1) + '^' * self.length
        return (
            f'line {self.line}, column {self.column}: {self.message}\n'
            f'    {self.text}\n'
            f'    {caret_line}'
        )
