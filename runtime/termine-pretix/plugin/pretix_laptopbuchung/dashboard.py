"""Dashboard der Veranstaltung: pretix-Standardkacheln durch Laptop-Kennzahlen ersetzen.

Die Kern-Empfänger (Ticketshop-Status, Teilnehmende, Umsatz, aktive Produkte, Anwesend) werden umhüllt und
liefern für Veranstaltungen mit aktivem Plugin keine Kacheln mehr; alle anderen Veranstaltungen bleiben unverändert.
Eingriff in pretix-Interna (pretix 2026.8.0) – nach pretix-Updates prüfen.
"""
import functools
import logging

logger = logging.getLogger(__name__)

PLUGIN = "pretix_laptopbuchung"
ERSETZTE_KACHELN = ("base_widgets", "shop_state_widget", "checkin_widget")


def standardkacheln_ausblenden():
    from pretix.control.signals import event_dashboard_widgets
    from pretix.control.views import dashboards

    for name in ERSETZTE_KACHELN:
        original = getattr(dashboards, name, None)
        if original is None:
            logger.warning("laptopbuchung: Dashboard-Kachel %s nicht gefunden", name)
            continue

        @functools.wraps(original)
        def huelle(sender, *args, _original=original, **kwargs):
            if sender is not None and PLUGIN in sender.get_plugins():
                return []
            return _original(sender, *args, **kwargs)

        huelle.__module__ = original.__module__  # gilt für pretix weiterhin als Kern-Empfänger (immer aktiv)
        event_dashboard_widgets.disconnect(original)
        event_dashboard_widgets.connect(huelle, weak=False, dispatch_uid=f"laptopbuchung_{name}")
