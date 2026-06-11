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
```

Die SQLite-Datenbank liegt im Volume `bereitschaft_data`.

