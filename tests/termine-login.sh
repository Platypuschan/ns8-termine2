#!/bin/bash
# Meldet sich an der pretix-Verwaltung an; gibt "ok" aus, wenn pretix nach /control/ weiterleitet.
# Aufruf: termine-login.sh <basis-url> <login> <passwort> [curl-optionen…]
# Mit SEITE=<pfad> wird diese Seite nach der Anmeldung zusätzlich abgerufen und ausgegeben.
set -euo pipefail
basis="$1" login="$2" passwort="$3"
shift 3
jar="$(mktemp)"
trap 'rm -f "${jar}"' EXIT
c=(curl -sk --max-time 20 -b "${jar}" -c "${jar}" "$@")
"${c[@]}" -o /dev/null "${basis}/control/login"
token="$(awk '$6 ~ /csrftoken$/ {print $7}' "${jar}" | tail -1)"
ziel="$("${c[@]}" -o /dev/null -w '%{redirect_url}' -H "Referer: ${basis}/control/login" \
    --data-urlencode "csrfmiddlewaretoken=${token}" --data-urlencode "email=${login}" \
    --data-urlencode "password=${passwort}" "${basis}/control/login")"
case "${ziel}" in
    */control/ | */control/\?*) echo ok ;;
    *) echo "fehlgeschlagen: ${ziel:-keine Weiterleitung}"; exit 0 ;;
esac
if [[ -n "${SEITE:-}" ]]; then
    "${c[@]}" "${basis}${SEITE}"
fi
