# -*- coding: utf-8 -*-
# Copyright (c) 2026 Mentor GmbH, Am Hoppenhof 30a, 33104 Paderborn
# Haus iT Caller ID - https://hausit-portal.de
#
# Veroeffentlicht unter der GNU Lesser General Public License v3.
# Siehe LICENSE im selben Verzeichnis.
"""One row per call detail record - and one *call* per correlation id."""

import datetime
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class WebexCall(models.Model):
    _name = "webex.call"
    _description = "Webex call detail record"
    _order = "start_time desc, id desc"

    connection_id = fields.Many2one(
        "webex.connection", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(
        related="connection_id.company_id", store=True, index=True)

    # Cisco's own identifier for the single record.
    report_id = fields.Char(required=True, index=True, readonly=True)

    # THE IMPORTANT ONE. Read the class docstring below.
    correlation_id = fields.Char(index=True, readonly=True)

    start_time = fields.Datetime(index=True, readonly=True)
    answer_time = fields.Datetime(readonly=True)
    duration = fields.Integer(readonly=True, help="Seconds of conversation.")
    ring_duration = fields.Integer(readonly=True, help="Seconds of ringing.")

    call_type = fields.Char(readonly=True)
    call_outcome = fields.Char(readonly=True)

    direction = fields.Selection(
        [("inbound", "Inbound"), ("outbound", "Outbound")],
        index=True, readonly=True)
    answered = fields.Boolean(index=True, readonly=True)

    calling_number = fields.Char(readonly=True)
    called_number = fields.Char(readonly=True)
    other_party = fields.Char(
        index=True, readonly=True,
        help="The number outside your own organisation - the one a partner "
             "can be matched against.")

    user_name = fields.Char(readonly=True)
    user_uuid = fields.Char(readonly=True)
    location = fields.Char(readonly=True)

    partner_id = fields.Many2one("res.partner", index=True, ondelete="set null")
    resolved = fields.Boolean(compute="_compute_resolved", store=True)

    _sql_constraints = [
        # The importer runs again after a failed night. Without this the
        # second run would double every record it already had, and every
        # report built on top would quietly double with it.
        ("report_id_uniq", "unique(connection_id, report_id)",
         "This call detail record has already been imported."),
    ]

    @api.depends("partner_id")
    def _compute_resolved(self):
        for record in self:
            record.resolved = bool(record.partner_id)

    # -------------------------------------------------------------- import

    @api.model
    def _absorb(self, connection, rows):
        """Turn Cisco's rows into records. Returns how many were created."""
        if not rows:
            return 0

        incoming = [_report_id(row) for row in rows]

        known = set(self.search([
            ("connection_id", "=", connection.id),
            ("report_id", "in", [i for i in incoming if i]),
        ]).mapped("report_id"))

        values = []

        for row, report_id in zip(rows, incoming):
            # No identifier means we could not deduplicate it, and a record
            # that gets imported again on every run is worse than a missing
            # one: it inflates every count that follows.
            if not report_id or report_id in known:
                continue

            known.add(report_id)
            values.append(self._from_cdr(connection, row))

        if not values:
            return 0

        created = self.create(values)
        created._match_partners()

        return len(created)

    @api.model
    def _from_cdr(self, connection, row):
        # Cisco says "ORIGINATING" for a call your user placed and
        # "TERMINATING" for one they received. The words describe the leg,
        # not the business meaning, and swapping them inverts every
        # reachability figure you will ever build on this table.
        direction = _get(row, "Direction", "direction").strip().upper()
        inbound = direction == "TERMINATING"

        calling = _get(row, "Calling number", "callingNumber").strip()
        called = _get(row, "Called number", "calledNumber").strip()

        # ANSWERED IS NOT JUST THE "Answered" FLAG.
        #
        # Some records carry an answer time and no flag. Reading only the
        # flag turns those into missed calls - which is the one direction
        # that makes a reachability figure look worse than reality, and
        # nobody questions a bad number.
        answer_time = _parse_time(_get(row, "Answer time", "answerTime"))
        answered = bool(answer_time) or _get(
            row, "Answered", "answered").strip().lower() in ("true", "yes", "1")

        return {
            "connection_id": connection.id,
            "report_id": _report_id(row),
            "correlation_id": _get(row, "Correlation ID", "correlationId") or None,
            "start_time": _parse_time(_get(row, "Start time", "startTime")),
            "answer_time": answer_time,
            "duration": _int(_get(row, "Duration", "duration")),
            "ring_duration": _int(_get(row, "Ring duration", "ringDuration")),
            "direction": "inbound" if inbound else "outbound",
            "answered": answered,
            "calling_number": calling or False,
            "called_number": called or False,
            "other_party": (calling if inbound else called) or False,
            "user_name": _get(row, "User", "user") or False,
            "user_uuid": _get(row, "User UUID", "userUuid") or False,
            "call_type": _get(row, "Call type", "callType") or False,
            "call_outcome": _get(row, "Call outcome", "callOutcome") or False,
            "location": _get(row, "Location", "location") or False,
        }

    def _match_partners(self):
        connections = self.env["webex.connection"]

        for record in self:
            if record.partner_id or not record.other_party:
                continue

            partner = connections.resolve(record.other_party)

            if partner:
                record.partner_id = partner

        return True

    @api.model
    def _cron_rematch(self):
        """Give unresolved calls another chance.

        A partner created today can explain a call from yesterday. Without
        this the number stays anonymous forever, which reads like a broken
        integration when it is really just a contact that arrived late.
        """
        stale = self.search([
            ("partner_id", "=", False),
            ("other_party", "!=", False),
        ], limit=2000)

        stale._match_partners()

    # ------------------------------------------------------------ analysis

    @api.model
    def count_conversations(self, domain=None):
        """Count CALLS, not records.

        THE ONE THING PEOPLE GET WRONG WITH WEBEX CALL DATA
        A call that rings a hunt group produces one record per extension
        that rang. We have seen a single conversation arrive as seventeen
        rows. Anyone counting rows reads a hunt group as a wall of missed
        calls, and the "missed" figure comes out roughly seven times too
        high.

        The bracket around the rows is the correlation id. Records without
        one are counted on their own - dropping them would be the opposite
        error.
        """
        rows = self.search(domain or [])

        seen = set()
        total = 0

        for row in rows:
            key = row.correlation_id or ("report:%s" % row.report_id)

            if key in seen:
                continue

            seen.add(key)
            total += 1

        return total

    def action_open_partner(self):
        self.ensure_one()

        if not self.partner_id:
            return False

        return {
            "type": "ir.actions.act_window",
            "res_model": "res.partner",
            "res_id": self.partner_id.id,
            "view_mode": "form",
            "name": _("Caller"),
        }


def _get(row, *keys):
    """Read one CDR field, whichever spelling this organisation gets.

    THIS IS NOT DEFENSIVE PROGRAMMING, IT IS NECESSARY.
    The same feed hands out ``Report ID`` in one place and ``reportId`` in
    another, depending on API version and region. Code that knows only one
    spelling does not crash - it silently reads an empty column and writes
    empty records, and the import log says "1,400 rows imported".

    An empty string counts as absent. Cisco fills unused columns with "",
    not with null.
    """
    for key in keys:
        value = row.get(key)

        if value not in (None, ""):
            return value if isinstance(value, str) else str(value)

    return ""


def _report_id(row):
    """The identifier this record is deduplicated by.

    ``Call ID`` first, because that is what our own production importer has
    used since day one; ``Report ID`` as the fallback. Both are unique per
    record - what they are NOT is unique per call. See count_conversations().
    """
    return _get(row, "Call ID", "callId", "Report ID", "reportId") or False


def _parse_time(value):
    if not value:
        return False

    text = str(value).strip().replace("Z", "+00:00")

    for pattern in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                    "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            moment = datetime.datetime.strptime(text, pattern)
        except ValueError:
            continue

        if moment.tzinfo:
            moment = moment.astimezone(datetime.timezone.utc).replace(tzinfo=None)

        return moment

    _logger.warning("Webex: cannot read the timestamp %r", value)

    return False


def _int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0
