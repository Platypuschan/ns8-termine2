# ns8-termine2

NethServer-8-Modul der **UK-IT Services Terminvergabe**: pretix 2026.8.0 mit dem Plugin `pretix_laptopbuchung`
aus [termine-pretix](https://github.com/Platypuschan/termine-pretix) (Laptop-Neuinstallation, persönliche
Einladungslinks, Terminzuweisung, Annahme/Ausgabe per Check-in, Tagesübersicht).

## Installation

```sh
add-module ghcr.io/platypuschan/termine2:latest 1
```

Danach in der Modul-Oberfläche unter **Einstellungen** Adresse (FQDN), erste Terminserie und Mailversand eintragen und speichern.
Ohne Startdatum beginnt eine neue Serie am nächsten Montag (Europe/Berlin); fest eingebaute Demo-Termine gibt es nicht.
Wochen, Minuten pro Termin, Plätze pro Termin, Ort und Kontaktadresse sind für die erste Einrichtung konfigurierbar.
Bestehende Veranstaltungen und Buchungen werden beim Speichern und Update nicht neu erzeugt. Spätere
Terminänderungen erfolgen in pretix. Die Shop-Wochenansicht blättert ausschließlich mit den Pfeilen zur
vorherigen beziehungsweise nächsten Woche; der persönliche Einladungslink bleibt dabei erhalten.
Beim ersten Speichern

- wird die Datenbank angelegt und pretix eingerichtet (Veranstalter `it`, Veranstaltung `laptop`, Termine, Teams),
- werden **2 Admins** (`admin1@<adresse>`, `admin2@<adresse>`, Team „Administratoren“) und **10 IT-Mitarbeiter**
  (`it01@<adresse>` … `it10@<adresse>`, Team „IT-Abteilung“) mit zufälligen Passwörtern angelegt,
- werden die pretix-Standardzugänge `admin@localhost` und `it-team@example.invalid` deaktiviert.

## Einstellungsseite

| Bereich | Inhalt |
|---|---|
| Adresse | FQDN, Let's-Encrypt-Zertifikat, HTTP→HTTPS |
| Erste Terminserie | Startdatum (leer = nächster Montag), 1–52 Wochen, 5–180 Minuten, 1–1000 Plätze, Ort und Kontaktadresse; nur bei erstmaliger Anlage wirksam |
| E-Mail-Versand | **NS8-Smarthost** (Cluster-Einstellung, Änderungen werden automatisch übernommen) oder **externer SMTP-Server** (Server, Port, Verschlüsselung STARTTLS/SSL/keine, Benutzer, Passwort); Absenderadresse (leer = `no-reply@<adresse>`) |
| Zugänge | Login, Name und Passwort aller Admins und IT-Mitarbeiter; Passwort anzeigen/kopieren, einzeln oder alle **neu erzeugen** |

Verwaltung: `https://<adresse>/control/` – Shop: `https://<adresse>/it/laptop/` (gebucht wird nur über die
persönlichen Einladungslinks).

Aktionen auch per CLI:

```sh
api-cli run module/termine21/get-configuration
api-cli run module/termine21/reset-passwords --data '{"login":"it03@termine.example.org"}'
api-cli run module/termine21/reset-passwords --data '{}'      # alle Konten
```

Anwenderlisten importieren (`name;email;inventarnummer`):

```sh
runagent -m termine21 podman exec -i pretix-app termine-entrypoint anwender-import - --welle "Welle 1" < welle1.csv
```

## Aufbau

Pod `termine` (rootless, nur `127.0.0.1:${TCP_PORT}` → Traefik):

| Dienst | Image | Aufgabe |
|---|---|---|
| `pretix-app` | `termine2-runtime` (aus `runtime/`) | nginx, gunicorn, celery; Migrationen beim Start |
| `cron-app` | `termine2-runtime` | pretix' regelmäßige Aufgaben alle 5 Minuten |
| `postgresql-app` | `postgres:16` | Datenbank (Volume `postgres-data`) |
| `redis-app` | `redis:7` | Cache, Sitzungen, Warteschlange |

Die Zugänge werden vom Modul verwaltet: Passwortänderungen unter **Einstellungen → Zugänge** ausführen.
Ein normaler Kontenabgleich behält unveränderte Passwort-Hashes und laufende Sitzungen.
Ein einzelner Passwort-Reset verändert nur das gewählte Konto. Während einer unterbrochenen Übernahme
bewahrt `konten.pending.json` die neuen Daten auf; der nächste Abgleich beziehungsweise das Laden der
Einstellungen setzt dieselbe Übernahme fort. Bis zum Abschluss werden keine möglicherweise veralteten
Zugangsdaten angezeigt.

Modulzustand (`state/`, nur für den Modulbenutzer lesbar): `termine.json` (Mail-Einstellungen), `konten.json`
(Zugänge), `database.env`, `pretix.env`, `mail.env` (bei jedem Start von pretix neu erzeugt).

**Sicherung:** `termine.json`, `konten.json`, ein gegebenenfalls vorhandenes `konten.pending.json`, `database.env`, ein `pg_dump` der Datenbank und das Volume
`pretix-data`. Bei der Wiederherstellung wird die Datenbank eingespielt und die Konten werden erneut abgeglichen.

## Entwicklung

- `runtime/termine-pretix/` enthält den übernommenen Stand von termine-pretix (siehe `runtime/VERSION`).
- `build-images.sh` baut Modul-Image und (lokal) das Laufzeit-Image; der Tag des Laufzeit-Images ergibt sich aus
  dem Inhalt von `runtime/`.
- Unit-Tests: `python3 -m unittest discover -s tests -p 'test_*.py'`.
- pretix-Regressionstests: In einer Python-Umgebung `pip install 'pretix==2026.8.0'` und
  `pip install --no-deps -e runtime/termine-pretix/plugin`, danach `python tests/run-pretix-tests.py`.
  Geprüft werden echte Bestelltransaktionen, CSV-Import, Kontenabgleich und gerenderte Wochennavigation
  mit SQLite. PostgreSQL-Advisory-Locks werden dabei ersetzt; diese Prüfung ersetzt keinen NS8-Lauf.
- QEMU-Tests über den Workflow „Test module on QEMU“.
- **GHCR-Pakete** `termine2` und `termine2-runtime` müssen öffentlich sein, sonst können NS8 (und die QEMU-Tests)
  die Images nicht laden.
