"""Verwaltungsseite „Laptop-Anwender“: Stand je Anwender, Einladungen, Abgabe/Ausgabe, Import, Export."""
import csv

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import TemplateView, View

from pretix.base.models import Checkin
from pretix.control.permissions import EventPermissionRequiredMixin

from .admin_only import ist_admin
from .models import Teilnehmer
from .services import (
    STATUS, abgabe_buchen, anlegen, anwender_status, ausgabe_buchen, einladen, einladungslink, importiere, lese_csv,
    scan_zuruecknehmen,
)


def _url(request, name="control"):
    return reverse(f"plugins:pretix_laptopbuchung:{name}", kwargs={
        "organizer": request.event.organizer.slug, "event": request.event.slug,
    })


def _gefiltert(request):
    rows = anwender_status(request.event)
    welle, status, q = request.GET.get("welle", ""), request.GET.get("status", ""), request.GET.get("q", "").strip().lower()
    if welle:
        rows = [r for r in rows if r["tn"].welle == welle]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if q:
        rows = [r for r in rows if q in f"{r['tn'].name} {r['tn'].email} {r['tn'].inventarnummer}".lower()]
    return rows


class AnwenderView(EventPermissionRequiredMixin, TemplateView):
    template_name = "pretix_laptopbuchung/control.html"
    permission = "event.orders:read"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        alle = anwender_status(self.request.event)
        ctx["rows"] = _gefiltert(self.request)
        ctx["wellen"] = sorted({r["tn"].welle for r in alle})
        ctx["status_choices"] = [(k, v[0]) for k, v in STATUS.items()]
        ctx["summen"] = [(k, STATUS[k][0], STATUS[k][1], sum(1 for r in alle if r["status"] == k)) for k in STATUS]
        ctx["gesamt"] = len(alle)
        ctx["offen_je_welle"] = [
            (w, sum(1 for r in alle if r["tn"].welle == w and not r["tn"].eingeladen_am)) for w in ctx["wellen"]
        ]
        ctx["darf_schreiben"] = self.request.user.has_event_permission(
            self.request.organizer, self.request.event, "event.orders:write", request=self.request)
        # CSV-Import nur für Administratoren; das IT-Team legt Anwender einzeln an
        ctx["darf_importieren"] = ctx["darf_schreiben"] and ist_admin(self.request)
        return ctx


