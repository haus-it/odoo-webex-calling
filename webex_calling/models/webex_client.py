# -*- coding: utf-8 -*-
# Copyright (c) 2026 Mentor GmbH, Am Hoppenhof 30a, 33104 Paderborn
# Haus iT Caller ID - https://hausit-portal.de
#
# Veroeffentlicht unter der GNU Lesser General Public License v3.
# Siehe LICENSE im selben Verzeichnis.
"""A small, honest HTTP client for the Cisco Webex Calling APIs.

Everything in this file was learned the hard way while running this against
real customer organisations. The comments say *why*, because the "what" is
readable from the code and the "why" is what Cisco's documentation does not
tell you.

Deliberately dependency-light: ``requests`` and the standard library. No
SDK, so you can read every request that leaves your server.
"""

import datetime
import logging
import re

import requests

_logger = logging.getLogger(__name__)

AUTH_URL = "https://webexapis.com/v1/authorize"
TOKEN_URL = "https://webexapis.com/v1/access_token"
ANALYTICS_BASE = "https://analytics.webexapis.com/v1"

# Read-only, every single one of them.
#
# WHY telephony_config_read IS IN HERE
# A call detail record names a hunt group only by its number. What the
# queue is *called* lives in the switch configuration and nowhere else.
# Without this scope your reports show "+49 521 12345" where they should
# show "Support Bielefeld".
ADMIN_SCOPES = [
    "spark-admin:calling_cdr_read",
    "spark-admin:locations_read",
    "spark-admin:devices_read",
    "spark-admin:people_read",
    "spark-admin:telephony_config_read",
]

# The same set without the queue names.
#
# WHY A SECOND SET EXISTS
# Cisco rejects the *whole* authorisation with ``invalid_scope`` as soon as
# ONE requested scope is missing from your integration - and it does not say
# which one. A customer then has no connection at all, although four out of
# five scopes were fine. Falling back to this set costs exactly one thing:
# call queues appear with their number instead of their name.
#
# Make that fallback a conscious choice, never an automatic retry. A tool
# that quietly shrinks its own permission request until something goes
# through is the opposite of auditable.
CORE_SCOPES = ADMIN_SCOPES[:4]

# Cisco refuses any CDR query wider than this.
MAX_WINDOW = datetime.timedelta(hours=12)

# And it keeps nothing older than this. 720 hours. Thirty days. Hard limit.
RETENTION = datetime.timedelta(hours=720)


class WebexError(RuntimeError):
    """Carries Cisco's own wording. Ours would be less useful."""


class WebexClient:
    def __init__(self, client_id, client_secret, access_token=None,
                 refresh_token=None, analytics_base=ANALYTICS_BASE,
                 timeout=30):
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.analytics_base = (analytics_base or ANALYTICS_BASE).rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------------ auth

    def authorize_url(self, redirect_uri, state, scopes=None):
        """The URL you send the customer's Webex administrator to.

        Note that this needs an account with **administrator rights in
        Control Hub**. An ordinary user account is not allowed to read the
        organisation's call data, and Cisco's error for that case points in
        an unhelpful direction.
        """
        from urllib.parse import urlencode

        return AUTH_URL + "?" + urlencode({
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes or ADMIN_SCOPES),
            "state": state,
        })

    def exchange_code(self, code, redirect_uri):
        return self._token_call({
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        })

    def refresh(self):
        if not self.refresh_token:
            raise WebexError("No refresh token stored - authorise again.")

        return self._token_call({
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
        })

    def _token_call(self, payload):
        response = requests.post(TOKEN_URL, data=payload, timeout=self.timeout)
        body = _json(response)

        if response.status_code >= 400:
            hint = ""
            if body.get("error") == "invalid_scope":
                # This is the single most common wall, and the message is
                # actively misleading: it sounds like your request is wrong.
                # It is not. A scope is missing from the *integration*, at
                # developer.webex.com -> My Webex Apps -> your integration
                # -> Scopes.
                hint = (" - one of the read scopes is not ticked on the "
                        "integration itself. Check all five at "
                        "developer.webex.com -> My Webex Apps -> Scopes.")

            raise WebexError("Webex refused the token request (HTTP %s): %s%s" % (
                response.status_code,
                body.get("error_description") or body.get("error") or "no reason given",
                hint,
            ))

        self.access_token = body.get("access_token") or self.access_token
        self.refresh_token = body.get("refresh_token") or self.refresh_token

        return body

    # ------------------------------------------------------------------- cdr

    def cdr_feed(self, start, end, page_size=500):
        """Call detail records between two UTC datetimes.

        Splits the range into 12-hour slices by itself, because Cisco
        rejects anything wider - and a caller that has to know that is a
        caller that will forget it.
        """
        if end <= start:
            return []

        oldest = _utcnow() - RETENTION
        if start < oldest:
            # Not an error, but worth saying out loud: what you are asking
            # for is gone, and no retry will bring it back.
            _logger.warning(
                "Webex CDR: %s is beyond the 720 hour window; starting at %s "
                "instead. The gap before that is permanent.", start, oldest)
            start = oldest

        rows = []
        cursor = start

        while cursor < end:
            slice_end = min(cursor + MAX_WINDOW, end)
            rows.extend(self._cdr_slice(cursor, slice_end, page_size))
            cursor = slice_end

        return rows

    def _cdr_slice(self, start, end, page_size):
        from urllib.parse import urlencode

        query = urlencode({
            "startTime": _iso(start),
            "endTime": _iso(end),
            "max": page_size,
        })

        try:
            return self._paged(self.analytics_base + "/cdr_feed?" + query)
        except WebexError as error:
            # CALL DATA LIVES IN THE ORGANISATION'S REGION.
            #
            # Cisco runs analytics regionally. A European organisation asking
            # the global address is turned away with HTTP 451 - and the error
            # body names the correct address in plain text. So we learn it
            # and retry once.
            #
            # Better than a region setting in your config file: the region
            # belongs to the customer, not to your installation.
            match = re.search(r"should go to URL:\s*(https://[a-z0-9.\-]+)",
                              str(error), re.IGNORECASE)
            if not match:
                raise

            self.analytics_base = match.group(1).rstrip("/") + "/v1"
            _logger.info("Webex CDR: switching to regional endpoint %s",
                         self.analytics_base)

            return self._paged(self.analytics_base + "/cdr_feed?" + query)

    def _paged(self, url):
        """Follow RFC 5988 ``Link: <...>; rel="next"`` headers to the end."""
        out = []
        seen = 0

        while url:
            response = requests.get(
                url,
                headers={"Authorization": "Bearer %s" % self.access_token},
                timeout=self.timeout,
            )

            if response.status_code >= 400:
                raise WebexError("Webex answered HTTP %s: %s" % (
                    response.status_code,
                    (_json(response).get("message")
                     or response.text[:400] or "no reason given"),
                ))

            out.extend(_json(response).get("items") or [])

            url = _next_link(response.headers.get("Link"))

            seen += 1
            if seen > 200:
                # A runaway pager is worse than a short result: it looks
                # like work while it burns the token's rate limit.
                _logger.warning("Webex CDR: stopping after 200 pages.")
                break

        return out


def _next_link(header):
    if not header:
        return None

    for part in header.split(","):
        match = re.search(r'<([^>]+)>\s*;\s*rel="?next"?', part.strip())
        if match:
            return match.group(1)

    return None


def _json(response):
    try:
        body = response.json()
    except ValueError:
        return {}

    return body if isinstance(body, dict) else {"items": body}


def _iso(moment):
    return moment.astimezone(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (moment.microsecond // 1000)


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc)
