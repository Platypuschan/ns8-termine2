"""Verhaltensprüfungen gegen die tatsächlichen pretix-Modelle und Bestelltransaktionen."""
import datetime as dt
import io
import json
from contextlib import nullcontext
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace
from unittest.mock import patch

from django.db import transaction
from django.template.loader import render_to_string
from django.test import RequestFactory, TransactionTestCase
from django.utils.timezone import now
from django_scopes import scopes_disabled

from pretix.base.models import Event, Item, Order, Organizer, Quota, SubEvent, Team, User
from pretix.base.signals import order_placed
from pretix_laptopbuchung import services
from pretix_laptopbuchung.control import AnwenderView
from pretix_laptopbuchung.models import Buchung, Teilnehmer

ROOT = Path(__file__).resolve().parents[1]


class PluginRegressions(TransactionTestCase):
    def setUp(self):
        self.scope = scopes_disabled()
        self.scope.__enter__()
        self.addCleanup(self.scope.__exit__, None, None, None)
        self.org = Organizer.objects.create(name="Test-IT", slug="it")
        self.event = Event.objects.create(
            organizer=self.org, name="Laptop", slug="laptop", currency="EUR",
            date_from=now() + dt.timedelta(days=14), has_subevents=True, live=True,
            plugins="pretix_laptopbuchung",
        )
        self.event.settings.locales = ["de"]
        self.event.settings.timezone = "Europe/Berlin"
        self.event.settings.invoice_generate = "False"
        self.event.settings.mail_sales_channel_placed_paid = []
        self.item = Item.objects.create(
            event=self.event, name="Abgabe", default_price=0, admission=True,
            active=True, all_sales_channels=False,
        )
        self.item.limit_sales_channels.add(services.verkaufskanal(self.org))
        self.slot = SubEvent.objects.create(
            event=self.event, name="Termin", active=True,
            date_from=now() + dt.timedelta(days=14),
            date_to=now() + dt.timedelta(days=14, minutes=30),
        )
        quota = Quota.objects.create(event=self.event, subevent=self.slot, name="Plätze", size=2)
        quota.items.add(self.item)
        self.tn = Teilnehmer.objects.create(
            event=self.event, name="Alice", email="alice@example.org", inventarnummer="INV-1", welle="Welle 1",
        )

    def book(self, **kwargs):
        with patch.object(services, "anwender_sperre", return_value=nullcontext()):
            return services.buchen(self.tn, self.slot.pk, **kwargs)

    def test_buchung_ist_zugeordnet_bevor_bestelltransaktion_committet(self):
        seen = []
        def observe(sender, order, **kwargs):
            seen.append((transaction.get_connection().in_atomic_block,
                         Buchung.objects.filter(teilnehmer=self.tn, position__order=order).exists()))
        observe.__module__ = "pretix_laptopbuchung.signals"
        order_placed.connect(observe, weak=False)
        try:
            position = self.book()
        finally:
            order_placed.disconnect(observe)
        self.assertEqual(seen, [(True, True)])
        self.assertEqual(Buchung.objects.get(teilnehmer=self.tn).position_id, position.pk)
        with self.assertRaises(services.BereitsGebucht):
            self.book()
        self.assertEqual(self.event.orders.count(), 1)

    def test_fehler_innerhalb_bestelltransaktion_rollt_zuordnung_zurueck(self):
        def fail(sender, **kwargs):
            raise RuntimeError("Transaktion fehlgeschlagen")
        fail.__module__ = "pretix_laptopbuchung.signals"
        order_placed.connect(fail, weak=False)
        try:
            with self.assertRaises(services.BuchungFehlgeschlagen):
                self.book()
        finally:
            order_placed.disconnect(fail)
        self.assertFalse(self.event.orders.exists())
        self.assertFalse(Buchung.objects.exists())

    def test_mailfehler_nach_commit_erzeugt_keine_doppelbuchung(self):
        self.event.settings.mail_sales_channel_placed_paid = ["laptopbuchung"]
        with patch("pretix.base.services.orders._order_placed_email", side_effect=RuntimeError("SMTP ausgefallen")):
            position = self.book()
        self.assertEqual(services.aktive_buchung(self.tn).pk, position.pk)
        with self.assertRaises(services.BereitsGebucht):
            self.book()
        self.assertEqual(self.event.orders.count(), 1)

    def test_alte_bestellung_ohne_zuordnung_wird_wiedergefunden(self):
        position = self.book()
        Buchung.objects.all().delete()
        self.assertEqual(services.aktive_buchung(self.tn).pk, position.pk)
        self.assertEqual(Buchung.objects.get().position_id, position.pk)
        with self.assertRaises(services.BereitsGebucht):
            self.book()

    def test_csv_strukturfehler_werden_als_bedienfehler_gemeldet(self):
        for text in (
            "name;email;inventarnummer\nBob;bob@example.org;INV-2;extra\n",
            "name;email;inventarnummer\nBob;bob@example.org\n",
            "ungueltig\nBob\n",
            "name;email;inventarnummer\n",
            "name;email;inventarnummer\nBob;keine-mail;INV-2\n",
            'name;email;inventarnummer\n"Bob;bob@example.org;INV-2\n',
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                services.lese_csv(text)

    def test_csv_bom_komma_und_quotierte_trenner(self):
        rows = services.lese_csv('\ufeffname,email,inventarnummer\n"Bob, Test",bob@example.org,INV-2\n')
        self.assertEqual(rows[0]["name"], "Bob, Test")
        self.assertEqual(services.importiere(self.event, rows, "Welle 2")[0][0].email, "bob@example.org")

    def test_csv_duplikat_laesst_keinen_teilimport_zurueck(self):
        rows = [
            {"name": "Bob", "email": "bob@example.org", "inventarnummer": "INV-2"},
            {"name": "Carol", "email": "carol@example.org", "inventarnummer": "inv-1"},
        ]
        with self.assertRaisesRegex(ValueError, "bereits vergeben"):
            services.importiere(self.event, rows, "Welle 2")
        self.assertEqual(Teilnehmer.objects.count(), 1)

    def test_identischer_wiederholter_import_ist_idempotent(self):
        rows = services.lese_csv("name;email;inventarnummer\nAlice;ALICE@example.org;INV-1\n")
        self.assertEqual(services.importiere(self.event, rows, "Welle 2"), [(self.tn, False)])
        self.assertEqual(Teilnehmer.objects.count(), 1)

    def test_konten_sync_behaelt_fremde_passwort_hashes_und_sitzungen(self):
        Team.objects.create(organizer=self.org, name="Administratoren")
        Team.objects.create(organizer=self.org, name="IT-Abteilung")
        konten = {"admins": [{"login": "admin1@example.org", "name": "Admin", "passwort": "admin-test"}],
                  "mitarbeiter": [{"login": "it01@example.org", "name": "IT", "passwort": "it-test"}]}
        def sync():
            with patch("sys.stdin", io.StringIO(json.dumps(konten))), patch("sys.stdout", io.StringIO()):
                runpy.run_path(str(ROOT / "runtime/docker/konten.py"))
        sync()
        user = User.objects.get(email="it01@example.org")
        before = user.password, user.get_session_auth_hash()
        sync()
        user.refresh_from_db()
        self.assertEqual((user.password, user.get_session_auth_hash()), before)
        konten["admins"][0]["passwort"] = "neues-admin-passwort"
        sync()
        user.refresh_from_db()
        self.assertEqual((user.password, user.get_session_auth_hash()), before)
        self.assertTrue(User.objects.get(email="admin1@example.org").check_password("neues-admin-passwort"))

    def test_wochenansicht_hat_nur_pfeile_und_erhaelt_einladungslink(self):
        request = RequestFactory().get("/it/laptop/", {"einladung": self.tn.token, "date": "2026-W53"})
        weeks = SimpleNamespace(
            date=dt.date(2026, 12, 28), before=dt.date(2026, 12, 21), after=dt.date(2027, 1, 4),
            has_before=True, has_after=True, week_format="W", days=[], any_events=False, show_names=False,
        )
        def render():
            return render_to_string("pretix_laptopbuchung/fragment_subevent_calendar_week.html",
                                    {"subevent_list": weeks, "event": self.event, "request": request})
        html = render()
        self.assertNotIn("<select", html)
        self.assertNotIn("<form", html)
        self.assertIn("2026-W52", html)
        self.assertIn("2027-W1", html)
        self.assertIn(self.tn.token, html)
        weeks.has_before = weeks.has_after = False
        html = render()
        self.assertNotIn("2026-W52", html)
        self.assertNotIn("2027-W1", html)

    def test_erste_terminserie_verwendet_konfigurierte_werte(self):
        User.objects.create_user("admin@localhost", "test")
        script = ROOT / "runtime/termine-pretix/setup_demo.py"
        env = {"TERMINE_STARTDATUM": "2099-01-05", "TERMINE_WOCHEN": "1",
               "TERMINE_SLOT_MINUTEN": "15", "TERMINE_PLAETZE": "4",
               "TERMINE_ORT": "IT, Raum 2", "TERMINE_KONTAKT": "help@example.org"}
        with patch.dict("os.environ", env), patch("sys.argv", [str(script), "test"]), \
                patch("sys.path", [str(script.parent)] + sys.path), patch("sys.stderr", io.StringIO()):
            runpy.run_path(str(script))
        event = Event.objects.get(organizer__slug="it", slug="laptop")
        self.assertEqual(event.subevents.count(), 130)
        self.assertEqual(event.subevents.order_by("date_from").first().date_from.date(), dt.date(2099, 1, 5))
        self.assertEqual(set(event.quotas.values_list("size", flat=True)), {4})
        self.assertEqual(event.location, "IT, Raum 2")
        self.assertEqual(event.settings.contact_mail, "help@example.org")
        self.assertIn("15-Minuten", str(event.settings.frontpage_text))

    def test_anwenderansicht_berechnet_status_nur_einmal_und_paginiert(self):
        Teilnehmer.objects.bulk_create([
            Teilnehmer(event=self.event, name=f"Test {i:03d}", email=f"test{i}@example.org",
                       inventarnummer=f"T-{i}", welle="Welle 1") for i in range(200)
        ])
        user = User.objects.create_user("admin@example.org", "test")
        Team.objects.create(organizer=self.org, name="Admin", all_events=True,
                            all_event_permissions=True, all_organizer_permissions=True).members.add(user)
        request = RequestFactory().get("/", {"page": "2"})
        request.event, request.organizer, request.user = self.event, self.org, user
        request.session = SimpleNamespace(session_key=None)
        view = AnwenderView()
        view.request, view.kwargs = request, {}
        with patch("pretix_laptopbuchung.control.anwender_status", wraps=services.anwender_status) as status:
            context = view.get_context_data()
        status.assert_called_once_with(self.event)
        self.assertEqual(context["gesamt"], 201)
        self.assertEqual(len(context["rows"]), 100)
        self.assertEqual(context["page_obj"].number, 2)
