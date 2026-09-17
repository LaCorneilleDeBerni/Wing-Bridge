#!/usr/bin/env python3
"""
MA2 Wing — couche basse (protocole MATRIX_USB)
===============================================
Protocole reverse-engineered de la command wing : paquets, lecture d'état,
entrées/sorties USB, et mappings PAR DÉFAUT dont part un profil neuf.

Ce module ne s'exécute pas et n'envoie plus rien lui-même. Le bridge complet
est wing_ui.py ; les profils sont dans wing_mapper.py.

⚠️ CE QUE CE FICHIER ANNONÇAIT ET QUI ÉTAIT FAUX (corrigé depuis)
L'en-tête décrivait un protocole OSC natif MA3 :
    /gma3/cmd "Go+" · /gma3/fader/1/1 0.75 · /gma3/key/1/1 1
Aucune de ces adresses ne fonctionne. Testé méthodiquement (six méthodes
comparées) : grandMA3 ignore les schémas /Page/Fader et /gma3/…, hérités de la
MA2. Wing Bridge passe par la LIGNE DE COMMANDE :

    /cmd  "FaderMaster Executor 101 At 75"
    /cmd  "Go+ Executor 101"
    /cmd  "Attribute Focus1 at + 1"

Côté grandMA3 : Settings ▸ Network ▸ OSC, Enable Input, port de réception
8000 par défaut (réglable dans l'app, onglet Paramètres ▸ « Cible OSC »).
"""

import struct

import usb.core

# ── Réseau ─────────────────────────────────────────────────────────────────────
MA3_IP   = "127.0.0.1"   # même Mac → 127.0.0.1 ; autre PC → son IP
MA3_PORT = 8000           # port OSC grandMA3 (Settings > Network > OSC)

# ── USB ────────────────────────────────────────────────────────────────────────
VID        = 0x03EB
PID        = 0x160B
EP_IN      = 0x81
EP_OUT     = 0x02
TIMEOUT_MS = 200

# ── Paquets protocole MATRIX_USB (capturés d.pcapng — régime établi post-init) ─
POLL    = bytes.fromhex("05900000")                       # 4 B
LED_A   = bytes.fromhex("0690040200020100") + bytes(512)  # 520 B — LEDs éteintes
LED_B   = bytes.fromhex("0690040200020200") + bytes(512)  # 520 B
CMD_264 = bytes.fromhex("04900401") + bytes(260)          # 264 B

assert len(LED_A)   == 520
assert len(LED_B)   == 520
assert len(CMD_264) == 264

# ── Mapping boutons → commande OSC grandMA3 ────────────────────────────────────
#
# Format : btn_id  →  commande texte MA3
#
# ⚠️ Ce sont les DÉFAUTS D'USINE, pas la configuration active. Ils servent de
# point de départ à un profil neuf (wing_mapper.new_profile_from_defaults) et
# ne sont plus lus une fois qu'un profil est chargé.
#
# Pour identifier un bouton physique : onglet Boutons de l'interface, mode
# apprentissage — appuie sur le bouton, il s'allume dans le tableau. (Cet
# en-tête décrivait l'ancien repérage par le terminal, disparu avec main().)
#
# Commandes MA3 utiles :
#   Hardkeys   : "Please"  "Go+"  "Go-"  "Clear"  "Oops"  "Assign"
#                "Copy"  "Move"  "Delete"  "Edit"  "Store"  "Update"  "Label"
#                "Fixture"  "Sequence"  "Group"  "Preset"  "Macro"
#                "Page"  "Effect"  "View"  "Layout"
#   Executors  : "Go+ Exec 1.1"  "Go- Exec 1.1"  "Top Executor 1.1"
#   Divers     : "BlindEdit"  "Freeze"  "FullHighlight"

