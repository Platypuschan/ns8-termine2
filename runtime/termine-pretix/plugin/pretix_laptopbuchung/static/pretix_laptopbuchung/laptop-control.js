/* Laptop-Terminbuchung – Verwaltung (pretix erlaubt kein Inline-JavaScript, daher als Datei) */
(function () {
    'use strict';
    // Web-Check-in als Pop-up (?fenster=1): pretix-Kopfleiste und Menü ausblenden
    if (/[?&]fenster=1(&|$)/.test(window.location.search)) {
        document.documentElement.classList.add('laptop-ohne-rahmen');
    }
    // Web-Check-in: Begriffe an die Laptop-Abgabe anpassen (die App zeichnet neu -> MutationObserver)
    if (window.location.pathname.indexOf('/webcheckin/') !== -1) {
        var TEXTE = {
            'Eingang': 'Annahme',
            'Ausgang': 'Ausgabe',
            'Ausgang gespeichert': 'Ausgabe gespeichert',
            'Eingecheckte Tickets': 'Offene Termine',
            'Gültige Tickets': 'Bestätigte Termine',
            'Derzeit anwesend': 'Geräte im Service',
            'Derzeit Anwesend': 'Geräte im Service'
        };
        var ersetzen = function (wurzel) {
            var walker = document.createTreeWalker(wurzel, NodeFilter.SHOW_TEXT);
            var knoten;
            while ((knoten = walker.nextNode())) {
                var t = knoten.nodeValue.trim();
                if (TEXTE.hasOwnProperty(t)) {
                    knoten.nodeValue = knoten.nodeValue.replace(t, TEXTE[t]);
                }
            }
        };
        // „Offene Termine“ = bestätigte Termine minus angenommene Laptops.
        // pretix liefert in der ersten Zahl die Anzahl angenommener (eingecheckter) Tickets; den Originalwert merken wir
        // uns, damit die Rechnung nach jeder Aktualisierung durch die App wieder stimmt.
        var offeneTermine = function () {
            var zahlen = document.querySelectorAll('.row.status span.statistic');
            if (zahlen.length < 2) { return; }
            var feld = zahlen[0], bestaetigt = parseInt(zahlen[1].textContent, 10);
            if (feld.textContent !== feld.getAttribute('data-laptop-gesetzt')) {
                feld.setAttribute('data-laptop-angenommen', feld.textContent);
            }
            var angenommen = parseInt(feld.getAttribute('data-laptop-angenommen'), 10);
            if (isNaN(bestaetigt) || isNaN(angenommen)) { return; }
            var offen = String(Math.max(0, bestaetigt - angenommen));
            if (feld.textContent !== offen) { feld.textContent = offen; }
            feld.setAttribute('data-laptop-gesetzt', offen);
        };
        document.addEventListener('DOMContentLoaded', function () {
            ersetzen(document.body);
            offeneTermine();
            new MutationObserver(function (aenderungen) {
                aenderungen.forEach(function (a) {
                    if (a.type === 'characterData') { ersetzen(a.target.parentNode || document.body); }
                    a.addedNodes.forEach(function (n) { ersetzen(n.nodeType === 3 ? n.parentNode : n); });
                });
                offeneTermine();
            }).observe(document.body, {childList: true, subtree: true, characterData: true});
        });
    }
    // Seiten mit data-laptop-autorefresh="<Sekunden>" (Tagesübersicht) regelmäßig neu laden
    document.addEventListener('DOMContentLoaded', function () {
        var el = document.querySelector('[data-laptop-autorefresh]');
        if (el) {
            var sek = parseInt(el.getAttribute('data-laptop-autorefresh'), 10) || 60;
            window.setTimeout(function () { window.location.reload(); }, sek * 1000);
        }
    });
    // Rückfrage vor Aktionen: <button data-confirm="Text">
    document.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-confirm]');
        if (btn && !window.confirm(btn.getAttribute('data-confirm'))) {
            e.preventDefault();
            e.stopImmediatePropagation();
        }
    }, true);
    // Links mit ?fenster=1 als Pop-up-Fenster öffnen
    document.addEventListener('click', function (e) {
        var a = e.target.closest('a[href*="fenster=1"]');
        if (!a) { return; }
        e.preventDefault();
        var w = window.open(a.href, 'laptop-webcheckin', 'popup,width=1100,height=850');
        if (w) {
            w.focus();
        } else {
            // Pop-up blockiert: im selben Tab mit Menü öffnen (ohne fenster=1)
            window.location.href = a.href.replace(/([?&])fenster=1(&|$)/, '$1').replace(/[?&]$/, '');
        }
    });
    // Ganze Tabellenzeile anklickbar: <tr data-href="…"> (Links, Knöpfe und Felder in der Zeile behalten ihr Verhalten)
    document.addEventListener('click', function (e) {
        var tr = e.target.closest('tr[data-href]');
        if (tr && !e.target.closest('a, button, input, select, textarea, label')) {
            window.location.href = tr.getAttribute('data-href');
        }
    });
})();
