# Webex Calling Connector for Odoo

Connect an Odoo Community database to a **Cisco Webex Calling** organisation:
import call detail records, match every caller to a partner, and answer the
question *"who is calling?"* while the phone is still ringing.

Licensed LGPL-3, like Odoo itself. Built and maintained by
[haus iT](https://www.haus-it.de) (Mentor GmbH, Paderborn), who run this
against real customer organisations every night.

---

## Why this exists

Cisco publishes the APIs. What Cisco does not publish is the handful of
facts that decide whether an integration works or quietly loses data. This
module is mostly those facts, written down in code:

| The trap | What actually happens |
|---|---|
| **720 hours** | Webex serves call data for 30 days and not one hour longer. A sync that has been broken for five weeks cannot be repaired — the missing days are gone for good. |
| **`invalid_scope`** | Cisco rejects the *entire* authorisation if **one** requested scope is missing from your integration, and it does not say which one. Four out of five correct scopes still get you nothing. |
| **HTTP 451** | Call data is served regionally. A European organisation asking the global endpoint is turned away — and the error body names the correct address. This module learns it and retries. |
| **12-hour window** | Any CDR query wider than 12 hours is refused. The client slices the range itself. |
| **One call, many rows** | A call through a hunt group writes **one row per extension that rang**. We have seen a single conversation arrive as seventeen rows. Count rows and your "missed calls" figure comes out roughly seven times too high. The bracket is `Correlation ID` — see `count_conversations()`. |
| **ORIGINATING / TERMINATING** | These describe the call *leg*, not the business direction. Swap them and every reachability number you build is inverted. |

## What it does

* **One-time OAuth** against Webex. The customer's Webex password is never
  asked for and never stored — the sign-in happens at Cisco.
* **Nightly import** of call detail records into `webex.call`, catching up
  from the last successful run rather than "today".
* **Caller matching** against `res.partner`, trying several spellings of the
  same number (`+4952512020808`, `05251 2020808`, …). Two partners sharing a
  number produce **no** match — a confident wrong name is worse than none.
* **A lookup endpoint** (`POST /webex/lookup`) so a phone system, a Webex
  embedded app or any screen-pop tool can ask Odoo who is calling.

## What it deliberately does not do

* It **never writes to Webex.** Every requested scope is read-only.
* It does not record audio and does not read message content.
* It does not compute performance ratings for employees. Call counts say who
  reached how many customers, not who works well — and in Germany, using
  them to assess staff requires works council approval
  (§ 87 (1) 6 BetrVG).

## Install

The repository carries one tree per Odoo release. Point your addons path at
the one you run:

```
odoo-webex-calling/
├── 17.0/webex_calling/     ← Odoo 17 (Community and Enterprise)
├── 18.0/webex_calling/     ← Odoo 18 (Community and Enterprise)
└── tools/make-17.sh        ← regenerates 17.0 from 18.0
```

```bash
git clone https://github.com/haus-it/odoo-webex-calling.git
pip install requests
# then add odoo-webex-calling/18.0 (or /17.0) to addons_path
```

Update the apps list and install **Webex Calling Connector**.

**Community and Enterprise** both work: the module depends only on `base`,
`mail` and `phone_validation`, all of which ship with Community. It adds no
Enterprise-only widgets, so nothing degrades on either edition.

The two version trees differ in exactly four mechanical places — the list
view tag, `view_mode`, and two web-client URLs. `17.0/` is therefore
**generated**, not hand-maintained: change `18.0/`, run `sh tools/make-17.sh`,
commit both. Two hand-kept copies would drift apart on the first bug fix,
and the drift would stay invisible until a customer on the older release hit
it.

## Set up

1. **Create the integration** at
   [developer.webex.com](https://developer.webex.com) → *My Webex Apps* →
   *Create an Integration*. Redirect URI:
   `https://your-odoo/webex/callback` — Cisco compares it character for
   character.
2. **Tick all five scopes** on the integration:
   `spark-admin:calling_cdr_read`, `spark-admin:locations_read`,
   `spark-admin:devices_read`, `spark-admin:people_read`,
   `spark-admin:telephony_config_read`.
   Miss one and you get `invalid_scope` with no hint which.
3. **In Control Hub**, the account you authorise with needs administrator
   rights, and under *Analytics* the role **Webex Calling CDR API Access**.
   A role only takes effect in a **new** token — if you add it after
   authorising, authorise again.
4. In Odoo: *Webex Calling → Configuration → Webex connections*, enter
   client id and secret, press **Connect with Webex**.
5. Press **Import now**. The first import reaches back 30 days at most.

If Cisco answers `invalid_scope` and you cannot find the missing scope,
untick **Also request queue names** and authorise again. You keep calls,
locations, users and devices; call queues then show their number instead of
their name.

## The lookup endpoint

Set a shared secret once:

*Settings → Technical → System Parameters* →
`webex_calling.lookup_token` = a long random string.
**Without this parameter the endpoint stays shut**, it does not fall open.

```bash
curl -X POST https://your-odoo/webex/lookup \
     -H 'Content-Type: application/json' \
     -d '{"number":"+4952512020808","token":"YOUR_SECRET"}'
```

```json
{"found": true, "id": 42, "name": "Erika Beispiel",
 "company": "Muster GmbH", "url": "https://your-odoo/odoo/contacts/42"}
```

A plain HTTP route with a JSON body, deliberately — not JSON-RPC. Odoo
renamed the JSON route type between releases, and a switchboard should not
have to build an envelope to ask one question. A wrong or missing token
gets **401** and nothing else; the three ways of being wrong are not told
apart.

It answers with name, company and a link — and nothing else. A screen pop is
read in one second by whoever happens to be standing at the desk; the
address, the balance and the notes have no business being on it.

---

## Where this fits

```
   Webex Calling  ──(CDR, read-only)──►  Odoo        ← this module
   Webex Calling  ──(analytics)───────►  hausit-portal.de
   hausit-portal.de  ──(JSON-RPC)─────►  Odoo        ← no module needed
```

**You do not need this module to use Odoo with
[hausit-portal.de](https://hausit-portal.de).** The portal talks to a stock
Odoo over JSON-RPC and searches whichever phone fields your `res.partner`
actually has — a read-only Odoo user is enough. This module is the *other*
direction: getting Webex call data **into** Odoo, next to your partners.

Use both and each does what it is good at: Odoo keeps the customer record,
the portal does the analysis across locations, queues and users — and shows
the caller's name in the Webex client while the phone rings.

### Other systems that can be connected

Beyond Odoo, hausit-portal.de currently connects: **SAP Cloud for Customer,
HubSpot, Pipedrive, Zoho CRM, monday.com, Microsoft 365 (Outlook),
Microsoft Dynamics 365 Business Central, lexoffice (Lexware Office),
sevdesk, casavi, Propstack and Freshdesk** — with a described-not-programmed
connector format, so a new system is a description file rather than a
release.

**Telephony:** Webex Calling, Microsoft Teams Phone and
[Placetel](https://www.placetel.de/preise?ref=7x8t2xyViH4qTQWErm2aUxhSUesQggDi)
(from €6.90 per user per month; "Webex für Placetel" from €14.90). Placetel
itself connects Microsoft Teams, HubSpot, Salesforce, DATEV, Freshdesk,
monday.com, Zoho, Pipedrive, Miro and Slido.

### Available in 19 languages

The portal is fully translated — not partly, and measured rather than
claimed: 1,632 of 1,632 texts in every one of them.

Dansk · Deutsch · English · Español · Français · Italiano · Lietuvių ·
Magyar · Nederlands · Norsk · Polski · Română · Slovenčina · Suomi ·
Svenska · Türkçe · Čeština · Русский · Українська

Dates, number formats and the audit log follow the reader's language too —
a log you cannot read is not an audit trail.

---

## Honesty notes

* This module is written against Cisco's documented behaviour and our own
  production experience with exactly these endpoints — the traps in the
  table above are ones we have actually walked into. **The Odoo code itself
  has not yet been installed and run on a live database, and it ships with
  no test suite.** Treat the first install as a pilot, not as a release.
  Read the code before you trust it with a customer — that is what LGPL is
  for, and every non-obvious decision is commented with its reason.
* Pull requests welcome, especially: other countries' number variants in
  `_variants()`, and Odoo 16 compatibility.

## Support

Questions about the module: open an issue.

Questions about Webex Calling, Placetel or a connection we have not built
yet — or if you would rather someone else ran this:

**+49 5251 2020505** · [www.haus-it.de/support](https://www.haus-it.de/support)
