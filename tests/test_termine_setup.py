#
# SPDX-License-Identifier: GPL-3.0-or-later
#

import json
import os
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "imageroot", "pypkg"))
import termine_setup as ts  # noqa: E402


class TermineSetupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        self.sync = patch.object(ts, "_konten_uebernehmen")
        self.apply = self.sync.start()
        self.addCleanup(self.sync.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def test_standard_ist_smarthost(self):
        self.assertEqual(ts.read_settings(self.d)["mail_mode"], "smarthost")

    def test_extern_speichert_und_behaelt_passwort(self):
        ts.apply_request({"mail_mode": "external", "smtp": {"host": "smtp.x.org", "port": 587, "username": "u",
                                                            "password": "geheim", "encryption": "starttls"}}, self.d)
        s = ts.apply_request({"mail_mode": "external", "smtp": {"host": "smtp.x.org", "port": 465, "password": "",
                                                                "encryption": "tls"}}, self.d)
        self.assertEqual(s["external"]["password"], "geheim")
        self.assertEqual(s["external"]["port"], 465)
        mode = stat.S_IMODE(os.stat(os.path.join(self.d, ts.SETTINGS_FILE)).st_mode)
        self.assertEqual(mode, 0o600)

    def test_extern_braucht_host_und_gueltigen_port(self):
        with self.assertRaises(ts.SettingsError) as c:
            ts.apply_request({"mail_mode": "external", "smtp": {"host": ""}}, self.d)
        self.assertEqual(c.exception.field, "smtp_host")
        with self.assertRaises(ts.SettingsError) as c:
            ts.apply_request({"mail_mode": "external", "smtp": {"host": "a.b", "port": 0}}, self.d)
        self.assertEqual(c.exception.field, "smtp_port")
        with self.assertRaises(ts.SettingsError):
            ts.apply_request({"mail_mode": "brieftaube"}, self.d)
        with self.assertRaises(ts.SettingsError):
            ts.apply_request({"mail_from": "kein-mail"}, self.d)

    def test_mail_werte(self):
        s = ts.read_settings(self.d)
        smart = {"enabled": True, "host": "relay.x.org", "port": 587, "username": "r", "password": "p",
                 "encrypt_smtp": "starttls"}
        w = ts.mail_werte(s, smart, "termine.x.org")
        self.assertEqual((w["PRETIX_MAIL_HOST"], w["PRETIX_MAIL_TLS"], w["PRETIX_MAIL_SSL"]), ("relay.x.org", "on", "off"))
        self.assertEqual(w["PRETIX_MAIL_FROM"], "no-reply@termine.x.org")
        self.assertEqual(ts.mail_werte(s, {"enabled": False}, "t.x")["PRETIX_MAIL_HOST"], "127.0.0.1")
        s = ts.apply_request({"mail_mode": "external", "mail_from": "it@x.org", "smtp": {
            "host": "smtp.x.org", "port": 465, "password": "pw", "encryption": "tls"}}, self.d)
        w = ts.mail_werte(s, smart, "t.x")
        self.assertEqual((w["PRETIX_MAIL_HOST"], w["PRETIX_MAIL_PORT"], w["PRETIX_MAIL_SSL"], w["PRETIX_MAIL_FROM"]),
                         ("smtp.x.org", "465", "on", "it@x.org"))

    def test_konten_einmalig_und_passwoerter_neu(self):
        k = ts.ensure_konten("Termine.X.org", self.d)
        self.assertEqual((len(k["admins"]), len(k["mitarbeiter"])), (2, 10))
        self.assertEqual(k["admins"][0]["login"], "admin1@termine.x.org")
        self.assertEqual(k["mitarbeiter"][9]["login"], "it10@termine.x.org")
        self.assertEqual(len({x["passwort"] for x in k["admins"] + k["mitarbeiter"]}), 12)
        self.assertEqual(ts.ensure_konten("anders.org", self.d), k)  # nicht neu erzeugt
        alt = {x["login"]: x["passwort"] for x in k["admins"] + k["mitarbeiter"]}
        self.assertEqual(ts.passwoerter_neu("it03@termine.x.org", self.d), ["it03@termine.x.org"])
        neu = ts.read_konten(self.d)
        geaendert = [x["login"] for x in neu["admins"] + neu["mitarbeiter"] if x["passwort"] != alt[x["login"]]]
        self.assertEqual(geaendert, ["it03@termine.x.org"])
        self.assertEqual(len(ts.passwoerter_neu(None, self.d)), 12)
        with self.assertRaises(ts.SettingsError):
            ts.passwoerter_neu("unbekannt@x.org", self.d)

    def test_fehlgeschlagener_reset_behaelt_alte_anzeige_und_journal(self):
        vorher = ts.ensure_konten("termine.x.org", self.d)
        self.apply.side_effect = RuntimeError("Container ausgefallen")
        with self.assertRaises(RuntimeError):
            ts.passwoerter_neu(vorher["admins"][0]["login"], self.d)
        self.assertEqual(ts.read_konten(self.d), vorher)
        journal = os.path.join(self.d, ts.KONTEN_PENDING)
        with open(journal) as stream:
            geplant = json.load(stream)
        self.assertNotEqual(geplant["admins"][0]["passwort"], vorher["admins"][0]["passwort"])
        self.assertEqual(geplant["mitarbeiter"], vorher["mitarbeiter"])
        self.apply.side_effect = None
        ts.sync_konten(self.d)
        self.assertEqual(ts.read_konten(self.d), geplant)
        self.assertFalse(os.path.exists(journal))

    def test_abbruch_nach_db_commit_wird_wiederaufgenommen(self):
        vorher = ts.ensure_konten("termine.x.org", self.d)
        original_replace = os.replace
        def replace(src, dst):
            if str(src).endswith(ts.KONTEN_PENDING):
                raise OSError("Dateisystem vorübergehend ausgefallen")
            return original_replace(src, dst)
        with patch.object(ts.os, "replace", side_effect=replace):
            with self.assertRaises(OSError):
                ts.passwoerter_neu(vorher["admins"][0]["login"], self.d)
        applied = self.apply.call_args.args[0]
        ts.sync_konten(self.d)
        self.assertEqual(ts.read_konten(self.d), applied)

    def test_terminserie_wird_validiert_und_als_umgebung_geschrieben(self):
        request = {"initial_schedule": {"start_date": "2099-01-05", "weeks": 3,
                   "slot_minutes": 15, "capacity": 4, "location": "IT, Raum 2",
                   "contact_email": "help@example.org"}}
        ts.apply_request(request, self.d)
        ts.write_database_env(self.d)
        ts.write_pretix_env("termine.x.org", self.d)
        env = ts.read_envfile(os.path.join(self.d, ts.PRETIX_ENV))
        self.assertEqual(env["TERMINE_STARTDATUM"], "2099-01-05")
        self.assertEqual(env["TERMINE_PLAETZE"], "4")
        self.assertEqual(env["TERMINE_SLOT_MINUTEN"], "15")
        self.assertEqual(env["TERMINE_ORT"], "IT, Raum 2")
        before = ts.read_settings(self.d)
        for update in ({"weeks": 0}, {"slot_minutes": 1}, {"capacity": True},
                       {"location": "Ort\nENV=1"}, {"start_date": "2026-02-30"},
                       {"start_date": "2000-01-01"}, {"contact_email": "keine-mail"}):
            with self.subTest(update=update), self.assertRaises(ts.SettingsError):
                ts.apply_request({"initial_schedule": update}, self.d)
            self.assertEqual(ts.read_settings(self.d), before)

    def test_env_dateien(self):
        ts.write_database_env(self.d)
        pw = ts.read_envfile(os.path.join(self.d, ts.DATABASE_ENV))["POSTGRES_PASSWORD"]
        ts.write_database_env(self.d)  # bleibt
        self.assertEqual(ts.read_envfile(os.path.join(self.d, ts.DATABASE_ENV))["POSTGRES_PASSWORD"], pw)
        ts.write_pretix_env("termine.x.org", self.d)
        e = ts.read_envfile(os.path.join(self.d, ts.PRETIX_ENV))
        self.assertEqual((e["PRETIX_PRETIX_URL"], e["PRETIX_DATABASE_PASSWORD"]), ("https://termine.x.org", pw))
        cfg = ts.configuration(ts.read_settings(self.d), ts.ensure_konten("termine.x.org", self.d),
                               "termine.x.org", True, True, None)
        self.assertNotIn("password", cfg["smtp"])
        self.assertEqual(json.loads(json.dumps(cfg))["shop_url"], "https://termine.x.org/it/laptop/")


if __name__ == "__main__":
    unittest.main()
