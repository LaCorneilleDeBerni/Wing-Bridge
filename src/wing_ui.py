#!/usr/bin/env python3
#
# Wing Bridge — command wing grandMA2 → grandMA3
# Copyright (C) 2026 LaCorneilleDeBerni
#
# Distribué sous licence GNU GPL-3.0 — voir le fichier LICENSE à la racine.
# Ce programme est un logiciel libre : sans AUCUNE garantie, dans la mesure
# permise par la loi.
#
"""
Wing UI — interface graphique (web locale) pour le bridge MA2 Wing → grandMA3
==============================================================================
Tout-en-un : mapping interactif (mode apprentissage), profils nommés,
et bridge OSC intégré avec log en direct.

Lancement :
  ~/wing-env/bin/python3 wing_ui.py

→ ouvre http://127.0.0.1:8765 dans ton navigateur.

⚠️ PAS de `sudo`. L'accès USB ne demande aucun droit root sur macOS. Cet
en-tête l'exigeait encore.

Le terminal ne sert qu'à lancer le script ; tout se passe dans le navigateur.
"""

import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from collections import deque
from http.server import ThreadingHTTPServer
from pathlib import Path

from pythonosc import udp_client

import etat
import wing_bridge as wb
import wing_detect
import wing_jeton
import wing_mapper as wm
import wing_init
import wing_etat_materiel
from wing_init import full_init

# ⚠️ PIÈGE PYTHON CLASSIQUE, PAS SPÉCIFIQUE À PYINSTALLER — trouvé en
# vérifiant l'extraction du module Profils sur l'app réelle :
# `wing_ui.py` est le POINT D'ENTRÉE (`__name__ == "__main__"` au lancement,
# figé ou non). Un `import wing_ui as core` fait depuis `wing_diagnostic.py`
# ou `wing_profils.py` ne retrouve PAS ce même module en cours d'exécution —
# Python ne connaît que `sys.modules["__main__"]`, pas `sys.modules["wing_ui"]`
# — et RÉIMPORTE le fichier depuis zéro sous ce second nom : un module FANTÔME,
# avec son propre PROFILE/STATE/SETTINGS jamais touchés par le vrai process.
# `charger_favori()` mettait donc à jour le PROFILE du fantôme ; `/api/status`
# (qui vit dans le VRAI `__main__`) continuait d'afficher les défauts —
# aucune exception, aucun contrôle du smoke test ne le voit (il importe
# toujours wing_ui sous son vrai nom, jamais comme `__main__`).
#
# 🔑 Alias explicite AVANT tout import de module qui nous réimporte en
# retour : la même exécution répond désormais aux deux noms.
sys.modules.setdefault("wing_ui", sys.modules[__name__])

import wing_diagnostic
from wing_diagnostic import build_diagnostic, install_crash_logging
import wing_profils
from wing_profils import (_profil_de_secours, autosave_loop, detect_recovery,
                           save_reference, importer_profil, charger_favori,
                           ensure_reference, reference_info)
import wing_ma3
from wing_ma3 import (ma3_etat, ma3_executor, ma3_master, _resume_sonde,
                       osc_config_ma3, vm_active, ma3_sockets, ma3_reachable,
                       ma3_attributes, ma3_fader_functions, ma3_motscles,
                       corriger_casse, corriger_casse_attribut, ma3_encodeurs,
                       ATTRS_REPLI, FADER_FUNC_KINDS)
import wing_raccourcis
from wing_raccourcis import (shcuts_etat, shcuts_envoyer, MA3_SHCUTS_NOM,
                             _shcuts_par_touche, _shcuts_vocabulaire,
                             _shcut_style_ma3, _shcuts_entrees)
import wing_touches_leds
from wing_touches_leds import (enqueue_key, drain_keys, enqueue_key_down,
                               enqueue_key_up, niveau_led_ma3,
                               rafraichir_leds_ma3, set_led_offset, slot_led,
                               set_btn_led, vegas_loop)
import wing_faders
from wing_faders import (suivi_actif, kind_selon_ma3, token_selon_ma3,
                         pickup_autorise, pickup_page_changee,
                         pickup_verifier_repos, send_fader,
                         faders_instantane, executors_en_attente,
                         faders_vider_attente, enc_attr_selon_ma3)
import wing_boutons
from wing_boutons import (handle_button_release, handle_button_bridge,
                          CYCLE, DERNIER_APPUI, _btn_last_event)
import wing_i18n
import wing_reglages
from wing_reglages import (osc_in_bind, osc_in_loop, OSC_IN, OSC_IN_HIST,
                           valid_osc_target, apply_osc_target,
                           load_settings, save_settings, SETTINGS_FILE,
                           LOG, LOG_FILE, log, log_plural, _log_to_file,
                           journal_affiche, _rendre_entree, _rendre_appel,
                           log_init, _INIT_MSG, archiver_session_precedente,
                           vider_journal)
import wing_connexion
from wing_connexion import (connect_wing, arreter_usb, restart_self,
                            USB_ARRET, USB_SORTIE, WingUnplugged, WING_FLUX,
                            cycle_dmx, dmx_listener, usb_loop)
import wing_handler
from wing_handler import Handler

try:                                    # numéro de build (généré au build)
    from wing_version import BUILD, BUILD_DATE
except Exception:                       # exécution depuis les sources, hors build
    # ⚠️ Placeholder BOOTSTRAP, pas résolu ici : _lire_locale n'existe pas
    # encore à ce point du chargement du module (même piège que PROFILE["name"]
    # plus bas — voir son commentaire). Résolu dans main().
    BUILD, BUILD_DATE = 0, "err.build_date.sources"

UI_PORT = 8765

# 🔒 JETON D'API — exigé sur tout POST et sur GET /api/keystrokes (voir
# wing_jeton.py pour le pourquoi ET la limite assumée). Un par lancement de
# l'app. ⚠️ Transmis au successeur d'un redémarrage moteur (`os.execv` hérite
# de l'environnement) : sans ça, l'onglet ouvert et l'assistant clavier
# garderaient l'ancien et toutes leurs requêtes seraient refusées jusqu'au
# rechargement. Un NOUVEAU lancement de l'app (launcher) n'hérite de rien.
API_JETON = os.environ.get("WING_API_JETON") or wing_jeton.nouveau_jeton()
os.environ["WING_API_JETON"] = API_JETON


# ── Cycle de vie : instance unique, réutilisation d'onglet, arrêt à la fermeture
#
# 🎯 Deux comportements voulus, universels (aucune dépendance à Chrome/--app,
#    identiques sous Safari/Firefox) :
#   1. Relancer l'app pendant qu'un onglet est déjà ouvert ⇒ AUCUN nouvel
#      onglet, aucun 2ᵉ serveur — le nouveau process ressort.
#   2. Fermer la fenêtre/onglet ⇒ extinction PROPRE du serveur (plus de process
#      fantôme). Comme « ⏻ Quitter » : la wing repart en bootloader (assumé,
#      documenté dans docs/HARDWARE.md).
#
# Battement de cœur : l'onglet ouvert appelle `/api/status` toutes les 400 ms
# (ui/init.js). C'est le SEUL appelant de cette route — vérifié : l'assistant
# clavier, lui, ne sonde que `/api/keystrokes`. `_get_status` horodate donc
# `UI_VIE["dernier_ping"]`, et `ui_active` n'est vrai que si ce ping est frais.
# Un assistant clavier qui tourne seul ne le rend jamais vrai.
UI_PING_FRAIS_S    = 6.0   # au-delà, plus aucun onglet n'est considéré ouvert
FERMETURE_GRACE_S  = 5.0   # délai entre le beacon `pagehide` et l'arrêt réel :
                           # le temps qu'un rechargement (F5) fasse revenir la page


def _ui_active() -> bool:
    """Un vrai onglet est-il ouvert et STABLE ? (≠ « l'assistant clavier tourne »)

    Faux si une fermeture est en cours (`arret_t` armé par `pagehide`) : l'onglet
    qui vient de partir ne compte plus. Sans ça, relancer l'app pendant les
    `FERMETURE_GRACE_S` de battement verrait encore `ui_active` vrai, ne rouvrirait
    rien, et le serveur s'éteindrait juste après — l'utilisateur se retrouve sans
    rien. Vu ainsi, la relance tombe sur « fantôme » → rouvre le navigateur → le
    ping du nouvel onglet désarme l'arrêt.
    """
    if etat.E.UI_VIE["arret_t"]:
        return False
    dp = etat.E.UI_VIE["dernier_ping"]
    return bool(dp) and (time.monotonic() - dp) < UI_PING_FRAIS_S


def _vie_verdict(now: float, arret_t: float, dernier_ping: float,
                 grace: float) -> str:
    """Que faire d'un arrêt différé ? → 'rien' | 'annule' | 'arret'. PUR.

    `vie_loop` n'est qu'une boucle autour de cette fonction ; le test de fumée
    l'appelle directement (réinjection ROUGE : grâce = 0 ⇒ l'annulation ne peut
    plus se produire, le verdict doit basculer sur 'arret').

    Ordre voulu : une fois la grâce écoulée avec l'échéance dépassée, on
    S'ENGAGE — un rechargement qui prendrait plus de `grace` secondes en local
    est pathologique. Sinon, un ping postérieur à l'armement = la page est
    revenue (F5) ⇒ on annule.
    """
    if not arret_t:
        return "rien"
    if now - arret_t >= grace:
        return "arret"
    if dernier_ping > arret_t:
        return "annule"
    return "rien"


# ── État partagé ───────────────────────────────────────────────────────────────



# Auto-reconnexion USB : tant que want_connected est vrai mais que la wing a
# disparu (câble arraché, pas une déconnexion volontaire), on retente tout seul.
#
# `attend_rebranchement` : verrou posé après un échec d'init. Un essai d'init
# RÉ-ENVOIE le firmware et fait rebooter la wing ; or une wing dont le firmware
# a échoué à démarrer ne repartira JAMAIS sans coupure d'alimentation (établi
# par l'expérience : 6 essais d'affilée → 6 échecs ; coupure de 18 s + 1 essai
# → succès en 1,5 s). Réessayer entretient donc le blocage — LED qui clignotent.
# Le verrou n'est levé que lorsque la wing disparaît du bus : la preuve qu'elle
# a bien été débranchée.
#
# ⚠️ Ne pas remplacer ce verrou par un simple espacement des essais : déjà
# tenté, ça ne fait que ralentir un acharnement inutile.

