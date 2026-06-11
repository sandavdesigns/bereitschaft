# Bereitschaft

Kleine interne Web-App zur Pflege von Rufbereitschaft und Einsätzen mit Monats-PDF im Formularstil.

## Start mit Docker Compose

```bash
docker compose up -d --build
```

Die App läuft danach auf `http://localhost:8080`.

Beim ersten Start wird ein Admin-Benutzer angelegt:

- Benutzer: `admin`
- Passwort: Wert aus `ADMIN_PASSWORD`, sonst `admin123`

Bitte das Passwort nach dem ersten Login über Umgebungsvariable ändern.

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

## Drucken

Für das unterschriftsfähige Formular ist die Schaltfläche **Druckansicht** vorgesehen.
Im Browser anschließend `Drucken` wählen und Kopf-/Fußzeilen deaktivieren.
So bleibt die Ausgabe auf einer A4-Seite und entspricht dem alten Formular deutlich besser als der serverseitige PDF-Export.
