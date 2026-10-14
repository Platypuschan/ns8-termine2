"""Import, Einladungsversand, Status sowie Abgabe/Ausgabe (Check-in/Check-out) der Laptop-Anwender."""
import csv
import io
import logging
import secrets
import uuid
from contextlib import contextmanager

from django.db import connection, transaction
from django.utils.timezone import now
from i18nfield.strings import LazyI18nString

from pretix.base.models import Checkin, CheckinList, CartPosition, Order, QuestionAnswer, SalesChannel, Voucher
from pretix.base.services.cart import CartError, CartManager
from pretix.base.services.orders import OrderError, _perform_order
from pretix.base.services.checkin import perform_checkin
from pretix.base.services.mail import mail
from pretix.multidomain.urlreverse import eventreverse_absolute

from .models import Buchung, Teilnehmer

logger = logging.getLogger(__name__)

VERKAUFSKANAL = "laptopbuchung"
INVENTAR_IDENTIFIER = "INVENTARNUMMER"
LOCK_NAMESPACE = 0x4C415054  # "LAPT"
CHECKIN_LISTE = "Laptop-Abgabe"

EINLADUNG_BETREFF = "Neuinstallation Ihres Laptops – bitte Termin buchen"
EINLADUNG_TEXT = """Hallo {name},

Ihr Laptop (Inventarnummer {inventarnummer}) wird neu installiert. Bitte buchen Sie über Ihren
persönlichen Link einen Termin, zu dem Sie das Gerät in der IT-Abteilung abgeben:

{link}

Der Link gilt nur für Sie. Bitte geben Sie ihn nicht weiter.

Ihre IT-Abteilung
"""


def einladungslink(tn):
    return eventreverse_absolute(tn.event, "plugins:pretix_laptopbuchung:einladung", kwargs={"token": tn.token})


def verkaufskanal(organizer):
    """Eigener Verkaufskanal: das Produkt ist nur über die Einladungslinks buchbar, nicht im normalen Shop."""
    sc = organizer.sales_channels.filter(identifier=VERKAUFSKANAL).first()
    if not sc:
        sc = SalesChannel.objects.create(organizer=organizer, identifier=VERKAUFSKANAL, type="api",
                                         label="Laptop-Einladungslinks")
    return sc


def lese_csv(text):
    """CSV (Trenner , oder ;) mit Spalten name, email, inventarnummer -> Liste von Dicts."""
    text = text.lstrip("﻿")
    lines = text.splitlines()
    if not lines:
        raise ValueError("Die Datei ist leer.")
    dialect = csv.Sniffer().sniff(lines[0], delimiters=",;")
    rows = [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
            for r in csv.DictReader(io.StringIO(text), dialect=dialect)]
    fehlend = {"name", "email", "inventarnummer"} - set(rows[0].keys() if rows else [])
    if fehlend:
        raise ValueError(f"Spalten fehlen: {', '.join(sorted(fehlend))}")
    return [r for r in rows if r["email"]]


@transaction.atomic
def importiere(event, rows, welle, user=None):
    """Legt neue Anwender an (bekannte E-Mail-Adressen werden übersprungen). Rückgabe: [(Teilnehmer, neu)]."""
    result = []
    for r in rows:
        tn = Teilnehmer.objects.filter(event=event, email__iexact=r["email"]).first()
        if tn:
            result.append((tn, False))
            continue
        tn = Teilnehmer.objects.create(event=event, name=r["name"], email=r["email"],
                                       inventarnummer=r["inventarnummer"], welle=welle)
        event.log_action("pretix_laptopbuchung.anwender.importiert", user=user,
                         data={"teilnehmer": tn.pk, "email": tn.email, "welle": welle})
        result.append((tn, True))
    return result


@transaction.atomic
def anlegen(event, name, email, inventarnummer, welle, user=None):
    """Legt einen einzelnen Anwender an (Verwaltung, ohne CSV). ValueError bei fehlenden/ungültigen/doppelten Angaben."""
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email

    name, email, inventarnummer, welle = (x.strip() for x in (name, email, inventarnummer, welle))
    if not (name and email and inventarnummer and welle):
        raise ValueError("Bitte Name, E-Mail, Inventarnummer und Welle angeben.")
    try:
        validate_email(email)
    except ValidationError:
        raise ValueError(f"„{email}“ ist keine gültige E-Mail-Adresse.")
    doppelt = Teilnehmer.objects.filter(event=event, email__iexact=email).first()
    if doppelt:
        raise ValueError(f"Die E-Mail-Adresse {email} ist schon vergeben ({doppelt.name}).")
    doppelt = Teilnehmer.objects.filter(event=event, inventarnummer__iexact=inventarnummer).first()
    if doppelt:
        raise ValueError(f"Die Inventarnummer {inventarnummer} ist schon vergeben ({doppelt.name}).")
    tn = Teilnehmer.objects.create(event=event, name=name, email=email, inventarnummer=inventarnummer, welle=welle)
    event.log_action("pretix_laptopbuchung.anwender.angelegt", user=user,
                     data={"teilnehmer": tn.pk, "email": tn.email, "welle": welle})
    return tn