# Durée d'absence à partir de laquelle on considère qu'il y a eu un VRAI
# débranchement. En dessous, c'est la wing qui décroche seule pendant un
# reboot — et lever le verrou sur ce signal-là relançait l'envoi de firmware
# qui la maintenait bloquée.
ABSENCE_REELLE_S = 5.0


# 🔒 ACCESSEURS DE L'ÉTAT PARTAGÉ (audit du 25/09/2026, point I8).
#
# Des champs de STATE (wing, mode, resume_mode, want_connected…) et TOUS ceux
# de SETTINGS étaient écrits HORS `LOCK`, alors que la doc promettait un
# invariant « STATE/SETTINGS ne s'écrivent que sous LOCK ». Le GIL rend chaque
# affectation atomique, mais pas un GROUPE d'affectations (wing + mode +
# resume_mode doivent changer ensemble), ni `json.dumps(SETTINGS)` pendant
# qu'un autre fil y ajoute une clé (« dictionary changed size during
# iteration », rattrapé en silence : la sauvegarde était perdue).
# Tranché : toute écriture passe soit par un bloc `with LOCK:`, soit par ces
# accesseurs, qui prennent le verrou et écrivent tous leurs champs d'un coup.
# ⚠️ LOCK n'est PAS réentrant : ne JAMAIS appeler un accesseur depuis un bloc
# `with LOCK:` — interblocage de tout le moteur. Le contrôle
# test_ecritures_etat_sous_verrou refuse les deux fautes.
def etat_poser(**champs):
    """Écrit un ou plusieurs champs de STATE sous LOCK, ensemble."""
    with etat.E.LOCK:
        etat.E.STATE.update(champs)


def reglage_poser(**champs):
    """Écrit un ou plusieurs champs de SETTINGS sous LOCK, ensemble."""
    with etat.E.LOCK:
        etat.E.SETTINGS.update(champs)


def mark_dirty():
    etat_poser(dirty=True)



# ── Faders → types de master MA3 ──────────────────────────────────────────────
# Chaque fader physique a un "kind" — reflète très exactement la liste
# "Select Function" que MA3 propose pour la propriété Fader d'un executor
# (Menu Executor → Fader → Select Function). Deux familles :
#
# 1) Famille FADER_KEYWORDS — toutes suivent le même moule confirmé par la
#    doc officielle MA Lighting (juillet 2026), page "General Keywords",
#    vérifiée à jour sur DEUX versions (2.0 et 2.3) : la liste complète des
#    mots-clés Fader* n'en contient QUE 8. Highlight/Lowlight/Solo — pourtant
#    proposés dans le sélecteur "Select Function" de MA3 pour la propriété
#    Fader d'un executor — n'ont PAS de mot-clé FaderX dédié confirmé et ont
#    donc été retirés d'ici (une tentative d'extrapolation s'est révélée
#    fausse ; mieux vaut ne pas proposer l'option que d'envoyer une commande
#    invalide).
FADER_KEYWORDS = {
    "executor":   "FaderMaster",     # Master  — niveau d'intensité
    "crossfade":  "FaderCrossFade",  # X       — position de crossfade
    "crossfadeA": "FaderCrossFadeA", # XA      — crossfade manuel, fader A
    "crossfadeB": "FaderCrossFadeB", # XB      — crossfade manuel, fader B
    "temp":       "FaderTemp",       # Temp    — crossfade la 1ère cue on/off
    "rate":       "FaderRate",       # Rate    — multiplie/divise fade+delay
    "time":       "FaderTime",       # Time    — écrase les temps de cue stockés
}
# 2) "faderspeed" (Speed, propriété Fader de l'executor) et "speed" (Speed
#    Master séparé, pool Master 3.N) sont deux mécanismes DIFFÉRENTS malgré
#    le nom proche — tous deux prennent une UNITÉ (BPM/Hz/Seconds), pas un %.
#      faderspeed : FaderSpeed Executor <n> At <UNITÉ> <valeur>
#      speed      : Master 3.<n> At <UNITÉ> <valeur>
#      gm         : Master 2.1 At <pct>  (grandmaster, fixe, pas d'executor)
#
# 📖 VÉRIFIÉ dans le manuel MA3 2.4.2 installé :
# `keyword_faderspeed.html`/`keyword_bpm.html`/`keyword_hz.html`/
# `keyword_seconds.html` documentent tous « At <UNITÉ> <valeur> » (mot-clé
# d'unité EXPLICITE) comme une valeur ABSOLUE, ex. officiel : « Master 3.1 At
# BPM 75 » → 75 BPM. C'est DIFFÉRENT du mot-clé général `At <nombre>` SANS
# unité (`keyword_at.html`), qui lui est un pourcentage — deux commandes
# distinctes malgré la ressemblance ; un doute de forum sur « At 95 » venait
# très probablement de la forme sans unité. Voir `_mapped_speed_value()` dans
# `wing_faders.py` (mappage linéaire depuis `min`/`max`) pour le détail et les
# sources.
#
# ⚠️ RÈGLE CRITIQUE : le "kind" choisi ici DOIT correspondre exactement à la
# fonction que l'executor a RÉELLEMENT dans MA3 (Menu Executor → Fader →
# Select Function, ou "Set Page X.N Property 'Fader' <Fonction>"). L'OSC n'a
# aucune visibilité sur la config MA3 — c'est notre commande qui décide, pas
# l'inverse. Si le fader de l'executor est réglé sur Crossfade dans MA3 mais
# qu'on envoie FaderMaster ici, ça ne correspondra pas.
# ── Masters de la SÉQUENCE SÉLECTIONNÉE (pool Master 1.x) ────────────────────
# Relevé dans le manuel installé (masters_selected.html) :
# « Selected masters give access to the individual masters of the selected
# sequence. » Ils suivent donc la séquence active, sans executor fixe.
#
# 🎯 C'est ce que fait le fader « XFade » sérigraphié sur une command wing :
# le crossfade de ce qui est actif, pas d'un executor précis.
#
# 📌 Résout une question qui restait ouverte : Highlight, Lowlight et
# Solo n'ont pas de mot-clé Fader* — ils existent ICI, en Master 1.8 à 1.10.
MASTERS_SELECTION = {
    1: "Master", 2: "XFade", 3: "XFadeA", 4: "XFadeB", 5: "Temp",
    6: "Rate", 7: "Speed", 8: "Highlight", 9: "Lowlight", 10: "Solo",
    11: "Time",
}

SPEED_UNITS = {"bpm": "BPM", "hz": "Hz", "sec": "Seconds"}


# Débit maximal d'un fader vers MA3 : 25 envois/s — MA3 interpole, et c'est
# bien au-delà de ce que l'œil distingue. ⚠️ La cadence de LECTURE de la wing
# (30 Hz) et celle d'ÉCRITURE vers MA3 sont indépendantes et doivent le rester :
# accélérer la boucle USB faisait saturer la ligne de commande de MA3 (tout
# devenait mou).
FADER_INTERVALLE = 0.04          # 40 ms → 25 envois/s au plus, par fader


# ⚠️ _envoyer_fader/_send_throttled/faders_vider_attente ont déménagé dans
# wing_faders.py (étape 6) — réexportées ci-dessous, section imports.
# FADER_LAST/FADER_T/FADER_ATTENTE/FADER_INTERVALLE restent ici : les trois
# premiers monkeypatchés (`.clear()`) par smoke_test.py.

# MA3_FADER_KINDS / MA3_KEY_VERBES vivent dans wing_faders.py (seul lecteur).

# Fonctions MAINTENUES : elles acceptent On à l'appui et Off au relâchement.
# Syntaxes relevées mot pour mot dans le manuel :
#   Flash (On/Off) [Object]      Temp (On/Off) [Object]
#   Swap  (On/Off) [Object]      Black (On or Off) [Object]
# Toggle, Top et Go+ n'en prennent AUCUN — leur syntaxe est « Verbe [Object] ».
# « On » n'est PAS un suffixe : c'est un mot-clé à part entière.
MA3_VERBES_MAINTENUS = {"flash", "temp", "swap", "black"}


# ⚠️ _suivi_dit/suivi_actif/kind_selon_ma3/token_selon_ma3 ont déménagé dans
# wing_faders.py (étape 6 du découpage) — réexportées ci-dessous,
# section imports. _SUIVI_VU et _RE_EXEC_CMD restent ici : lus/écrits aussi
# par le futur découpage « boutons/executors ».

# Grammaire réelle des commandes d'executor du profil :
#     <Verbe> [On|Off] Executor <n>
# Le On/Off est conservé tel quel : il dit l'appui ou le relâchement, pas la
# fonction (« Flash On Executor 206 » doit être reconnu, pas un seul mot).
_RE_EXEC_CMD = re.compile(
    r"^([A-Za-z][A-Za-z+\-]*)(\s+(?:On|Off))?\s+Executor\s+(\d+)$", re.I)


# ⚠️ token_selon_ma3 a déménagé dans wing_faders.py (étape 6) — réexportée
# ci-dessous, section imports.

# ── Rattrapage de fader (« pickup ») ─────────────────────────────────────────
#
# Après un changement de page ou un rechargement de show, le fader physique et
# la valeur MA3 divergent : au premier contact, le niveau SAUTERAIT (visible
# depuis la salle). Le fader ne prend donc la main qu'une fois qu'il ATTEINT ou
# TRAVERSE la valeur de MA3 (principe des vraies consoles), la garde tant qu'on
# s'en sert, et la perd si MA3 change sous lui — typiquement un changement de
# page. La valeur de MA3 vient de la sonde Lua (position réelle, 1×/s), jamais
# devinée : une première implémentation qui devinait a été retirée, ne pas y
# revenir.

# ⚠️ pickup_autorise/pickup_page_changee/pickup_verifier_repos/send_fader ont
# déménagé dans wing_faders.py (étape 6) — réexportées ci-dessous, section
# imports. PICKUP reste ici : monkeypatchée (`.clear()`) par smoke_test.py.

# Ordre d'affichage des faders : octet-source lu pour chaque position F1..F8.
# Calibré d'après la wing réelle (physique 1 = octet 6, etc.).
FADER_ORDER = [6, 7, 0, 1, 2, 3, 4, 5]

