"""Bereiche, die nur Administratoren sehen und nutzen dürfen.

pretix blendet einige Menüpunkte unabhängig von den Team-Rechten ein (Veranstalter-„Export“, globale Menüs) bzw.
bindet Seiten nur an „Bestellungen lesen“ (Überblick, Erstattungen, Export). Hier werden Menüpunkte für
Nicht-Administratoren ausgeblendet und die zugehörigen Seiten an Admin-Rechte gebunden.
Eingriff in pretix-Interna (pretix 2026.8.0) – nach pretix-Updates prüfen.
"""
import logging

logger = logging.getLogger(__name__)

ADMIN_RECHT_ORG = "organizer.settings.general:write"
ADMIN_RECHT_EVENT = "event.settings.general:write"
PLUGIN = "pretix_laptopbuchung"

# (Modul, Klasse, neues Recht)
GESPERRTE_SEITEN = [
    ("pretix.control.views.organizer", "ExportView", ADMIN_RECHT_ORG),
    ("pretix.control.views.organizer", "ExportDoView", ADMIN_RECHT_ORG),
    ("pretix.control.views.organizer", "DeleteScheduledExportView", ADMIN_RECHT_ORG),
    ("pretix.control.views.organizer", "RunScheduledExportView", ADMIN_RECHT_ORG),
    ("pretix.control.views.orders", "OverView", ADMIN_RECHT_EVENT),
    ("pretix.control.views.orders", "RefundList", ADMIN_RECHT_EVENT),
    ("pretix.control.views.orders", "ExportView", ADMIN_RECHT_EVENT),
    ("pretix.control.views.orders", "ExportDoView", ADMIN_RECHT_EVENT),
    ("pretix.control.views.modelimport", "OrderImportView", ADMIN_RECHT_EVENT),
    # Produkte und pretix-Terminverwaltung (für die IT ersetzt durch die Plugin-Seite „Termine“)
    ("pretix.control.views.item", "ItemList", ADMIN_RECHT_EVENT),
    ("pretix.control.views.item", "CategoryList", ADMIN_RECHT_EVENT),
    ("pretix.control.views.item", "QuestionList", ADMIN_RECHT_EVENT),
    ("pretix.control.views.item", "QuotaList", ADMIN_RECHT_EVENT),
    ("pretix.control.views.discounts", "DiscountList", ADMIN_RECHT_EVENT),
    ("pretix.control.views.subevents", "SubEventList", ADMIN_RECHT_EVENT),
    # Bestellliste und E-Mail-Versand (einzelne Bestellungen bleiben über die Plugin-Seiten erreichbar)
    ("pretix.control.views.orders", "OrderList", ADMIN_RECHT_EVENT),
    ("pretix.plugins.sendmail.views", "IndexView", ADMIN_RECHT_EVENT),
    ("pretix.plugins.sendmail.views", "OrderSendView", ADMIN_RECHT_EVENT),
    ("pretix.plugins.sendmail.views", "WaitinglistSendView", ADMIN_RECHT_EVENT),
    ("pretix.plugins.sendmail.views", "EmailHistoryView", ADMIN_RECHT_EVENT),
    ("pretix.plugins.sendmail.views", "CreateRule", ADMIN_RECHT_EVENT),
    ("pretix.plugins.sendmail.views", "ScheduleView", ADMIN_RECHT_EVENT),
    ("pretix.plugins.sendmail.views", "DeleteRule", ADMIN_RECHT_EVENT),
    ("pretix.plugins.sendmail.views", "UpdateRule", ADMIN_RECHT_EVENT),
    ("pretix.plugins.sendmail.views", "ListRules", ADMIN_RECHT_EVENT),
]

# Menüpunkte (URL-Namen), die Nicht-Administratoren nicht sehen
GLOBAL_AUSBLENDEN = {"control:events", "control:organizers", "control:search.payments"}
EVENT_AUSBLENDEN = {"control:event.items", "control:event.subevents", "control:event.orders",
                    "control:event.orders.overview", "control:event.orders.refunds", "control:event.orders.export",
                    "control:event.orders.import", "plugins:sendmail:send"}


