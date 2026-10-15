#
# SPDX-License-Identifier: GPL-3.0-or-later
#

"""Einstellungen, Konten und Konfigurationsdateien des Moduls „Terminvergabe“.

Dateien im Modulzustand (state/, alle nur für den Modulbenutzer lesbar):
  termine.json   Mail-Modus (Smarthost/extern), Daten des externen SMTP-Servers, Absender
  konten.json    2 Admins und 10 IT-Mitarbeiter mit Login und Passwort (für die Einstellungsseite)
  database.env   Zugangsdaten der PostgreSQL-Datenbank (create-module)
  pretix.env     pretix-Konfiguration (PRETIX_*), aus den Einstellungen erzeugt
  mail.env       Mail-Konfiguration für pretix, bei jedem Start von pretix neu erzeugt (bin/discover-mail)
"""

import datetime as dt
import fcntl
import json
import os
import re
import secrets
import string
import subprocess
import sys
from zoneinfo import ZoneInfo

SETTINGS_FILE = "termine.json"
KONTEN_FILE = "konten.json"
KONTEN_PENDING = "konten.pending.json"
DATABASE_ENV = "database.env"
PRETIX_ENV = "pretix.env"
MAIL_ENV = "mail.env"

ANZAHL_ADMINS = 2
ANZAHL_MITARBEITER = 10
INSTANZ_NAME = "UK-IT Services Terminvergabe"
MAIL_MODI = ("smarthost", "external")
VERSCHLUESSELUNG = ("none", "starttls", "tls")
PASSWORT_ZEICHEN = string.ascii_letters + string.digits


class SettingsError(Exception):
    def __init__(self, field, value, error):
        super().__init__(error)
        self.field = field
        self.value = value
        self.error = error


def _schreiben(path, inhalt):
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(inhalt)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _json_lesen(path, standard):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return standard


def _env_schreiben(path, werte):
    zeilen = []
    for key, value in werte.items():
        value = str(value)
        if "\n" in value:
            raise ValueError(f"{key}: Zeilenumbruch nicht erlaubt")
        zeilen.append(f"{key}={value}")
    _schreiben(path, "\n".join(zeilen) + "\n")


def neues_passwort(laenge=16):
    return "".join(secrets.choice(PASSWORT_ZEICHEN) for _ in range(laenge))


# --- Einstellungen ------------------------------------------------------------------------------------------------

def read_settings(state_dir="."):
    s = _json_lesen(os.path.join(state_dir, SETTINGS_FILE), {})
    s.setdefault("mail_mode", "smarthost")
    s.setdefault("mail_from", "")
    s.setdefault("initial_schedule", {})
    defaults = {
        "start_date": "", "weeks": 2, "slot_minutes": 30, "capacity": 2,
        "location": "IT-Abteilung", "contact_email": "",
    }
    for key, value in defaults.items():
        s["initial_schedule"].setdefault(key, value)
    s.setdefault("external", {})
    ext = s["external"]
    ext.setdefault("host", "")
    ext.setdefault("port", 587)
    ext.setdefault("username", "")
    ext.setdefault("password", "")
    ext.setdefault("encryption", "starttls")
    return s


