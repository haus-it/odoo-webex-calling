# -*- coding: utf-8 -*-
# Copyright (c) 2026 Mentor GmbH, Am Hoppenhof 30a, 33104 Paderborn
# Haus iT Caller ID - https://hausit-portal.de
#
# Veroeffentlicht unter der GNU Lesser General Public License v3.
# Siehe LICENSE im selben Verzeichnis.
"""Offline tests for the logic that does not need Odoo.

    python -m unittest discover -s tests -v

These cover the parts where being wrong is silent: reading a CDR column that
Cisco spells two ways, deciding a call was answered, slicing a range Cisco
will accept, and turning a phone number into the shapes a CRM might hold.

They do NOT cover Odoo itself. See tests/odoo_stub.py for why.
"""

import datetime
import importlib.machinery
import importlib.util
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import odoo_stub  # noqa: E402

odoo_stub.install()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Which version tree to test. 17.0 is generated from 18.0 by
# tools/make-17.sh, so running the same suite against both is what proves
# the generator did not change behaviour - the one risk a generated copy
# actually carries.
#
#     WEBEX_TREE=17.0 python -m unittest discover -s tests
TREE = os.environ.get("WEBEX_TREE", "18.0")
MODULE = os.path.join(ROOT, TREE, "webex_calling", "models")