BUTTON_COMMANDS = {
    # ── Hardkeys ──────────────────────────────────────────────────────────────
    0x05: "Menu",           # ex-Backup → ouvre le menu MA3 (F12 en mode console)
    0x09: "Select",         # physique "Select"
    0x0e: "Delete",         # physique "Del"
    0x16: "Copy",           # physique "Copy"
    0x26: "Move",           # physique "Move"
    0x27: "Assign",         # physique "Assign"
    0x31: "Oops",           # physique "Oops"
    0x38: "Update",         # physique "Update"
    0x39: "Clear",          # physique "Clear"
    0x40: "Store",          # physique "Store"
    0x46: "Please",         # physique "Please"
    0x1b: "Sequence",       # physique "Sequ"
    0x1c: "Cue",            # physique "Cue"
    0x1d: "Executor",       # physique "Exec"

    # ── Pavé numérique ────────────────────────────────────────────────────────
    0x3a: "1",
    0x3b: "2",
    0x3c: "3",
    0x32: "4",
    0x33: "5",
    0x34: "6",
    0x2a: "7",
    0x2b: "8",
    0x2c: "9",

    # ── Opérateurs / ligne de commande ───────────────────────────────────────
    0x42: "0",              # physique "0"
    0x43: ".",              # physique "."
    0x2d: "+",              # physique "+"
    0x3d: "-",              # physique "-"
    0x35: "Thru",           # physique "Thru"
    0x45: "At",             # physique "At"
    0x44: "If",             # physique "If"

    # ── Executors ─────────────────────────────────────────────────────────────
    0x7e: "Go+",                     # GO+ principal
    0x78: "Go+ Executor 101",
    0x79: "Go+ Executor 102",
    0x7a: "Go+ Executor 103",
    0x7b: "Go+ Executor 104",
    0x7c: "Go+ Executor 105",
    0x7d: "Go+ Executor 106",

    # ── Go séquences 1-6 ─────────────────────────────────────────────────────
    0x70: "Go+ Executor 201",
    0x71: "Go+ Executor 202",
    0x72: "Go+ Executor 203",
    0x73: "Go+ Executor 204",
    0x74: "Go+ Executor 205",
    0x75: "Go+ Executor 206",

    # ── Go- et Pause principaux ───────────────────────────────────────────────
    0x76: "Pause",          # physique "Pause"
    0x77: "Go-",            # physique "Go-"

    # ── Push encodeurs (clic roue) → change groupe attributs ────────────────
    0x48: "__ENC1_PUSH__",
    0x49: "__ENC2_PUSH__",
    0x4a: "__ENC3_PUSH__",
    0x4b: "__ENC4_PUSH__",
}

# ── Double rôle des boutons executor ─────────────────────────────────────────
# Buffer VIDE  → action directe  (ex: Go+ Exec 1.101)
# Buffer ACTIF → référence objet (ex: "Store Executor 1.101 Please")
EXECUTOR_REF = {
    0x78: "Executor 101",  0x79: "Executor 102",
    0x7a: "Executor 103",  0x7b: "Executor 104",
    0x7c: "Executor 105",  0x7d: "Executor 106",
    0x70: "Executor 201",  0x71: "Executor 202",
    0x72: "Executor 203",  0x73: "Executor 204",
    0x74: "Executor 205",  0x75: "Executor 206",
}

# ── Faders → OSC grandMA3 ─────────────────────────────────────────────────────
# Format : (page, executor) par fader.
# Bytes 80-95 = 8 faders (F1..F8). L'ordre physique exact à confirmer en testant.
# Le premier fader bougé dans la capture était F7 (bytes 92-93).
# [0] = inutilisé (compat), [1] = N° d'EXECUTOR MA3 COMPLET (page×100 + rang).
# Défaut : executors 101..108 (page 1). À remapper selon ta config MA3 dans l'UI.
FADER_EXEC = [
    (1, 101),   # F1
    (1, 102),   # F2
    (1, 103),   # F3
    (1, 104),   # F4
    (1, 105),   # F5
    (1, 106),   # F6
    (1, 107),   # F7
    (1, 108),   # F8
]

# ── Encodeurs → attributs fixtures (commandes relatives MA3) ──────────────────
#
# Format : /cmd  "Attribute Pan at + 3"
# Agit sur les fixtures ACTUELLEMENT SÉLECTIONNÉES dans MA3.
#
# Chaque roue a son propre cycle d'attributs, parcouru au clic (push).
# La roue démarre sur le 1er attribut de sa liste.
#
# ⚠️ Le nom doit être le nom INTERNE de l'attribut, PAS le libellé affiché sur
# l'Encoder Bar de MA3 : la barre montre le champ "Pretty", souvent différent.
#   Encoder Bar « Focus » → attribut réel Focus1   ("Focus" est un FeatureGroup)
#   Encoder Bar « Sh1 »   → attribut réel Shutter1 ("Shutter" n'existe pas)
#   Encoder Bar « Dim »   → attribut réel Dimmer
# Source de vérité, installée avec MA3 :
#   ~/MALightingTechnology/gma3_<version>/shared/resource/attribute_definitions.xml
# Seuls les <Attribute Name="…"> sont valides ; <FeatureGroup> et <Feature> ne
# le sont pas. Un mauvais nom échoue en SILENCE côté Wing Bridge : MA3 répond
# « illegal object » sur SA ligne de commande, rien ne revient en OSC.