def apply_request(data, state_dir="."):
    """Übernimmt die Mail-Einstellungen aus configure-module; ein leeres Passwort behält das gespeicherte."""
    s = read_settings(state_dir)
    modus = data.get("mail_mode", s["mail_mode"])
    if modus not in MAIL_MODI:
        raise SettingsError("mail_mode", modus, "invalid_mail_mode")
    s["mail_mode"] = modus
    absender = str(data.get("mail_from", s["mail_from"]) or "").strip()
    if absender and ("@" not in absender or " " in absender):
        raise SettingsError("mail_from", absender, "invalid_mail_from")
    s["mail_from"] = absender
    if modus == "external":
        ext = dict(s["external"])
        neu = data.get("smtp", {}) or {}
        for key in ("host", "username", "encryption"):
            if key in neu:
                ext[key] = str(neu[key] or "").strip()
        if "port" in neu:
            ext["port"] = neu["port"]
        if neu.get("password"):
            ext["password"] = str(neu["password"])
        if not ext["host"]:
            raise SettingsError("smtp_host", ext["host"], "smtp_host_required")
        try:
            port = int(ext["port"])
        except (TypeError, ValueError):
            port = 0
        if not 1 <= port <= 65535:
            raise SettingsError("smtp_port", ext["port"], "invalid_smtp_port")
        ext["port"] = port
        if ext["encryption"] not in VERSCHLUESSELUNG:
            raise SettingsError("smtp_encryption", ext["encryption"], "invalid_smtp_encryption")
        s["external"] = ext
    if "initial_schedule" in data:
        schedule = dict(s["initial_schedule"])
        schedule.update(data["initial_schedule"])
        for key in ("start_date", "location", "contact_email"):
            value = str(schedule[key]).strip()
            if any(c in value for c in ("\n", "\r")):
                raise SettingsError("initial_schedule", key, "invalid_initial_schedule")
            schedule[key] = value
        if schedule["start_date"]:
            try:
                start = dt.date.fromisoformat(schedule["start_date"])
                today = dt.datetime.now(ZoneInfo("Europe/Berlin")).date()
                if start <= today and (
                    not read_konten(state_dir) or schedule["start_date"] != s["initial_schedule"]["start_date"]
                ):
                    raise ValueError("Das Startdatum muss in der Zukunft liegen.")
            except ValueError:
                raise SettingsError("initial_schedule", "start_date", "invalid_initial_schedule") from None
        for key, minimum, maximum in (("weeks", 1, 52), ("slot_minutes", 5, 180), ("capacity", 1, 1000)):
            value = schedule[key]
            if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                raise SettingsError("initial_schedule", key, "invalid_initial_schedule")
        if not schedule["location"] or len(schedule["location"]) > 255:
            raise SettingsError("initial_schedule", "location", "invalid_initial_schedule")
        if schedule["contact_email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+", schedule["contact_email"]):
            raise SettingsError("initial_schedule", "contact_email", "invalid_initial_schedule")
        s["initial_schedule"] = schedule
    _schreiben(os.path.join(state_dir, SETTINGS_FILE), json.dumps(s, indent=2))
    return s


# --- Konten -------------------------------------------------------------------------------------------------------

def read_konten(state_dir="."):
    return _json_lesen(os.path.join(state_dir, KONTEN_FILE), None)


def ensure_konten(domain, state_dir="."):
    """Legt beim ersten Aufruf 2 Admins und 10 Mitarbeiter mit zufälligen Passwörtern an."""
    konten = read_konten(state_dir)
    if konten:
        return konten
    domain = domain.strip().lower()
    konten = {
        "admins": [{"login": f"admin{i}@{domain}", "name": f"Administrator {i}", "passwort": neues_passwort()}
                   for i in range(1, ANZAHL_ADMINS + 1)],
        "mitarbeiter": [{"login": f"it{i:02d}@{domain}", "name": f"IT-Mitarbeiter {i:02d}",
                         "passwort": neues_passwort()}
                        for i in range(1, ANZAHL_MITARBEITER + 1)],
    }
    _schreiben(os.path.join(state_dir, KONTEN_FILE), json.dumps(konten, indent=2))
    return konten


def _konten_uebernehmen(konten):
    subprocess.run(["termine-warten"], check=True, stdout=sys.stderr)
    subprocess.run(
        ["podman", "exec", "-i", "pretix-app", "termine-entrypoint", "konten-sync"],
        input=json.dumps(konten), text=True, check=True, stdout=sys.stderr,
    )


