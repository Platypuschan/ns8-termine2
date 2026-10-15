"""Anfang der neuen Terminserie; vorhandene Veranstaltungen werden nie verändert."""
import datetime as dt
from zoneinfo import ZoneInfo


def startdatum(value="", heute=None):
    heute = heute or dt.datetime.now(ZoneInfo("Europe/Berlin")).date()
    if value:
        start = dt.date.fromisoformat(value)
        if start <= heute:
            raise ValueError("Das Startdatum einer neuen Veranstaltung muss in der Zukunft liegen.")
        return start
    return heute + dt.timedelta(days=7 - heute.weekday())


def zahl(env, key, standard, minimum, maximum):
    value = int(env.get(key) or standard)
    if not minimum <= value <= maximum:
        raise ValueError(f"{key} muss zwischen {minimum} und {maximum} liegen.")
    return value