def _load(name):
    """Load one model file as part of a stand-in package.

    A stand-in package and not a plain file: webex_connection.py imports
    ``from .webex_client import …``, and a relative import needs a parent.
    Faking that parent is cheaper - and more honest - than rewriting the
    addon so it imports differently when tested than when it runs.
    """
    if "wx" not in sys.modules:
        parent = importlib.util.module_from_spec(
            importlib.machinery.ModuleSpec("wx", None, is_package=True))
        parent.__path__ = [MODULE]
        sys.modules["wx"] = parent

    full = "wx." + name
    spec = importlib.util.spec_from_file_location(
        full, os.path.join(MODULE, name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    spec.loader.exec_module(module)

    return module


client = _load("webex_client")
call = _load("webex_call")
connection = _load("webex_connection")


class ReadingCdrColumns(unittest.TestCase):
    """Cisco spells the same column two ways. Both must work."""

    def test_both_spellings(self):
        self.assertEqual(call._get({"Report ID": "a"}, "Report ID", "reportId"), "a")
        self.assertEqual(call._get({"reportId": "b"}, "Report ID", "reportId"), "b")

    def test_empty_string_counts_as_absent(self):
        # Cisco fills unused columns with "", not null. Treating "" as a value
        # would write empty records and call it a successful import.
        row = {"Correlation ID": "", "correlationId": "c-1"}
        self.assertEqual(call._get(row, "Correlation ID", "correlationId"), "c-1")

    def test_missing_gives_empty_string(self):
        self.assertEqual(call._get({}, "User", "user"), "")

    def test_report_id_falls_back(self):
        self.assertEqual(call._report_id({"Call ID": "x"}), "x")
        self.assertEqual(call._report_id({"reportId": "y"}), "y")
        self.assertIs(call._report_id({}), False)


class _Connection:
    """Stands in for a webex.connection recordset - id is all _from_cdr reads."""

    id = 7


class Direction(unittest.TestCase):
    """TERMINATING is inbound. Swapping this inverts every later figure."""

    def _row(self, direction, calling="+491", called="+492"):
        return {"Call ID": "1", "Direction": direction,
                "Calling number": calling, "Called number": called,
                "Start time": "2026-08-30T09:14:00.000Z"}

    def test_terminating_is_inbound(self):
        got = call.WebexCall._from_cdr(call.WebexCall, _Connection(), self._row("TERMINATING"))
        self.assertEqual(got["direction"], "inbound")
        # The other party of an inbound call is whoever called us.
        self.assertEqual(got["other_party"], "+491")

    def test_originating_is_outbound(self):
        got = call.WebexCall._from_cdr(call.WebexCall, _Connection(), self._row("ORIGINATING"))
        self.assertEqual(got["direction"], "outbound")
        self.assertEqual(got["other_party"], "+492")

    def test_lowercase_and_padding(self):
        got = call.WebexCall._from_cdr(call.WebexCall, _Connection(), self._row("  terminating "))
        self.assertEqual(got["direction"], "inbound")


class Answered(unittest.TestCase):
    """An answer time means answered, flag or no flag."""

    def _built(self, row):
        row = dict({"Call ID": "1", "Direction": "TERMINATING",
                    "Start time": "2026-08-30T09:14:00.000Z"}, **row)

        return call.WebexCall._from_cdr(call.WebexCall, _Connection(), row)

    def test_flag_true(self):
        self.assertTrue(self._built({"Answered": "true"})["answered"])

    def test_answer_time_without_flag(self):
        # This is the case that would otherwise become a missed call - the
        # one direction in which a wrong number never gets questioned.
        self.assertTrue(self._built({"Answer time": "2026-08-30T09:14:07.000Z"})["answered"])

    def test_neither(self):
        self.assertFalse(self._built({})["answered"])
        self.assertFalse(self._built({"Answered": "false"})["answered"])


class Timestamps(unittest.TestCase):
    def test_iso_with_milliseconds(self):
        got = call._parse_time("2026-08-30T09:14:07.123Z")
        self.assertEqual(got, datetime.datetime(2026, 8, 30, 9, 14, 7, 123000))

    def test_iso_without_milliseconds(self):
        self.assertEqual(call._parse_time("2026-08-30T09:14:07Z"),
                         datetime.datetime(2026, 8, 30, 9, 14, 7))

    def test_offset_is_converted_to_utc(self):
        # Odoo stores naive UTC. A timestamp kept in local time would shift
        # every report by an hour twice a year.
        self.assertEqual(call._parse_time("2026-08-30T11:14:07+02:00"),
                         datetime.datetime(2026, 8, 30, 9, 14, 7))

    def test_rubbish_is_false_not_an_exception(self):
        self.assertIs(call._parse_time("gestern"), False)
        self.assertIs(call._parse_time(""), False)

    def test_int_is_forgiving(self):
        self.assertEqual(call._int("12"), 12)
        self.assertEqual(call._int("12.7"), 12)
        self.assertEqual(call._int(None), 0)
        self.assertEqual(call._int("keine"), 0)


class NumberVariants(unittest.TestCase):
    """The same telephone, spelled the ways a CRM might hold it."""

    def test_german_international_to_national(self):
        got = connection._variants("4952512020808")
        self.assertIn("+4952512020808", got)
        self.assertIn("052512020808", got)

    def test_national_to_international(self):
        got = connection._variants("05251202080")
        self.assertIn("+495251202080", got)
        self.assertIn("495251202080", got)

    def test_last_eight_digits_are_offered_last(self):
        got = connection._variants("4952512020808")
        self.assertIn("12020808", got)
        self.assertEqual(got[-1], "12020808")

    def test_no_duplicates(self):
        got = connection._variants("4952512020808")
        self.assertEqual(len(got), len(set(got)))


class PagingLinks(unittest.TestCase):
    def test_next_link(self):
        header = ('<https://a/x?cursor=1>; rel="prev", '
                  '<https://a/x?cursor=3>; rel="next"')
        self.assertEqual(client._next_link(header), "https://a/x?cursor=3")

    def test_no_next(self):
        self.assertIsNone(client._next_link('<https://a/x>; rel="prev"'))
        self.assertIsNone(client._next_link(None))
        self.assertIsNone(client._next_link(""))


class QueryWindow(unittest.TestCase):
    """Cisco refuses more than 12 hours and keeps only 720."""

    def setUp(self):
        self.calls = []

        self.client = client.WebexClient("id", "secret", access_token="t")
        self.client._cdr_slice = lambda a, b, size: (
            self.calls.append((a, b)) or [{"Call ID": "%s" % len(self.calls)}])

    def test_range_is_sliced_into_12_hour_pieces(self):
        end = client._utcnow()
        start = end - datetime.timedelta(hours=30)

        rows = self.client.cdr_feed(start, end)

        self.assertEqual(len(self.calls), 3)          # 12 + 12 + 6
        self.assertEqual(len(rows), 3)
        for a, b in self.calls:
            self.assertLessEqual(b - a, client.MAX_WINDOW)
        # No gaps, no overlaps.
        self.assertEqual(self.calls[0][1], self.calls[1][0])
        self.assertEqual(self.calls[1][1], self.calls[2][0])
        self.assertEqual(self.calls[-1][1], end)

    def test_start_is_clamped_to_the_retention_limit(self):
        end = client._utcnow()
        start = end - datetime.timedelta(days=90)

        self.client.cdr_feed(start, end)

        oldest = self.calls[0][0]
        self.assertGreaterEqual(oldest, end - client.RETENTION
                                - datetime.timedelta(seconds=5))

    def test_empty_range(self):
        now = client._utcnow()
        self.assertEqual(self.client.cdr_feed(now, now), [])
        self.assertEqual(self.calls, [])


class Scopes(unittest.TestCase):
    def test_five_and_the_fallback_of_four(self):
        self.assertEqual(len(client.ADMIN_SCOPES), 5)
        self.assertEqual(len(client.CORE_SCOPES), 4)
        self.assertIn("spark-admin:telephony_config_read", client.ADMIN_SCOPES)
        # The fallback is exactly the five minus the queue names, nothing else.
        self.assertNotIn("spark-admin:telephony_config_read", client.CORE_SCOPES)
        self.assertEqual(client.CORE_SCOPES, client.ADMIN_SCOPES[:4])

    def test_every_scope_is_read_only(self):
        for scope in client.ADMIN_SCOPES:
            self.assertTrue(scope.endswith("_read"), scope)

    def test_authorize_url_carries_them(self):
        url = client.WebexClient("cid", "sec").authorize_url(
            "https://odoo/webex/callback", "nonce-1")
        self.assertIn("client_id=cid", url)
        self.assertIn("state=nonce-1", url)
        self.assertIn("calling_cdr_read", url)
        self.assertIn("webexapis.com/v1/authorize", url)


if __name__ == "__main__":
    unittest.main(verbosity=2)