# Cliquer sur une roue réassigne les 4 roues d'un coup (comme un groupe d'attributs).
# None = roue inactive dans ce groupe.
#
# 🎯 Groupes 5-8 : un DOUBLE-clic sur la roue N
# active le groupe N+4 — même mécanisme d'édition que les groupes 1-4
# (onglet Encodeurs), juste un geste différent pour y accéder. Vierges par
# défaut (None partout) : contrairement à 1-4, ce ne sont pas des valeurs de
# référence choisies pour l'utilisateur — chaque wing/show est différent, ce
# sont les 4 emplacements que GUIDE_PROJET.md exige de laisser personnalisables,
# pas des exemples à deviner à sa place. Voir `ENC_GROUPES_SIMPLE` ci-dessous
# pour le point de bascule simple/double, et `wing_boutons.py::handle_button_bridge`
# pour le geste.
ENC_GROUPS = [
    # Clic ENC1 — Intensité
    ["Dimmer",     "Iris",       "Shutter1",   None],

    # Clic ENC2 — Position
    ["Pan",        "Tilt",       "Zoom",       "Focus1"],

    # Clic ENC3 — Gobos
    ["Gobo1",      "Gobo1Pos",   "Gobo2",      "Gobo2Pos"],

    # Clic ENC4 — Couleur
    ["ColorRGB_R", "ColorRGB_G", "ColorRGB_B", "ColorRGB_W"],

    # Double-clic ENC1 — groupe 5, à configurer
    [None, None, None, None],

    # Double-clic ENC2 — groupe 6, à configurer
    [None, None, None, None],

    # Double-clic ENC3 — groupe 7, à configurer
    [None, None, None, None],

    # Double-clic ENC4 — groupe 8, à configurer
    [None, None, None, None],
]

# Nombre de groupes accessibles au CLIC SIMPLE (1..ENC_GROUPES_SIMPLE) — les
# suivants (ENC_GROUPES_SIMPLE+1..len(ENC_GROUPS)) sont au DOUBLE-clic.
# wing_boutons.py additionne ce décalage à l'index de roue pressée en double.
ENC_GROUPES_SIMPLE = 4

# Groupe actif au démarrage (0=Intensité, 1=Position, 2=Gobos, 3=Couleur)
ENC_DEFAULT_GROUP = 1   # Position au démarrage

# Pas de valeur par tick (1 unité MA3 — augmenter si mouvement trop lent)
ENC_STEP = 1.0


# ── Chargement de profil en ligne de commande : RETIRÉ ───────────────────────
#
# `_default_profile_dir()`, `PROFILE_DIR`, `resolve_profile()` et
# `apply_profile()` vivaient ici, pour `wing_bridge.py --profile <nom>`.
#
# Deux raisons de les retirer :
#   1. `apply_profile()` faisait `FADER_EXEC = [tuple(x) for x in p["faders"]]`.
#      Les faders sont des dicts {"kind": …} depuis longtemps : sur un profil
#      d'aujourd'hui, ça donnait 8 tuples de clés ("kind","exec") et un bridge
#      qui envoyait n'importe quoi. Cassé en silence, pas en erreur.
#   2. `PROFILE_DIR` était une SECONDE définition du dossier des profils, en
#      double avec celle de wing_mapper.py. Deux sources pour un même chemin,
#      c'est une divergence qui attend son heure.
#
# Le chargement de profil se fait dans l'app (wing_ui.py), via wing_mapper.
# ── Parsing ────────────────────────────────────────────────────────────────────

def parse_events(data: bytes) -> list:
    """Retourne [(btn_id, pressed), ...] depuis un paquet IN > 140 bytes."""
    events = []
    if len(data) <= 140:
        return events
    i = 112
    while i <= len(data) - 12:
        if (data[i+1] == 0x91 and data[i+2] == 0x08 and
                data[i+3] == 0x00 and data[i] in (0x01, 0x02)):
            btn_id  = struct.unpack_from('<I', data, i + 8)[0]
            pressed = (data[i] == 0x01)
            events.append((btn_id, pressed))
            i += 12
        elif (data[i+1] == 0x91 and data[i+2] == 0x18 and
              data[i+3] == 0x00 and data[i] in (0x0a, 0x0b)):
            i += 28   # crypto dongle — ignorer
        else:
            i += 1
    return events


def parse_state(data: bytes) -> dict:
    """
    Faders  : bytes 80-95 → 8 × uint16 LE (0-1023)
    Encodeurs :
      ENC1 bytes 32-35 int32 LE
      ENC2 byte  36    uint8
      ENC3 bytes 40-43 int32 LE
      ENC4 byte  44    uint8
    """
    if len(data) < 96:
        return {}
    faders = [struct.unpack_from('<H', data, 80 + i * 2)[0] for i in range(8)]
    return {
        'faders':   faders,
        'encoders': (
            struct.unpack_from('<i', data, 32)[0],
            data[36],
            struct.unpack_from('<i', data, 40)[0],
            data[44],
        ),
    }


