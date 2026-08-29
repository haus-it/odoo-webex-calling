# Odoo und Webex Calling verbinden — und die fünf Fallen, die Cisco nicht dokumentiert

*Ein quelloffenes Modul für Odoo 17 und 18, Community wie Enterprise.
LGPL-3, auf GitHub, ohne Anmeldung und ohne Antrag.*

---

Wer in Odoo arbeitet und mit Cisco Webex Calling telefoniert, hat zwei
Datenbestände, die nichts voneinander wissen. In Odoo steht, wer der Kunde
ist. In Webex steht, dass er heute um 9:14 Uhr angerufen hat und niemand
abgenommen hat. Beides einzeln ist wenig wert.

Die Schnittstellen dafür sind seit Jahren öffentlich. Was fehlt, sind nicht
die Endpunkte — es sind die fünf Dinge, an denen man scheitert, ohne dass
irgendwo steht, warum. Wir haben sie beim Betrieb echter Kundenanlagen
eingesammelt und in ein Modul geschrieben, das wir jetzt offenlegen:

**[github.com/haus-it/odoo-webex-calling](https://github.com/haus-it/odoo-webex-calling)**

## Was das Modul tut

* Einmalige Freigabe über OAuth. **Ihr Webex-Kennwort wird dabei weder
  abgefragt noch gespeichert** — die Anmeldung passiert bei Cisco, Odoo
  bekommt danach nur einen Schlüssel.
* Nächtlicher Abruf der Anrufdaten in ein Modell `webex.call`.
* Jeder Anruf wird über die Rufnummer einem `res.partner` zugeordnet.
* Ein abgesicherter Endpunkt `/webex/lookup`, den eine Telefonanlage oder
  eine Webex-Kachel fragen kann, **während es klingelt**.

Alle angeforderten Rechte sind **ausschließlich lesend**. Das Modul schreibt
nichts nach Webex zurück.

---

## Die fünf Fallen

### 1. 720 Stunden — und keine Stunde länger

Cisco gibt Anrufdaten **30 Tage rückwirkend** heraus. Das ist keine
Voreinstellung, die man hochsetzen kann, sondern eine harte Grenze.

Die Folge ist unangenehmer, als sie klingt: Ein Abgleich, der fünf Wochen
lang nicht lief, lässt sich nicht reparieren. Die fehlenden Tage sind
endgültig weg. Und man merkt es nicht, weil nichts kaputtgeht — die Zahlen
werden einfach kleiner.

Deshalb beginnt der Abruf im Modul beim **letzten erfolgreichen Lauf** und
nicht bei „heute". Ein Auftrag, der nur den heutigen Tag holt, verliert
jeden Tag, an dem der Cron nicht ansprang, und schweigt darüber.

### 2. `invalid_scope` sagt nicht, welcher

Cisco lehnt die **gesamte** Freigabe ab, sobald **ein** angeforderter
Berechtigungsbereich bei der Integration nicht eingetragen ist. Welcher,
verrät die Fehlermeldung nicht. Vier von fünf richtig gesetzten Bereichen
ergeben: keine Verbindung.

Die fünf sind:

```
spark-admin:calling_cdr_read
spark-admin:locations_read
spark-admin:devices_read
spark-admin:people_read
spark-admin:telephony_config_read
```

Der letzte ist der, den alle vergessen. Ohne ihn erscheinen Anrufwarte­
schlangen mit ihrer **Rufnummer statt mit ihrem Namen** — der Anrufdatensatz
nennt nur die Nummer, wie die Warteschlange heißt, steht ausschließlich in
der Anlagenkonfiguration.

Das Modul kann deshalb bewusst auf die vier Kernbereiche zurückfallen. Aber
als **Häkchen, nicht als stiller Automatismus**: Ein Programm, das seine
eigene Rechteanfrage heimlich verkleinert, bis irgendetwas durchgeht, ist
das Gegenteil von nachvollziehbar.

### 3. HTTP 451 — Ihre Daten liegen woanders

Cisco betreibt die Auswertung regional getrennt. Eine europäische
Organisation, die die globale Adresse fragt, wird mit **HTTP 451**
abgewiesen — und die Fehlermeldung nennt die richtige Adresse im Klartext.

Das Modul liest sie aus der Fehlermeldung, merkt sie sich und wiederholt den
Aufruf. Das ist besser als eine Region in der Konfigurationsdatei: Die
Region gehört zum Kunden, nicht zu Ihrer Installation.

### 4. Zwölf Stunden pro Abfrage

Jede CDR-Abfrage über ein Fenster von mehr als zwölf Stunden wird abgelehnt.
Der Client zerlegt den Zeitraum selbst — ein Aufrufer, der das wissen muss,
ist ein Aufrufer, der es vergisst.

### 5. Ein Gespräch, siebzehn Zeilen

Das ist die wichtigste, und die einzige, die auch dann noch schadet, wenn
alles technisch funktioniert.

Ein Anruf über eine **Rufgruppe** erzeugt **eine Zeile je angeklingeltem
Apparat**. Bei einem unserer Kunden bestand ein einziges Gespräch aus
siebzehn Datensätzen: sechzehn Kollegen, die nicht abgenommen haben, und
einer, der abgenommen hat.

Wer Zeilen zählt, liest eine Rufgruppe als Wand verpasster Anrufe. Über
einen kompletten Datenbestand gemessen lagen bei uns **7,5 Datensätze auf
einem Gespräch**. Eine Kennzahl „verpasste Anrufe", die daraus entsteht, ist
nicht ungenau — sie ist falsch.

Die Klammer um die Zeilen ist die `Correlation ID`. Im Modul steht dafür
`webex.call.count_conversations()`, und der Kommentar darüber erklärt,
warum es die Methode gibt.

**Nebenbei, gleiche Kategorie:** `ORIGINATING` und `TERMINATING` beschreiben
die *Verbindungsrichtung*, nicht die betriebliche. Wer sie vertauscht, dreht
jede Erreichbarkeitszahl um, die je auf dieser Tabelle aufbaut.

---

## Einrichtung in fünf Minuten

1. Integration anlegen unter **developer.webex.com → My Webex Apps**.
   Redirect-URI: `https://ihr-odoo/webex/callback` — Cisco vergleicht
   zeichengenau.
2. Alle **fünf** Bereiche anhaken (siehe oben).
3. In **Control Hub**: Das freigebende Konto braucht Administratorrechte und
   unter *Analytics* die Rolle **Webex Calling CDR API Access**. Wichtig:
   Eine Rolle wirkt nur in einem **neuen** Token. Wer sie nachträglich
   vergibt, muss erneut freigeben — sonst bleibt es beim 403, obwohl die
   Rolle gesetzt ist.
4. In Odoo: *Webex Calling → Konfiguration*, Client-ID und Geheimnis
   eintragen, **Mit Webex verbinden**.
5. **Jetzt importieren.** Der erste Lauf reicht höchstens 30 Tage zurück.

---

## Und wenn es mehr sein soll als eine Tabelle

Das Modul bringt die Anrufe **in** Odoo. Die andere Richtung — der Name des
Anrufers erscheint in der Webex-Kachel, während das Telefon klingelt —
braucht keine Installation in Odoo: Unser Portal
**[hausit-portal.de](https://hausit-portal.de)** spricht mit einem
unveränderten Odoo über JSON-RPC und durchsucht die Rufnummernfelder, die
Ihr `res.partner` tatsächlich hat. Ein lesender Odoo-Benutzer genügt.

Beides zusammen macht das, was jedes für sich nicht kann: Odoo führt den
Kundendatensatz, das Portal wertet über Standorte, Warteschlangen und
Benutzer aus — und zeigt beim Klingeln, wer dran ist.

### Welche Systeme sonst noch angebunden sind

Neben Odoo: **SAP Cloud for Customer, HubSpot, Pipedrive, Zoho CRM,
monday.com, Microsoft 365 (Outlook), Microsoft Dynamics 365 Business
Central, lexoffice (Lexware Office), sevdesk, casavi, Propstack** und
**Freshdesk**. Das Anbindungsformat ist beschreibend statt programmiert —
ein neues System ist eine Beschreibungsdatei, keine Auslieferung.

**Telefonie:** Webex Calling, Microsoft Teams Phone und
**[Placetel](https://www.placetel.de/preise?ref=7x8t2xyViH4qTQWErm2aUxhSUesQggDi)**
— ab 6,90 € je Benutzer und Monat, „Webex für Placetel" ab 14,90 €. Placetel
selbst verbindet Microsoft Teams, HubSpot, Salesforce, DATEV, Freshdesk,
monday.com, Zoho, Pipedrive, Miro und Slido.

### In 19 Sprachen

Das Portal ist **vollständig** übersetzt — nicht teilweise, und nachgezählt
statt behauptet: 1.632 von 1.632 Texten in jeder einzelnen Sprache.

> Dansk · Deutsch · English · Español · Français · Italiano · Lietuvių ·
> Magyar · Nederlands · Norsk · Polski · Română · Slovenčina · Suomi ·
> Svenska · Türkçe · Čeština · Русский · Українська

Datum, Zahlenformat und das Zugriffsprotokoll folgen der Sprache des Lesers
mit. Ein Protokoll, das man nicht lesen kann, ist kein Nachweis.

---

## Was das Modul bewusst nicht tut

Es berechnet **keine Leistungsbewertung**. Anrufzahlen sagen, wer wie viele
Kunden erreicht hat — nicht, wer gut arbeitet. Ein Innendienst mit fünf
Gesprächen am Tag kann mehr bewegt haben als fünfzig Wahlversuche. Wer
daraus eine Bewertung von Mitarbeitern macht, braucht in Deutschland die
Zustimmung des Betriebsrats (§ 87 Abs. 1 Nr. 6 BetrVG).

Und eine offene Angabe zum Reifegrad: Die beschriebenen Webex-Fallen stammen
aus dem Wirkbetrieb, dagegen haben wir uns tatsächlich gestoßen. **Der
Odoo-Code selbst ist noch nicht auf einer laufenden Datenbank installiert
worden und bringt keine Testsuite mit.** Behandeln Sie die erste
Installation als Pilot. Der Quelltext ist offen, jede nicht offensichtliche
Entscheidung steht als Kommentar daneben — genau dafür ist LGPL da.

---

## Mitmachen

Pull Requests willkommen, besonders für Rufnummernvarianten anderer Länder
in `_variants()` und für Odoo 16.

Fragen zu Webex Calling, zu Placetel, zu einer Anbindung, die es noch nicht
gibt — oder wenn das lieber jemand anderes betreiben soll:

**+49 5251 2020505** · **[www.haus-it.de/support](https://www.haus-it.de/support)**
