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

import json
import os
import secrets
import string

SETTINGS_FILE = "termine.json"
KONTEN_FILE = "konten.json"
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


def passwoerter_neu(login=None, state_dir="."):
    """Erzeugt neue Passwörter für ein Konto (login) oder für alle (login=None). Gibt die geänderten Logins zurück."""
    konten = read_konten(state_dir)
    if not konten:
        raise SettingsError("login", login or "", "accounts_not_created")
    geaendert = []
    for konto in konten["admins"] + konten["mitarbeiter"]:
        if login is None or konto["login"] == login:
            konto["passwort"] = neues_passwort()
            geaendert.append(konto["login"])
    if login is not None and not geaendert:
        raise SettingsError("login", login, "unknown_login")
    _schreiben(os.path.join(state_dir, KONTEN_FILE), json.dumps(konten, indent=2))
    return geaendert


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
