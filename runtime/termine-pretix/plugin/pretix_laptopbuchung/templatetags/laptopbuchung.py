from django import template

register = template.Library()


@register.filter
def plaetze_frei(subevent):
    """Freie Plätze eines Termins (kleinste Restmenge aller Kontingente; None = unbegrenzt)."""
    frei = None
    for q in subevent.quotas.all():
        code, num = q.availability()
        if num is None:
            continue
        frei = num if frei is None else min(frei, num)
    return frei


@register.simple_tag
def laptop_verfuegbarkeit(days):
    """Setzt `laptop_frei` an allen Terminen der Wochenansicht (Kontingente gesammelt berechnet)."""
    from pretix.base.services.quotas import QuotaAvailability

    subevents = {e["event"].pk: e["event"] for d in days for e in d.get("events", []) if hasattr(e.get("event"), "quotas")}
    if not subevents:
        return ""
    from pretix.base.models import Quota
    quotas = list(Quota.objects.filter(subevent_id__in=subevents.keys()))
    qa = QuotaAvailability(full_results=False)
    qa.queue(*quotas)
    qa.compute()
    frei = {}
    for q in quotas:
        num = qa.results[q][1]
        if num is None:
            continue
        frei[q.subevent_id] = num if q.subevent_id not in frei else min(frei[q.subevent_id], num)
    for pk, se in subevents.items():
        se.laptop_frei = frei.get(pk)
    return ""


@register.simple_tag
def laptop_teilnehmer(event, token):
    """Anwender zum Einladungs-Token (oder None)."""
    from ..models import Teilnehmer
    if not token:
        return None
    return Teilnehmer.objects.filter(event=event, token=token).first()


@register.filter
def qr_svg(data):
    """QR-Code als Inline-SVG (für den Ticket-Code auf der Bestätigungsseite)."""
    import io

    import qrcode
    import qrcode.image.svg
    from django.utils.safestring import mark_safe

    img = qrcode.make(str(data), image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf)
    svg = buf.getvalue().decode()
    return mark_safe(svg[svg.index("<svg"):])
