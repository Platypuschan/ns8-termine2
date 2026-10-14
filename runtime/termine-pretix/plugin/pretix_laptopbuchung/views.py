import logging

from django.http import HttpResponseNotAllowed
from django.shortcuts import redirect
from django.views import View

from pretix.multidomain.urlreverse import eventreverse

from .models import Teilnehmer
from .services import BereitsGebucht, BuchungFehlgeschlagen, aktive_buchung, buchen

logger = logging.getLogger(__name__)


def _order_url(event, op):
    return eventreverse(event, "presale:event.order", kwargs={"order": op.order.code, "secret": op.order.secret})


def _uebersicht(event, token=None, fehler=None, subevent_id=None):
    """Zurück zur Terminübersicht bzw. -seite; Hinweise als URL-Parameter (Erstbesucher haben keine Sitzung)."""
    if subevent_id and str(subevent_id).isdigit() and event.subevents.filter(pk=subevent_id, active=True).exists():
        url = eventreverse(event, "presale:event.index", kwargs={"subevent": subevent_id})
    else:
        url = eventreverse(event, "presale:event.index")
    params = [f"einladung={token}"] if token else []
    if fehler:
        params.append(f"fehler={fehler}")
    return redirect(url + ("?" + "&".join(params) if params else ""))


class EinladungView(View):
    """Persönlicher Link aus der E-Mail: prüft das Token und zeigt die Terminauswahl (oder die bestehende Buchung)."""

    def get(self, request, token, *args, **kwargs):
        event = request.event
        tn = Teilnehmer.objects.filter(event=event, token=token).first()
        if not tn:
            return _uebersicht(event, fehler="ungueltig")
        op = aktive_buchung(tn)
        if op:
            return redirect(_order_url(event, op) + "?bereits=1")
        return _uebersicht(event, token=tn.token)


class DirektBuchungView(View):
    """Bucht den gewählten Termin sofort: Warenkorb, Angaben und Prüfschritt entfallen."""

    def get(self, request, *args, **kwargs):
        return HttpResponseNotAllowed(["POST"])

    def post(self, request, *args, **kwargs):
        event = request.event
        token = (request.POST.get("einladung") or "").strip()
        subevent_id = request.POST.get("subevent") or None
        tn = Teilnehmer.objects.filter(event=event, token=token).first() if token else None
        if not tn:
            return _uebersicht(event, fehler="ungueltig", subevent_id=subevent_id)

        try:
            op = buchen(tn, subevent_id)
        except BereitsGebucht as e:
            return redirect(_order_url(event, e.position) + "?bereits=1")
        except BuchungFehlgeschlagen as e:
            return _uebersicht(event, token=tn.token, fehler=e.grund, subevent_id=subevent_id)
        order = op.order
        return redirect(eventreverse(event, "presale:event.order", kwargs={
            "order": order.code, "secret": order.secret}) + "?thanks=1")
