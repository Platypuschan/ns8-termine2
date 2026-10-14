"""Richtet die pretix-Demo 'Laptop-Neuinstallation' ein (löscht Veranstalter 'it' und erzeugt ihn neu).

Aufruf:  [IT_PASSWORT=...] setup_demo.py [ADMIN-PASSWORT]   (IT_PASSWORT legt den Demo-Zugang it-team@example.invalid an)
Die Anwender (persönliche Einladungslinks) werden danach mit `python -m pretix laptop_import it laptop <csv> --welle ...` erzeugt.
"""
import datetime as dt
import os
import sys
from zoneinfo import ZoneInfo

import django

django.setup()

from django.db import transaction  # noqa: E402
from django.db.models import Q  # noqa: E402
from django_scopes import scopes_disabled  # noqa: E402

from pretix.base.models import (  # noqa: E402
    CheckinList, Event, Item, LogEntry, Order, OrderFee, OrderPayment, OrderPosition, Organizer, Question, Quota,
    SubEvent, Team, Transaction, User,
)
from pretix.base.reldate import RelativeDateWrapper  # noqa: E402

TZ = ZoneInfo("Europe/Berlin")
FIRST_DAY = dt.date(2026, 10, 19)  # Montag
WEEKS = 2
SLOT_MIN = 30
# Zeitblöcke pro Werktag (Beginn, Ende); Mittagspause 11:30–12:30
BLOCKS = [(dt.time(8, 0), dt.time(11, 30)), (dt.time(12, 30), dt.time(15, 30))]
PER_SLOT = 2

MAIL_TEXT = """Hallo {teilnehmer_name},

Ihr Termin zur Abgabe Ihres Laptops ist gebucht:

Termin:          {termin}
Ort:             IT-Abteilung, Raum 0.12
Inventarnummer:  {inventarnummer}

Ihr Ticket-Code – bitte bei Abgabe und Abholung des Laptops vorzeigen:

{ticket_qr}

Ihre Buchung ansehen:
{url}

Termin stornieren:
Falls Sie den Termin nicht wahrnehmen können, stornieren Sie ihn bitte über diesen Link.
Anschließend können Sie mit dem Link aus der ersten E-Mail einen neuen Termin buchen.
{url_cancel}

Ihre IT-Abteilung
"""

IT_EMAIL = "it-team@example.invalid"
IT_RECHTE = {"event.orders:read": True, "event.orders:write": True, "event.orders:checkin": True}