class AktionView(EventPermissionRequiredMixin, View):
    permission = "event.orders:write"

    SCANS = {
        "abgegeben": (abgabe_buchen, "Laptop {inv} als abgegeben markiert."),
        "ausgegeben": (ausgabe_buchen, "Laptop {inv} als ausgegeben markiert."),
    }
    ZURUECK = {"abgabe_zurueck": Checkin.TYPE_ENTRY, "ausgabe_zurueck": Checkin.TYPE_EXIT}

    def post(self, request, *args, **kwargs):
        event = request.event
        aktion = request.POST.get("aktion", "")
        tn_pk = request.POST.get("tn")
        if ":" in aktion:  # Zeilen-Schaltflächen: "<aktion>:<anwender-id>"
            aktion, tn_pk = aktion.split(":", 1)
        if aktion == "anlegen":
            try:
                tn = anlegen(event, request.POST.get("name", ""), request.POST.get("email", ""),
                             request.POST.get("inventarnummer", ""), request.POST.get("welle", ""), user=request.user)
            except ValueError as e:
                messages.error(request, f"Anwender nicht angelegt: {e}")
            else:
                messages.success(request, f"{tn.name} ({tn.inventarnummer}) angelegt – {tn.welle}, noch nicht eingeladen.")
        elif aktion == "import":
            if not ist_admin(request):
                messages.error(request, "Der CSV-Import ist nur für Administratoren möglich.")
                return redirect(_url(request))
            f = request.FILES.get("datei")
            welle = request.POST.get("welle", "").strip()
            if not f or not welle:
                messages.error(request, "Bitte CSV-Datei und Bezeichnung der Welle angeben.")
                return redirect(_url(request))
            try:
                result = importiere(event, lese_csv(f.read().decode("utf-8-sig")), welle, user=request.user)
            except (ValueError, UnicodeDecodeError) as e:
                messages.error(request, f"Import fehlgeschlagen: {e}")
                return redirect(_url(request))
            neu = sum(1 for _, n in result if n)
            messages.success(request, f"{welle}: {neu} Anwender neu angelegt, {len(result) - neu} waren schon vorhanden.")
        elif aktion in ("einladen_welle", "einladen_auswahl"):
            qs = Teilnehmer.objects.filter(event=event).select_related("event")
            if aktion == "einladen_welle":
                qs = qs.filter(welle=request.POST.get("welle", ""), eingeladen_am__isnull=True).order_by("pk")
                anzahl = request.POST.get("anzahl", "").strip()
                if anzahl.isdigit() and int(anzahl) > 0:
                    qs = qs[:int(anzahl)]  # gestaffelt: nur die nächsten N der Welle
            else:
                qs = qs.filter(pk__in=request.POST.getlist("auswahl"))
            n = 0
            for tn in qs:
                einladen(tn, user=request.user)
                n += 1
            messages.success(request, f"{n} Einladung(en) verschickt.")
        elif aktion in self.SCANS or aktion in self.ZURUECK:
            tn = Teilnehmer.objects.filter(event=event, pk=tn_pk).select_related("event").first()
            if not tn:
                messages.error(request, "Anwender nicht gefunden.")
            elif aktion in self.SCANS:
                funktion, text = self.SCANS[aktion]
                try:
                    funktion(tn, user=request.user)
                    messages.success(request, f"{tn.name}: " + text.format(inv=tn.inventarnummer))
                except Exception as e:
                    messages.error(request, f"{tn.name}: Aktion nicht möglich ({e}).")
            else:
                scan_zuruecknehmen(tn, self.ZURUECK[aktion], user=request.user)
                messages.success(request, f"{tn.name}: zurückgenommen.")
        return redirect(_url(request) + ("?" + request.POST["zurueck"] if request.POST.get("zurueck") else ""))


class ExportView(EventPermissionRequiredMixin, View):
    permission = "event.orders:read"

    def get(self, request, *args, **kwargs):
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="laptop-anwender-{request.event.slug}.csv"'
        resp.write("﻿")
        w = csv.writer(resp, delimiter=";")
        w.writerow(["Name", "E-Mail", "Inventarnummer", "Welle", "Einladungslink", "Angeschrieben am",
                    "Einladungen", "Status", "Termin", "Buchung", "Abgegeben am", "Ausgegeben am"])
        tz = request.event.timezone
        fmt = lambda d: d.astimezone(tz).strftime("%d.%m.%Y %H:%M") if d else ""
        for r in _gefiltert(request):
            tn, t = r["tn"], r["termin"]
            w.writerow([tn.name, tn.email, tn.inventarnummer, tn.welle, einladungslink(tn),
                        fmt(tn.eingeladen_am), tn.einladungen, r["status_label"],
                        fmt(t.subevent.date_from) if t and t.subevent else "", t.order.code if t else "",
                        fmt(r["abgegeben_am"]), fmt(r["ausgegeben_am"])])
        return resp


