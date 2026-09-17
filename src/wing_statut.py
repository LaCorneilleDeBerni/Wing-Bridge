"""Instantané de l'état du moteur pour `/api/status`.

Sorti de `wing_handler._get_status` (audit du 25/09/2026, point D3) : 145
lignes d'assemblage de données dans un Handler HTTP. La route ne fait plus que
noter le battement de cœur de l'onglet puis renvoyer `statut()`.

🔒 Même règle que partout : `etat.E.LOCK` ne couvre QUE la copie des champs
partagés (STATE/SETTINGS/PROFILE) ; les appels lents (`ma3_sockets`,
`ma3_reachable`…) se font hors verrou. Contrôle test_get_status_verrou_minimal.
"""

import etat
import sys

import wing_init
import wing_firmware
import wing_ma3
import wing_bridge as wb


def statut() -> dict:
    """Le dictionnaire renvoyé par /api/status."""
    import wing_ui as core
    # 🔒 Le verrou ne protège QUE l'instantané de STATE/SETTINGS/PROFILE, jamais les
    # appels qui suivent : `ma3_sockets()` (pgrep/lsof) peut prendre ~5 s, et
    # usb_loop prend le même verrou à 30 Hz.
    with etat.E.LOCK:
        instantane = {
            "wing":       etat.E.STATE["wing"],
            "connecting": etat.E.STATE["connecting"],
            "want":       etat.E.STATE["want_connected"],
            "mode":       etat.E.STATE["mode"],
            "dirty":      etat.E.STATE["dirty"],
            "last_event": etat.E.STATE["last_event"],
            "cmd_buf":    etat.E.STATE["cmd_buf"],
            "enc_attr":   etat.E.STATE["enc_attr"],
            "profile":    etat.E.PROFILE["name"],
            "suivre_ma3": etat.E.SETTINGS.get("suivre_ma3", True),
            "fader_pickup": etat.E.SETTINGS.get("fader_pickup", True),
            "verbe_cible": etat.E.SETTINGS.get("verbe_cible", True),
            # `encodeurs_ma3` RÉINTRODUIT : cette fois elle pilote
            # réellement, via enc_attr_selon_ma3()
            # (wing_faders.py). `encodeurs` reste l'OBSERVATION brute.
            "encodeurs_ma3": etat.E.SETTINGS.get("encodeurs_ma3", False),
            "plugin_slot": etat.E.SETTINGS.get("plugin_slot",
                                             wing_ma3.PLUGIN_SLOT_DEFAUT),
            # Horodate (epoch) du dernier succès de shcuts_envoyer() —
            # None = jamais. Exposée ici (pollée toutes les 400 ms) plutôt
            # que dans /api/shcuts (coûteux, comparaison à la sonde) : la
            # date seule n'a pas besoin de cette fraîcheur-là.
            "shcuts_horodate": etat.E.SETTINGS.get("shcuts_horodate"),
        }
    return ({
        "wing":       instantane["wing"],
        # Wing présente mais qui n'envoie plus rien : distinct de
        # « débranchée ». Sans ça, l'état mort passait pour sain.
        "boucle":     {"hz": etat.E.BOUCLE["hz"],
                       "cycle_ms": round(etat.E.BOUCLE["cycle_ms"], 1),
                       "cycle_max": round(etat.E.BOUCLE["cycle_max"], 1),
                       "leds_ms": round(etat.E.BOUCLE["leds_ms"], 2),
                       "vides": etat.E.BOUCLE["vides"],
                       "t_write": round(etat.E.BOUCLE["t_write"], 1),
                       "t_read": round(etat.E.BOUCLE["t_read"], 1),
                       "t_ecr": round(etat.E.BOUCLE["t_ecr"], 1),
                       "n_pkt": etat.E.BOUCLE["n_pkt"],
                       # Filet de la boucle : tours abandonnés sur
                       # exception, relances par le superviseur.
                       "erreurs_tour": etat.E.BOUCLE.get("erreurs_tour", 0),
                       "relances": etat.E.BOUCLE.get("relances", 0),
                       "ecritures_ko": etat.E.BOUCLE.get("ecritures_ko", 0),
                       "ecriture_err": etat.E.BOUCLE.get("ecriture_err", ""),
                       # "" = interface bien revendiquée.
                       "claim": wing_init.DERNIER_OPEN.get("claim", ""),
                       # Temps de réponse mesuré à la connexion.
                       # ~0,4 ms = normal ; >50 ms = wing lente.
                       "poll_ms": wing_init.DERNIER_POLL_MS["ms"]},
        "sonde":      core._resume_sonde(),
        "suivre_ma3": instantane["suivre_ma3"],
        "fader_pickup": instantane["fader_pickup"],
        "verbe_cible": instantane["verbe_cible"],
        "encodeurs_ma3": instantane["encodeurs_ma3"],
        "plugin_slot": instantane["plugin_slot"],
        "shcuts_horodate": instantane["shcuts_horodate"],
        "encodeurs": core.ma3_encodeurs(),
        "led_ma3":    etat.E.LED["ma3"],
        "wing_muette": core.WING_FLUX["muette"],
        # Init échouée : plus aucun essai jusqu'au rebranchement.
        "wing_replug": etat.E.AUTO["attend_rebranchement"],
        "wing_erreur": core.WING_FLUX["erreur"],
        # Thread mort (exception non rattrapée OU battement figé) —
        # distinct de "wing_muette" : ça ne se corrige JAMAIS tout
        # seul, contrairement à une wing qui peut reparler.
        "thread_mort": core.threads_morts(),
        "connecting": instantane["connecting"],
        "want":       instantane["want"],
        "mode":       instantane["mode"],
        "profile":    instantane["profile"],
        "dirty":      instantane["dirty"],
        "last_event": instantane["last_event"],
        "cmd_buf":    instantane["cmd_buf"],
        "enc_attr":   instantane["enc_attr"],
        "console":    {"enabled": core.console_helper_alive(),
                       "connected": core.console_helper_alive(),
                       "trusted": etat.E.WS["helper_trusted"],
                       # Sous Windows, SendInput ne demande aucune permission
                       # (wing_keyboard_windows.py se déclare "trusted" tout
                       # seul) : l'étape « Autoriser l'Accessibilité » du
                       # wizard (Paramètres) n'a rien à faire sur cette
                       # plateforme et doit rester absente, pas juste verte.
                       "windows": sys.platform.startswith("win")},
        "osc":        {"target": wb.MA3_IP,
                       "port": wb.MA3_PORT,
                       "reachable": core.ma3_reachable(),
                       "vm": core.vm_active(),
                       # Config OSC LUE DANS MA3 : permet de dire
                       # POURQUOI il n'écoute pas, au lieu de
                       # supposer.
                       "ma3": core.osc_config_ma3(),
                       # Compté SEULEMENT quand MA3 est là mais muet :
                       # c'est le seul cas où ça sert, et `lsof` n'est
                       # pas gratuit.
                       "sockets": (core.ma3_sockets()
                                   if core.ma3_reachable() == "muet"
                                   else None)},
        # Firmware : configuré (cache ou blob livré) ou non. Lu à
        # CHAQUE poll — l'interface bloque proprement la connexion wing
        # et renvoie vers « Configurer le firmware » quand il manque.
        "firmware":   wing_firmware.firmware_statut(),
        # Capture intégrée (Windows) : progression EN DIRECT pendant
        # les ~45 s-2 min de wing_firmware_capture.capturer_firmware
        # (installation USBPcap comprise), + visibilité du bouton de
        # secours « Retirer le composant de capture » (Paramètres).
        # None hors Windows ou si le module est absent — l'UI s'en
        # sert pour masquer entièrement la carte, pas juste le désactiver.
        "capture":    capture_statut(),
        "build":      {"server": core.BUILD, "date": core.BUILD_DATE,
                       "keyboard": etat.E.WS["helper_build"]},
        "reference":  core.reference_info(),
        "recovery":   etat.E.RECOVERY["available"],
        # Journal RENDU dans la langue courante de l'app (wing_i18n.
        # LANGUE, posée par POST /api/lang). Les entrées de LOG sont
        # structurées {cle, params} : un changement de langue re-traduit
        # tout l'historique en mémoire au poll suivant. Le fichier
        # disque, lui, reste anglais (voir wing_reglages._log_to_file).
        "log":        core.journal_affiche(60),
        # Chemin RÉEL du fichier utilisé par CE processus — dépend du
        # mode de lancement (wing_mapper._default_profile_dir()) :
        # sources → src/wing_server.log, app figée → ~/Library/...
        # Affiché dynamiquement pour ne plus jamais coder le chemin
        # en dur côté interface (confusion déjà vécue).
        "log_file":   str(core.LOG_FILE),
    })


def capture_statut():
    """État de la capture intégrée pour /api/status. None = carte masquée
    côté UI (hors Windows x64, ou module absent — build sans vendor/usbpcap).
    Windows ARM est exclu : USBPcap et grandMA2 onPC n'existent qu'en x64
    (voir wing_firmware_capture.capture_supportee).
    """
    if not sys.platform.startswith("win"):
        return None
    try:
        import wing_firmware_capture as fwc
    except Exception:
        return None
    if not fwc.capture_supportee():
        return None
    d = dict(fwc.CAPTURE_STATE)
    d["bouton_secours"] = fwc.statut_bouton_secours()
    return d
