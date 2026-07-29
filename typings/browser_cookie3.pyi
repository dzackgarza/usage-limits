"""Minimal stubs for browser_cookie3 (ships no py.typed marker).

Only the surface this project uses is declared.
"""

from collections.abc import Iterator

class _Cookie:
    name: str
    value: str | None

def chromium(domain_name: str = ...) -> Iterator[_Cookie]: ...
def chrome(domain_name: str = ...) -> Iterator[_Cookie]: ...
def firefox(domain_name: str = ...) -> Iterator[_Cookie]: ...
