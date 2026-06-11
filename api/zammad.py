"""Zammad REST-API-Client (API v1).

Schreibt in eine bestehende Instanz – ausschließlich additive Operationen
(Suchen + Anlegen), keine Lösch- oder Überschreib-Aktionen auf Bestandsdaten.
"""
import logging

import requests

log = logging.getLogger("migrator.zammad")


class ZammadError(Exception):
    pass


class ZammadClient:
    PER_PAGE = 100
    TIMEOUT = 60

    def __init__(self, url: str, token: str, session: requests.Session | None = None):
        self.base = url.strip().rstrip("/") + "/api/v1"
        self.session = session or requests.Session()
        self.session.headers["Authorization"] = f"Token token={token.strip()}"

    # ---------- HTTP ----------

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        resp = self.session.request(method, self.base + path, timeout=self.TIMEOUT, **kwargs)
        if resp.status_code >= 400:
            raise ZammadError(
                f"HTTP {resp.status_code} bei {method} {path}: {resp.text[:300]}"
            )
        return resp

    def _get_paginated(self, path: str, params: dict | None = None) -> list:
        params = dict(params or {})
        params["per_page"] = self.PER_PAGE
        page = 1
        out: list = []
        while True:
            params["page"] = page
            data = self._request("GET", path, params=params).json()
            if not data:
                break
            out.extend(data)
            if len(data) < self.PER_PAGE:
                break
            page += 1
        return out

    # ---------- Stammdaten ----------

    def test_connection(self) -> tuple[bool, str]:
        try:
            me = self._request("GET", "/users/me").json()
            name = f"{me.get('firstname', '')} {me.get('lastname', '')}".strip()
            name = name or me.get("email") or "unbekannt"
            return True, f"Verbunden als {name}"
        except Exception as e:  # noqa: BLE001
            return False, str(e)

    def get_groups(self) -> list:
        return [g for g in self._get_paginated("/groups") if g.get("active", True)]

    def get_ticket_states(self) -> list:
        return [s for s in self._get_paginated("/ticket_states") if s.get("active", True)]

    def get_ticket_priorities(self) -> list:
        return self._get_paginated("/ticket_priorities")

    # ---------- Benutzer / Organisationen ----------

    def search_user_by_email(self, email: str | None) -> dict | None:
        """Sucht einen Benutzer per E-Mail; nur exakte Treffer zählen."""
        if not email:
            return None
        results = self._request(
            "GET", "/users/search",
            params={"query": f'email:"{email}"', "limit": 10},
        ).json()
        for user in results:
            if (user.get("email") or "").strip().lower() == email.strip().lower():
                return user
        return None

    def create_user(self, data: dict) -> dict:
        return self._request("POST", "/users", json=data).json()

    def search_organization_by_name(self, name: str | None) -> dict | None:
        if not name:
            return None
        results = self._request(
            "GET", "/organizations/search",
            params={"query": f'name:"{name}"', "limit": 10},
        ).json()
        for org in results:
            if (org.get("name") or "").strip().lower() == name.strip().lower():
                return org
        return None

    def create_organization(self, data: dict) -> dict:
        return self._request("POST", "/organizations", json=data).json()

    # ---------- Tickets ----------

    def create_ticket(self, payload: dict) -> dict:
        return self._request("POST", "/tickets", json=payload).json()

    def update_ticket(self, ticket_id: int, payload: dict) -> dict:
        return self._request("PUT", f"/tickets/{ticket_id}", json=payload).json()

    def create_article(self, payload: dict) -> dict:
        return self._request("POST", "/ticket_articles", json=payload).json()

    def add_tag(self, ticket_id: int, tag: str) -> None:
        self._request(
            "POST", "/tags/add",
            json={"object": "Ticket", "o_id": ticket_id, "item": tag},
        )

    def search_tickets(self, query: str, limit: int = 10) -> list:
        data = self._request(
            "GET", "/tickets/search",
            params={"query": query, "limit": limit, "expand": "true"},
        ).json()
        if isinstance(data, dict):
            # Ohne expand liefert Zammad {"tickets": [ids], "assets": {...}}
            return data.get("tickets") or []
        return data