# ── Sortie DMX (XLR de la wing) ───────────────────────────────────────────────
# Découverte capture "capture étapes.pcapng" : le paquet 520 o "banque 01"
# envoyé à chaque cycle EST l'univers DMX 1 (8 o d'en-tête + 512 canaux).
# On le remplit depuis le sACN (E1.31) ou l'Art-Net émis par grandMA3.
# La wing a DEUX sorties DMX : banque 01 = XLR A, banque 02 = XLR B
# (confirmé par la capture "test univers 2.pcapng").

# ── LEDs des boutons (paquet CMD_264) ─────────────────────────────────────────
# Découverte capture leds_exec.pcapng : les 260 octets de données du paquet
# CMD_264 sont la carte des LEDs — un slot 16 bits little-endian par LED
# (offsets pairs 6 à 242). Valeurs : 0x0000 éteint, 0x0030 veilleuse,
# 0x07F8 plein feu (PWM 0-2047).
# Boutons executor : offset = 196 + 2 × (btn_id − 0x70)   pour 0x70-0x7d.
# Payload de repos capturé sur MA2 onPC (toutes les touches en veilleuse) :
LED_BASE = wb.LED_BASE   # constante de protocole : vit dans wing_bridge.py

LED_GLOW = 0x0030   # veilleuse
LED_FULL = 0x07F8   # plein feu

# ── Mode console : injection clavier système ──────────────────────────────────
# Les touches de la wing sont écrites dans la VRAIE ligne de commande de MA3,
# par un clavier système : le serveur met les frappes dans une file, et
# l'assistant clavier (wing_keyboard.py, dans la session de l'utilisateur) la
# consomme et tape dans le process MA3. Résultat : Store s'affiche dans la
# ligne de commande, et Store + clic écran fonctionne.
#
# ⌨️ Le mode console est LE comportement, pas une option : démarrer le bridge
# démarre tout. Seul repli, automatique et annoncé : sans assistant clavier,
# les touches partent en OSC pur (fonctions réduites). L'utilisateur ne choisit
# jamais.


def console_helper_alive() -> bool:
    """L'assistant clavier a-t-il polé récemment (< 3 s) ?"""
    return (time.time() - etat.E.WS["helper_seen"]) < 3.0


# ── Santé OSC → MA3 ───────────────────────────────────────────────────────────
# L'OSC est de l'UDP sans accusé de réception : on ne peut PAS confirmer qu'une
# commande est arrivée. Mais la panne n°1 — grandMA3 pas lancé — se détecte :
# cible locale (127.0.0.1) → on vérifie le process ; cible distante → None
# (pastille grise « inconnu »).
#
# ⚠️ « MA3 est lancé » ≠ « MA3 écoute l'OSC » (aucun socket lié au port 8000 :
# faders et executors muets pendant que le mode console marchait) : on teste
# les DEUX séparément, et l'interface le dit.
#
# `_MA3_CHECK` : invalidé par `apply_osc_target()` (wing_reglages.py), lu par
# `ma3_reachable()` (wing_ma3.py).

# Dossier des raccourcis clavier de MA3, via wing_ma3._ma3_base() (~/ sous
# macOS, %PROGRAMDATA% sous Windows — un chemin codé en dur sur ~/ était
# introuvable sous Windows). Redirigé vers un dossier jetable par le test de
# fumée.
MA3_SHCUTS_DIR = (wing_ma3._ma3_base() / "gma3_library"
                  / "userprofiles" / "keyboardshortcuts")