with scopes_disabled(), transaction.atomic():
    admin = User.objects.get(email="admin@localhost")
    if len(sys.argv) > 1:
        admin.set_password(sys.argv[1])
        admin.save()

    old = Organizer.objects.filter(slug="it").first()
    if old:
        # alte Demo inkl. Buchungen entfernen (pretix schützt diese Daten sonst vor dem Löschen)
        LogEntry.objects.filter(Q(organizer_id=old.pk) | Q(api_token__team__organizer=old)).delete()
        Transaction.objects.filter(order__event__organizer=old).delete()
        OrderPosition.all.filter(order__event__organizer=old).delete()
        OrderPayment.objects.filter(order__event__organizer=old).delete()
        OrderFee.all.filter(order__event__organizer=old).delete()
        Order.objects.filter(event__organizer=old).delete()
        old.delete_sub_objects()
        old.delete()
    org = Organizer.objects.create(name="IT-Abteilung", slug="it")
    # Administratoren: alles. IT-Abteilung: nur Bestellungen (Laptop-Anwender, Check-in, Web-Check-in);
    # ohne Einstellungen, Teams, Wertgutscheine, Geräte, Gutscheine und Veranstalter-Export.
    admins = Team.objects.create(organizer=org, name="Administratoren", all_events=True,
                                 all_event_permissions=True, all_organizer_permissions=True)
    admins.members.add(admin)
    it_team = Team.objects.create(organizer=org, name="IT-Abteilung", all_events=True,
                                  all_event_permissions=False, limit_event_permissions=IT_RECHTE,
                                  all_organizer_permissions=False, limit_organizer_permissions={})
    it_pw = os.environ.get("IT_PASSWORT")
    if it_pw:
        it_user = User.objects.filter(email=IT_EMAIL).first() or User.objects.create_user(IT_EMAIL, it_pw)
        it_user.set_password(it_pw)
        it_user.locale = "de"
        it_user.save()
        it_team.members.add(it_user)

    first = dt.datetime.combine(FIRST_DAY, BLOCKS[0][0], TZ)
    ev = Event.objects.create(
        organizer=org, name="Laptop-Neuinstallation", slug="laptop",
        currency="EUR", date_from=first, has_subevents=True,
        location="IT-Abteilung, Raum 0.12", live=True,
        plugins="pretix.plugins.sendmail,pretix.plugins.statistics,pretix.plugins.ticketoutputpdf,"
                "pretix.plugins.webcheckin,pretix_laptopbuchung",
    )
    s = ev.settings
    s.locales = ["de"]
    s.locale = "de"
    s.timezone = "Europe/Berlin"
    s.event_list_type = "week"
    s.show_times = True
    s.show_quota_left = True
    s.max_items_per_order = 1
    s.invoice_generate = "False"
    s.cancel_allow_user = True
    s.mail_attach_ical = True
    s.ticket_download = True       # Ticket (QR-Code) als PDF an der Bestätigungsmail
    s.mail_attach_tickets = True
    s.set("ticketoutput_pdf__enabled", True)  # Standard-PDF-Ticket mit QR-Code
    # Bestell-/Erinnerungsmails auch für Buchungen über den Kanal der Einladungslinks
    s.mail_sales_channel_placed_paid = ["web", "laptopbuchung"]
    s.mail_sales_channel_download_reminder = ["web", "laptopbuchung"]
    s.contact_mail = "it-rollout@example.invalid"
    # laptopbuchung: eigene Templates, keine nachträglichen Änderungen der Angaben
    s.laptopbuchung_templates = "pretix_laptopbuchung"
    # Shop-Farben: Blautöne der Uniklinik-Homepage
    s.primary_color = "#004077"
    s.theme_color_background = "#eef5fc"
    s.last_order_modification_date = RelativeDateWrapper(dt.datetime(2000, 1, 1, tzinfo=TZ))
    s.mail_subject_order_free = "Ihr Termin zur Laptop-Abgabe: {termin}"
    s.mail_text_order_free = MAIL_TEXT
    s.frontpage_text = (
        "<p>Ihr Laptop wird neu installiert. Bitte wählen Sie einen 30-Minuten-Termin, "
        "zu dem Sie das Gerät in der IT-Abteilung abgeben (Mo–Fr 8:00–11:30 und 12:30–15:30 Uhr). "
        "Pro Termin sind maximal 2 Plätze verfügbar.</p>"
    )

    # Produkt nur über den eigenen Verkaufskanal der Einladungslinks buchbar (nicht im normalen Shop)
    from pretix_laptopbuchung.services import verkaufskanal
    item = Item.objects.create(
        event=ev, name="Abgabe Laptop zur Neuinstallation", default_price=0,
        admission=True, active=True, all_sales_channels=False,
    )
    item.limit_sales_channels.set([verkaufskanal(org)])
    q = Question.objects.create(
        event=ev, question="Inventarnummer", identifier="INVENTARNUMMER",
        type=Question.TYPE_STRING, required=False, hidden=True,
    )
    q.items.add(item)
    # Check-in-Liste für die Laptop-Abgabe (alle Termine)
    CheckinList.objects.create(event=ev, name="Laptop-Abgabe", all_products=True)

    n_slots = 0
    for d in range(WEEKS * 7):
        day = FIRST_DAY + dt.timedelta(days=d)
        if day.weekday() >= 5:
            continue
        for start, ende in BLOCKS:
            t = dt.datetime.combine(day, start, TZ)
            end = dt.datetime.combine(day, ende, TZ)
            while t + dt.timedelta(minutes=SLOT_MIN) <= end:
                se = SubEvent.objects.create(
                    event=ev, name=ev.name, active=True, date_from=t,
                    date_to=t + dt.timedelta(minutes=SLOT_MIN),
                    location=ev.location,
                )
                quota = Quota.objects.create(event=ev, subevent=se, name="Plätze", size=PER_SLOT)
                quota.items.add(item)
                n_slots += 1
                t += dt.timedelta(minutes=SLOT_MIN)

    # Fußbereich (Verwaltung und Shop): lizenzkonform umformuliert – "powered by UK-IT Services" + "based on pretix"
    from pretix.base.settings import GlobalSettingsObject
    gs = GlobalSettingsObject()
    lc = dict(gs.settings.license_check_input or {})
    lc.update(poweredby_name="UK-IT Services", poweredby_url="https://ism.uk-koeln.de/HEAT/")
    gs.settings.license_check_input = lc

    print(f"{n_slots} Slots à {PER_SLOT} Plätze angelegt", file=sys.stderr)
