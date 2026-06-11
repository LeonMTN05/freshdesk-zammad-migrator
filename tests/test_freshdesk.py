"""Tests für den Freshdesk-Client – ausschließlich mit Mock-Daten."""
import unittest
from unittest.mock import MagicMock, patch

from api.freshdesk import FreshdeskClient, FreshdeskError
from tests.mocks import FakeResponse, page_of


def make_client():
    session = MagicMock()
    client = FreshdeskClient("testfirma", "geheimer-key", session=session)
    return client, session


class TestFreshdeskClient(unittest.TestCase):
    def test_base_url_and_auth(self):
        client, session = make_client()
        self.assertEqual(client.base, "https://testfirma.freshdesk.com/api/v2")
        # Basic Auth: API-Key als Benutzer, "X" als Passwort
        self.assertEqual(session.auth, ("geheimer-key", "X"))

    def test_pagination_collects_all_pages(self):
        client, session = make_client()
        session.request.side_effect = [
            FakeResponse(json_data=page_of(100)),
            FakeResponse(json_data=page_of(42, start=101)),
        ]
        result = client.get_companies()
        self.assertEqual(len(result), 142)
        self.assertEqual(session.request.call_count, 2)
        # per_page=100 muss gesetzt sein, Seite 2 beim zweiten Aufruf
        _, kwargs = session.request.call_args
        self.assertEqual(kwargs["params"]["per_page"], 100)
        self.assertEqual(kwargs["params"]["page"], 2)

    def test_pagination_stops_on_short_page(self):
        client, session = make_client()
        session.request.return_value = FakeResponse(json_data=page_of(3))
        result = client.get_contacts()
        self.assertEqual(len(result), 3)
        self.assertEqual(session.request.call_count, 1)

    @patch("api.freshdesk.time.sleep")
    def test_429_retries_with_retry_after(self, sleep_mock):
        client, session = make_client()
        session.request.side_effect = [
            FakeResponse(status_code=429, json_data={}, headers={"Retry-After": "7"}),
            FakeResponse(json_data=page_of(1)),
        ]
        result = client.get_agents()
        self.assertEqual(len(result), 1)
        sleep_mock.assert_called_once_with(7)

    @patch("api.freshdesk.time.sleep")
    def test_throttles_when_remaining_low(self, sleep_mock):
        client, session = make_client()
        session.request.return_value = FakeResponse(
            json_data=page_of(1), headers={"X-RateLimit-Remaining": "1"},
        )
        client.get_agents()
        sleep_mock.assert_called_once_with(FreshdeskClient.THROTTLE_SLEEP)

    @patch("api.freshdesk.time.sleep")
    def test_429_gives_up_after_max_retries(self, _sleep_mock):
        client, session = make_client()
        session.request.return_value = FakeResponse(
            status_code=429, json_data={}, headers={"Retry-After": "1"},
        )
        with self.assertRaises(FreshdeskError):
            client.get_agents()
        self.assertEqual(session.request.call_count, FreshdeskClient.MAX_RETRIES)

    def test_http_error_raises(self):
        client, session = make_client()
        session.request.return_value = FakeResponse(status_code=403, json_data={"message": "nope"})
        with self.assertRaises(FreshdeskError):
            client.get_companies()

    def test_get_tickets_includes_requester_and_description(self):
        client, session = make_client()
        session.request.return_value = FakeResponse(json_data=page_of(1))
        client.get_tickets(updated_since="2024-01-01T00:00:00Z")
        _, kwargs = session.request.call_args
        self.assertEqual(kwargs["params"]["include"], "requester,description")
        self.assertEqual(kwargs["params"]["updated_since"], "2024-01-01T00:00:00Z")

    def test_test_connection_ok_and_fail(self):
        client, session = make_client()
        session.request.return_value = FakeResponse(
            json_data={"contact": {"name": "Max Mustermann"}},
        )
        ok, msg = client.test_connection()
        self.assertTrue(ok)
        self.assertIn("Max Mustermann", msg)

        session.request.return_value = FakeResponse(status_code=401, json_data={})
        ok, msg = client.test_connection()
        self.assertFalse(ok)
        self.assertIn("401", msg)


if __name__ == "__main__":
    unittest.main()