# ── Assistant de configuration guidée ────────────────────────────────────────
#
# 🎯 Le mode apprentissage marche à l'envers de ce qu'on
# veut quand on part d'une wing vierge : il faut appuyer sur une touche PUIS
# se souvenir de ce qu'on voulait y mettre. L'assistant inverse le sens — il
# annonce « appuie sur la touche 1 », on appuie, il passe à la suivante.
#
# ⚠️ Chaque token proposé ici DOIT être connu de l'app, sinon on ferait
# assigner à l'utilisateur des commandes qui ne partiront jamais. Le test de
# fumée le vérifie (contrôle test_assistant) : tout token doit figurer dans la table des
# raccourcis console, dans les verbes, ou dans les fonctions d'executor.
#
# L'ordre suit la disposition d'une command wing MA2, de gauche à droite et de
# haut en bas, pour qu'on puisse suivre physiquement sans chercher.
# Le 1er élément de chaque tuple est une clé i18n (ui.touches.assistant.groupe.*),
# PAS le libellé en dur — résolue dans la langue courante par assistant_liste().
# ⚠️ Namespace `ui.*` mais résolution SERVEUR (wing_i18n.L) : ce contenu part
# dans le JSON de /api/assistant déjà « fini », comme journal.*/err.* — pas
# une clé que le client résoudrait lui-même. Exception pragmatique au tableau
# de docs/I18N.md (« ui.* → client t() ») plutôt qu'un namespace de plus.
ASSISTANT_ETAPES = [
    ("ui.touches.assistant.groupe.numpad", "cmd",
     ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0", ".", "+", "-"]),
    ("ui.touches.assistant.groupe.ligne_commande", "cmd",
     ["Please", "Clear", "Oops", "At", "Thru", "If", "Full", "Esc"]),
    ("ui.touches.assistant.groupe.verbes", "cmd",
     ["Store", "Update", "Delete", "Copy", "Move", "Assign", "Edit",
      "Select", "Goto", "Label", "Off", "On"]),
    # ⚠️ « Executor » et non « Exec ». La TOUCHE de MA3 s'appelle Exec, mais le
    # mot-clé de commande est Executor — voir TOKENS_RENOMMES dans wing_mapper.
    ("ui.touches.assistant.groupe.objets", "cmd",
     ["Fixture", "Channel", "Group", "Preset", "Sequence", "Cue", "Executor",
      "Macro", "Effect", "View"]),
    ("ui.touches.assistant.groupe.playback", "cmd",
     ["Go+", "Go-", "Pause", "Top", "Learn", "Fix", "Temp", "Black"]),
    ("ui.touches.assistant.groupe.navigation", "cmd",
     ["Next Page", "Previous Page", "Prev", "Next", "Up", "Down",
      "Menu", "Blind", "Highlight", "Solo", "Freeze"]),
    ("ui.touches.assistant.groupe.roues", "push", ["1", "2", "3", "4"]),
    ("ui.touches.assistant.groupe.executor_haut", "exec",
     ["101", "102", "103", "104", "105", "106"]),
    ("ui.touches.assistant.groupe.executor_bas", "exec",
     ["201", "202", "203", "204", "205", "206"]),
]


def assistant_liste():
    """Étapes de l'assistant, à plat, pour l'interface.

    Chaque entrée : groupe, type d'assignation, valeur, et un libellé lisible.
    Les tokens inconnus de l'app sont ÉCARTÉS plutôt que proposés — mieux vaut
    une étape en moins qu'une touche configurée pour rien.
    """
    import wing_i18n
    connus = set(wm.CONSOLE_KEY_DEFAULTS) | VERBES_CIBLE | set(EXEC_FUNCS)
    etapes, ignores = [], []
    for groupe_cle, atype, valeurs in ASSISTANT_ETAPES:
        for v in valeurs:
            if atype == "cmd" and v not in connus:
                ignores.append(v)
                continue
            if atype == "push":
                libelle = wing_i18n.L("ui.touches.assistant.cible_roue", n=v)
            elif atype == "exec":
                libelle = wing_i18n.L("ui.touches.assistant.cible_executor", n=v)
            else:
                libelle = v
            etapes.append({"groupe": wing_i18n.L(groupe_cle), "type": atype,
                           "valeur": v, "libelle": libelle})
    return {"etapes": etapes, "ignores": sorted(set(ignores)),
            "total": len(etapes)}


# ── Appui long : TOUTES les touches, sans réglage ────────────────────────────
#
# Le comportement de maintien est NATIF à la touche côté MA3 (Clear maintenu =
# ClearAll, Oops maintenu = historique — pages officielles Clear Key / Oops
# Key) : on relaie fidèlement la vraie durée d'appui, et MA3 décide seul. Rien
# à cocher ; un maintien ajouté un jour par MA3 est déjà géré.
#
# ⚠️ APPARIEMENT PAR BOUTON PHYSIQUE, pas par token : le profil peut changer
# entre l'appui et le relâchement. On retient ce qu'on a réellement enfoncé,
# indexé par btn_id (leçon « appui et relâchement ont divergé »).

# ⚠️ enqueue_key/enqueue_key_down/enqueue_key_up/drain_keys ont déménagé dans
# wing_touches_leds.py (étape 5 du découpage) — réexportées ci-dessous,
# section imports.


# Dernier envoi des univers DMX : ils ne repartent qu'une fois par seconde
# quand la sortie est coupée, au lieu d'être réécrits à chaque tour pour un
# blackout qui ne change jamais (voir cycle_dmx). La carte des LEDs, elle,
# n'est PAS concernée : elle part à chaque tour, exprès.

# ── Mesure de la boucle USB ──────────────────────────────────────────────────
# La boucle s'instrumente elle-même : une latence ressentie se MESURE ici (où
# passe le temps : écriture, lecture, LEDs) avant de corriger quoi que ce
# soit.


# ── Threads critiques : détection de mort ────────────────────────────────────
# Un thread mort doit se VOIR dans l'interface — sinon la wing semble saine
# pendant que ses faders sont gelés. Deux détections complémentaires :
#   • PRÉCISE : `THREAD_MORT` est posé par `wing_diagnostic._hook_thread`, à
#     l'instant exact où l'exception tue le thread. Zéro faux positif.
#   • FILET : la fraîcheur de `t_tour`/`DMX["t_tour"]`, pour un thread qui se
#     bloquerait SANS lever d'exception (deadlock, appel bloquant).

# 🔢 GÉNÉRATION DE LA BOUCLE USB. Incrémentée (sous LOCK) à chaque relance de
# `usb_loop` par `connect_wing()`. Chaque boucle retient la sienne et se retire
# dès qu'elle n'est plus la courante — voir `wing_connexion._generation_perimee`
# et le contrôle test_une_seule_boucle_usb (smoke_securite.py).
THREAD_HEARTBEAT_SEUIL_S = 5.0


def threads_morts() -> dict:
    """Threads critiques morts, par nom → texte de l'erreur.

    Ne déclenche jamais avant le premier tour d'un thread (t_tour à 0.0 =
    pas encore démarré, pas encore jugé mort) — même garde que `_flux_muet`.
    """
    morts = dict(etat.E.THREAD_MORT)
    now = time.time()
    if etat.E.BOUCLE["t_tour"] and now - etat.E.BOUCLE["t_tour"] > THREAD_HEARTBEAT_SEUIL_S:
        morts.setdefault("usb_loop", f"aucun battement depuis "
                          f"{now - etat.E.BOUCLE['t_tour']:.0f} s")
    if etat.E.DMX["t_tour"] and now - etat.E.DMX["t_tour"] > THREAD_HEARTBEAT_SEUIL_S:
        morts.setdefault("dmx_listener", f"aucun battement depuis "
                          f"{now - etat.E.DMX['t_tour']:.0f} s")
    return morts


# ⚠️ LA CADENCE A DEUX ÉTATS : ~0,4 ms (30 Hz) ou ~320-337 ms (2,7 Hz), et ils
#    ALTERNAIENT d'un démarrage à l'autre (vérifié sur 8 redémarrages). App
#    arrêtée, la wing répond en < 1 ms : ce n'est donc pas elle.
#
# ❌ NE PAS REFAIRE — trois pistes mesurées SANS EFFET : purger le canal à la
#    connexion (drain 40 × 5 ms) · réinitialiser la wing quand la boucle est
#    lente · réduire le délai du drain (celui-là EFFONDRE la cadence).
#    Réglé en supprimant la source.
#    → docs/HARDWARE.md#cadence-de-boucle-a-deux-etats-30-hz-ou-2-7-hz-une-fois-sur-deux
BOUCLE_LENTE_HZ = 12.0        # en dessous, la boucle est considérée anormale
BOUCLE_LENT_SECONDES = 3      # …et il faut que ça DURE avant d'en parler


def _boucle_tic(cycle_ms: float, vide: bool):
    """Comptabilise un tour de boucle. Doit rester trivial : on mesure, on ne
    calcule pas."""
    now = time.time()
    etat.E.BOUCLE["n"] += 1
    etat.E.BOUCLE["cycle_ms"] = cycle_ms
    if cycle_ms > etat.E.BOUCLE["cycle_max"]:
        etat.E.BOUCLE["cycle_max"] = cycle_ms
    if vide:
        etat.E.BOUCLE["vides"] += 1
    if now - etat.E.BOUCLE["t_sec"] >= 1.0:
        ecoule = now - etat.E.BOUCLE["t_sec"] if etat.E.BOUCLE["t_sec"] else 1.0
        etat.E.BOUCLE["hz"] = round(etat.E.BOUCLE["n"] / ecoule, 1)

        # 🔎 Trace écrite AU MOMENT où la lenteur se produit, une seule fois :
        #   • beaucoup de tours VIDES → la wing ne répond pas (lectures en échec de
        #     délai) : piste « interface non revendiquée » ;
        #   • zéro tour vide mais une lecture longue → elle répond, lentement.
        # ⚠️ Seulement si la lenteur DURE : une seconde molle isolée se rattrape au
        # tour suivant, et la signaler remplirait le journal d'une alerte suivie de son
        # démenti.
        if etat.E.BOUCLE["hz"] < BOUCLE_LENTE_HZ and etat.E.BOUCLE["t_sec"]:
            etat.E.BOUCLE["lent_n"] += 1
            if etat.E.BOUCLE["lent_n"] >= BOUCLE_LENT_SECONDES and not etat.E.BOUCLE["signale"]:
                etat.E.BOUCLE["signale"] = True
                log("journal.boucle.lente", s=etat.E.BOUCLE['lent_n'], hz=etat.E.BOUCLE['hz'],
                    vides=etat.E.BOUCLE['vides'], n=etat.E.BOUCLE['n'],
                    lecture=f"{etat.E.BOUCLE['t_read']:.0f}", ecriture=f"{etat.E.BOUCLE['t_ecr']:.0f}",
                    claim=(wing_init.DERNIER_OPEN.get('claim') or 'ok'))
                # ⚠️ Aucun conseil d'action ici. La lenteur au démarrage est
                # traitée toute seule (réouverture de la liaison, 0,3 s). Si
                # elle survient EN COURS de route, on ne sait pas encore quoi
                # recommander — et un conseil inventé coûte plus cher qu'un
                # constat. Trois mauvais conseils dans la journée ont suffi.
        else:
            if etat.E.BOUCLE["signale"]:
                log("journal.boucle.revenue", hz=etat.E.BOUCLE["hz"])
            etat.E.BOUCLE["signale"] = False
            etat.E.BOUCLE["lent_n"] = 0

        etat.E.BOUCLE["t_sec"] = now
        etat.E.BOUCLE["n"] = 0
        etat.E.BOUCLE["cycle_max"] = 0.0
        etat.E.BOUCLE["vides"] = 0


# ⚠️ faders_instantane/executors_en_attente ont déménagé dans wing_faders.py
# (étape 6) — réexportées ci-dessous, section imports.



# ── Chenillard de test (mode "Vegas") ─────────────────────────────────────────
# Les fonctions LED vivent dans wing_touches_leds.py ; VEGAS reste ici (lu et
# écrit par les routes HTTP).

# ⚠️ LOG (le deque en mémoire) a déménagé dans wing_reglages.py (étape 8),
# avec log()/_log_to_file() — réexporté ci-dessous, section imports.

# ⚠️ Nom BOOTSTRAP seulement — PAS résolu ici via wing_i18n.L(). `_lire_locale`
# (plus bas dans CE fichier) n'existe pas encore à ce point du chargement du
# module : un appel à L() ici retomberait sur la clé brute (_cat() avale
# l'AttributeError et rend {}), donnant "ui.profils.defauts_nom" comme nom de
# profil au lieu d'un texte. La vraie résolution se fait dans main(), une fois
# le module entièrement chargé — voir plus bas.
etat.E.PROFILE["name"] = "ui.profils.defauts_nom"

# ── Config sûre : filet de sécurité (profil de RÉFÉRENCE verrouillé) ──────────
# Un « connu-qui-marche » restaurable en 1 clic, protégé de tout écrasement
# accidentel. Stocké dans un fichier réservé, JAMAIS listé ni écrasé comme un
# profil normal. Amorcé au 1er lancement depuis « Défaut sécurité » s'il existe,
# sinon depuis les défauts d'usine.
REFERENCE_FILE = wm.PROFILE_DIR / "__reference__.json"
# Nom du profil de secours comparé NORMALISÉ (accents, pluriel et casse varient
# d'une machine à l'autre) : une comparaison exacte ne l'a jamais trouvé, et la
# config sûre était amorcée depuis les défauts d'usine, en silence.
SEED_PROFILE   = "défauts-sécurité.json"   # amorçage préféré de la 1re config sûre


# ── Sauvegarde automatique (récupération après plantage) ──────────────────────
# Volontairement PAS un « enregistrement automatique par-dessus ton profil ».
# L'utilisateur décide seul de ce qu'il committe dans un profil nommé (bouton
# Enregistrer + pastille « modifié ») : écraser dans son dos serait pire que
# le problème résolu — on expérimente souvent sans vouloir garder.
#
# Modèle retenu : un fichier de RÉCUPÉRATION à part, écrit tant qu'il y a des
# modifs non enregistrées. Au démarrage suivant, s'il existe, c'est qu'on n'est
# pas sorti proprement (coupure, plantage, Mac redémarré en plein show) :
# l'interface propose de récupérer. Un enregistrement manuel le supprime, il
# n'a alors plus de raison d'être.
AUTOSAVE_FILE = wm.PROFILE_DIR / "__autosave__.json"
AUTOSAVE_EVERY_S = 5.0       # au plus une écriture toutes les 5 s




# ── Réglages MACHINE (≠ profil) ───────────────────────────────────────────────
# La cible OSC est délibérément HORS profil : les profils s'échangent entre
# collègues, et une IP embarquée dedans redirigerait silencieusement l'OSC de
# celui qui l'importe vers la machine de l'autre. Un réglage machine reste sur
# la machine. Stocké à côté du dossier des profils pour survivre aux mises à
# jour de l'app. (Lecture/écriture : wing_reglages.py.)

# ── Écoute OSC entrante — OBSERVATION UNIQUEMENT ─────────────────────────────
# Outil de diagnostic : on journalise ce qui arrive, sans rien interpréter.
#
# ⚠️ MA3 n'émet RIEN lors d'un changement de page : un rattrapage de fader
# construit sur le seul retour OSC travaillerait sur des valeurs périmées. Le
# rattrapage lit donc la sonde Lua, pas l'OSC. (Le retour natif de MA3 est
# indexé par numéro de SÉQUENCE, /11.14.1.5.<seq>, pas par executor.)
#
# L'OSC entrant, la cible OSC et les réglages machine vivent dans
# wing_reglages.py.

# Tokens qui s'accumulent dans le buffer de commande (repris de wing_bridge)
CMD_BUF_TOKENS = {
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
    ".", "+", "-", "Thru", "At", "If",
    "Sequence", "Cue", "Executor", "Fixture",
    "Group", "Preset", "Macro", "Effect",
    "Delete", "Copy", "Move", "Assign", "Label", "Store", "Update",
}


# Le journal serveur vit dans wing_reglages.py. `log`/`_log_to_file` sont
# remplacés par le test de fumée : les modules les appellent via
# `core.log(...)`, jamais par un appel nu.

wing_init.JOURNAL = log_init

# Anti-martèlement qui SURVIT à un redémarrage du moteur : on donne
# à wing_init où poser sa mémoire du dernier envoi de firmware. À côté des
# réglages, dans le dossier de données — pas dans le bundle (lecture seule).
wing_etat_materiel.ETAT_FICHIER = wm.PROFILE_DIR.parent / "wing_hw_state.json"


def appliquer_groupe_enc(gi: int):
    """Rend le groupe `gi` actif sur les 4 roues, et retient LEQUEL c'est.

    ⚠️ Passer par ici et nulle part ailleurs : c'est la mémoire de `enc_group`
    qui permet à l'onglet Encodeurs de ré-appliquer le groupe COURANT après une
    modification, au lieu de sauter sur le groupe par défaut.
    """
    with etat.E.LOCK:
        groupes = etat.E.PROFILE["enc_groups"]
        gi = gi if 0 <= gi < len(groupes) else 0
        etat.E.STATE["enc_group"] = gi
        etat.E.STATE["enc_attr"] = groupes[gi][:]
    return gi


def reset_enc_attr():
    """Repart du groupe PAR DÉFAUT — chargement de profil, démarrage."""
    appliquer_groupe_enc(etat.E.PROFILE["enc_default_group"])


reset_enc_attr()


# ⚠️ Connexion USB (connect_wing/_echec_init/_release_device), redémarrage
# du moteur (arreter_usb/restart_self/_relancer_process_neuf/USB_ARRET/
# USB_SORTIE) ont déménagé dans wing_connexion.py (étape 9) — réexportés
# ci-dessous, section imports.



KBD_PATTERN = "Wing Keyboard.app/Contents/MacOS/Wing Keyboard"

# ── Assistant clavier sous Windows ────────────────────────────────────────────
# Contrairement à macOS (session graphique + Accessibilité, d'où le détour par
# `open` une vraie .app), l'assistant Windows n'a besoin d'aucune permission ni
# session particulière : c'est un simple exe enfant que le serveur lance, suit
# et tue directement. On garde donc une poignée sur son process.
_kbd_proc = None                                   # subprocess.Popen (Windows)
_kbd_supervise = False                             # le watchdog doit-il relancer ?
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)   # pas de fenêtre console


