"""Importiert Anwender aus einer CSV-Liste (name, email, inventarnummer); jeder bekommt einen persönlichen Link.

Ausgabe (stdout, CSV): name, email, inventarnummer, welle, link
"""
import csv
import sys

from django.core.management.base import BaseCommand, CommandError
from django_scopes import scopes_disabled

from pretix.base.models import Event

from ...services import einladungslink, importiere, lese_csv


class Command(BaseCommand):
    help = "Anwenderliste importieren (gibt die persönlichen Einladungslinks aus)"

    def add_arguments(self, parser):
        parser.add_argument("organizer")
        parser.add_argument("event")
        parser.add_argument("csvfile", help="Pfad zur CSV-Datei oder - für stdin")
        parser.add_argument("--welle", required=True, help="Bezeichnung der Welle, z. B. 'Welle 1'")

    @scopes_disabled()
    def handle(self, organizer, event, csvfile, welle, **opts):
        try:
            ev = Event.objects.get(organizer__slug=organizer, slug=event)
        except Event.DoesNotExist:
            raise CommandError("Veranstaltung nicht gefunden")
        text = sys.stdin.read() if csvfile == "-" else open(csvfile, encoding="utf-8-sig").read()
        try:
            result = importiere(ev, lese_csv(text), welle)
        except ValueError as e:
            raise CommandError(str(e))
        out = csv.writer(self.stdout, lineterminator="\n")
        out.writerow(["name", "email", "inventarnummer", "welle", "link"])
        for tn, _neu in result:
            out.writerow([tn.name, tn.email, tn.inventarnummer, tn.welle, einladungslink(tn)])
        neu = sum(1 for _, n in result if n)
        self.stderr.write(f"{neu} neu angelegt, {len(result) - neu} bereits vorhanden")
