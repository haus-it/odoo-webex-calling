# -*- coding: utf-8 -*-
# Copyright (c) 2026 Mentor GmbH, Am Hoppenhof 30a, 33104 Paderborn
# Haus iT Caller ID - https://hausit-portal.de
#
# Veroeffentlicht unter der GNU Lesser General Public License v3.
# Siehe LICENSE im selben Verzeichnis.
"""Two endpoints: the OAuth return, and "who is calling?"."""

import datetime
import hmac
import json
from html import escape
import logging

from odoo import fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)


class WebexController(http.Controller):

    @http.route("/webex/callback", type="http", auth="user", website=False,
                methods=["GET"], csrf=False)
    def callback(self, code=None, state=None, error=None, **kw):
        """Where Cisco sends the administrator back to."""
        if error:
            return _page("Webex declined", error)

        connection = request.env["webex.connection"].sudo().search(
            [("state_nonce", "=", state)], limit=1) if state else None

        if not connection:
            # An unknown state is either a stale browser tab or somebody
            # trying their luck. Both deserve the same flat answer.
            return _page("Not expected",
                         "This authorisation does not belong to any pending "
                         "connection. Start again from the Webex connection "
                         "form.")

        if not hmac.compare_digest(connection.state_nonce or "", state or ""):
            return _page("Not expected", "State mismatch.")

        client = connection._client()

        try:
            body = client.exchange_code(code, connection._redirect_uri())
        except Exception as exc:                # noqa: BLE001 - shown to a human
            connection.last_error = str(exc)[:500]

            return _page("Webex declined", str(exc))

        connection._store(client)
        connection.write({
            "state_nonce": False,
            "org_id": body.get("orgId") or connection.org_id,
            "token_expires_at": fields.Datetime.now() + datetime.timedelta(
                seconds=int(body.get("expires_in") or 3600)),
            "last_error": False,
        })

        return request.redirect("/web#action=webex_calling.action_connection")

    @http.route("/webex/lookup", type="http", auth="public", methods=["POST"],
                csrf=False, save_session=False)
    def lookup(self, **kw):
        """Resolve a phone number to a partner.

        For a screen pop: your phone system, a Webex embedded app or a
        desktop tool asks this while the phone is still ringing.

        WHY type="http" AND NOT type="json"
        Odoo renamed the JSON route type between releases. A plain HTTP
        route with a JSON body behaves identically on 17 and 18, and a
        switchboard finds it far easier to call than JSON-RPC's envelope.
        One less thing that works on one version and not the other.

        WHY A SHARED SECRET AND NOT auth="user"
        The caller is a switchboard, not a person with a session. The token
        lives in a system parameter (``webex_calling.lookup_token``); if it
        is not set, this endpoint stays shut rather than falling open.

        WHY IT RETURNS SO LITTLE
        Name, company, a link. Not the address, not the balance, not the
        notes. A screen pop is answered in a second and read by whoever
        happens to be standing at the desk.
        """
        try:
            payload = json.loads(request.httprequest.get_data() or b"{}")
        except ValueError:
            payload = {}

        if not isinstance(payload, dict):
            payload = {}

        token = payload.get("token") or kw.get("token") or ""
        number = payload.get("number") or kw.get("number") or ""

        expected = request.env["ir.config_parameter"].sudo().get_param(
            "webex_calling.lookup_token")

        if not expected or not hmac.compare_digest(str(expected), str(token)):
            # Same answer for "no token configured", "wrong token" and
            # "no token sent". Telling them apart would help exactly one
            # kind of caller, and it is not the switchboard.
            return _json({"error": "unauthorised"}, status=401)

        partner = request.env["webex.connection"].sudo().resolve(number)

        if not partner:
            return _json({"found": False})

        base = request.env["ir.config_parameter"].sudo().get_param("web.base.url")

        return _json({
            "found": True,
            "id": partner.id,
            "name": partner.name,
            "company": partner.parent_id.name or partner.commercial_company_name or None,
            "url": "%s/web#id=%s&model=res.partner&view_type=form" % (base.rstrip("/"), partner.id),
        })


def _page(title, message):
    """A plain error page.

    ESCAPED, because ``message`` is whatever Cisco or an exception said, and
    that is text from outside this application. An error page that renders
    foreign text as markup is a cross-site scripting hole with an apology
    written on it.
    """
    return request.make_response(
        "<!doctype html><meta charset='utf-8'>"
        "<title>%s</title>"
        "<body style=\"font:15px/1.6 system-ui,sans-serif;margin:3rem auto;max-width:34em\">"
        "<h1 style='font-size:19px'>%s</h1><p>%s</p></body>"
        % (escape(title), escape(title), escape(message)),
        headers=[("Content-Type", "text/html; charset=utf-8")],
    )


def _json(payload, status=200):
    return request.make_response(
        json.dumps(payload),
        status=status,
        headers=[("Content-Type", "application/json; charset=utf-8"),
                 ("Cache-Control", "no-store")],
    )
