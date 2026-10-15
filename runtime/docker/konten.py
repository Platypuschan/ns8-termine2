"""Gleicht die pretix-Benutzer mit der Kontenliste des NS8-Moduls ab (JSON auf stdin).

Eingabe: {"admins": [{"login": ..., "name": ..., "passwort": ...}], "mitarbeiter": [...]}
- Admins: aktiv, Systemadministrator (staff), Team „Administratoren“ (alle Rechte)
- Mitarbeiter: aktiv, Team „IT-Abteilung“ (nur Bestellungen lesen/ändern/einchecken)
- pretix' Standard-Zugänge (admin@localhost mit Passwort "admin", Demo-Zugang it-team@example.invalid) werden
  deaktiviert. Andere, in pretix selbst angelegte Benutzer bleiben unberührt.
Passwörter werden nie ausgegeben.
"""
import json
import sys

import django

django.setup()

from django.db import transaction  # noqa: E402
from django_scopes import scopes_disabled  # noqa: E402

from pretix.base.models import Organizer, Team, User  # noqa: E402

VERANSTALTER = "it"
TEAM_ADMINS = "Administratoren"
TEAM_IT = "IT-Abteilung"
STANDARD_ZUGAENGE = ["admin@localhost", "it-team@example.invalid"]

daten = json.load(sys.stdin)
admins = daten.get("admins", [])
mitarbeiter = daten.get("mitarbeiter", [])

with scopes_disabled(), transaction.atomic():
    org = Organizer.objects.get(slug=VERANSTALTER)
    team_admins = Team.objects.get(organizer=org, name=TEAM_ADMINS)
    team_it = Team.objects.get(organizer=org, name=TEAM_IT)
    gewollt = set()
    for konto, team, staff in [(k, team_admins, True) for k in admins] + [(k, team_it, False) for k in mitarbeiter]:
        login = konto["login"].strip().lower()
        gewollt.add(login)
        user = User.objects.filter(email__iexact=login).first()
        if user is None:
            user = User.objects.create_user(login, konto["passwort"])
        elif not user.check_password(konto["passwort"]):
            # Unveränderte Passwörter behalten ihren Hash und damit laufende Sitzungen.
            user.set_password(konto["passwort"])
        user.fullname = konto.get("name", "")
        user.locale = "de"
        user.is_active = True
        user.is_staff = staff
        user.save()
        team.members.add(user)
        (team_it if staff else team_admins).members.remove(user)
    entfernt = 0
    for user in User.objects.filter(email__in=STANDARD_ZUGAENGE, is_active=True):
        if user.email.lower() not in gewollt:
            user.is_active = False
            user.is_staff = False
            user.save()
            for team in (team_admins, team_it):
                team.members.remove(user)
            entfernt += 1

print(f"termine: {len(admins)} Admins, {len(mitarbeiter)} Mitarbeiter abgeglichen; {entfernt} Standard-Zugänge deaktiviert")
