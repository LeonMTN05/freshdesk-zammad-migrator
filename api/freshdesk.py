"""Freshdesk REST-API-Client (API v2).

Beachtet Rate Limits (X-RateLimit-Remaining, 429 + Retry-After) und
paginiert mit per_page=100.
"""
import logging
import time

import requests

log = logging.getLogger("migrator.freshdesk")


class FreshdeskError(Exception):
    pass


class FreshdeskClient:
    PER_PAGE = 100
    MAX_RETRIES = 5
    TIMEOUT = 60
    # Freshdesk liefert pro Listen-Endpunkt maximal 300 Seiten
    MAX_PAGES = 300
    # Unter diesem Restkontingent wird gedrosselt
    THROTTLE_THRESHOLD = 3
    THROTTLE_SLEEP = 5

    def __init__(self, subdomain: str, api_key: str, session: requests.Session | None = None):
        self.subdomain = subdomain.strip()
        self.base = f"https://{self.subdomain}.freshdesk.com/api/v2"
        self.session = session or requests.Session()
        # Freshdesk: API-Key als Basic-Auth-Benutzer, Passwort beliebig
        self.session.auth = (api_key.strip(), "X")

    # ---------- HTTP ----------

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = self.base + path
        for attempt in range(1, self.MAX_RETRIES + 1):
            resp = self.session.request(method, url, timeout=self.TIMEOUT, **kwargs)

            if resp.status_code == 429:
                wait = int(resp.headers.get("Retry-After", 30))
                log.warning(
                    "Rate-Limit erreicht (Versuch %d/%d), warte %ds",
                    attempt, self.MAX_RETRIES, wait,
                )
                time.sleep(wait)
                continue

            remaining = resp.headers.get("X-RateLimit-Remaining")
            if remaining is not None:
                try:
                    if int(remaining) < self.THROTTLE_THRESHOLD:
                        log.info(
                            "Nur noch %s API-Calls übrig, drossle %ds",
                            remaining, self.THROTTLE_SLEEP,
                        )
                        time.sleep(self.THROTTLE_SLEEP)
                except ValueError:
                    pass

            if resp.status_code >= 400:
                raise FreshdeskError(
                    f"HTTP {resp.status_code} bei {method} {path}: {resp.text[:300]}"
                )
            return resp

        raise FreshdeskError(
            f"Rate-Limit: maximale Wiederholungen ({self.MAX_RETRIES}) bei {method} {path} erreicht"
        )

    def _get_paginated(self, path: str, params: dict | None = None) -> list:
        params = dict(params or {})
        params["per_page"] = self.PER_PAGE
        page = 1
        out: list = []
        while True:
            params["page"] = page
            data = self._request("GET", path, params=params).json()
            if isinstance(data, dict):
                data = data.get("results", [])
            out.extend(data)
            if len(data) < self.PER_PAGE:
                break
            page += 1
            if page > self.MAX_PAGES:
                log.warning(
                    "Seitenlimit (%d) bei %s erreicht – Daten ggf. unvollständig. "
                    "Bei Tickets: Zeitraumfilter (updated_since) nutzen.",
                    self.MAX_PAGES, path,
                )
                break
        return out

    # ---------- Endpunkte ----------

    def test_connection(self) -> tuple[bool, str]:
        try:
            me = self._request("GET", "/agents/me").json()
            name = (me.get("contact") or {}).get("name") or "unbekannt"
            return True, f"Verbunden als {name}"
        except Exception as e:  # noqa: BLE001
            return False, str(e)

    def get_companies(self) -> list:
        return self._get_paginated("/companies")

    def get_contacts(self) -> list:
        return self._get_paginated("/contacts")

    def get_agents(self) -> list:
        return self._get_paginated("/agents")

    def get_ticket_fields(self) -> list:
        # Endpunkt ist nicht paginiert
        return self._request("GET", "/ticket_fields").json()

    def get_tickets(self, updated_since: str | None = None) -> list:
        """Lädt Tickets inkl. Beschreibung und Requester-Objekt."""
        params = {
            "include": "requester,description",
            "order_by": "updated_at",
            "order_type": "asc",
        }
        if updated_since:
            params["updated_since"] = updated_since
        return self._get_paginated("/tickets", params)

    def get_conversations(self, ticket_id: int) -> list:
        return self._get_paginated(f"/tickets/{ticket_id}/conversations")

    def download_attachment(self, url: str) -> bytes:
        # Anhang-URLs sind vorsignierte S3-Links – ohne Basic-Auth abrufen,
        # sonst lehnt S3 die Anfrage ab.
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
        return resp.content
