# -*- coding: utf-8 -*-
# Copyright (c) 2026 Mentor GmbH, Am Hoppenhof 30a, 33104 Paderborn
# Haus iT Caller ID - https://hausit-portal.de
#
# Veroeffentlicht unter der GNU Lesser General Public License v3.
# Siehe LICENSE im selben Verzeichnis.
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
    # The Odoo Apps store expects an e-mail address here, not a web page.
    "support": "callerid@haus-it.de",
    # First entry is the cover the store shows in its listing.
    "images": ["static/description/banner.png"],
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
