"""Tests für den Zammad-Client – ausschließlich mit Mock-Daten."""
import unittest
from unittest.mock import MagicMock

from api.zammad import ZammadClient, ZammadError
from tests.mocks import FakeResponse


def make_client():
    session = MagicMock()
    session.headers = {}
    client = ZammadClient("https://zammad.example.com/", "tok123", session=session)
    return client, session


class TestZammadClient(unittest.TestCase):
    def test_base_url_and_token_header(self):
        client, session = make_client()
        self.assertEqual(client.base, "https://zammad.example.com/api/v1")
        self.assertEqual(session.headers["Authorization"], "Token token=tok123")

    def test_search_user_exact_match_only(self):
        client, session = make_client()
        session.request.return_value = FakeResponse(json_data=[
            {"id": 1, "email": "max.mueller@example.com"},
            {"id": 2, "email": "Max@Example.com"},
        ])
        user = client.search_user_by_email("max@example.com")
        self.assertIsNotNone(user)
        self.assertEqual(user["id"], 2)  # exakter Treffer, case-insensitiv

    def test_search_user_no_match_returns_none(self):
        client, session = make_client()
        session.request.return_value = FakeResponse(json_data=[
            {"id": 1, "email": "anders@example.com"},
        ])
        self.assertIsNone(client.search_user_by_email("max@example.com"))
        self.assertIsNone(client.search_user_by_email(""))

    def test_search_organization_exact_match(self):
        client, session = make_client()
        session.request.return_value = FakeResponse(json_data=[
            {"id": 5, "name": "ACME GmbH "},
            {"id": 6, "name": "ACME GmbH & Co"},
        ])
        org = client.search_organization_by_name("acme gmbh")
        self.assertEqual(org["id"], 5)

    def test_create_ticket_posts_payload(self):
        client, session = make_client()
        session.request.return_value = FakeResponse(json_data={"id": 99})
        payload = {"title": "Test", "group_id": 1}
        result = client.create_ticket(payload)
        self.assertEqual(result["id"], 99)
        args, kwargs = session.request.call_args
        self.assertEqual(args[0], "POST")
        self.assertEqual(args[1], "https://zammad.example.com/api/v1/tickets")
        self.assertEqual(kwargs["json"], payload)

    def test_search_tickets_handles_both_response_shapes(self):
        client, session = make_client()
        # Dict-Form (ohne expand): {"tickets": [ids]}
        session.request.return_value = FakeResponse(json_data={"tickets": [4, 7], "assets": {}})
        self.assertEqual(client.search_tickets("tags:fd-1"), [4, 7])
        # Listen-Form (mit expand): Ticket-Objekte
        session.request.return_value = FakeResponse(json_data=[{"id": 4}])
        self.assertEqual(client.search_tickets("tags:fd-1"), [{"id": 4}])

    def test_get_groups_filters_inactive(self):
        client, session = make_client()
        session.request.return_value = FakeResponse(json_data=[
            {"id": 1, "name": "Support", "active": True},
            {"id": 2, "name": "Alt", "active": False},
        ])
        groups = client.get_groups()
        self.assertEqual([g["id"] for g in groups], [1])

    def test_http_error_raises(self):
        client, session = make_client()
        session.request.return_value = FakeResponse(status_code=422, json_data={"error": "invalid"})
        with self.assertRaises(ZammadError):
            client.create_user({"email": "x"})


if __name__ == "__main__":
    unittest.main()
