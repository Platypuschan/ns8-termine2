import secrets

from django.db import models


def neues_token():
    return secrets.token_urlsafe(16)  # 22 Zeichen, ~128 Bit


class Teilnehmer(models.Model):
    """Ein Anwender aus der Rollout-Liste; der Einladungslink enthält sein persönliches Token."""

    event = models.ForeignKey("pretixbase.Event", on_delete=models.CASCADE, related_name="laptop_teilnehmer")
    token = models.CharField(max_length=64, unique=True, default=neues_token)
    name = models.CharField(max_length=255)
    email = models.EmailField()
    inventarnummer = models.CharField(max_length=100)
    welle = models.CharField(max_length=100, blank=True)
    eingeladen_am = models.DateTimeField(null=True, blank=True)
    einladungen = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = (("event", "email"), ("event", "inventarnummer"))
        ordering = ("name",)

    def __str__(self):
        return f"{self.name} <{self.email}> ({self.inventarnummer})"


class Buchung(models.Model):
    """Verknüpft eine Bestellposition (Termin) mit dem Anwender, der sie gebucht hat."""

    teilnehmer = models.ForeignKey(Teilnehmer, on_delete=models.CASCADE, related_name="buchungen")
    position = models.OneToOneField("pretixbase.OrderPosition", on_delete=models.CASCADE, related_name="laptop_buchung")
    erstellt = models.DateTimeField(auto_now_add=True)
