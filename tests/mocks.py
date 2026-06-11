"""Gemeinsame Test-Hilfen: gefälschte HTTP-Antworten und Stub-Clients."""
import json


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, headers=None, text=None):
        self.status_code = status_code
        self._json = json_data
        self.headers = headers or {}
        self.text = text if text is not None else json.dumps(json_data)

    def json(self):
        return self._json


def page_of(n, start=1):
    """Erzeugt n Dummy-Datensätze mit fortlaufender ID."""
    return [{"id": i} for i in range(start, start + n)]
