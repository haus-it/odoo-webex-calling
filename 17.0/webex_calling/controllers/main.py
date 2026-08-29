# -*- coding: utf-8 -*-
"""Two endpoints: the OAuth return, and "who is calling?"."""

import datetime
import hmac
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

    @http.route("/webex/lookup", type="json", auth="public", methods=["POST"],
                csrf=False)
    def lookup(self, number=None, token=None, **kw):
        """Resolve a phone number to a partner.

        For a screen pop: your phone system, a Webex embedded app or a
        desktop tool asks this while the phone is still ringing.

        WHY A SHARED SECRET AND NOT auth="user"
        The caller is a switchboard, not a person with a session. The token
        lives in a system parameter (``webex_calling.lookup_token``); if it
        is not set, this endpoint stays shut rather than open.

        WHY IT RETURNS SO LITTLE
        Name, company, a link. Not the address, not the balance, not the
        notes. A screen pop is answered in a second and read by whoever
        happens to be standing at the desk.
        """
        expected = request.env["ir.config_parameter"].sudo().get_param(
            "webex_calling.lookup_token")

        if not expected or not token or not hmac.compare_digest(
                str(expected), str(token)):
            return {"error": "unauthorised"}

        partner = request.env["webex.connection"].sudo().resolve(number)

        if not partner:
            return {"found": False}

        base = request.env["ir.config_parameter"].sudo().get_param("web.base.url")

        return {
            "found": True,
            "id": partner.id,
            "name": partner.name,
            "company": partner.parent_id.name or partner.commercial_company_name or None,
            "url": "%s/web#id=%s&model=res.partner&view_type=form" % (base.rstrip("/"), partner.id),
        }


def _page(title, message):
    return request.make_response(
        "<!doctype html><meta charset='utf-8'>"
        "<title>%s</title>"
        "<body style=\"font:15px/1.6 system-ui,sans-serif;margin:3rem auto;max-width:34em\">"
        "<h1 style='font-size:19px'>%s</h1><p>%s</p></body>"
        % (title, title, message),
        headers=[("Content-Type", "text/html; charset=utf-8")],
    )