def ist_admin(request):
    """Administrator = Systemadministrator-Sitzung oder ein Team mit Veranstalter-Einstellungsrechten."""
    user = request.user
    if not user.is_authenticated:
        return False
    try:
        if user.has_active_staff_session(request.session.session_key):
            return True
    except Exception:
        pass
    for team in user.teams.all():
        if team.all_organizer_permissions or team.limit_organizer_permissions.get(ADMIN_RECHT_ORG):
            return True
    return False


def _filtern(nav, verbotene_urls):
    out = []
    for n in nav:
        if n.get("url") in verbotene_urls:
            continue
        if n.get("children"):
            n = dict(n, children=_filtern(n["children"], verbotene_urls))
        out.append(n)
    return out


def _urls(namen, **kwargs):
    from django.urls import NoReverseMatch, reverse
    urls = set()
    for name in namen:
        try:
            urls.add(reverse(name, kwargs=kwargs or None))
        except NoReverseMatch:
            logger.warning("laptopbuchung: URL %s nicht gefunden", name)
    return urls


def _sperren(view, recht):
    """Seite nur mit `recht` aufrufbar. Umhüllt dispatch, weil manche pretix-Listen keine eigene Rechteprüfung haben."""
    from django.core.exceptions import PermissionDenied

    if getattr(view.dispatch, "_laptopbuchung", False):
        return
    original = view.dispatch

    def dispatch(self, request, *args, **kwargs):
        rechte = getattr(request, "eventpermset" if recht.startswith("event") else "orgapermset", set())
        if recht not in rechte:
            raise PermissionDenied("Nur für Administratoren.")
        return original(self, request, *args, **kwargs)

    dispatch._laptopbuchung = True
    view.dispatch = dispatch


def _checkin_menue(nav, request):
    """IT-Team: „Check-in“ öffnet den Web-Check-in direkt als Pop-up (laptop-control.js), ohne Untermenü."""
    from django.urls import NoReverseMatch, reverse
    kw = {"organizer": request.organizer.slug, "event": request.event.slug}
    try:
        listen_url = reverse("control:event.orders.checkinlists", kwargs=kw)
        web_url = reverse("plugins:webcheckin:index", kwargs=kw)
    except NoReverseMatch:
        return nav
    return [dict(n, url=web_url + "?fenster=1", active=False, children=[]) if n.get("url") == listen_url else n
            for n in nav]


def nur_fuer_admins():
    import importlib

    from django.urls import reverse
    from pretix.control import context as control_context

    for modul, klasse, recht in GESPERRTE_SEITEN:
        view = getattr(importlib.import_module(modul), klasse, None)
        if view is None:
            logger.warning("laptopbuchung: %s.%s nicht gefunden – Sperre unvollständig", modul, klasse)
            continue
        _sperren(view, recht)

    if getattr(control_context.get_organizer_navigation, "_laptopbuchung", False):
        return
    orig_org = control_context.get_organizer_navigation
    orig_event = control_context.get_event_navigation
    orig_global = control_context.get_global_navigation

    def get_organizer_navigation(request):
        nav = orig_org(request)
        if ADMIN_RECHT_ORG in getattr(request, "orgapermset", set()):
            return nav
        return _filtern(nav, {reverse("control:organizer.export", kwargs={"organizer": request.organizer.slug})})

    def get_event_navigation(request):
        nav = orig_event(request)
        if PLUGIN not in request.event.get_plugins() or ist_admin(request):
            return nav
        kw = {"organizer": request.organizer.slug, "event": request.event.slug}
        return _checkin_menue(_filtern(nav, _urls(EVENT_AUSBLENDEN, **kw)), request)

    def get_global_navigation(request):
        nav = orig_global(request)
        if ist_admin(request):
            return nav
        return _filtern(nav, _urls(GLOBAL_AUSBLENDEN))

    for f in (get_organizer_navigation, get_event_navigation, get_global_navigation):
        f._laptopbuchung = True
    control_context.get_organizer_navigation = get_organizer_navigation
    control_context.get_event_navigation = get_event_navigation
    control_context.get_global_navigation = get_global_navigation