def einladen(tn, user=None):
    """Schickt die Einladungsmail mit persönlichem Link und merkt sich Zeitpunkt und Anzahl."""
    event = tn.event
    betreff = event.settings.get("laptopbuchung_einladung_betreff") or EINLADUNG_BETREFF
    text = event.settings.get("laptopbuchung_einladung_text") or EINLADUNG_TEXT
    ctx = {"name": tn.name, "email": tn.email, "inventarnummer": tn.inventarnummer,
           "link": einladungslink(tn), "event": str(event.name)}
    mail(tn.email, betreff, LazyI18nString(text), ctx, event, locale="de",
         plain_text_only=True, no_order_links=True)
    tn.eingeladen_am = now()
    tn.einladungen += 1
    tn.save(update_fields=["eingeladen_am", "einladungen"])
    event.log_action("pretix_laptopbuchung.einladung", user=user,
                     data={"teilnehmer": tn.pk, "email": tn.email, "anzahl": tn.einladungen})


def aktive_buchung(tn):
    """Aktuell gültige Buchung (Bestellposition) des Anwenders oder None."""
    b = (Buchung.objects.filter(teilnehmer=tn, position__canceled=False,
                                position__order__status__in=(Order.STATUS_PAID, Order.STATUS_PENDING))
         .select_related("position__order", "position__subevent").order_by("-erstellt").first())
    return b.position if b else None


class BereitsGebucht(Exception):
    def __init__(self, position):
        super().__init__("Der Anwender hat bereits einen Termin.")
        self.position = position


class BuchungFehlgeschlagen(Exception):
    def __init__(self, grund, text):
        super().__init__(text)
        self.grund = grund  # "nicht_verfuegbar" | "technisch"


@contextmanager
def anwender_sperre(tn):
    """PostgreSQL-Advisory-Lock je Anwender: gleichzeitige Buchungsversuche laufen nacheinander.
    (pretix' Bestellfunktion nutzt eigene durable-Transaktionen, ein select_for_update drumherum geht nicht.)"""
    with connection.cursor() as c:
        c.execute("SELECT pg_advisory_lock(%s, %s)", [LOCK_NAMESPACE, tn.pk])
    try:
        yield
    finally:
        with connection.cursor() as c:
            c.execute("SELECT pg_advisory_unlock(%s, %s)", [LOCK_NAMESPACE, tn.pk])


def _aufraeumen(event, cart_id, zuweisung):
    CartPosition.objects.filter(event=event, cart_id=cart_id).delete()
    if zuweisung and not zuweisung.orderposition_set.exists():
        zuweisung.delete()


def buchen(tn, subevent_id, user=None, ueberbuchen=False):
    """Bucht einen Termin für den Anwender (Einladungslink oder Zuweisung durch die IT).
    pretix prüft dabei die Plätze; die Bestätigungsmail mit Ticket geht automatisch raus.
    ueberbuchen=True (Zuweisung durch die IT): ein interner Einmal-Gutschein mit „Kontingent ignorieren“ erlaubt die
    Buchung auch bei vollem Termin; sie zählt trotzdem zur Belegung (Selbstbucher sehen den Termin dann als voll)."""
    event = tn.event
    with anwender_sperre(tn):
        op = aktive_buchung(tn)
        if op:
            raise BereitsGebucht(op)
        item = event.items.filter(active=True).first()
        sc = verkaufskanal(event.organizer)
        cart_id = secrets.token_urlsafe(24) + "@laptopbuchung"
        zuweisung = None
        if ueberbuchen:
            zuweisung = Voucher.objects.create(
                event=event, code="ZUW-" + secrets.token_hex(6).upper(), item=item, subevent_id=subevent_id,
                max_usages=1, allow_ignore_quota=True, tag="IT-Zuweisung",
                comment=f"{tn.name} ({tn.inventarnummer}) – zugewiesen von {user.email if user else 'System'}",
            )
        try:
            cm = CartManager(event=event, cart_id=cart_id, sales_channel=sc)
            cm.add_new_items([{"item": item.pk, "variation": None, "count": 1, "subevent": subevent_id,
                               "voucher": zuweisung.code if zuweisung else None, "price": None, "seat": None}])
            cm.commit()
            positions = list(CartPosition.objects.filter(event=event, cart_id=cart_id))
            q = event.questions.filter(identifier=INVENTAR_IDENTIFIER).first()
            for p in positions:
                p.attendee_name_parts = {"_legacy": tn.name}
                p.attendee_email = tn.email
                p.save(update_fields=["attendee_name_parts", "attendee_email"])
                if q:
                    QuestionAnswer.objects.create(cartposition=p, question=q, answer=tn.inventarnummer)
            # wie der Checkout bei kostenlosen Warenkörben: implizite 'free'-Zahlung -> sofort bestätigt
            free_payment = [{"id": str(uuid.uuid4()), "provider": "free", "multi_use_supported": False,
                             "min_value": None, "max_value": None, "info_data": {}}]
            meta = {"laptopbuchung": {"teilnehmer": tn.pk, "zugewiesen_von": user.email if user else None}}
            result = _perform_order(event, free_payment, [p.id for p in positions], tn.email, "de", None,
                                    meta_info=meta, sales_channel=sc.identifier, cart_id=cart_id)
        except (CartError, OrderError) as e:
            _aufraeumen(event, cart_id, zuweisung)
            logger.info("Buchung abgelehnt (Anwender %s): %s", tn.pk, e)
            raise BuchungFehlgeschlagen("nicht_verfuegbar", str(e))
        except Exception as e:
            _aufraeumen(event, cart_id, zuweisung)
            logger.exception("Buchung fehlgeschlagen")
            raise BuchungFehlgeschlagen("technisch", str(e))
        order = event.orders.get(pk=result["order_id"])
        for p in order.positions.all():
            Buchung.objects.create(teilnehmer=tn, position=p)
        if user:
            order.log_action("pretix_laptopbuchung.zugewiesen", user=user, data={"teilnehmer": tn.pk})
        return order.positions.first()


