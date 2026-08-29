# -*- coding: utf-8 -*-
{
    "name": "Webex Calling Connector",
    "summary": "Connect Odoo to Cisco Webex Calling: import call detail "
               "records, match callers to partners, look up numbers.",
    "description": """
Webex Calling Connector
=======================

Connects an Odoo database to a Cisco Webex Calling organisation.

What it does
------------
* One-time OAuth authorisation against Webex (read-only scopes).
* Nightly import of Call Detail Records (CDR) into ``webex.call``.
* Matches every call to a ``res.partner`` by phone number.
* Exposes a token-protected lookup endpoint so a phone system, a Webex
  embedded app or any screen-pop tool can ask Odoo "who is calling?".

What it deliberately does not do
--------------------------------
* It never writes anything back to Webex. All requested scopes are read-only.
* It does not record audio and it does not read message content.

Honesty note
------------
Cisco hands out call data for **720 hours** (30 days) only. A gap longer
than that cannot be filled afterwards - see the README.
""",
    "author": "haus iT / Mentor GmbH",
    "website": "https://www.haus-it.de",
    "support": "https://www.haus-it.de/support",
    "license": "LGPL-3",
    "category": "Productivity/Telephony",
    "version": "17.0.1.0.0",
    "depends": ["base", "phone_validation", "mail"],
    "external_dependencies": {"python": ["requests"]},
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/webex_views.xml",
    ],
    "installable": True,
    "application": True,
}
