"""Verschickt die Einladungsmail an alle noch nicht angeschriebenen Anwender einer Welle."""
from django.core.management.base import BaseCommand, CommandError
from django_scopes import scopes_disabled

from pretix.base.models import Event

from ...models import Teilnehmer
from ...services import einladen


class Command(BaseCommand):
    help = "Einladungen für eine Welle verschicken (nur bisher nicht angeschriebene Anwender)"

    def add_arguments(self, parser):
        parser.add_argument("organizer")
        parser.add_argument("event")
        parser.add_argument("--welle", required=True)
        parser.add_argument("--erneut", action="store_true", help="auch bereits angeschriebene erneut anschreiben")
        parser.add_argument("--anzahl", type=int, help="nur die nächsten N (gestaffelt einladen)")

    @scopes_disabled()
    def handle(self, organizer, event, welle, erneut=False, anzahl=None, **opts):
        try:
            ev = Event.objects.get(organizer__slug=organizer, slug=event)
        except Event.DoesNotExist:
            raise CommandError("Veranstaltung nicht gefunden")
        qs = Teilnehmer.objects.filter(event=ev, welle=welle).select_related("event")
        if not erneut:
            qs = qs.filter(eingeladen_am__isnull=True)
        qs = qs.order_by("pk")
        if anzahl:
            qs = qs[:anzahl]
        n = 0
        for tn in qs:
            einladen(tn)
            n += 1
        self.stdout.write(f"{n} Einladungen verschickt")