def checkin_liste(event):
    """Check-in-Liste für alle Termine (wird bei Bedarf angelegt)."""
    cl = event.checkin_lists.filter(name=CHECKIN_LISTE).first()
    if not cl:
        cl = CheckinList.objects.create(event=event, name=CHECKIN_LISTE, all_products=True, subevent=None)
    return cl


def _scan(tn, typ, user=None):
    op = aktive_buchung(tn)
    if not op:
        raise ValueError(f"{tn.name} hat keinen gebuchten Termin.")
    perform_checkin(op, checkin_liste(tn.event), {}, force=True, ignore_unpaid=True, user=user, type=typ)
    return op


def abgabe_buchen(tn, user=None):
    """Laptop abgegeben = Einlass (Check-in) auf der aktiven Buchung."""
    return _scan(tn, Checkin.TYPE_ENTRY, user)


def ausgabe_buchen(tn, user=None):
    """Laptop an den Anwender zurückgegeben = Auslass (Check-out) auf der aktiven Buchung."""
    return _scan(tn, Checkin.TYPE_EXIT, user)


def scan_zuruecknehmen(tn, typ, user=None):
    op = aktive_buchung(tn)
    if not op:
        return 0
    n, _ = op.checkins.filter(list=checkin_liste(tn.event), type=typ).delete()
    op.order.log_action("pretix_laptopbuchung.scan_zurueckgenommen", user=user, data={"position": op.pk, "typ": typ})
    return n


STATUS = {
    "nicht_angeschrieben": ("nicht angeschrieben", "default"),
    "angeschrieben": ("angeschrieben", "info"),
    "gebucht": ("gebucht", "primary"),
    "nicht_erschienen": ("nicht erschienen", "danger"),
    "abgegeben": ("Laptop abgegeben", "warning"),
    "ausgegeben": ("Laptop ausgegeben", "success"),
}


def anwender_status(event):
    """Stand je Anwender. Stornierte Buchungen zählen nicht (Anwender gilt dann wieder als angeschrieben);
    pretix protokolliert Stornierungen selbst an der Bestellung."""
    tns = list(Teilnehmer.objects.filter(event=event).order_by("welle", "name"))
    termine = {}
    for b in (Buchung.objects.filter(teilnehmer__event=event, position__canceled=False,
                                     position__order__status__in=(Order.STATUS_PAID, Order.STATUS_PENDING))
              .select_related("position__order", "position__subevent").order_by("erstellt")):
        termine[b.teilnehmer_id] = b.position
    scans = {}
    cl = checkin_liste(event)
    for c in Checkin.objects.filter(list=cl, successful=True, position__order__event=event).order_by("datetime"):
        scans.setdefault((c.position_id, c.type), c.datetime)
    jetzt = now()
    out = []
    for tn in tns:
        t = termine.get(tn.pk)
        abgegeben = scans.get((t.pk, Checkin.TYPE_ENTRY)) if t else None
        ausgegeben = scans.get((t.pk, Checkin.TYPE_EXIT)) if t else None
        if t and ausgegeben:
            key = "ausgegeben"
        elif t and abgegeben:
            key = "abgegeben"
        elif t and t.subevent and (t.subevent.date_to or t.subevent.date_from) < jetzt:
            key = "nicht_erschienen"
        elif t:
            key = "gebucht"
        elif tn.eingeladen_am:
            key = "angeschrieben"
        else:
            key = "nicht_angeschrieben"
        out.append({"tn": tn, "status": key, "status_label": STATUS[key][0], "status_class": STATUS[key][1],
                    "termin": t, "abgegeben_am": abgegeben, "ausgegeben_am": ausgegeben})
    return out
