# -*- coding: utf-8 -*-
# Copyright (c) 2026 Mentor GmbH, Am Hoppenhof 30a, 33104 Paderborn
# Haus iT Caller ID - https://hausit-portal.de
#
# Veroeffentlicht unter der GNU Lesser General Public License v3.
# Siehe LICENSE im selben Verzeichnis.
"""The connection to one Webex Calling organisation."""

import datetime
import logging
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .webex_client import (ADMIN_SCOPES, CORE_SCOPES, RETENTION, WebexClient,
                           WebexError)

_logger = logging.getLogger(__name__)


class WebexConnection(models.Model):
    _name = "webex.connection"
    _description = "Webex Calling connection"

    # NOTE: no _rec_name = "display_name" here. display_name is *derived*
    # from _rec_name, so pointing one at the other is a loop.

    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda s: s.env.company)

    client_id = fields.Char(required=True)
    client_secret = fields.Char(required=True, groups="base.group_system")

    # Tokens are secrets. groups= keeps them out of every export and every
    # read by a user who is not an administrator.
    access_token = fields.Char(groups="base.group_system", copy=False)
    refresh_token = fields.Char(groups="base.group_system", copy=False)
    token_expires_at = fields.Datetime(copy=False)

    state_nonce = fields.Char(groups="base.group_system", copy=False)
    org_id = fields.Char(readonly=True, copy=False)

    analytics_base = fields.Char(
        readonly=True, copy=False,
        help="Learned from Cisco on the first HTTP 451. Call data is served "
             "regionally; this is the address for THIS organisation.")

    request_queue_names = fields.Boolean(
        string="Also request queue names", default=True,
        help="Adds spark-admin:telephony_config_read. Without it call queues "
             "show their number instead of their name. If Cisco answers "
             "invalid_scope, untick this and authorise again - you keep "
             "calls, locations, users and devices.")

    last_sync = fields.Datetime(readonly=True, copy=False)
    last_error = fields.Char(readonly=True, copy=False)
    call_count = fields.Integer(compute="_compute_call_count")

    # WHY A SEPARATE FLAG INSTEAD OF TESTING refresh_token IN THE VIEW
    # A field the view switches on has to be IN the view, and the refresh
    # token has no business being sent to a browser - not even an
    # administrator’s. This carries the one bit the form actually needs.
    is_connected = fields.Boolean(compute="_compute_is_connected")

    @api.depends("refresh_token")
    def _compute_is_connected(self):
        for record in self:
            record.is_connected = bool(record.sudo().refresh_token)

    # Not stored, so it is recomputed on every read - which is what we
    # want here. The depends is on the record itself; depending on the
    # calls would rewrite this on every import for no benefit.
    def _compute_call_count(self):
        for record in self:
            record.call_count = self.env["webex.call"].search_count(
                [("connection_id", "=", record.id)])

    @api.depends("org_id")
    def _compute_display_name(self):
        for record in self:
            record.display_name = record.org_id or _("not connected yet")

    # ---------------------------------------------------------------- oauth

    def action_authorize(self):
        """Open Cisco's consent screen.

        The customer's Webex password is neither asked for nor stored here -
        the sign-in happens at Cisco, and this database only ever receives a
        token afterwards. Worth saying in the UI, because people ask.
        """
        self.ensure_one()

        self.state_nonce = secrets.token_urlsafe(24)

        scopes = ADMIN_SCOPES if self.request_queue_names else CORE_SCOPES

        return {
            "type": "ir.actions.act_url",
            "target": "self",
            "url": self._client().authorize_url(
                self._redirect_uri(), self.state_nonce, scopes),
        }

    def _redirect_uri(self):
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url")

        return base.rstrip("/") + "/webex/callback"

    def _client(self):
        self.ensure_one()
        record = self.sudo()

        return WebexClient(
            client_id=record.client_id,
            client_secret=record.client_secret,
            access_token=record.access_token,
            refresh_token=record.refresh_token,
            analytics_base=record.analytics_base or None,
        )

    def _store(self, client):
        """Write back whatever the client learned during the call."""
        self.sudo().write({
            "access_token": client.access_token,
            "refresh_token": client.refresh_token,
            "analytics_base": client.analytics_base,
        })

    def _ensure_token(self):
        """Refresh a few minutes early.

        A token that expires *during* a request produces a 401 in the middle
        of a ringing phone, and that is the one moment where a retry is too
        late to be useful.
        """
        self.ensure_one()
        record = self.sudo()

        soon = fields.Datetime.now() + datetime.timedelta(minutes=5)

        if record.access_token and record.token_expires_at \
                and record.token_expires_at > soon:
            return record._client()

        client = record._client()
        body = client.refresh()
        record._store(client)
        record.token_expires_at = fields.Datetime.now() + datetime.timedelta(
            seconds=int(body.get("expires_in") or 3600))

        return client

    # ----------------------------------------------------------------- sync

    @api.model
    def _cron_sync(self):
        for connection in self.search([("refresh_token", "!=", False)]):
            try:
                connection.sync()
            except Exception as error:          # noqa: BLE001 - cron must go on
                connection.sudo().last_error = str(error)[:500]
                _logger.exception("Webex sync failed for %s", connection.org_id)

    def action_sync(self):
        self.sync()

        return True

    def sync(self):
        """Fetch everything since the last successful run.

        WHY IT CATCHES UP INSTEAD OF FETCHING "TODAY"
        Cisco keeps call data for 720 hours. A run that only ever asks for
        today silently loses every day the cron did not fire - and nobody
        notices, because the numbers simply get smaller. So the window
        starts at the last successful run, capped by the retention limit.
        """
        self.ensure_one()

        client = self._ensure_token()

        end = fields.Datetime.now().replace(tzinfo=datetime.timezone.utc)
        start = self.last_sync.replace(tzinfo=datetime.timezone.utc) \
            if self.last_sync else end - datetime.timedelta(days=2)

        floor = end - RETENTION
        lost = None
        if start < floor:
            lost = (floor - start).days
            start = floor

        try:
            rows = client.cdr_feed(start, end)
        except WebexError as error:
            self.sudo().last_error = str(error)[:500]
            raise UserError(str(error)) from error

        self._store(client)

        created = self.env["webex.call"]._absorb(self, rows)

        self.sudo().write({
            "last_sync": fields.Datetime.now(),
            "last_error": False,
        })

        if lost:
            _logger.warning(
                "Webex: %s day(s) were older than the 720 hour window and are "
                "permanently gone for organisation %s.", lost, self.org_id)

        return created

    # --------------------------------------------------------------- lookup

    @api.model
    def resolve(self, number):
        """Who is calling? Returns a partner or None.

        Deliberately tries several spellings instead of demanding one.
        A CRM stores what somebody typed; a phone system reports E.164.
        "+493023125000" and "030 23125000" are the same telephone and two
        different strings, and only one side of that can be fixed.
        """
        partner = self.env["res.partner"]
        digits = "".join(character for character in (number or "")
                         if character.isdigit())

        if len(digits) < 5:
            # Too short to be a phone number: an internal extension, a
            # withheld number, or noise. Matching on it would produce a
            # confident wrong name, which is worse than no name at all.
            return None

        for variant in _variants(digits):
            found = partner.search(
                ["|", ("phone", "ilike", variant), ("mobile", "ilike", variant)],
                limit=2)

            # Exactly one hit, or nothing. Two partners sharing a number
            # means a head office line - naming one of them at random would
            # be a guess wearing a nametag.
            if len(found) == 1:
                return found

        return None


def _variants(digits):
    """Spellings of the same number, most specific first."""
    out = []

    def add(value):
        if value and value not in out:
            out.append(value)

    add("+" + digits)
    add(digits)

    # German national/international pair. Adjust for your own country code;
    # kept explicit rather than clever so it is obvious what it assumes.
    if digits.startswith("49"):
        add("0" + digits[2:])
    elif digits.startswith("0") and not digits.startswith("00"):
        add("+49" + digits[1:])
        add("49" + digits[1:])

    # Last resort: the final eight digits. Enough to be a subscriber number,
    # short enough to survive any prefix notation.
    if len(digits) >= 8:
        add(digits[-8:])

    return out