def enc_delta(curr: int, prev: int, is_int32: bool) -> int:
    if is_int32:
        return curr - prev
    d = (curr - prev) & 0xFF
    return d if d < 128 else d - 256


# ── Aides OSC : RETIRÉES ─────────────────────────────────────────────────────
#
# `osc_cmd()`, `osc_fader()` et `osc_attr()` ne servaient qu'à `main()`
# ci-dessous, disparu. wing_ui.py construit ses commandes
# lui-même (voir send_fader / handle_button_bridge) : les garder ici, c'était
# deux endroits où écrire la même syntaxe MA3, donc deux endroits à corriger.


# ── Entrées/sorties USB ──────────────────────────────────────────────────────

# Dernière erreur de lecture non-timeout, conservée ici pour que l'appelant
# puisse la montrer. Un `print` ne servirait à rien : la sortie standard du
# binaire figé n'arrive nulle part (voir launcher.sh).
# C'est wing_ui.py qui affiche cette information, via WING_FLUX.
DERNIERE_ERREUR = ""


def read_pkt(dev, timeout_ms=TIMEOUT_MS):
    global DERNIERE_ERREUR
    try:
        return bytes(dev.read(EP_IN, 512, timeout=timeout_ms))
    except usb.core.USBTimeoutError:
        return None                     # normal : la wing n'avait rien à dire
    except Exception as e:
        DERNIERE_ERREUR = f"{type(e).__name__}: {e}"
        return None


def drain(dev, n=3, timeout_ms=10):
    """Consomme les réponses en attente après une écriture.

    ⚠️ `timeout_ms` est du temps PERDU quand la wing n'a rien à dire : la
    lecture attend la totalité du délai avant d'abandonner. Du temps où les
    trois paquets partaient à chaque tour, un délai de 10 ms coûtait 30 ms par
    tour et plafonnait la boucle à 17 Hz (mesuré).

    ⚠️ Ne pas RÉDUIRE le délai pour autant : essayé à 1 ms, la
    cadence s'est effondrée à 2,8 Hz. Le drain ne perd pas du temps, il VIDE
    la file de la wing. Voir cycle_dmx dans wing_ui.py.
    """
    for _ in range(n):
        if read_pkt(dev, timeout_ms=timeout_ms) is None:
            break


# ── Le bridge autonome en terminal : RETIRÉ ──────────────────────────────────
#
# `main()` (~205 lignes) et son bloc argparse rejouaient en
# terminal, en version figée, ce que fait wing_ui.py : cycle USB, faders,
# encodeurs, buffer de commande, double rôle des executors.
#
# Il ne connaissait RIEN de ce qui a été construit depuis : ni le suivi de la
# configuration MA3, ni les LED d'état, ni le rattrapage de fader, ni le mode
# console, ni la limitation de débit vers MA3. Il redéfinissait même son
# propre `CMD_BUF_TOKENS`, en double avec celui de wing_ui.py.
#
# Ce fichier est aujourd'hui la couche BASSE, et rien d'autre :
#   • le protocole MATRIX_USB (POLL, LED_A, LED_B, CMD_264, endpoints)
#   • la lecture des paquets (parse_state, parse_events, enc_delta)
#   • les entrées/sorties USB (read_pkt, drain)
#   • les mappings PAR DÉFAUT dont wing_mapper part pour un profil neuf
# C'est ce que wing_ui.py et wing_mapper.py lui demandent, et c'est tout.


# Carte des LEDs AU REPOS (paquet CMD_264, 260 octets), capturée sur MA2 onPC :
# toutes les touches en veilleuse. Déplacée depuis wing_ui.py (audit du
# 25/09/2026, D1) : c'est une donnée de PROTOCOLE, et `etat.Etat` en a besoin
# pour initialiser `LED["buf"]` sans importer wing_ui.
LED_BASE = bytearray(bytes.fromhex(
    "000000000000300030003000300030003000300030003000300030003000"
    "300030003000300030003000300030003000300030003000300030003000"
    "300030003000300030003000300030003000300030003000300030003000"
    "300030003000300030003000300030003000300030003000300030003000"
    "300030003000300030003000300030003000300030003000000000000000"
    "000000000000000000000492600030003000300030003000300000000000"
    "300030003000300030003000000000003000300030003000300030003000"
    "300030003000300030003000300030000000000000003000300030003000"
    "3000300000000000000000000000000000000000"
))
assert len(LED_BASE) == 260