def _belegung(event, slots):
    """Freie Plätze, Kontingentgröße und gebuchte Anwender je Termin."""
    from collections import defaultdict

    from pretix.base.services.quotas import QuotaAvailability

    from .models import Buchung

    quotas = list(event.quotas.filter(subevent__in=slots))
    qa = QuotaAvailability(full_results=False)
    qa.queue(*quotas)
    qa.compute()
    frei, groesse = {}, {}
    for q in quotas:
        frei[q.subevent_id] = min(frei.get(q.subevent_id, 10 ** 6), qa.results[q][1] or 0)
        groesse[q.subevent_id] = q.size
    belegt = defaultdict(list)
    for b in (Buchung.objects.filter(position__subevent__in=slots, position__canceled=False,
                                     position__order__status__in=("p", "n"))
              .select_related("teilnehmer", "position__order").order_by("erstellt")):
        belegt[b.position.subevent_id].append(b)
    out = []
    for se in slots:
        n, g = len(belegt.get(se.pk, [])), groesse.get(se.pk)
        out.append({"se": se, "frei": frei.get(se.pk, 0), "groesse": g, "belegt": belegt.get(se.pk, []),
                    "ueberbucht": bool(g is not None and n > g)})
    return out


class TermineView(EventPermissionRequiredMixin, TemplateView):
    """Termine eines Tages mit Belegung; ein Klick öffnet den Termin (dort Zuweisung)."""
    template_name = "pretix_laptopbuchung/termine.html"
    permission = "event.orders:read"

    def get_context_data(self, **kwargs):
        from datetime import date

        from django.utils.timezone import now

        ctx = super().get_context_data(**kwargs)
        event = self.request.event
        tz = event.timezone
        tage = sorted({se.date_from.astimezone(tz).date() for se in event.subevents.filter(active=True)})
        heute = now().astimezone(tz).date()
        try:
            tag = date.fromisoformat(self.request.GET.get("tag", ""))
        except ValueError:
            tag = next((t for t in tage if t >= heute), tage[0] if tage else heute)
        slots = [se for se in event.subevents.filter(active=True).order_by("date_from")
                 if se.date_from.astimezone(tz).date() == tag]
        ctx.update(tage=tage, tag=tag, slots=_belegung(event, slots))
        # Anwendersuche: Termine einzelner Anwender anzeigen
        suche = self.request.GET.get("suche", "").strip()
        ctx["suche"] = suche
        if suche:
            s = suche.lower()
            ctx["treffer"] = [r for r in anwender_status(event)
                              if s in f"{r['tn'].name} {r['tn'].email} {r['tn'].inventarnummer}".lower()][:50]
        return ctx


class TerminView(EventPermissionRequiredMixin, TemplateView):
    """Ein Termin: gebuchte Anwender und Zuweisung (auch über die Platzgrenze hinaus)."""
    template_name = "pretix_laptopbuchung/termin.html"
    permission = "event.orders:read"

    def get_context_data(self, **kwargs):
        from django.http import Http404

        ctx = super().get_context_data(**kwargs)
        event = self.request.event
        se = event.subevents.filter(pk=self.kwargs["subevent"], active=True).first()
        if not se:
            raise Http404()
        ctx["slot"] = _belegung(event, [se])[0]
        ctx["tag"] = se.date_from.astimezone(event.timezone).date()
        ctx["darf_schreiben"] = self.request.user.has_event_permission(
            self.request.organizer, event, "event.orders:write", request=self.request)
        return ctx


class AnwenderSucheView(EventPermissionRequiredMixin, View):
    """JSON für das Suchfeld (select2): Anwender ohne aktiven Termin, Suche nach Name, E-Mail, Inventarnummer."""
    permission = "event.orders:write"

    def get(self, request, *args, **kwargs):
        from django.db.models import Q
        from django.http import JsonResponse

        from pretix.base.models import Order

        from .models import Buchung

        q = request.GET.get("query", "").strip()
        try:
            seite = max(1, int(request.GET.get("page", 1)))
        except ValueError:
            seite = 1
        gebucht = Buchung.objects.filter(teilnehmer__event=request.event, position__canceled=False,
                                         position__order__status__in=(Order.STATUS_PAID, Order.STATUS_PENDING)
                                         ).values("teilnehmer_id")
        qs = Teilnehmer.objects.filter(event=request.event).exclude(pk__in=gebucht).order_by("name")
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(email__icontains=q) | Q(inventarnummer__icontains=q))
        pro_seite = 20
        treffer = list(qs[(seite - 1) * pro_seite:seite * pro_seite + 1])
        return JsonResponse({
            "results": [{"id": tn.pk, "text": f"{tn.name} – {tn.inventarnummer} ({tn.email})"}
                        for tn in treffer[:pro_seite]],
            "pagination": {"more": len(treffer) > pro_seite},
        })