def _windows_kbd_exe():
    """Chemin de l'assistant clavier Windows dans le build figé, ou None.

    Le build (build_windows.ps1, --onedir) pose wing_server.exe dans
    …\\wing_server\\ et « Wing Keyboard.exe » dans …\\Wing Keyboard\\ à côté."""
    exe = Path(sys.executable).parent.parent / "Wing Keyboard" / "Wing Keyboard.exe"
    return exe if exe.exists() else None


def _kill_windows_kbd():
    """Tue l'assistant clavier Windows (process suivi + tout résiduel), SANS
    désarmer le watchdog. Utilisé par la relance (tuer l'ancien avant le neuf)
    ET par l'arrêt définitif."""
    global _kbd_proc
    try:
        if _kbd_proc is not None and _kbd_proc.poll() is None:
            _kbd_proc.terminate()
            try:
                _kbd_proc.wait(timeout=2)
            except Exception:
                _kbd_proc.kill()
    except Exception as e:
        log("journal.kbd.arret_ko", err=e)
    # Filet : tuer aussi tout exemplaire résiduel (ancien build, lancement
    # manuel) pour ne RIEN laisser sonder dans le vide.
    try:
        subprocess.run(["taskkill", "/F", "/IM", "Wing Keyboard.exe"],
                       capture_output=True, creationflags=_NO_WINDOW)
    except Exception:
        pass
    _kbd_proc = None


def stop_keyboard_helper():
    """Tue l'assistant clavier, sans le relancer.

    ⚠️ Sans ça, « ⏻ Quitter » laissait l'assistant tourner pour de bon : sa
    boucle de sondage (wing_keyboard*.py, main()) n'a AUCUNE condition de
    sortie quand le serveur ne répond plus — `except: time.sleep(1); continue`
    à l'infini. Il restait donc visible dans le Moniteur d'activité / le
    Gestionnaire des tâches, à sonder dans le vide un serveur déjà mort
    (constaté côté macOS ; même risque sous Windows).
    """
    if not getattr(sys, "frozen", False):
        return
    if sys.platform.startswith("win"):
        global _kbd_supervise
        _kbd_supervise = False        # arrêt DÉFINITIF : le watchdog ne relance plus
        _kill_windows_kbd()
        return
    try:
        subprocess.run(["pkill", "-f", KBD_PATTERN], capture_output=True)
    except Exception as e:
        log("journal.kbd.arret_ko", err=e)


def _restart_keyboard_helper_windows():
    """Relance l'assistant clavier Windows comme exe enfant du serveur.

    Pas de session graphique ni d'Accessibilité à gérer (cf. l'en-tête de
    wing_keyboard_windows.py). On tue l'ancien exemplaire puis on relance un
    process frais, sans fenêtre visible (CREATE_NO_WINDOW), en lui passant le
    port réel de l'interface pour qu'il sonde le bon serveur. Arme le watchdog
    (_kbd_supervise) pour qu'il soit relancé s'il meurt."""
    global _kbd_proc, _kbd_supervise
    exe = _windows_kbd_exe()
    if exe is None:
        attendu = Path(sys.executable).parent.parent / "Wing Keyboard" / "Wing Keyboard.exe"
        log("journal.kbd.introuvable", chemin=attendu)
        return
    _kill_windows_kbd()                             # tue l'ancien, sans désarmer
    try:
        _kbd_proc = subprocess.Popen(
            [str(exe), "--url", f"http://127.0.0.1:{UI_PORT}"],
            creationflags=_NO_WINDOW)
        _kbd_supervise = True                       # (ré)arme la surveillance
        log("journal.kbd.lance", pid=_kbd_proc.pid)
    except Exception as e:
        log("journal.kbd.lancement_ko", err=e)


_KBD_WATCHDOG_WINDOW_S = 60.0   # fenêtre glissante d'observation des morts
_KBD_WATCHDOG_MAX = 5           # relances max dans la fenêtre avant d'abandonner


def _keyboard_watchdog():
    """Windows : relance l'assistant clavier s'il MEURT (crash, kill externe).

    La relance Mac est opportuniste (au démarrage du Bridge, qui exige une wing
    connectée) : insuffisant pour « se relancer s'il meurt » pendant un show.
    Ce watchdog comble ce trou. Il ne relance QUE si _kbd_supervise est armé —
    « ⏻ Quitter » le désarme (stop_keyboard_helper) pour ne pas ressusciter
    l'assistant pendant l'arrêt.

    🛡️ Anti boucle-de-plantage : un assistant sain tourne indéfiniment ; s'il
    meurt _KBD_WATCHDOG_MAX fois en moins de _KBD_WATCHDOG_WINDOW_S, c'est
    pathologique (exe cassé, dépendance manquante…). On ABANDONNE alors la
    relance — avec un log clair, jamais en silence — plutôt que de le relancer
    toutes les 2 s à l'infini. Un démarrage de Bridge ou un redémarrage moteur
    (restart_keyboard_helper) réarme la surveillance pour retenter."""
    global _kbd_supervise
    morts = []                              # horodatages des relances récentes
    while True:
        time.sleep(2.0)
        if not _kbd_supervise:
            morts.clear()                   # désarmé (arrêt/abandon) : on oublie
            continue
        if _kbd_proc is None or _kbd_proc.poll() is not None:
            now = time.time()
            morts[:] = [t for t in morts if now - t < _KBD_WATCHDOG_WINDOW_S]
            if len(morts) >= _KBD_WATCHDOG_MAX:
                log_plural("journal.kbd.mort_abandon", len(morts),
                           s=int(_KBD_WATCHDOG_WINDOW_S))
                _kbd_supervise = False      # stoppe la surveillance (pas de spam)
                continue
            morts.append(now)
            log("journal.kbd.relance_watchdog", n=len(morts), max=_KBD_WATCHDOG_MAX)
            restart_keyboard_helper()


def restart_keyboard_helper():
    """Relance l'assistant clavier.

    Windows : exe enfant géré par le serveur (voir _restart_keyboard_helper_windows).

    macOS : relance Wing Keyboard.app DANS LA SESSION GRAPHIQUE de l'utilisateur
    connecté — jamais en root (sinon macOS bloque l'injection clavier).

    ⚠️ Cet en-tête affirmait « ce process tourne en root ». Ce n'est plus vrai :
    le serveur tourne en uid 501, et `run_in_user_session`
    lance alors directement, sans `sudo` ni mot de passe. Le détour
    `launchctl asuser` + `sudo -u` ne sert QUE dans le repli root, où c'est la
    méthode standard macOS.

    Ne touche PAS au binaire
    (même signature, même autorisation Accessibilité déjà accordée — juste
    un redémarrage de process, pas une reconstruction)."""
    if not getattr(sys, "frozen", False):
        log("(assistant clavier : pas de bundle en mode dev, redémarrage ignoré)")
        return
    if sys.platform.startswith("win"):
        _restart_keyboard_helper_windows()
        return
    kbd_app = Path(sys.executable).parent.parent / "Wing Keyboard.app"
    if not kbd_app.exists():
        log("journal.kbd.app_introuvable", chemin=kbd_app)
        return
    try:
        subprocess.run(["pkill", "-f", KBD_PATTERN], capture_output=True)
        # Attend ACTIVEMENT la mort CONFIRMÉE du process (jusqu'à 2 s) plutôt qu'un
        # délai fixe : relancer trop tôt fait que macOS RÉACTIVE parfois l'ancien
        # process, avec son autorisation Accessibilité périmée (« clavier console :
        # prêt » affiché à tort ; 0,3 s fixes se sont révélées insuffisantes).
        for _ in range(20):   # 20 × 0.1s = 2s max
            r = subprocess.run(["pgrep", "-f", KBD_PATTERN], capture_output=True)
            if r.returncode != 0:   # pgrep : rien trouvé → vraiment mort
                break
            time.sleep(0.1)
        else:
            # Toujours vivant après 2s → SIGKILL pour être sûr de repartir propre
            subprocess.run(["pkill", "-9", "-f", KBD_PATTERN], capture_output=True)
            time.sleep(0.2)
        open_in_user_session(kbd_app)
        user = subprocess.run(["stat", "-f", "%Su", "/dev/console"],
                               capture_output=True, text=True, timeout=2).stdout.strip()
        log("journal.kbd.relance_user", user=user)
    except Exception as e:
        log("journal.kbd.relance_ko", err=e)


def run_in_user_session(args, timeout=10):
    """Exécute une commande dans la session GRAPHIQUE de l'utilisateur connecté.
    Renvoie (CompletedProcess, nom d'utilisateur).

    Deux cas, et il FAUT les distinguer :
      • serveur lancé en root (ancien mode, ou repli) : lancer directement
        depuis root n'atteint pas la bonne session ni le bon contexte TCC →
        `launchctl asuser` + `sudo -u`, méthode standard macOS.
      • serveur lancé en utilisateur (le mode normal) : on EST
        déjà dans la bonne session. Passer par `sudo` ici **demanderait un mot
        de passe** et bloquerait — c'est exactement ce qu'on cherche à éviter.
    """
    if os.geteuid() != 0:
        r = subprocess.run(list(args), capture_output=True, text=True,
                           timeout=timeout)
        return r, os.environ.get("USER", "?")
    user = subprocess.run(["stat", "-f", "%Su", "/dev/console"],
                           capture_output=True, text=True, timeout=2).stdout.strip()
    uid = subprocess.run(["id", "-u", user],
                          capture_output=True, text=True, timeout=2).stdout.strip()
    r = subprocess.run(["launchctl", "asuser", uid, "sudo", "-u", user] + list(args),
                        capture_output=True, text=True, timeout=timeout)
    return r, user


