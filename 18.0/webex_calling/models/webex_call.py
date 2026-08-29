# -*- coding: utf-8 -*-
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
    duration = fields.Integer(readonly=True, help="Seconds of conversation.")
    ring_duration = fields.Integer(readonly=True, help="Seconds of ringing.")

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
    user_email = fields.Char(readonly=True)
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

        known = set(self.search([
            ("connection_id", "=", connection.id),
            ("report_id", "in", [r.get("Report ID") for r in rows if r.get("Report ID")]),
        ]).mapped("report_id"))

        values = []

        for row in rows:
            report_id = row.get("Report ID")

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
        direction = (row.get("Direction") or "").strip().lower()
        inbound = direction == "terminating"

        calling = (row.get("Calling number") or "").strip()
        called = (row.get("Called number") or "").strip()

        return {
            "connection_id": connection.id,
            "report_id": row.get("Report ID"),
            "correlation_id": row.get("Correlation ID") or None,
            "start_time": _parse_time(row.get("Start time")),
            "duration": _int(row.get("Duration")),
            "ring_duration": _int(row.get("Ring duration")),
            "direction": "inbound" if inbound else "outbound",
            "answered": (row.get("Answered") or "").strip().lower()
                        in ("true", "yes", "1"),
            "calling_number": calling or False,
            "called_number": called or False,
            "other_party": (calling if inbound else called) or False,
            "user_name": row.get("User") or False,
            "user_email": row.get("User email") or row.get("Email address") or False,
            "location": row.get("Location") or False,
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
