#!/bin/sh
# Einstiegspunkt des termine-pretix-Images. Unbekannte Befehle gehen unverändert an pretix' eigenen Einstiegspunkt.
set -eu
PRETIX=/usr/local/bin/pretix
VERANSTALTER=it
VERANSTALTUNG=laptop

django() {
    (cd /pretix/src && DJANGO_SETTINGS_MODULE=production_settings DATA_DIR=/data/ python3 "$@")
}

vorlagen_kopieren() {
    mkdir -p /data/templates
    cp -r /opt/termine/templates/. /data/templates/
}

ist_eingerichtet() {
    django -c "
import sys, django
django.setup()
from django_scopes import scopes_disabled
from pretix.base.models import Organizer
with scopes_disabled():
    sys.exit(0 if Organizer.objects.filter(slug='$VERANSTALTER').exists() else 1)
"
}

case "${1:-all}" in
    all|web|webworker)
        vorlagen_kopieren
        exec "$PRETIX" "$@"
        ;;
    cron-schleife)
        # pretix' regelmäßige Aufgaben (Erinnerungen, Aufräumen); Intervall in Sekunden.
        # Als PID 1 ignoriert die Shell SIGTERM sonst; sleep im Hintergrund + wait, damit "docker stop" sofort greift.
        trap 'echo "termine: cron beendet"; exit 0' TERM INT
        while true; do
            "$PRETIX" cron || echo "termine: cron fehlgeschlagen" >&2
            sleep "${CRON_INTERVALL:-300}" &
            wait $!
        done
        ;;
    einrichten)
        # Legt Veranstalter, Veranstaltung, Termine, Teams usw. an (setup_demo.py).
        # Ohne --neu passiert nichts, wenn bereits eingerichtet; --neu LÖSCHT den Veranstalter samt Buchungen.
        vorlagen_kopieren
        django -m pretix migrate --noinput
        if [ "${2:-}" != "--neu" ] && ist_eingerichtet; then
            echo "termine: bereits eingerichtet – nichts geändert (\"einrichten --neu\" setzt alles neu auf und LÖSCHT Buchungen)."
            exit 0
        fi
        : "${ADMIN_PASSWORT:?ADMIN_PASSWORT setzen (Passwort für admin@localhost)}"
        IT_PASSWORT="${IT_PASSWORT:-}" django /opt/termine/setup_demo.py "$ADMIN_PASSWORT"
        echo "termine: eingerichtet. Anmeldung: admin@localhost${IT_PASSWORT:+, it-team@example.invalid}"
        ;;
    konten-sync)
        # Admins und IT-Mitarbeiter abgleichen (JSON auf stdin, siehe /opt/termine/konten.py)
        django /opt/termine/konten.py
        ;;
    demo-anwender)
        # Beispiel-Anwender (Welle 1 und 2) importieren; gibt die persönlichen Einladungslinks aus
        django -m pretix laptop_import "$VERANSTALTER" "$VERANSTALTUNG" /opt/termine/anwender-welle1.csv --welle "Welle 1"
        django -m pretix laptop_import "$VERANSTALTER" "$VERANSTALTUNG" /opt/termine/anwender-welle2.csv --welle "Welle 2"
        ;;
    anwender-import)
        # anwender-import <datei.csv|-> --welle "Welle 3"   (CSV: name;email;inventarnummer)
        shift
        django -m pretix laptop_import "$VERANSTALTER" "$VERANSTALTUNG" "$@"
        ;;
    *)
        exec "$PRETIX" "$@"
        ;;
esac