def _konten_abgleichen(login, reset, state_dir, uebernehmen):
    """Journal vor DB-Änderung schreiben; nach Erfolg atomar freigeben.

    Bei einem Abbruch nach dem DB-Commit wird dasselbe Journal erneut angewendet.
    Das ist idempotent und verändert keine anderen Passwort-Hashes.
    """
    pending = os.path.join(state_dir, KONTEN_PENDING)
    with open(os.path.join(state_dir, "konten.lock"), "a") as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        # Auch nach einem verlorenen Prozess-/Container-Exit zuverlässig abschließen.
        if os.path.exists(pending):
            uebernehmen(_json_lesen(pending, None))
            os.replace(pending, os.path.join(state_dir, KONTEN_FILE))
        konten = read_konten(state_dir)
        if not konten:
            raise SettingsError("login", login or "", "accounts_not_created")
        changed = []
        if reset:
            for konto in konten["admins"] + konten["mitarbeiter"]:
                if login is None or konto["login"] == login:
                    konto["passwort"] = neues_passwort()
                    changed.append(konto["login"])
            if login is not None and not changed:
                raise SettingsError("login", login, "unknown_login")
            _schreiben(pending, json.dumps(konten, indent=2))
        uebernehmen(konten)
        if reset:
            os.replace(pending, os.path.join(state_dir, KONTEN_FILE))
        return changed


def passwoerter_neu(login=None, state_dir=".", uebernehmen=None):
    """Passwörter erst nach erfolgreicher Übernahme anzeigen; fehlgeschlagene Übernahme wiederaufnehmen."""
    return _konten_abgleichen(login, True, state_dir, uebernehmen or _konten_uebernehmen)


def sync_konten(state_dir=".", uebernehmen=None):
    _konten_abgleichen(None, False, state_dir, uebernehmen or _konten_uebernehmen)


def recover_konten(state_dir="."):
    if os.path.exists(os.path.join(state_dir, KONTEN_PENDING)):
        sync_konten(state_dir)


# --- Konfigurationsdateien ----------------------------------------------------------------------------------------

def write_database_env(state_dir="."):
    path = os.path.join(state_dir, DATABASE_ENV)
    if os.path.exists(path):
        return
    _env_schreiben(path, {"POSTGRES_DB": "pretix", "POSTGRES_USER": "pretix",
                          "POSTGRES_PASSWORD": secrets.token_urlsafe(24)})


def read_envfile(path):
    werte = {}
    try:
        with open(path) as f:
            for zeile in f:
                zeile = zeile.rstrip("\n")
                if zeile and not zeile.startswith("#") and "=" in zeile:
                    key, value = zeile.split("=", 1)
                    werte[key] = value
    except FileNotFoundError:
        pass
    return werte


def write_pretix_env(host, state_dir="."):
    db = read_envfile(os.path.join(state_dir, DATABASE_ENV))
    settings = read_settings(state_dir)
    schedule = settings["initial_schedule"]
    _env_schreiben(os.path.join(state_dir, PRETIX_ENV), {
        "PRETIX_PRETIX_INSTANCE_NAME": INSTANZ_NAME,
        "PRETIX_PRETIX_URL": f"https://{host}",
        "PRETIX_PRETIX_CURRENCY": "EUR",
        "PRETIX_PRETIX_DATADIR": "/data",
        # Traefik terminiert TLS und setzt X-Forwarded-*
        "PRETIX_PRETIX_TRUST_X_FORWARDED_FOR": "on",
        "PRETIX_PRETIX_TRUST_X_FORWARDED_PROTO": "on",
        "PRETIX_LOCALE_DEFAULT": "de",
        "PRETIX_LOCALE_TIMEZONE": "Europe/Berlin",
        "PRETIX_DATABASE_BACKEND": "postgresql",
        "PRETIX_DATABASE_NAME": db.get("POSTGRES_DB", "pretix"),
        "PRETIX_DATABASE_USER": db.get("POSTGRES_USER", "pretix"),
        "PRETIX_DATABASE_PASSWORD": db.get("POSTGRES_PASSWORD", ""),
        "PRETIX_DATABASE_HOST": "127.0.0.1",
        "PRETIX_REDIS_LOCATION": "redis://127.0.0.1:6379/0",
        "PRETIX_REDIS_SESSIONS": "true",
        "PRETIX_CELERY_BACKEND": "redis://127.0.0.1:6379/1",
        "PRETIX_CELERY_BROKER": "redis://127.0.0.1:6379/2",
        "NUM_WORKERS": "2",
        "TERMINE_STARTDATUM": schedule["start_date"],
        "TERMINE_WOCHEN": schedule["weeks"],
        "TERMINE_SLOT_MINUTEN": schedule["slot_minutes"],
        "TERMINE_PLAETZE": schedule["capacity"],
        "TERMINE_ORT": schedule["location"],
        "TERMINE_KONTAKT": schedule["contact_email"],
    })


