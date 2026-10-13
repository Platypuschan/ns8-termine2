*** Settings ***
Library    SSHLibrary
Library    String

*** Variables ***
${IMAGE_URL}         ghcr.io/platypuschan/termine2:latest
# Das Update-Szenario startet mit der letzten veröffentlichten Version (test-module-update.sh).
${PREVIOUS_IMAGE_URL}    ${EMPTY}
${SCENARIO}          install
${HOST}              termine.test
${module_id}         ${EMPTY}
&{konten_vorher}

*** Keywords ***
Get configuration
    ${output}    ${rc} =    Execute Command    api-cli run module/${module_id}/get-configuration
    ...    return_rc=True
    Should Be Equal As Integers    ${rc}    0    get-configuration failed: ${output}
    &{config} =    Evaluate    json.loads(r'''${output}''')    modules=json
    RETURN    &{config}

Run action
    [Arguments]    ${action}    ${payload}
    ${output}    ${rc} =    Execute Command    api-cli run module/${module_id}/${action} --data '${payload}'
    ...    return_rc=True
    RETURN    ${output}    ${rc}

Configure current module
    [Arguments]    &{extra}
    ${payload} =    Evaluate    json.dumps({"host": $HOST, "http2https": False, "lets_encrypt": False, **$extra})    modules=json
    ${output}    ${rc} =    Run action    configure-module    ${payload}
    Should Be Equal As Integers    ${rc}    0    configure-module failed: ${output}

# Anmeldung an der pretix-Verwaltung über Traefik (HTTPS, weil pretix sichere Cookies setzt)
Login
    [Arguments]    ${login}    ${passwort}
    Put File    ${CURDIR}/termine-login.sh    /root/termine-login.sh    mode=0755
    ${output} =    Execute Command    /root/termine-login.sh https://${HOST} '${login}' '${passwort}' --resolve ${HOST}:443:127.0.0.1
    RETURN    ${output}

Login gelingt
    [Arguments]    ${login}    ${passwort}
    ${output} =    Login    ${login}    ${passwort}
    Should Be Equal    ${output}    ok    Anmeldung ${login}: ${output}

Login scheitert
    [Arguments]    ${login}    ${passwort}
    ${output} =    Login    ${login}    ${passwort}
    Should Not Be Equal    ${output}    ok

Pretix ist erreichbar
    ${status} =    Execute Command    curl -sk --max-time 10 --resolve ${HOST}:443:127.0.0.1 -o /dev/null -w '\%{http_code}' https://${HOST}/control/login
    Should Be Equal    ${status}    200

Warten bis pretix läuft
    Wait Until Keyword Succeeds    300 seconds    5 seconds    Pretix ist erreichbar

Konten prüfen
    &{config} =    Get configuration
    Length Should Be    ${config.admins}    2
    Length Should Be    ${config.mitarbeiter}    10
    Should Be Equal    ${config.admins}[0][login]    admin1@${HOST}
    Should Be Equal    ${config.mitarbeiter}[9][login]    it10@${HOST}
    Login gelingt    ${config.admins}[0][login]    ${config.admins}[0][passwort]
    Login gelingt    ${config.mitarbeiter}[0][login]    ${config.mitarbeiter}[0][passwort]
    Login scheitert    admin@localhost    admin
    RETURN    &{config}

*** Test Cases ***
Add module for ${SCENARIO} scenario
    IF    r'${SCENARIO}' == 'update'
        Set Local Variable    ${install_image}    ${PREVIOUS_IMAGE_URL}
    ELSE
        Set Local Variable    ${install_image}    ${IMAGE_URL}
    END
    ${output}    ${rc} =    Execute Command    add-module ${install_image} 1
    ...    return_rc=True
    Should Be Equal As Integers    ${rc}    0    add-module ${install_image} failed: ${output}
    &{output} =    Evaluate    ast.literal_eval(r'''${output}''')    modules=ast
    Set Suite Variable    ${module_id}    ${output.module_id}

Configure initial module
    Configure current module
    Warten bis pretix läuft
    &{config} =    Konten prüfen
    Set Suite Variable    &{konten_vorher}    &{config}

Update module from the previous release
    Skip If    r'${SCENARIO}' != 'update'    only the update scenario updates the module
    ${output}    ${rc} =    Execute Command    api-cli run update-module --data '{"module_url":"${IMAGE_URL}","instances":["${module_id}"]}'
    ...    return_rc=True
    Should Be Equal As Integers    ${rc}    0    update-module ${IMAGE_URL} failed: ${output}
    ${journal} =    Execute Command    journalctl -q --no-pager SYSLOG_IDENTIFIER=agent@${module_id}
    Should Not Contain    ${journal}    has failed    an update-module.d step failed
    Warten bis pretix läuft
    &{config} =    Konten prüfen
    Should Be Equal    ${config.admins}    ${konten_vorher.admins}    die Konten müssen das Update überstehen

Externer SMTP-Server braucht einen Host
    ${output}    ${rc} =    Run action    configure-module    {"host":"${HOST}","http2https":false,"lets_encrypt":false,"mail_mode":"external","smtp":{"host":""}}
    Should Not Be Equal As Integers    ${rc}    0
    Should Contain    ${output}    smtp_host

Externen SMTP-Server speichern
    Configure current module    mail_mode=external    mail_from=it@example.org    smtp=${{ {"host": "smtp.example.org", "port": 587, "username": "u", "password": "geheim", "encryption": "starttls"} }}
    &{config} =    Get configuration
    Should Be Equal    ${config.mail_mode}    external
    Should Be Equal    ${config.smtp.host}    smtp.example.org
    Should Be True    ${config.smtp.password_set}
    Should Not Contain    ${config.smtp}    password
    ${env} =    Execute Command    runagent -m ${module_id} podman exec pretix-app printenv PRETIX_MAIL_HOST PRETIX_MAIL_TLS PRETIX_MAIL_FROM
    Should Be Equal    ${env}    smtp.example.org\non\nit@example.org
    Configure current module    mail_mode=smarthost
    Warten bis pretix läuft

Passwort eines Kontos neu erzeugen
    &{alt} =    Get configuration
    ${konto} =    Set Variable    ${alt.mitarbeiter}[2]
    ${output}    ${rc} =    Run action    reset-passwords    {"login":"${konto}[login]"}
    Should Be Equal As Integers    ${rc}    0    reset-passwords failed: ${output}
    &{neu} =    Get configuration
    Should Not Be Equal    ${neu.mitarbeiter}[2][passwort]    ${konto}[passwort]
    Should Be Equal    ${neu.mitarbeiter}[3]    ${alt.mitarbeiter}[3]
    Login scheitert    ${konto}[login]    ${konto}[passwort]
    Login gelingt    ${konto}[login]    ${neu.mitarbeiter}[2][passwort]

Unbekanntes Konto wird abgelehnt
    ${output}    ${rc} =    Run action    reset-passwords    {"login":"niemand@example.org"}
    Should Not Be Equal As Integers    ${rc}    0

Remove module
    ${rc} =    Execute Command    remove-module --no-preserve ${module_id}
    ...    return_rc=True  return_stdout=False
    Should Be Equal As Integers  ${rc}  0