class TerminZuweisenView(EventPermissionRequiredMixin, View):
    permission = "event.orders:write"

    def post(self, request, *args, **kwargs):
        from .services import BereitsGebucht, BuchungFehlgeschlagen, buchen

        event = request.event
        se = event.subevents.filter(pk=self.kwargs["subevent"], active=True).first()
        tn = Teilnehmer.objects.filter(event=event, pk=request.POST.get("teilnehmer")).first()
        zurueck = reverse("plugins:pretix_laptopbuchung:termin", kwargs={
            "organizer": event.organizer.slug, "event": event.slug, "subevent": self.kwargs["subevent"]})
        if not tn or not se:
            messages.error(request, "Bitte einen Anwender auswählen.")
            return redirect(zurueck)
        try:
            op = buchen(tn, se.pk, user=request.user, ueberbuchen=True)
        except BereitsGebucht as e:
            messages.error(request, f"{tn.name} hat bereits einen Termin (Buchung {e.position.order.code}).")
        except BuchungFehlgeschlagen as e:
            messages.error(request, f"{tn.name}: Termin konnte nicht zugewiesen werden ({e}).")
        else:
            messages.success(request, f"{tn.name} ist dem Termin zugewiesen (Buchung {op.order.code}); "
                                      f"die Bestätigung mit Ticket wurde an {tn.email} geschickt.")
        return redirect(zurueck)


class BestellverlaufView(EventPermissionRequiredMixin, TemplateView):
    """Bestellverlauf (pretix-Protokoll) einer Terminbuchung – ersetzt „Transaktionen ansehen“."""
    template_name = "pretix_laptopbuchung/bestellverlauf.html"
    permission = "event.orders:read"

    def get_context_data(self, **kwargs):
        from django.http import Http404

        ctx = super().get_context_data(**kwargs)
        order = self.request.event.orders.filter(code=self.kwargs["code"]).first()
        if not order:
            raise Http404()
        ctx["order"] = order
        return ctx


class TagesuebersichtView(EventPermissionRequiredMixin, TemplateView):
    """Dashboard eines Tages: je Termin Uhrzeit, Anwender und Inventarnummern (für einen Bildschirm, lädt neu)."""
    template_name = "pretix_laptopbuchung/tagesuebersicht.html"
    permission = "event.orders:read"

    def get_context_data(self, **kwargs):
        from datetime import date

        from django.utils.timezone import now

        ctx = super().get_context_data(**kwargs)
        event = self.request.event
        tz = event.timezone
        tage = sorted({se.date_from.astimezone(tz).date() for se in event.subevents.filter(active=True)})
        heute = now().astimezone(tz).date()
        try:
            tag = date.fromisoformat(self.request.GET.get("tag", ""))
        except ValueError:
            tag = next((t for t in tage if t >= heute), tage[-1] if tage else heute)
        slots = [se for se in event.subevents.filter(active=True).order_by("date_from")
                 if se.date_from.astimezone(tz).date() == tag]
        belegung = _belegung(event, slots)
        status = {r["tn"].pk: r for r in anwender_status(event)}
        for s in belegung:
            s["anwender"] = [status.get(b.teilnehmer_id) for b in s["belegt"]]
        ctx.update(
            tag=tag, heute=heute, slots=belegung, jetzt=now(),
            vorher=max((t for t in tage if t < tag), default=None),
            nachher=min((t for t in tage if t > tag), default=None),
            summe=sum(len(s["belegt"]) for s in belegung),
        )
        return ctx
