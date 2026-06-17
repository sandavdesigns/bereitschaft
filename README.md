# Bereitschaft

Kleine interne Web-App zur Pflege von Rufbereitschaft und Einsätzen mit Monats-PDF im Formularstil.

## Start mit Docker Compose

```bash
docker compose up -d --build
```

Die App läuft danach auf `http://localhost:8080`.

Die erste Anmeldung ist weiter unten beschrieben.

## Portainer

Als Stack kann diese `docker-compose.yml` verwendet werden. Sinnvolle Variablen:

```env
SECRET_KEY=bitte-aendern
ADMIN_PASSWORD=bitte-aendern
HOST_PORT=8080
APP_PORT=8080
```

Die SQLite-Datenbank liegt im Volume `bereitschaft_data`.

Die Compose-Datei zieht standardmäßig das fertige Image `ghcr.io/sandavdesigns/bereitschaft:latest`.
Portainer muss dadurch kein Image bauen.

## Erste Anmeldung

Beim ersten Start gibt es den Admin-Benutzer:

- Benutzer: `admin`
- Passwort: Wert aus `ADMIN_PASSWORD`, sonst `admin123`

Nach der Anmeldung sollte das Admin-Passwort geändert werden:

1. Oben auf **Stammdaten** gehen.
2. Unter **Passwort ändern** aktuelles und neues Passwort eintragen.
3. Speichern.

Oben rechts wird angezeigt, welcher Benutzer aktuell angemeldet ist.

## Benutzer verwalten

Admins öffnen **Benutzer** in der oberen Navigation.

Dort können neue Benutzer angelegt werden mit:

- Benutzername
- Startpasswort
- Personalnummer
- Vorname
- Name

### Passwort zurücksetzen

Wenn ein Benutzer sein Passwort vergessen hat:

1. Als Admin **Benutzer** öffnen.
2. Beim Benutzer ein temporäres Passwort eintragen.
3. **Zurücksetzen** klicken.
4. Das temporäre Passwort dem Benutzer geben.

Der Benutzer muss dieses Passwort beim nächsten Login sofort ändern. Bis dahin kann er die Anwendung nicht weiter benutzen.

## Bereitschaftsarten verwalten

Admins öffnen **Bereitschaftsarten**.

Eine Bereitschaftsart hat:

- **Interner Name**: wird in Auswahlfeldern angezeigt, damit mehrere ähnliche Arten unterscheidbar bleiben.
- **Anzeigename**: steht später in Tabellen und PDF. Mehrere Arten dürfen denselben Anzeigenamen haben.
- Zeiten für **Mo-Do**, **Fr**, **Sa/So** und **Feiertag**.

Nicht mehr benötigte Arten können deaktiviert werden. Löschen ist nur möglich, wenn die Art noch nicht in Bereitschaften oder Einsätzen verwendet wurde. Die Spalte **Nutzung** zeigt das an.

## Feiertage verwalten

Admins öffnen **Feiertage**.

Die App berechnet Thüringer Feiertage automatisch, inklusive beweglicher Feiertage. Über **Thüringen-Feiertage neu berechnen** kann das Jahr neu befüllt werden.

Feiertage werden in der Monatsansicht wie Wochenenden rot markiert und in der Summe **Sa/So/Feiertag** gezählt.

## Bereitschaft eintragen

Im Bereich **Bereitschaft** wählt der Benutzer:

1. Von Tag
2. Bis Tag
3. Art
4. Bei Freitag-Feiertag: **Vormittag** oder **Nachmittag**

Die App berechnet daraus die passenden Zeiten je Tag. Wenn ein Feiertag auf einen Freitag fällt, wird die Feiertagszeit geteilt:

- Vormittag: erste Hälfte, z. B. `06:00-12:00`
- Nachmittag: zweite Hälfte, z. B. `12:00-18:00`

In **Bereitschaften im Monat** kann diese Vormittag-/Nachmittag-Auswahl für den Eintrag nachträglich geändert werden.

## Einsatz / Mehrarbeit eintragen

Einsätze können nur an Tagen eingetragen werden, an denen eine Bereitschaft vorhanden ist.

Die Einsatzzeit muss innerhalb der Bereitschaftszeit liegen. Beispiel: Bei Bereitschaft `06:00-18:00` ist ein Einsatz ab `19:00` nicht erlaubt.

Bei Feiertagen ist nur **Bezahlen** möglich. Die App stellt das automatisch ein und zeigt in der Tabelle an, dass **Freizeit** gesperrt ist.

## Monatsübersicht

Die Tabelle zeigt pro Tag:

- Soll-Rufbereitschaft
- Einsatzzeiten
- Stunden
- Bemerkung
- Bezahlen/Freizeit
- Ist-Rufbereitschaft

In der Bemerkung steht zuerst die Bereitschaftsart. Wenn zusätzlich eine Bemerkung eingegeben wurde, steht sie danach, z. B.:

```text
Bereitschaft - Einsatz Server
```

## PDF herunterladen

Für das unterschriftsfähige Formular ist die Schaltfläche **PDF herunterladen** vorgesehen.
Die PDF-Ausgabe ist auf eine A4-Seite ausgelegt und kann direkt gedruckt werden.

Die obere Tabelle im PDF zeigt die einzelnen Bereitschaftstage. Wenn mehr Einträge vorhanden sind, wird zuerst die linke obere Tabelle gefüllt und danach rechts fortgesetzt.

Die untere Tabelle entspricht der Monatsübersicht und ist für den Ausdruck mit Unterschriftenbereich optimiert.

## Datenspeicherung

Die Daten liegen in einer SQLite-Datenbank im Docker-Volume `bereitschaft_data`.

Für Backups sollte dieses Volume regelmäßig gesichert werden.
