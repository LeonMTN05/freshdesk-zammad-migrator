"""End-to-End-Tests der Migrations-Engine mit Stub-Clients (keine echten APIs)."""
import json
import tempfile
import unittest
from pathlib import Path

from migration.engine import MigrationEngine, MigrationOptions


class StubFreshdesk:
    def __init__(self):
        self.conversations = {
            101: [
                {
                    "id": 9001, "body": "<p>Antwort vom Agenten</p>", "incoming": False,
                    "private": False, "user_id": 7, "created_at": "2024-03-01T10:00:00Z",
                    "attachments": [],
                },
                {
                    "id": 9002, "body": "<p>Interne Notiz</p>", "incoming": False,
                    "private": True, "user_id": 7, "created_at": "2024-03-01T11:00:00Z",
                    "attachments": [],
                },
            ],
        }

    def get_conversations(self, ticket_id):
        return self.conversations.get(ticket_id, [])

    def download_attachment(self, url):
        return b"dateiinhalt"


class StubZammad:
    """Zeichnet alle Schreibzugriffe auf, kennt einen bestehenden Benutzer."""

    def __init__(self):
        self.created_orgs = []
        self.created_users = []
        self.created_tickets = []
        self.created_articles = []
        self.tags = []
        self.existing_users = {"bekannt@example.com": {"id": 77, "email": "bekannt@example.com"}}

    def search_organization_by_name(self, name):
        return None

    def search_user_by_email(self, email):
        return self.existing_users.get((email or "").lower())

    def create_organization(self, data):
        self.created_orgs.append(data)
        return {"id": 10 + len(self.created_orgs), **data}

    def create_user(self, data):
        self.created_users.append(data)
        return {"id": 100 + len(self.created_users), **data}

    def create_ticket(self, payload):
        self.created_tickets.append(payload)
        return {"id": 500 + len(self.created_tickets), **payload}

    def create_article(self, payload):
        self.created_articles.append(payload)
        return {"id": len(self.created_articles)}

    def update_ticket(self, ticket_id, payload):
        return {"id": ticket_id}

    def add_tag(self, ticket_id, tag):
        self.tags.append((ticket_id, tag))

    def search_tickets(self, query, limit=10):
        return []


SAMPLE_DATA = {
    "companies": [{"id": 1, "name": "ACME GmbH", "description": "Testfirma"}],
    "contacts": [
        {"id": 5, "name": "Erika Beispiel", "email": "erika@example.com", "company_id": 1},
        {"id": 6, "name": "Bekannt Bereits", "email": "bekannt@example.com", "company_id": None},
    ],
    "agents": [
        {"id": 7, "contact": {"name": "Agent Bekannt", "email": "bekannt@example.com"}},
    ],
    "tickets": [
        {
            "id": 101, "subject": "Drucker brennt", "status": 2, "priority": 3,
            "requester_id": 5,
            "requester": {"name": "Erika Beispiel", "email": "erika@example.com"},
            "description": "<p>Hilfe!</p>", "tags": ["hardware"],
            "created_at": "2024-03-01T09:00:00Z", "updated_at": "2024-03-02T09:00:00Z",
            "attachments": [],
        },
    ],
}


def make_engine(zd, fd=None, dry_run=False, tmpdir=None):
    options = MigrationOptions(
        group_id=1,
        status_map={2: 22, 3: 33, 4: 44, 5: 44},
        priority_map={1: 1, 2: 2, 3: 3, 4: 3},
        fallback_state_id=22,
        fallback_priority_id=2,
        dry_run=dry_run,
    )
    tmp = Path(tmpdir)
    return MigrationEngine(
        fd or StubFreshdesk(), zd, options,
        state_path=tmp / "state.json", failed_path=tmp / "failed.json",
    )