def open_in_user_session(path):
    """Ouvre un fichier/dossier (Finder, ou une .app) dans la session de
    l'utilisateur connecté. Voir run_in_user_session pour le pourquoi."""
    return run_in_user_session(["open", str(path)], timeout=5)[1]


KBD_BUNDLE_ID = "com.wingbridge.keyboard"


def forget_keyboard_authorization():
    """Efface l'enregistrement Accessibilité périmé de l'assistant clavier.

    Après un rebuild, « Wing Keyboard » reste AFFICHÉ et coché dans Réglages →
    Accessibilité, mais l'entrée ne correspond plus au nouveau binaire : la
    signature ad-hoc n'a pas d'ancrage stable (pas de Team ID payant), donc TCC
    a mémorisé l'empreinte de l'ANCIEN exécutable. Résultat : une case cochée
    qui n'autorise rien, et plusieurs entrées d'apparence identique dont
    l'utilisateur ne peut pas deviner laquelle est la bonne (constaté : 2
    enregistrements empilés). `tccutil reset` les supprime pour que la demande
    système reparte de zéro et en recrée un seul, valide.

    Appelé uniquement depuis le bouton 🔓, qui n'apparaît que lorsque
    l'autorisation ne fonctionne déjà pas — donc rien de fonctionnel à perdre.
    """
    try:
        r, _ = run_in_user_session(["tccutil", "reset", "Accessibility",
                                    KBD_BUNDLE_ID])
        if r.returncode == 0:
            log("journal.kbd.accessibilite_effacee")
            return True
        log("(tccutil : " + ((r.stderr or r.stdout or "").strip() or "échec") + ")")
    except Exception as e:
        log(f"(tccutil indisponible : {e})")
    return False


# ── Boucle USB (thread) ────────────────────────────────────────────────────────

# Fonctions de déclenchement disponibles pour un bouton "Executor" (miroir des
# fonctions assignables à un executor dans MA3 lui-même — Assign menu, Handle
# page). Doc officielle MA Lighting (juillet 2026), syntaxe confirmée pour
# chacune :
#   Go+ / Go- / Toggle / Off / Pause  → coup unique : "<Fonction> Executor N"
#   Flash / Temp / Swap               → MAINTENU : "<Fonction> On/Off Executor N"
EXEC_FUNCS = ["Go+", "Go-", "Toggle", "Off", "Pause", "Flash", "Temp", "Swap"]

# Fonctions executor MAINTENUES : « On » à l'appui, « Off » au relâchement (doc
# officielle MA Lighting) — sinon l'executor reste bloqué actif. Détecté par
# motif sur la commande stockée (ex. "Flash On Executor 105").
# ⚠️ UNE SEULE SOURCE : MA3_VERBES_MAINTENUS (un second jeu, sans « Black »,
# a déjà laissé « Black On Executor N » sans son Off).
MAINTENUES_UI = {v.capitalize() for v in MA3_VERBES_MAINTENUS} & set(EXEC_FUNCS)

# Anti-rebond, appui/relâchement, mode console : wing_boutons.py. Restent ici,
# lus aussi par l'assistant et les routes : VERBES_CIBLE, CONSOLE_CIBLES,
# VERBE, CMD_BUF_TOKENS.

# Verbes qui attendent une CIBLE : touches de la SECTION COMMANDE (Off puis un
# executor = « Off Executor 105 », comme sur une vraie console). Utilisé par
# assistant_liste() et wing_boutons.py (mot_cycle / handle_button_bridge).
# ⚠️ Chaque verbe ajouté DOIT avoir sa syntaxe « <Verbe> Executor <n> » vérifiée
# dans le manuel installé (shared/language/HTML/keyword_*.html, gma3 2.4.2) :
#   Off    « Stop an executor »              On     « Start or restart an executor »
#   Kill   « Kill Executor 102 »             Toggle « Toggle Executor 104 »
# ⚠️ Ne pas confondre avec MA3_KEY_VERBES (ce que fait la touche D'UN
# EXECUTOR, lu dans MA3). « Top » n'est PAS un verbe cible : un token
# Go+/Go-/Pause/Top est capté plus haut par le chemin de playback direct.
VERBES_CIBLE = {"Store", "Update", "Delete", "Copy", "Move", "Assign",
                "Edit", "Label", "Goto", "Load", "Select", "Fix",
                # actions de playback visant un executor
                "Off", "On", "Kill", "Toggle",
                # obtenus par appuis répétés — voir MA3_CYCLES (wing_boutons.py)
                "Exchange", "Collect", "EditSetting", "Insert"}

# Commande en cours d'assemblage depuis la wing, en mode console — reste ici,
# lue par la route HTTP _post_verbe_cible ET par wing_boutons.py.

# Verbe tapé depuis la wing en attente d'une cible — reste ici, lu par la
# route HTTP _post_verbe_cible ET par wing_boutons.py.
# ⚠️ WingUnplugged, santé du flux USB (WING_FLUX/_flux_ok/_flux_muet),
# cycle_dmx, dmx_listener et usb_loop ont déménagé dans wing_connexion.py
# (étape 9) — réexportés ci-dessous, section imports.

# ── API HTTP ───────────────────────────────────────────────────────────────────

# ⚠️ La classe Handler (toutes les routes /api/... et la page d'accueil) a
# déménagé dans wing_handler.py (étape 10, la dernière du découpage) —
# réexportée ci-dessous, section imports.

# ── Interface HTML ─────────────────────────────────────────────────────────────

