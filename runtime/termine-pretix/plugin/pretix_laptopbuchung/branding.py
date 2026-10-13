"""Instanzweites Branding des Fußbereichs.

Das gemeinsame ``poweredby``-Fragment lädt die CSS-Datei zum Ausblenden aller Seiten-Footer.
Damit gilt die Anpassung auch für Anmeldung und Passwortseiten sowie unabhängig davon,
ob das Laptop-Plugin für die jeweilige Veranstaltung aktiviert ist.
Die Serviceportal-Adresse wird auch sonst direkt verlinkt; alle anderen externen Links behalten die pretix-Umleitung.
"""

DIREKTE_LINKS = ("https://ism.uk-koeln.de/HEAT/",)


def einfache_fusslinks():
    from django.templatetags.static import static
    from django.utils.html import format_html

    from pretix.base import context

    original = context.get_powered_by
    if getattr(original, "_laptopbuchung", False):
        return

    def get_powered_by(request, safelink=True):
        # Alle pretix-Basisvorlagen (Verwaltung, Authentifizierung, Shop) verwenden
        # diesen Kontextwert. Die HTML-Kopf-Signale erreichen die Auth-Seiten nicht.
        return format_html(
            '<link rel="stylesheet" href="{}">{}',
            static("pretix_laptopbuchung/footer.css"),
            original(request, safelink=False),
        )

    get_powered_by._laptopbuchung = True
    context.get_powered_by = get_powered_by


def serviceportal_direkt():
    from pretix.base.templatetags import safelink as safelink_tag

    original = safelink_tag.sl
    if getattr(original, "_laptopbuchung", False):
        return

    def sl(url, *args, **kwargs):
        if str(url) in DIREKTE_LINKS:
            return url
        return original(url, *args, **kwargs)

    sl._laptopbuchung = True
    safelink_tag.sl = sl