class TestMigrationEngine(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmpdir = self._tmp.name

    def test_full_run_creates_expected_records(self):
        zd = StubZammad()
        engine = make_engine(zd, tmpdir=self.tmpdir)
        summary = engine.run(SAMPLE_DATA)

        # Organisation neu, Erika neu, "bekannt" als Kontakt + Agent nur gemappt
        self.assertEqual(len(zd.created_orgs), 1)
        self.assertEqual(len(zd.created_users), 1)
        self.assertEqual(zd.created_users[0]["email"], "erika@example.com")
        self.assertEqual(zd.created_users[0]["organization_id"], 11)

        # Ticket mit gemapptem Status/Priorität, Original-Zeitstempeln, Erstartikel
        self.assertEqual(len(zd.created_tickets), 1)
        ticket = zd.created_tickets[0]
        self.assertEqual(ticket["state_id"], 22)
        self.assertEqual(ticket["priority_id"], 3)
        self.assertEqual(ticket["created_at"], "2024-03-01T09:00:00Z")
        self.assertEqual(ticket["article"]["type"], "note")

        # Konversation: 2 Artikel, interne Notiz als internal markiert,
        # Autor (Agent fd-7) über origin_by_id auf Zammad-User 77 gemappt
        self.assertEqual(len(zd.created_articles), 2)
        self.assertFalse(zd.created_articles[0]["internal"])
        self.assertTrue(zd.created_articles[1]["internal"])
        self.assertEqual(zd.created_articles[0]["origin_by_id"], 77)

        # Marker-Tag + Original-Tag
        self.assertIn((501, "fd-101"), zd.tags)
        self.assertIn((501, "hardware"), zd.tags)

        self.assertEqual(summary["created"], 3)  # Org + Erika + Ticket
        self.assertEqual(summary["skipped"], 2)  # bekannter Kontakt + Agent
        self.assertEqual(summary["failed"], 0)

        # Zustandsdatei muss die Mappings für die Wiederaufnahme enthalten
        state = json.loads((Path(self.tmpdir) / "state.json").read_text())
        self.assertEqual(state["tickets"]["101"], 501)
        self.assertEqual(state["organizations"]["1"], 11)

    def test_dry_run_writes_nothing(self):
        zd = StubZammad()
        engine = make_engine(zd, dry_run=True, tmpdir=self.tmpdir)
        summary = engine.run(SAMPLE_DATA)

        self.assertEqual(zd.created_orgs, [])
        self.assertEqual(zd.created_users, [])
        self.assertEqual(zd.created_tickets, [])
        self.assertEqual(zd.tags, [])
        self.assertEqual(summary["created"], 3)
        self.assertEqual(summary["skipped"], 2)
        self.assertFalse((Path(self.tmpdir) / "state.json").exists())

    def test_resume_skips_already_migrated(self):
        zd = StubZammad()
        engine = make_engine(zd, tmpdir=self.tmpdir)
        engine.run(SAMPLE_DATA)

        zd2 = StubZammad()
        engine2 = make_engine(zd2, tmpdir=self.tmpdir)
        summary = engine2.run(SAMPLE_DATA)

        self.assertEqual(zd2.created_tickets, [])
        self.assertEqual(zd2.created_orgs, [])
        self.assertEqual(summary["created"], 0)
        self.assertEqual(summary["skipped"], 5)

    def test_single_record_failure_does_not_stop_run(self):
        zd = StubZammad()

        def broken_create_org(data):
            raise RuntimeError("Zammad sagt nein")

        zd.create_organization = broken_create_org
        engine = make_engine(zd, tmpdir=self.tmpdir)
        summary = engine.run(SAMPLE_DATA)

        self.assertEqual(summary["failed"], 1)
        # Ticket wurde trotz Organisations-Fehler migriert
        self.assertEqual(len(zd.created_tickets), 1)
        failed = json.loads((Path(self.tmpdir) / "failed.json").read_text())
        self.assertEqual(failed[0]["type"], "organization")
        self.assertEqual(failed[0]["freshdesk_id"], 1)

    def test_cancel_stops_before_next_record(self):
        zd = StubZammad()
        engine = make_engine(zd, tmpdir=self.tmpdir)
        engine.cancel()
        summary = engine.run(SAMPLE_DATA)
        self.assertTrue(summary["cancelled"])
        self.assertEqual(zd.created_orgs, [])


if __name__ == "__main__":
    unittest.main()
