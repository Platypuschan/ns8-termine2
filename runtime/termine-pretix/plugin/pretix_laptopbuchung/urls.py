from django.urls import re_path

from .control import (
    AktionView, AnwenderSucheView, AnwenderView, BestellverlaufView, ExportView, TagesuebersichtView, TermineView, TerminView,
    TerminZuweisenView,
)
from .views import DirektBuchungView, EinladungView

event_patterns = [
    re_path(r"^laptopbuchung/einladung/(?P<token>[A-Za-z0-9_-]{16,64})/$", EinladungView.as_view(), name="einladung"),
    re_path(r"^laptopbuchung/buchen/$", DirektBuchungView.as_view(), name="buchen"),
]

_CONTROL = r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/laptopbuchung/"

urlpatterns = [
    re_path(_CONTROL + r"$", AnwenderView.as_view(), name="control"),
    re_path(_CONTROL + r"aktion/$", AktionView.as_view(), name="aktion"),
    re_path(_CONTROL + r"export/$", ExportView.as_view(), name="export"),
    re_path(_CONTROL + r"termine/$", TermineView.as_view(), name="termine"),
    re_path(_CONTROL + r"termine/(?P<subevent>\d+)/$", TerminView.as_view(), name="termin"),
    re_path(_CONTROL + r"termine/(?P<subevent>\d+)/zuweisen/$", TerminZuweisenView.as_view(), name="termin_zuweisen"),
    re_path(_CONTROL + r"anwender-suche/$", AnwenderSucheView.as_view(), name="anwender_suche"),
    re_path(_CONTROL + r"tagesuebersicht/$", TagesuebersichtView.as_view(), name="tagesuebersicht"),
    re_path(_CONTROL + r"bestellung/(?P<code>[0-9A-Z]+)/verlauf/$", BestellverlaufView.as_view(), name="bestellverlauf"),
]
