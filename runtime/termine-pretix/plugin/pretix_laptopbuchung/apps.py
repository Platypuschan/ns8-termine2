from django.utils.translation import gettext_lazy as _

from pretix.base.plugins import PluginConfig

from . import __version__


class PluginApp(PluginConfig):
    default = True
    name = "pretix_laptopbuchung"
    verbose_name = "Laptop-Terminbuchung"

    class PretixPluginMeta:
        name = "Laptop-Terminbuchung"
        author = "IT-Abteilung"
        description = _(
            "Buchung eines Termins mit einem Klick über den persönlichen Code; "
            "Teilnehmerdaten (Name, E-Mail, Inventarnummer) kommen aus einer Liste."
        )
        visible = True
        version = __version__
        category = "CUSTOMIZATION"
        compatibility = "pretix>=2026.1"

    def ready(self):
        from . import signals  # noqa
        from .admin_only import nur_fuer_admins
        nur_fuer_admins()
        from .dashboard import standardkacheln_ausblenden
        standardkacheln_ausblenden()
        from .branding import einfache_fusslinks, serviceportal_direkt
        einfache_fusslinks()
        serviceportal_direkt()
