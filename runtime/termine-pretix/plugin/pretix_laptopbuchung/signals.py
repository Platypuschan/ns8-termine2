from django.dispatch import receiver

from pretix.base.services.placeholders import SimpleFunctionalTextPlaceholder
from pretix.base.signals import register_mail_placeholders


def _teilnehmer(order):
    """Anwender zur Bestellung (aus meta_info; die Buchungs-Verknüpfung entsteht erst nach dem Mailversand)."""
    from .models import Teilnehmer
    pk = (order.meta_info_data or {}).get("laptopbuchung", {}).get("teilnehmer")
    return Teilnehmer.objects.filter(pk=pk).first() if pk else None


WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def _termin(order):
    p = order.positions.select_related("subevent").first()
    if not p or not p.subevent:
        return ""
    tz = order.event.timezone
    von, bis = p.subevent.date_from.astimezone(tz), p.subevent.date_to.astimezone(tz) if p.subevent.date_to else None
    text = f"{WOCHENTAGE[von.weekday()]}, {von:%d.%m.%Y}, {von:%H:%M}"
    return text + (f"–{bis:%H:%M} Uhr" if bis else " Uhr")


def _ticket_qr(order):
    """QR-Code des Tickets: in der HTML-Mail als Bild (pretix bettet data:-Bilder als CID-Anhang ein)."""
    import base64
    import io

    import qrcode
    from pretix.helpers.format import PlainHtmlAlternativeString

    p = order.positions.first()
    if not p:
        return ""
    buf = io.BytesIO()
    qrcode.make(p.secret, box_size=8, border=2).save(buf, format="PNG")
    data = base64.b64encode(buf.getvalue()).decode()
    return PlainHtmlAlternativeString(
        "(Ticket-Code: siehe angehängtes PDF-Ticket)",
        f'<img src="data:image/png;base64,{data}" alt="Ticket-QR-Code" width="200" height="200">',
        is_block=True,
    )


@receiver(register_mail_placeholders, dispatch_uid="laptopbuchung_placeholders")
def placeholders(sender, **kwargs):
    return [
        SimpleFunctionalTextPlaceholder("termin", ["order"], _termin, "Montag, 19.10.2026, 08:00–08:30 Uhr"),
        SimpleFunctionalTextPlaceholder("ticket_qr", ["order"], _ticket_qr, "(QR-Code des Tickets)"),
        SimpleFunctionalTextPlaceholder(
            "inventarnummer", ["order"],
            lambda order: (_teilnehmer(order).inventarnummer if _teilnehmer(order) else ""),
            "INV-123456",
        ),
        SimpleFunctionalTextPlaceholder(
            "teilnehmer_name", ["order"],
            lambda order: (_teilnehmer(order).name if _teilnehmer(order) else ""),
            "Erika Musterfrau",
        ),
    ]


from django.urls import resolve, reverse  # noqa: E402

from pretix.control.signals import nav_event  # noqa: E402


@receiver(nav_event, dispatch_uid="laptopbuchung_nav")
def control_nav(sender, request=None, **kwargs):
    from .admin_only import ist_admin
    if not request.user.has_event_permission(request.organizer, request.event, "event.orders:read", request=request):
        return []
    url = resolve(request.path_info)
    kw = {"event": request.event.slug, "organizer": request.event.organizer.slug}
    return [
        {
            # für die IT ersetzt dieser Eintrag das pretix-Menü „Termine“
            "label": "Termine zuweisen" if ist_admin(request) else "Termine",
            "url": reverse("plugins:pretix_laptopbuchung:termine", kwargs=kw),
            "icon": "calendar",
            "active": url.namespace == "plugins:pretix_laptopbuchung" and url.url_name.startswith("termin"),
        },
        {
            "label": "Tagesübersicht",
            "url": reverse("plugins:pretix_laptopbuchung:tagesuebersicht", kwargs=kw),
            "icon": "th-large",
            "active": url.namespace == "plugins:pretix_laptopbuchung" and url.url_name == "tagesuebersicht",
        },
        {
            "label": "Laptop-Anwender",
            "url": reverse("plugins:pretix_laptopbuchung:control", kwargs=kw),
            "icon": "laptop",
            "active": url.namespace == "plugins:pretix_laptopbuchung" and url.url_name in ("control", "aktion", "export"),
        },
    ]


from django.utils.html import format_html  # noqa: E402
from django.utils.safestring import mark_safe  # noqa: E402

from pretix.control.signals import event_dashboard_widgets  # noqa: E402

NUM_WIDGET = '<div class="numwidget"><span class="num">{num}</span><span class="text">{text}</span></div>'


@receiver(event_dashboard_widgets, dispatch_uid="laptopbuchung_dashboard")
def dashboard_kacheln(sender, subevent=None, lazy=False, **kwargs):
    from .services import anwender_status
    rows = anwender_status(sender)
    url = reverse("plugins:pretix_laptopbuchung:control", kwargs={
        "organizer": sender.organizer.slug, "event": sender.slug})
    angeschrieben = sum(1 for r in rows if r["tn"].eingeladen_am)
    gebucht = sum(1 for r in rows if r["termin"])
    offen = sum(1 for r in rows if r["status"] == "angeschrieben")
    angenommen = sum(1 for r in rows if r["abgegeben_am"])
    ausgegeben = sum(1 for r in rows if r["ausgegeben_am"])
    im_service = sorted((r for r in rows if r["abgegeben_am"] and not r["ausgegeben_am"]),
                        key=lambda r: r["abgegeben_am"])

    def kachel(num, text, prio, link):
        return {"content": format_html(NUM_WIDGET, num=num, text=text), "display_size": "small",
                "priority": prio, "url": link}

    liste = format_html(
        '<div class="numwidget"><span class="num">{}</span><span class="text">Laptops im Service</span></div>'
        '<div class="laptop-im-service">{}</div>',
        len(im_service),
        mark_safe("".join(
            format_html("<div><strong>{}</strong> – {}</div>", r["tn"].inventarnummer, r["tn"].name)
            for r in im_service)) if im_service else format_html('<span class="text-muted">keine</span>'),
    )
    return [
        kachel(angeschrieben, "Anwender (angeschrieben)", 1006, url),
        kachel(gebucht, "Anwender (gebucht)", 1005, url + "?status=gebucht"),
        kachel(offen, "Anwender (offen)", 1004, url + "?status=angeschrieben"),
        kachel(angenommen, "Laptops (angenommen)", 1003, url),
        kachel(ausgegeben, "Laptops (ausgegeben)", 1002, url + "?status=ausgegeben"),
        {"content": liste, "display_size": "small", "priority": 1001, "url": url + "?status=abgegeben"},
    ]


from django.templatetags.static import static  # noqa: E402

from pretix.control.signals import html_head as control_html_head  # noqa: E402
from pretix.presale.signals import html_head as presale_html_head  # noqa: E402


@receiver(control_html_head, dispatch_uid="laptopbuchung_control_head")
def control_kopf(sender, request=None, **kwargs):
    return format_html('<link rel="stylesheet" href="{}"><script src="{}"></script>',
                       static("pretix_laptopbuchung/laptop.css"), static("pretix_laptopbuchung/laptop-control.js"))


@receiver(presale_html_head, dispatch_uid="laptopbuchung_presale_head")
def shop_kopf(sender, request=None, **kwargs):
    return format_html('<link rel="stylesheet" href="{}">', static("pretix_laptopbuchung/laptop.css"))