# ── Interface : chargée depuis wing_ui.html ───────────────────────────────────
# Fichier à part, pas une chaîne Python : ce qui est écrit est ce qui est servi
# (dans une chaîne, Python interprétait « \n » et coupait le JavaScript).
# ⚠️ Embarqué par PyInstaller (--add-data des scripts de build), sinon l'app
# ne sert aucune page.
if getattr(sys, "frozen", False):
    _RES_DIR = Path(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
else:
    _RES_DIR = Path(__file__).resolve().parent
HTML_FILE = _RES_DIR / "wing_ui.html"

# ── Le JavaScript : dossier `ui/`, un fichier par onglet ─────────────────────
#
# ⚠️ LE DOSSIER ENTIER doit être embarqué par les deux scripts de build
# (`--add-data "$SRC/ui:ui"`). Un seul fichier manquant et l'app démarre, sert
# une page complète… avec une interface INERTE : aucun bouton ne répond, aucune
# erreur nulle part. D'où la vérification au démarrage ci-dessous, et les
# scripts de build qui refusent de finir si le dossier n'est pas là.
#
# Chargés à la DEMANDE puis gardés en cache mémoire (voir `_lire_js`).
JS_DIR = _RES_DIR / "ui"

# ⚠️ L'ORDRE EST LE MÊME QUE DANS wing_ui.html : `core` en premier (il déclare
# les globales que les autres lisent), `i18n` juste après (t()/appliquerLangue()
# dont les onglets se servent dès leur premier rendu), `init` en dernier (il
# appelle les autres). Cette liste ne sert pas à servir les fichiers — le
# navigateur les demande un par un — mais à vérifier au démarrage qu'ils sont
# tous là. ⚠️ Un nom absent d'ici est refusé par `_lire_js` (liste blanche) :
# l'ajouter dans wing_ui.html SANS l'ajouter ici = fichier servi en 404 =
# interface inerte.
JS_FICHIERS = ("core", "i18n", "aides", "bridge", "touches", "faders_encodeurs",
               "profils", "parametres", "init")

_JS_CACHE = {}


def _lire_js(nom: str):
    """Contenu d'un fichier de `ui/`, ou None si le nom n'est pas légitime.

    ⚠️ LE NOM VIENT DE L'EXTÉRIEUR (l'URL). Il est donc validé par une liste
    BLANCHE, pas par un filtrage de « .. » : on ne se demande pas si le chemin
    est dangereux, on refuse tout ce qui n'est pas un fichier connu. C'est la
    seule forme qui ne se contourne pas.
    """
    if nom not in JS_FICHIERS:
        return None
    if nom not in _JS_CACHE:
        try:
            _JS_CACHE[nom] = (JS_DIR / f"{nom}.js").read_text(encoding="utf-8")
        except Exception as e:
            log("journal.ui.js_illisible", nom=nom, err=e)
            _JS_CACHE[nom] = (f"console.error('ui/{nom}.js illisible');")
    return _JS_CACHE[nom]


# Constat AU DÉMARRAGE plutôt qu'à la première panne : une interface muette ne
# dit rien d'elle-même, et c'est justement le mode de panne qu'on chasse.
_js_absents = [n for n in JS_FICHIERS if not (JS_DIR / f"{n}.js").is_file()]
if _js_absents:
    print(f"✗ ui/ INCOMPLET — manquant(s) : {', '.join(_js_absents)} "
          f"— l'interface sera inerte. Cherché dans {JS_DIR}")


# ── Catalogues de langue : dossier `locales/`, un JSON plat par langue ────────
#
# Servis par une route dédiée (voir wing_handler._get_locale), calquée sur
# `_lire_js` : même `_RES_DIR`, même liste blanche, même règle `no-store`. Ce
# choix (route plutôt que fichier statique) est le SEUL qui marche identiquement
# en app figée (sous sys._MEIPASS) et lancé depuis les sources. Voir docs/I18N.md
#
# ⚠️ Le dossier doit être embarqué par les trois scripts de build
# (`--add-data "$SRC/locales:locales"`). Absent, l'interface reste en français
# (repli assuré côté client) mais le sélecteur ne bascule rien.
LOCALES_DIR = _RES_DIR / "locales"
LOCALES = ("fr", "en")
_LOCALE_CACHE = {}


def _lire_locale(nom: str):
    """Contenu JSON d'un catalogue de `locales/`, ou None si le nom n'est pas
    une langue connue.

    ⚠️ LE NOM VIENT DE L'URL — validé par liste BLANCHE (LOCALES), jamais par un
    filtrage de « .. ». Même principe que `_lire_js`.
    """
    if nom not in LOCALES:
        return None
    if nom not in _LOCALE_CACHE:
        try:
            _LOCALE_CACHE[nom] = (LOCALES_DIR / f"{nom}.json").read_text(
                encoding="utf-8")
        except Exception as e:
            log("journal.ui.locale_illisible", nom=nom, err=e)
            _LOCALE_CACHE[nom] = "{}"
    return _LOCALE_CACHE[nom]


_loc_absents = [n for n in LOCALES if not (LOCALES_DIR / f"{n}.json").is_file()]
if _loc_absents:
    print(f"⚠️ locales/ INCOMPLET — manquant(s) : {', '.join(_loc_absents)} "
          f"— l'interface restera en français. Cherché dans {LOCALES_DIR}")

try:
    HTML = HTML_FILE.read_text(encoding="utf-8")
except Exception as _e:
    # Sans interface, l'app n'a plus d'intérêt : on le dit franchement plutôt
    # que de servir une page vide et laisser chercher.
    # ⚠️ Page de secours SANS JavaScript (rien ne peut charger si le HTML
    # lui-même est illisible) : t()/tHtml() n'existent pas ici, on résout donc
    # côté serveur via wing_i18n.L(), _lire_locale étant déjà défini plus haut.
    import wing_i18n
    HTML = ("<!doctype html><meta charset='utf-8'>"
            "<h1>{titre}</h1><p>{corps}</p>").format(
        titre=wing_i18n.L("err.html_introuvable.titre"),
        corps=wing_i18n.L("err.html_introuvable.corps",
                          erreur=_e, chemin=HTML_FILE))
    print(f"✗ wing_ui.html illisible ({_e}) — interface indisponible")



# ── Main ───────────────────────────────────────────────────────────────────────

def _pid_vivant(pid: int) -> bool:
    """Le process `pid` est-il encore vivant ? Multi-plateforme.

    ⚠️ Windows : `os.kill(pid, 0)` n'est PAS un test d'existence — le signal 0 y
    vaut CTRL_C_EVENT (il n'interroge rien). On passe par OpenProcess +
    GetExitCodeProcess. Sans ça, l'attente de l'instance précédente ne tenait
    pas sous Windows, et le redémarrage devient le chemin PRINCIPAL (execv cassé).
    """
    if sys.platform == "win32":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        k = ctypes.windll.kernel32
        h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False                 # introuvable = considéré mort
        try:
            code = ctypes.c_ulong()
            if k.GetExitCodeProcess(h, ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return True                  # doute : on le suppose vivant
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)                  # POSIX : signal 0 = test pur
        return True
    except ProcessLookupError:
        return False
    except Exception:
        return True                      # doute : vivant (borné par le délai)


def _attendre_instance_precedente(delai: float = 6.0):
    """Attend la mort de l'instance qui nous a lancés, avant de toucher l'USB.

    🐛 Vu dans le journal dès le premier redémarrage en process neuf. Les deux
    instances se sont chevauchées ~1 s, et la
    nouvelle a ouvert la wing pendant que l'ancienne la tenait encore :

        17:36:15  ↻ Moteur relancé dans un process neuf — celui-ci s'arrête
        17:36:15  Connexion à la wing…
        17:36:15  ⚠️ Wing annoncée opérationnelle mais muette
        17:36:15  ✗ Wing non initialisée (USBError: [Errno 32] Pipe error)
        17:36:15  ⏸ Nouvelles tentatives SUSPENDUES — ➜ DÉBRANCHE la wing…

    Ça se rattrapait tout seul 7 s plus tard, mais le message demandait de
    DÉBRANCHER la wing alors qu'il n'y avait rien à débrancher. Un mauvais
    conseil affiché avec autorité coûte plus cher que le bug lui-même.

    ⚠️ Ne concerne QUE le redémarrage depuis l'app : au lancement normal la
    variable est absente et cette fonction ne coûte rien.
    """
    pid = os.environ.pop("WING_ATTENDRE_PID", "")
    if not pid.isdigit():
        return
    pid = int(pid)
    fin = time.time() + delai
    while time.time() < fin:
        if not _pid_vivant(pid):
            break                    # l'instance précédente est morte
        time.sleep(0.1)
    else:
        log("journal.demarrage.instance_precedente", pid=pid, s=f"{delai:.0f}")
    # Le process est mort, mais la fermeture du périphérique côté système
    # n'est pas instantanée. Ce court délai évite le « Pipe error » ci-dessus.
    time.sleep(0.4)


def _ouvrir_url(url: str) -> bool:
    """Ouvre `url` dans le navigateur. Renvoie True si l'ouverture a été lancée.

    ⚠️ Repli admin macOS : le serveur tourne alors en root, et `webbrowser.open`
    (donc `open` en root) n'atteint pas la session graphique de l'utilisateur.
    On passe par le même détour que l'assistant clavier (`open_in_user_session`).
    """
    try:
        if sys.platform == "darwin" and os.geteuid() == 0:
            open_in_user_session(url)
            return True
        return bool(webbrowser.open(url))
    except Exception:
        return False


def _instance_deja_active(url: str):
    """Sonde une instance de Wing Bridge déjà en écoute sur le port.

    → 'onglet'  : elle tourne ET un onglet est ouvert  → ne rien faire
    → 'fantome' : elle tourne SANS onglet              → rouvrir le navigateur
    → None      : rien ne répond (ou redémarrage moteur en cours) → démarrer

    ⚠️ On saute la sonde quand `WING_ATTENDRE_PID` est présent : on est alors le
    SUCCESSEUR d'un redémarrage moteur (bouton 🔄 / hard_reset), l'ancien
    process agonise et c'est à NOUS de reprendre le port — le sonder ferait
    ressortir ce process et plus personne ne servirait l'interface.
    """
    if os.environ.get("WING_ATTENDRE_PID"):
        return None
    try:
        import urllib.request
        with urllib.request.urlopen(url + "/api/instance", timeout=0.8) as r:
            d = json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    return "onglet" if d.get("ui_active") else "fantome"


def arret_propre():
    """LE chemin d'arrêt unique : rend la wing, coupe l'assistant clavier, puis
    `os._exit(0)`. Partagé par « ⏻ Quitter » (`wing_handler._post_quit`) et par
    la fermeture d'onglet (`vie_loop`).

    ⚠️ Identique au corps historique de `_post_quit` (voir sa docstring : Quitter
    ne rendait pas la wing avant). La wing repartira en bootloader — c'est la
    conséquence assumée, documentée dans docs/HARDWARE.md.
    """
    try:
        # pas d'auto-reconnexion pendant l'arrêt
        etat_poser(want_connected=False, mode="idle")
        arreter_usb()                     # attend la lecture USB en vol, puis libère
    except Exception as e:
        log("journal.moteur.usb_imparfaite_arret", err=e)
    try:
        stop_keyboard_helper()
    except Exception as e:
        log("journal.moteur.kbd_imparfait_arret", err=e)
    vider_journal()          # os._exit saute atexit : le journal est différé
    os._exit(0)


def vie_loop():
    """Surveille l'arrêt différé armé par la fermeture d'un onglet.

    Fenêtre fermée pour de bon → au bout de `FERMETURE_GRACE_S` sans le moindre
    ping d'onglet, arrêt propre (le chemin de « ⏻ Quitter »).
    Rechargement (F5) → un ping revient dans la fenêtre de grâce → on désarme.

    ⚠️ Ne réagit QU'À l'armement explicite (`POST /api/fermeture-onglet`, via
    `navigator.sendBeacon` sur `pagehide`). Un simple arrêt du poll — veille de
    l'ordinateur, coupure réseau — ne déclenche RIEN : la veille ne doit pas
    tuer l'app.
    """
    while True:
        time.sleep(0.5)
        verdict = _vie_verdict(time.monotonic(), etat.E.UI_VIE["arret_t"],
                               etat.E.UI_VIE["dernier_ping"], FERMETURE_GRACE_S)
        if verdict == "annule":
            etat.E.UI_VIE["arret_t"] = 0.0
            log("journal.vie.rechargement")
        elif verdict == "arret":
            log("journal.vie.fermeture_arret")
            arret_propre()


def main(open_browser: bool = True):
    # ⚠️ Windows : la console par défaut est en cp1252/cp850, incapable
    # d'encoder les caractères non-ASCII omniprésents dans nos messages
    # (« → », « — », « ═ », emojis). Sans ce garde, le TOUT PREMIER print
    # ci-dessous plante l'app au démarrage (UnicodeEncodeError sur « → »,
    # constaté sur un build figé ; masqué depuis les sources par
    # PYTHONIOENCODING=utf-8, d'où la découverte tardive). On
    # bascule stdout/stderr en UTF-8 tolérant. Inoffensif sous macOS (déjà
    # UTF-8) et si le flux n'a pas .reconfigure (frozen sans console).
    for _flux in (sys.stdout, sys.stderr):
        try:
            _flux.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # ── Instance unique — AVANT tout : threads, fichiers, USB, serveur ─────────
    # Une instance répond déjà sur le port ? Alors on ne démarre RIEN : ni 2ᵉ
    # serveur, ni thread, ni ouverture de fichier. On journalise dans l'instance
    # DÉJÀ en place (elle tient le fichier) puis on ressort.
    import wing_i18n
    url = f"http://127.0.0.1:{UI_PORT}"
    _autre = _instance_deja_active(url)
    if _autre == "onglet":
        print(wing_i18n.L("journal.demarrage.deja_lance_onglet"))
        log("journal.demarrage.deja_lance_onglet")
        sys.exit(0)
    if _autre == "fantome":
        print(wing_i18n.L("journal.demarrage.deja_lance_fantome"))
        log("journal.demarrage.deja_lance_fantome")
        if open_browser:
            _ouvrir_url(url)
        sys.exit(0)

    # Résolution différée des placeholders bootstrap (posés plus haut avant que
    # _lire_locale existe — voir les commentaires à BUILD_DATE et PROFILE) :
    # le module est maintenant entièrement chargé, L() peut lire le catalogue.
    global BUILD_DATE
    import wing_i18n
    if BUILD_DATE == "err.build_date.sources":
        BUILD_DATE = wing_i18n.L("err.build_date.sources")
    if etat.E.PROFILE.get("name") == "ui.profils.defauts_nom":
        etat.E.PROFILE["name"] = wing_i18n.L("ui.profils.defauts_nom")
    print("=== Wing UI — MA2 Wing → grandMA3 ===")
    print(f"    build #{BUILD} ({BUILD_DATE})\n")
    # Séparateur dans le fichier : le bouton 🔄 relance le process en place
    # (execv), donc plusieurs sessions s'enchaînent dans le même fichier. Sans
    # marqueur, impossible de savoir où commence celle qui a posé problème.
    install_crash_logging()
    # Sauvegarde horodatée AVANT le séparateur : fige la session précédente
    # telle qu'elle était avant que celle-ci n'y ajoute quoi que ce soit.
    archiver_session_precedente()
    _log_to_file("")
    _log_to_file("═" * 62)
    _log_to_file(f"  DÉMARRAGE — build #{BUILD} ({BUILD_DATE}) — pid {os.getpid()}")
    _log_to_file("═" * 62)

    # Aussi dans le journal de l'interface : c'est là que l'utilisateur (ou un
    # collègue à qui on demande une copie d'écran) le lira le plus facilement.
    log(f"Wing Bridge build #{BUILD} ({BUILD_DATE})")

    # Réparation ponctuelle : de très anciennes versions écrivaient
    # profils et réglages en tant que root, rendant ces fichiers non
    # supprimables dans le Finder sans mot de passe. On réaligne tout ce qui
    # traîne sur le propriétaire du dossier — silencieux et sans effet une
    # fois fait.
    try:
        repares = 0
        for f in SETTINGS_FILE.parent.rglob("*.json"):
            st = f.stat()
            if st.st_uid == 0:
                wm.own_like_parent(f)
                repares += 1
        if repares:
            log_plural("journal.demarrage.reattribues", repares)
    except Exception:
        pass

    # Réglages machine (cible OSC) — AVANT de démarrer quoi que ce soit, pour
    # que les premiers envois partent déjà sur la bonne cible.
    load_settings()
    log(f"OSC → {wb.MA3_IP}:{wb.MA3_PORT}")

    # Windows : aucun launcher.sh ne crée le dossier des profils en amont (macOS
    # le fait via `mkdir -p "$DATA_DIR/profiles"` avant de lancer le serveur).
    # Sans lui, le tout premier lancement échouerait : save_reference() fait un
    # mkdir SANS parents, or %APPDATA%\Wing Bridge n'existe pas encore. On crée
    # donc l'arborescence ici, une fois, avant tout amorçage.
    if getattr(sys, "frozen", False) and sys.platform.startswith("win"):
        try:
            wm.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"[REF] création du dossier profils échouée : {e}")

    # Filet de sécurité : garantit qu'une « config sûre » existe dès le départ.
    try:
        ensure_reference()
    except Exception as e:
        print(f"[REF] amorçage config sûre échoué : {e}")

    # ⭐ Profil favori : chargé AVANT tout le reste, pour que l'app démarre
    # dans la configuration de CETTE wing.
    #
    # 🔑 Deux wings n'ont pas forcément la même
    # disposition : ordre des faders, touches présentes ou remplacées, rôle de
    # chaque roue. Redémarrer l'app et retomber sur les défauts d'usine oblige à
    # recharger son profil à la main à chaque fois.
    #
    # ⚠️ Un favori introuvable ou illisible ne doit JAMAIS empêcher le
    # démarrage : on le signale et on continue sur les défauts.
    charger_favori()

    # Récupération éventuelle d'une session précédente mal terminée — AVANT de
    # lancer la sauvegarde automatique, qui écraserait le fichier.
    detect_recovery()

    # Si on vient d'un redémarrage : laisser l'instance précédente rendre la
    # wing AVANT de lancer quoi que ce soit qui y touche.
    _attendre_instance_precedente()

    # Boucle USB en arrière-plan
    # ⚠️ `name=` explicite : c'est la clé que `wing_diagnostic._hook_thread`
    # utilise pour poser `THREAD_MORT[nom]` — sans lui, un thread mort
    # s'appellerait "Thread-N", inexploitable pour l'afficher honnêtement.
    threading.Thread(target=usb_loop, daemon=True, name="usb_loop").start()

    # Sauvegarde automatique (récupération après plantage)
    threading.Thread(target=autosave_loop, daemon=True).start()

    # Écoute OSC entrante (observation) — le thread tourne toujours, mais ne
    # fait rien tant qu'aucun port n'est lié.
    if etat.E.SETTINGS.get("osc_in_port"):
        osc_in_bind(etat.E.SETTINGS["osc_in_port"])
    threading.Thread(target=osc_in_loop, daemon=True).start()

    # Récepteur sACN / Art-Net (sortie DMX vers le XLR de la wing)
    threading.Thread(target=dmx_listener, daemon=True, name="dmx_listener").start()

    # Chenillard de test LED
    threading.Thread(target=vegas_loop, daemon=True).start()

    # Cycle de vie : surveille l'arrêt différé armé par la fermeture d'un onglet
    # (POST /api/fermeture-onglet). Ne fait rien tant que rien n'est armé.
    threading.Thread(target=vie_loop, daemon=True, name="vie_loop").start()

    # Réconciliation au démarrage (une seule fois, avant le premier essai) : un
    # blocage PÉRIMÉ dans wing_hw_state.json — posé lors d'un échec, jamais
    # effacé parce que l'app était fermée pendant le débranchement — refusait une
    # wing repartie de zéro. Seuls les blocages anciens sont levés ; un blocage
    # récent (🔄 Réinitialiser) reste. N'agit qu'ici, au démarrage.
    if wing_etat_materiel.reconcilier_blocage_au_demarrage():
        log("journal.demarrage.blocage_oublie")

    # Connexion wing en arrière-plan (l'UI est utilisable sans wing)
    threading.Thread(target=connect_wing, daemon=True).start()

    print(f"Interface : {url}")
    print("Ctrl+C pour arrêter.\n")
    if open_browser:
        # Le résultat est journalisé (« le navigateur s'est-il ouvert ? » doit être un
        # FAIT du journal) : un échec d'ouverture passait en silence. C'est le SERVEUR
        # qui ouvre le navigateur dans tous les cas (launcher.sh n'en ouvre plus).
        # Windows : `webbrowser` → os.startfile, sans console. macOS en repli root :
        # `_ouvrir_url` passe par la session graphique de l'utilisateur.
        def _ouvrir_navigateur():
            try:
                ouvert = _ouvrir_url(url)
                log("journal.demarrage.navigateur_ok" if ouvert
                    else "journal.demarrage.navigateur_manuel", url=url)
            except Exception as e:
                log("journal.demarrage.navigateur_ko", err=e, url=url)
        threading.Timer(0.8, _ouvrir_navigateur).start()

    # Le port peut être encore occupé quelques secondes après l'arrêt de
    # l'instance précédente (constaté : redémarrage de l'app juste
    # après un « Quitter » → OSError 48, le serveur mourait aussitôt et le
    # launcher croyait à un problème de droits). On réessaie au lieu d'abandonner.
    server = None
    for essai in range(20):                      # 20 × 0.5 s = 10 s max
        try:
            server = ThreadingHTTPServer(("127.0.0.1", UI_PORT), Handler)
            break
        except OSError as e:
            if essai == 0:
                log("journal.demarrage.port_occupe", port=UI_PORT)
            time.sleep(0.5)
    if server is None:
        log("journal.demarrage.port_toujours_occupe", port=UI_PORT)
        print(f"✗ Port {UI_PORT} occupé — abandon.")
        return
    # Le port est à nous : on publie le jeton pour l'assistant clavier (fichier
    # 0600). Un échec ne bloque pas l'app — l'onglet reçoit le jeton par la
    # page — mais l'assistant ne pourra plus taper : on le dit.
    try:
        log("journal.http.jeton_ecrit",
            chemin=wing_jeton.ecrire_jeton(API_JETON))
    except Exception as e:
        log("journal.http.jeton_ko", err=e)
    if essai:
        log("journal.demarrage.port_libere", port=UI_PORT, s=f"{essai * 0.5:.1f}")

    # Windows : démarrer l'assistant clavier AVEC le serveur. Sur macOS c'est
    # launcher.sh qui l'ouvre à l'ouverture de l'app ; Windows n'a pas de
    # launcher, donc le serveur s'en charge dès que le port est ouvert. Il se
    # relancera au besoin (démarrage du Bridge, redémarrage moteur) et sera tué
    # par « ⏻ Quitter » (stop_keyboard_helper). Le filet atexit couvre une sortie
    # non prévue (Ctrl+C, exception) pour ne pas laisser l'assistant orphelin —
    # « ⏻ Quitter » passe par os._exit et appelle stop_keyboard_helper lui-même.
    if getattr(sys, "frozen", False) and sys.platform.startswith("win"):
        import atexit
        atexit.register(stop_keyboard_helper)
        restart_keyboard_helper()
        # Watchdog : relance l'assistant s'il meurt (voir _keyboard_watchdog).
        threading.Thread(target=_keyboard_watchdog, daemon=True,
                         name="kbd_watchdog").start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Wing UI — bridge + mapping web")
    ap.add_argument("--no-browser", action="store_true",
                    help="ne pas ouvrir le navigateur automatiquement")
    ap.add_argument("--port", type=int, default=UI_PORT,
                    help=f"port de l'interface web (défaut {UI_PORT})")
    args = ap.parse_args()
    UI_PORT = args.port
    main(open_browser=not args.no_browser)


# ── État partagé DÉMÉNAGÉ dans etat.py (audit du 25/09/2026, D1) ─────────────
# Toute lecture ou écriture de `wing_ui.<NOM>` pour ces noms LÈVE, avec la
# nouvelle adresse : un module ou un test oublié ne peut plus lire (ou
# patcher) en silence un vieil objet que plus personne ne regarde.
import wing_demenagement as _demenagement
_demenagement.garder(__name__, {
    n: "etat.E." + {"_SUIVI_VU": "SUIVI_VU", "_MA3_CHECK": "MA3_CHECK"}.get(n, n)
    for n in ("LOCK", "STATE", "PROFILE", "SETTINGS", "OSC", "DEV", "AUTO",
              "BOUCLE", "DMX", "LED", "LED_RAFRAICHI", "ENVOI", "WS", "VEGAS",
              "PICKUP", "FADER_LAST", "FADER_T", "FADER_ATTENTE", "MAINTIENS",
              "VERBE", "CONSOLE_CIBLES", "_SUIVI_VU", "_MA3_CHECK", "THREAD_MORT",
              "USB_GEN", "BOUTONS_ENFONCES", "UI_VIE", "RECOVERY")},
    motif="D1")