def mail_werte(settings, smarthost, host):
    """PRETIX_MAIL_*-Werte für den gewählten Modus; smarthost = agent.get_smarthost_settings() oder None."""
    absender = settings.get("mail_from") or f"no-reply@{host or 'localhost.invalid'}"
    if settings["mail_mode"] == "external":
        q = settings["external"]
        quelle = {"host": q["host"], "port": q["port"], "username": q["username"], "password": q["password"],
                  "encrypt_smtp": q["encryption"]}
    elif smarthost and smarthost.get("enabled") and str(smarthost.get("host", "")).strip():
        quelle = smarthost
    else:
        # Kein Mailserver: pretix versucht localhost und meldet Zustellfehler im E-Mail-Ausgang
        return {"PRETIX_MAIL_FROM": absender, "PRETIX_MAIL_HOST": "127.0.0.1", "PRETIX_MAIL_PORT": "25",
                "PRETIX_MAIL_USER": "", "PRETIX_MAIL_PASSWORD": "", "PRETIX_MAIL_TLS": "off", "PRETIX_MAIL_SSL": "off"}
    verschluesselung = str(quelle.get("encrypt_smtp") or "none").lower()
    return {
        "PRETIX_MAIL_FROM": absender,
        "PRETIX_MAIL_HOST": str(quelle.get("host", "")),
        "PRETIX_MAIL_PORT": str(quelle.get("port", 25)),
        "PRETIX_MAIL_USER": str(quelle.get("username") or ""),
        "PRETIX_MAIL_PASSWORD": str(quelle.get("password") or ""),
        "PRETIX_MAIL_TLS": "on" if verschluesselung == "starttls" else "off",
        "PRETIX_MAIL_SSL": "on" if verschluesselung == "tls" else "off",
    }


def write_mail_env(settings, smarthost, host, state_dir="."):
    _env_schreiben(os.path.join(state_dir, MAIL_ENV), mail_werte(settings, smarthost, host))


# --- get-configuration --------------------------------------------------------------------------------------------

def configuration(settings, konten, host, http2https, lets_encrypt, smarthost):
    ext = settings["external"]
    return {
        "host": host,
        "http2https": http2https,
        "lets_encrypt": lets_encrypt,
        "initial_schedule": settings["initial_schedule"],
        "mail_mode": settings["mail_mode"],
        "mail_from": settings["mail_from"],
        "smtp": {
            "host": ext["host"],
            "port": ext["port"],
            "username": ext["username"],
            "encryption": ext["encryption"],
            "password_set": bool(ext["password"]),
        },
        "smarthost_available": bool(smarthost and smarthost.get("enabled") and smarthost.get("host")),
        "smarthost_host": (smarthost or {}).get("host", "") if smarthost else "",
        "admins": (konten or {}).get("admins", []),
        "mitarbeiter": (konten or {}).get("mitarbeiter", []),
        "shop_url": f"https://{host}/it/laptop/" if host else "",
        "control_url": f"https://{host}/control/" if host else "",
    }
