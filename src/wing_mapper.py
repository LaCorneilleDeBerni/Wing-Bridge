#!/usr/bin/env python3
"""
Wing Mapper — bibliothèque des PROFILS
=======================================
Schéma d'un profil, migration des anciens formats, lecture/écriture sur
disque, et table des raccourcis clavier du mode console.

Ce module ne s'exécute pas : il est importé par wing_ui.py (le serveur) et
par smoke_test.py. Le mode « apprentissage » en terminal qu'il abritait à
l'origine a été retiré — l'interface web le remplace, et le
code en question ne fonctionnait plus (voir la note en fin de fichier).

Emplacement des profils :
  • depuis les sources → ./profiles/
  • en app figée macOS → ~/Library/Application Support/Wing Bridge/profiles/
  • en app figée Windows → %APPDATA%\\Wing Bridge\\profiles\\
  • WING_PROFILE_DIR   → forçage explicite (utilisé par le launcher macOS)
"""

import json
import math
import os
import sys
import threading
from pathlib import Path

import wing_bridge as wb

# WING_PROFILE_DIR permet de stocker les profils ailleurs.
# En app figée (PyInstaller), défaut = Application Support (bundle en lecture seule).
def _default_profile_dir() -> Path:
    env = os.environ.get("WING_PROFILE_DIR")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        # Même principe que sys.frozen ci-dessus, décliné par OS : chaque
        # plateforme a son dossier de données utilisateur standard.
        if sys.platform.startswith("win"):
            # %APPDATA% = AppData\Roaming, l'emplacement Windows attendu pour la
            # config utilisateur (le bundle figé est en lecture seule). Repli sur
            # le home si la variable manque (session sans profil, cas rare).
            base = os.environ.get("APPDATA") or str(Path.home())
            return Path(base) / "Wing Bridge" / "profiles"
        return Path.home() / "Library" / "Application Support" / "Wing Bridge" / "profiles"
    return Path(__file__).resolve().parent / "profiles"

PROFILE_DIR = _default_profile_dir()

# ── Encodeurs : noms d'attributs invalides → nom réel MA3 ─────────────────────
# Clé en minuscules. Ces noms viennent de l'Encoder Bar (champ "Pretty") ou du
# FeatureGroup, pas de l'attribut lui-même. Voir attribute_definitions.xml.
ATTR_RENAMES = {
    "focus":   "Focus1",     # "Focus" = FeatureGroup ; "Focus1" a pour Pretty "Focus"
    "shutter": "Shutter1",   # "Shutter" n'existe pas ; Pretty de Shutter1 = "Sh1"
}

# ⚠️ Le nom vient de l'ÉTIQUETTE de la touche, pas du mot-clé de commande. Un
#    bouton réglé sur l'étiquette est MORT EN SILENCE — MA3 refuse, rien ne
#    remonte. → docs/KEYBOARD_MAPPING.md#le-nom-vient-de-l-etiquette-pas-du-mot-cle-exec-selfix-highlt
TOKENS_RENOMMES = {"Exec": "Executor", "SelFix": "SelectFixtures"}

# Doublons purs : même frappe qu'un token déjà présent, et pas un mot-clé MA3.
TOKENS_OBSOLETES = ("Highlt",)

# ⚠️ N'INSCRIRE ICI QUE des défauts DÉMONTRÉS faux — pas un simple écart avec
#    le fichier de MA3, qui ne prouve rien. Ne remplace que si le profil porte
#    encore EXACTEMENT l'ancien défaut : ce que l'utilisateur a changé lui
#    appartient. → docs/KEYBOARD_MAPPING.md#raccourcis-corriges-ne-corriger-que-ce-qui-est-demontre-faux
RACCOURCIS_CORRIGES = {
    "Set":   ("o", "q"),        # « o » était partagé avec Off → Set coupait
                                #   l'executor. → docs/KEYBOARD_MAPPING.md#set-valait-o-le-raccourci-de-off-le-pire-des-deux
    "Align": ("Ctrl+A", "Ctrl+B"),   # conflit de disposition clavier
}

# ── Token de l'app → KeyCode de MA3 ─────────────────────────────────────────
# La plupart des tokens portent déjà le nom du KeyCode en majuscules
# (« Store » → STORE) : cette table ne liste QUE les exceptions.
#
# ⚠️ SOURCE UNIQUE — elle sert au contrôle test_raccourcis_uniques ET à l'envoi des raccourcis
#    vers MA3. Deux copies divergeraient.
# ⚠️ « + » en est VOLONTAIREMENT absent, et GO_PLUS/GO_MINUS n'existent pas
#    dans MA3. → docs/KEYBOARD_MAPPING.md#pourquoi-n-est-pas-dans-token-vers-keycode
TOKEN_VERS_KEYCODE = {
    "Go+": "GO", "Go-": "GOBACK",
    "Next Page": "PAGE_UP", "Previous Page": "PAGE_DOWN",
    "SelectFixtures": "SELFIX",
    "<<<": "GOBACKFAST", ">>>": "GOFAST",
    "Executor": "EXEC",
    # Pavé numérique et opérateurs : les tokens de l'app sont les caractères
    # eux-mêmes, MA3 les nomme NUM0…NUM9 / DOT / PLUS / MINUS / SLASH.
    "0": "NUM0", "1": "NUM1", "2": "NUM2", "3": "NUM3", "4": "NUM4",
    "5": "NUM5", "6": "NUM6", "7": "NUM7", "8": "NUM8", "9": "NUM9",
    ".": "DOT", "-": "MINUS", "/": "SLASH",
}


# ── Liste blanche des RACCOURCIS clavier ──────────────────────────────────────
#
# 🟠 Audit du 25/09/2026. Une frappe de `console_keys` part à DEUX endroits
# hors de l'app : dans le fichier de raccourcis de MA3 (XML, où seuls `&` et
# `"` étaient échappés — un `<` le corrompait) et dans une commande OSC
# `Set KeyboardShortcut n Property "Shortcut" "<frappe>"` (où un `"` sortait
# de la chaîne). Elle venait pourtant d'un profil importé ou d'un champ de
# saisie, sans aucun filtre. On n'accepte donc QUE ce que l'assistant clavier
# sait taper : des modificateurs connus, puis une touche nommée connue ou UN
# caractère seul (é, ç… d'une disposition AZERTY restent permis).
#
# ⚠️ Ces deux ensembles recopient `MOD_FLAGS`/`NAMED_KEYS` de
# wing_keyboard_macos.py et `MOD_VK`/`NAMED_VK` de wing_keyboard_windows.py
# (non importables ici : Quartz / ctypes). Le contrôle test_raccourcis_filtres
# vérifie qu'ils restent identiques aux quatre tables.
MODIFICATEURS_RACCOURCI = {"ctrl", "control", "ctl", "cmd", "command", "alt",
                           "option", "opt", "shift"}
TOUCHES_NOMMEES = {
    "apostrophe", "backslash", "backspace", "clear", "comma", "del", "delete",
    "down", "end", "enter", "equal", "esc", "escape", "f1", "f10", "f11",
    "f12", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "forwarddelete",
    "fwddelete", "grave", "home", "left", "leftbracket", "minus", "pagedown",
    "pageup", "period", "please", "quote", "return", "right", "rightbracket",
    "semicolon", "slash", "space", "tab", "up"}
# Jamais comme caractère seul : ils cassent le XML ou la chaîne OSC. Chacun a
# son nom (« backslash »…) ou n'a rien à faire dans un raccourci.
_CARACTERES_INTERDITS = set('<>"&\\')
RACCOURCI_LONGUEUR_MAX = 40


def raccourci_valide(spec) -> bool:
    """La frappe `spec` est-elle sûre ET tapable ? "" (désassignée) l'est."""
    if not isinstance(spec, str):
        return False
    s = spec.strip()
    if s == "":
        return True
    if len(s) > RACCOURCI_LONGUEUR_MAX:
        return False
    if len(s) == 1:                     # même règle que parse_spec : « + » seul
        return s.isprintable() and not s.isspace() \
            and s not in _CARACTERES_INTERDITS
    parts = [p.strip() for p in s.split("+")]
    if any(p == "" for p in parts):     # « Ctrl++Z », « Ctrl+ » : ambigu
        return False
    *mods, base = parts
    if any(m.lower() not in MODIFICATEURS_RACCOURCI for m in mods):
        return False
    if base.lower() in TOUCHES_NOMMEES:
        return True
    return len(base) == 1 and base.isprintable() and not base.isspace() \
        and base not in _CARACTERES_INTERDITS


def keycode_de(token: str) -> str:
    """KeyCode MA3 correspondant à un token de l'app."""
    return TOKEN_VERS_KEYCODE.get(token, token.upper())


# ── Écarts ASSUMÉS : {token: (valeur, pourquoi)} — touches NON poussées ─────
# ⚠️ VIDE, et c'est un résultat, pas un oubli. Une entrée de trop ici SUPPRIME
#    silencieusement la possibilité de modifier la touche. L'exclusion suit la
#    VALEUR, jamais le token. → docs/KEYBOARD_MAPPING.md#les-ecarts-assumes-un-mecanisme-vide-et-c-est-un-resultat
ECARTS_ASSUMES = {}


def ecart_assume(token: str, spec: str) -> bool:
    """Cette touche doit-elle rester hors de l'envoi vers MA3 ?"""
    ref = ECARTS_ASSUMES.get(token)
    return bool(ref) and str(spec) == ref[0]

# ── Mode console (V2) : touches wing → raccourcis clavier MA3 ─────────────────
# Correspond à la table ShCuts de MA3 (Command Section, raccourcis en lilas).
# Clear = touche "Delete" (⌦ forward delete) et NON Backspace (sinon ça efface).
CONSOLE_KEY_DEFAULTS = {
    # Verbes / ligne de commande
    "Store":    "s",
    "Update":   "u",
    "Please":   "Enter",
    "Clear":    "Delete",       # ⌦ forward delete = Clear MA3
    # ⚠️ NE PAS « corriger » Clear en Backspace, ni aucun raccourci sur la
    #    seule foi du fichier de MA3 : il liste UNE liaison, pas la seule.
    #    → docs/KEYBOARD_MAPPING.md#un-raccourci-ne-se-corrige-jamais-sur-la-seule-foi-du-fichier-de-ma3
    "Oops":     "Ctrl+Z",
    "Move":     "Ctrl+M",
    "Copy":     "Ctrl+C",
    "Delete":   "Ctrl+D",
    # ⚠️ Align et Assign ont des valeurs contre-intuitives, exprès : conflits
    #    de disposition clavier. → docs/KEYBOARD_MAPPING.md#conflits-de-disposition-clavier-align-et-assign
    "Align":    "Ctrl+B",
    "Select":   "Ctrl+S",
    "Goto":     "Alt+G",
    "Assign":   "Ctrl+Alt+V",   # Alt+A entrait en conflit (Camera Set Pivot en vue 3D)
    "Edit":     "e",
    "Time":     "Ctrl+T",
    "Stomp":    "Alt+T",
    "Help":     "Ctrl+Alt+H",
    # ⚠️ « q », PAS « o » : « o » est la frappe de Off, un bouton Set coupait
    #    donc l'executor. Le contrôle test_raccourcis_uniques interdit tout doublon ici.
    #    → docs/KEYBOARD_MAPPING.md#set-valait-o-le-raccourci-de-off-le-pire-des-deux
    "Set":      "q",
    # Objets
    "Fixture":  "f",
    "Channel":  "c",
    "Group":    "g",
    "Preset":   "p",
    "Sequence": "Alt+S",
    "Cue":      "Alt+C",
    # Sélection / valeurs
    "Thru":     "t",
    "At":       "a",
    "If":       "i",
    "Full":     "Ctrl+F",
    "Highlight":"h",
    "On":       "Ctrl+O",
    "Off":      "o",
    "Solo":     "Ctrl+Alt+S",
    "Freeze":   "Alt+F",
    "Preview":  "Ctrl+Alt+P",
    "Blind":    "b",
    "SelectFixtures": "Ctrl+Alt+F",
    "Menu":     "F12",
    # Playback
    "Go+":      "Ctrl+G",
    "Go-":      "Ctrl+Alt+G",
    "Pause":    "Ctrl+P",
    "List":     "l",
    "Learn":    "Ctrl+L",
    # ⚠️ Le token est la COMMANDE MA3 (« Next Page »), pas le libellé de
    #    touche : c'est ce qui fait marcher le même bouton en console ET en
    #    OSC. Le renommer « Page+ » casserait l'OSC.
    #    → docs/KEYBOARD_MAPPING.md#next-page-le-token-est-la-commande-pas-le-libelle-de-touche
    "Next Page":     "pageup",
    "Previous Page": "pagedown",   # ⚠️ frappe confirmée ; la commande OSC
                                   # « Previous Page » reste NON vérifiée

    # ── Complément COMMAND WING MA2 ────────────────────────────────────────
    # Objectif : brancher une VRAIE command wing MA2 et pouvoir assigner
    # TOUS ses boutons, pas seulement ceux d'un modèle réduit.
    # Valeurs relevées dans la table de MA3 elle-même (fichier
    # KeyboardShortCuts.xml du profil utilisateur), pas devinées.
    "<<<":      "LeftBracket",     # GOBACKFAST
    ">>>":      "RightBracket",    # GOFAST
    "Esc":      "Escape",
    "Prev":     "Left",
    "Next":     "Right",
    "Up":       "Up",
    "Down":     "Down",
    "Xkeys":    "Comma",

    # ⚠️ VIDES EXPRÈS : MA3 ne leur attribue aucun raccourci. Elles restent
    #    listées pour être visibles et personnalisables.
    #    → docs/KEYBOARD_MAPPING.md#les-touches-laissees-vides-expres
    "Fix":      "",
    "Temp":     "",
    "Top":      "",
    "View":     "",
    "Effect":   "",
    "Macro":    "",
    "Executor": "",
    # Chiffres et opérateurs
    "0": "0", "1": "1", "2": "2", "3": "3", "4": "4",
    "5": "5", "6": "6", "7": "7", "8": "8", "9": "9",
    ".": "period",      # position US (sinon décalage AZERTY)
    "+": "+",           # numpad + (identique sur toutes dispositions)
    "-": "minus",       # position US (sinon interprété comme +)
    "/": "slash",       # position US
}


# ── Profils ────────────────────────────────────────────────────────────────────

def new_profile_from_defaults() -> dict:
    """Nouveau profil pré-rempli avec les mappings par défaut de wing_bridge."""
    return {
        "name": "Sans nom",
        "buttons":      {f"0x{k:02x}": v for k, v in wb.BUTTON_COMMANDS.items()},
        "executor_ref": {f"0x{k:02x}": v for k, v in wb.EXECUTOR_REF.items()},
        "faders":       [{"kind": "executor", "exec": exe} for (_, exe) in wb.FADER_EXEC],
        # Étiquette libre de chaque fader physique, pour coller à la
        # sérigraphie de LA wing de l'utilisateur (Master, XFade, 1…6).
        # Les copies de command wing n'ont ni le même nombre de faders
        # ni la même disposition : imposer « F1…F8 » ne marche que pour
        # le modèle qu'on a sous la main.
        "fader_noms":   ["" for _ in range(8)],
        "enc_groups":   [g[:] for g in wb.ENC_GROUPS],
        "enc_default_group": wb.ENC_DEFAULT_GROUP,
        "enc_step":     wb.ENC_STEP,
        # LEDs identifiées : nom → {"bank": 1|2, "offset": 0-511}
        "leds":         {},
        # Mode console (V2) : token → touche clavier envoyée au web remote MA3
        # (doit correspondre à la table de raccourcis ShCuts de MA3).
        # "" = pas de raccourci → le token repasse en OSC ou est ignoré.
        "console_keys": dict(CONSOLE_KEY_DEFAULTS),
        # Double appui rapide sur une touche → commande MA3 dédiée.
        # {token: "commande"} — indexé par TOKEN (ex. "Menu"), pas par code bouton
        # brut : ce code est propre à chaque wing, le token suit le bouton tel
        # qu'assigné. Défaut : Menu ×2 = SaveShow, comme sur une command wing.
        # ⚠️ Les boutons __ENCn_PUSH__ (roues) N'UTILISENT PAS cette table : leur
        # double-clic est câblé en dur sur les groupes 5-8
        # (wing_boutons.handle_button_bridge) — voir wing_bridge.ENC_GROUPES_SIMPLE.
        "double_clic": {"Menu": "SaveShow"},
    }


def slugify(name: str) -> str:
    s = name.strip().lower()
    s = "".join(c if c.isalnum() or c in " -_" else "" for c in s)
    return s.replace(" ", "-") or "profil"


def own_like_parent(path: Path):
    """Donne au fichier le même propriétaire que son dossier parent.

    ⚠️ « Le serveur tourne en ROOT (accès USB) » : PLUS VRAI — l'USB n'a besoin
    d'aucun droit root sur macOS, le serveur tourne en uid 501 et cette
    fonction ne fait donc rien la plupart du temps. Elle reste utile pour le
    repli root et pour réparer les fichiers écrits par de très anciennes
    versions : ils appartenaient à root dans un dossier qui est
    celui de l'UTILISATEUR, donc lisibles et copiables mais impossibles à
    renommer ou supprimer dans le Finder sans mot de passe — ce qui contredit
    l'objectif « profils faciles à échanger ».
    On s'aligne sur le propriétaire du dossier parent plutôt que d'aller
    chercher l'utilisateur de la console : ça marche pour n'importe quel
    compte, sans lancer de commande externe. Sans effet si on n'est pas root.
    """
    try:
        if os.geteuid() != 0:
            return
        st = os.stat(path.parent)
        if st.st_uid != 0:
            os.chown(path, st.st_uid, st.st_gid)
    except Exception:
        pass          # confort, jamais bloquant


_SAVE_PROFILE_LOCK = threading.Lock()


def save_profile(profile: dict, path: Path = None) -> Path:
    PROFILE_DIR.mkdir(exist_ok=True)
    if path is None:
        path = PROFILE_DIR / f"{slugify(profile['name'])}.json"
    # Écriture ATOMIQUE (temp-file + os.replace) — même motif que partout
    # ailleurs dans le projet (sauvegarde auto, raccourcis XML, cache
    # firmware) : une coupure en plein milieu de l'écriture DIRECTE laissait
    # un `.json` tronqué, illisible, à la place du profil précédent bon.
    # Temporaire PROPRE à l'appel (pid + fil), audit du 25/09/2026 : avec un
    # nom fixe (`profil.part`), deux sauvegardes simultanées du même profil
    # (bouton + sauvegarde auto, deux onglets) écrivaient dans le MÊME
    # temporaire — contenu mêlé, ou `os.replace` du second sur un fichier
    # déjà déplacé par le premier. Contrôle test_part_unique.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.part")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)
    # 🪟 Test réel Windows du 26/09/2026 : `os.replace()` n'y est pas atomique
    # comme `rename(2)` POSIX quand deux fils visent la MÊME destination en
    # même temps — `MoveFileEx` lève par intermittence un accès refusé
    # (WinError 5), jamais vu sur macOS. Le tmp reste unique par fil (protège
    # toujours contre un contenu mêlé) ; ce verrou sérialise seulement le
    # remplacement final, qui est le seul point qui peut se marcher dessus.
    with _SAVE_PROFILE_LOCK:
        os.replace(tmp, path)
    own_like_parent(path)
    return path


def list_profiles() -> list:
    PROFILE_DIR.mkdir(exist_ok=True)
    return sorted(PROFILE_DIR.glob("*.json"))


import re

def migrate_profile(p: dict) -> dict:
    """Corrige les anciens formats de commandes dans un profil chargé."""
    # Executors MA2 → MA3 : "Go+ Exec 1.101" → "Go+ Executor 101", et normalise
    # l'abréviation "Exec" → "Executor" même sans préfixe de page (bug de l'ancien
    # quick-assign "Executor 2-rôles" qui écrivait "Go+ Exec 101" sans le mot
    # complet — "Exec" n'est pas un raccourci MA3 reconnu, contrairement à "Ex").
    for k, v in list(p.get("buttons", {}).items()):
        m = re.match(r"(Go[+-]|Top|Off|Temp|Toggle|Pause) Exec(?:utor)?\s+(?:\d+\.)?(\d+)$", str(v))
        if m:
            p["buttons"][k] = f"{m.group(1)} Executor {m.group(2)}"
    for k, v in list(p.get("executor_ref", {}).items()):
        m = re.match(r"Executor\s+\d+\.(\d+)$", str(v))
        if m:
            p["executor_ref"][k] = f"Executor {m.group(1)}"
    # Faders : anciens modèles liste → format actuel {"kind": ...}.
    # Historique : ["GM",0] (grandmaster) / [page,exe 1..8] (pré-flatten) /
    # [page,exe_complet≥100] (flatten intermédiaire). Idempotent : un fader
    # déjà au format dict ({"kind": ...}) est laissé tel quel.
    faders = p.get("faders")
    if isinstance(faders, list):
        for i, fx in enumerate(faders):
            if isinstance(fx, dict):
                continue   # déjà au format actuel
            if isinstance(fx, list) and len(fx) == 2:
                if fx[0] == "GM":
                    faders[i] = {"kind": "gm"}
                elif isinstance(fx[0], int) and isinstance(fx[1], int):
                    exe = fx[1] if fx[1] >= 100 else fx[0] * 100 + fx[1]
                    faders[i] = {"kind": "executor", "exec": exe}

    # Complète les raccourcis console AJOUTÉS depuis l'enregistrement de ce profil
    # — on n'ajoute QUE ce qui manque, jamais d'écrasement (une valeur vide =
    # « volontairement désassigné »). Sinon une nouvelle touche des défauts ne
    # profiterait qu'aux profils neufs.
    ck = p.setdefault("console_keys", {})
    if isinstance(ck, dict):
        # Renommage AVANT le complément, sinon on rajouterait le nouveau nom
        # à côté de l'ancien et l'utilisateur verrait les deux.
        # On conserve SON raccourci s'il en avait mis un.
        for vieux, neuf in TOKENS_RENOMMES.items():
            if vieux in ck:
                spec = ck.pop(vieux)
                ck.setdefault(neuf, spec)
        for mort in TOKENS_OBSOLETES:
            ck.pop(mort, None)
        # Défauts FAUX déjà enregistrés dans le profil : on les remet droit,
        # mais uniquement s'ils sont restés tels quels (voir RACCOURCIS_CORRIGES).
        for token, (vieux, neuf) in RACCOURCIS_CORRIGES.items():
            if ck.get(token) == vieux:
                ck[token] = neuf
        for token, spec in CONSOLE_KEY_DEFAULTS.items():
            ck.setdefault(token, spec)

    # Les boutons peuvent AUSSI porter l'ancien nom, si l'utilisateur l'avait
    # assigné. Sans ça, la table serait corrigée mais la touche resterait
    # muette — le pire des deux mondes.
    for k, v in list(p.get("buttons", {}).items()):
        neuf = TOKENS_RENOMMES.get(str(v).strip())
        if neuf:
            p["buttons"][k] = neuf
    # `console_hold` (case « appui long » par touche) a disparu :
    # la vraie durée d'appui est désormais relayée pour TOUTES les touches.
    # On le retire des profils existants pour ne pas laisser de réglage mort
    # qui ferait croire qu'il agit encore.
    p.pop("console_hold", None)
    # `leds` (cartographie manuelle bouton → slot) a disparu : la
    # carte est intégrée, retrouvée dans a-1.pcapng. Aucun profil ne l'avait
    # remplie ; on la retire pour ne pas laisser un réglage mort.
    p.pop("leds", None)

    # Double appui : table indexée par TOKEN ("Menu"), plus par code bouton brut
    # ("0x05", propre à UNE wing). Les profils à l'ancienne forme sont CONVERTIS
    # via `buttons` de ce même profil (déjà migré ci-dessus) ; une clé dont le
    # bouton n'existe plus est abandonnée — un réglage qui ne peut plus
    # s'appliquer à rien.
    dbl = p.get("double_clic")
    if not isinstance(dbl, dict):
        dbl = {}
    boutons_actuels = p.get("buttons", {})
    convertis = {}
    for k, v in dbl.items():
        if re.fullmatch(r"0x[0-9a-fA-F]{2}", str(k)):
            token = boutons_actuels.get(k)
            if token:
                convertis[token] = v
        else:
            convertis[k] = v
    dbl = convertis
    # Défaut Menu ×2 = SaveShow : le Quick Save natif de MA3 ne répond QU'AU bouton
    # Menu à l'écran (souris), jamais à un double F12 — vérifié. Ne pas le retirer.
    # → docs/KEYBOARD_MAPPING.md, « Double-appui → commande MA3 ».
    dbl.setdefault("Menu", "SaveShow")
    p["double_clic"] = dbl

    # ── FORME DU PROFIL : ce que la boucle USB tient pour acquis ─────────────
    #
    # La boucle USB lit TOUJOURS 8 faders et 4 roues (c'est le matériel qui le
    # dit, parse_state) et indexe `faders[0..7]` / `enc_groups[0..3]` sans
    # vérifier : un profil plus court tuait le thread USB. On COMPLÈTE, on ne
    # tronque jamais : une entrée en trop est inoffensive, une manquante fatale.
    faders = p.get("faders")
    if not isinstance(faders, list):
        faders = []
    while len(faders) < len(wb.FADER_EXEC):
        faders.append({"kind": "executor", "exec": wb.FADER_EXEC[len(faders)][1]})
    p["faders"] = faders

    egs = p.get("enc_groups")
    if not isinstance(egs, list):
        egs = []
    for gi, defaut in enumerate(wb.ENC_GROUPS):
        if gi >= len(egs):
            egs.append(defaut[:])
        elif not isinstance(egs[gi], list):
            egs[gi] = defaut[:]
        # Chaque groupe doit couvrir les 4 roues.
        while len(egs[gi]) < len(defaut):
            egs[gi].append(None)
    p["enc_groups"] = egs

    # Le groupe de départ doit désigner un groupe qui existe.
    try:
        gi = int(p.get("enc_default_group", wb.ENC_DEFAULT_GROUP))
    except (TypeError, ValueError):
        gi = wb.ENC_DEFAULT_GROUP
    p["enc_default_group"] = gi if 0 <= gi < len(egs) else 0

    # Étiquettes de faders : on complète jusqu'au nombre de faders du profil,
    # sans jamais tronquer ce que l'utilisateur a écrit.
    noms = p.get("fader_noms")
    if not isinstance(noms, list):
        noms = []
    n_faders = len(p.get("faders") or []) or 8
    while len(noms) < n_faders:
        noms.append("")
    p["fader_noms"] = noms[:max(n_faders, len(noms))]

    # Encodeurs : noms qui N'EXISTENT PAS comme attributs dans MA3 (libellés
    # d'Encoder Bar « Pretty », FeatureGroups) → renommés vers l'attribut réel.
    # Sinon « illegal object » sur la ligne de commande de MA3, roue morte sans
    # explication. Vérifié dans attribute_definitions.xml de gma3 2.4.2.
    egs = p.get("enc_groups")
    if isinstance(egs, list):
        for g in egs:
            if not isinstance(g, list):
                continue
            for i, attr in enumerate(g):
                fix = ATTR_RENAMES.get(str(attr).strip().lower()) if attr else None
                if fix:
                    g[i] = fix

    # ⚠️ Casse corrigée ICI aussi : l'interface la corrige à la saisie, mais
    # `migrate_profile()` est le SEUL point de passage commun aux autres entrées
    # d'un profil (chargement local, import d'un profil reçu) — un mot-clé mal
    # capitalisé y échouerait en SILENCE dans MA3.
    # Import PARESSEUX de wing_ma3 : il importe wing_mapper au niveau module.
    import wing_ma3
    for k, v in list(p.get("buttons", {}).items()):
        corrige, _ = wing_ma3.corriger_casse(str(v))
        if corrige != v:
            p["buttons"][k] = corrige
    dbl = p.get("double_clic")
    if isinstance(dbl, dict):
        for token, v in list(dbl.items()):
            if v:
                corrige, _ = wing_ma3.corriger_casse(str(v))
                if corrige != v:
                    dbl[token] = corrige
    egs = p.get("enc_groups")
    if isinstance(egs, list):
        for g in egs:
            if not isinstance(g, list):
                continue
            for i, attr in enumerate(g):
                if attr:
                    g[i] = wing_ma3.corriger_casse_attribut(attr)
    valider_types(p)
    return p


# ── Validation des TYPES du profil ────────────────────────────────────────────
#
# 🔴 FAILLE CRITIQUE (audit du 25/09/2026). Le bloc « FORME DU PROFIL »
# ci-dessus garantit le NOMBRE d'entrées (8 faders, 4 roues), pas leur TYPE.
# Mesuré avant correction, sur un profil importé par `importer_profil` :
#     "faders": ["x", …]   → accepté → `dict("x")` dans usb_loop → ValueError
#     "enc_step": "1"      → accepté → `"1" * delta >= 0`       → TypeError
# Au premier tour en mode bridge (ou à la première roue tournée), le thread
# USB mourait : wing gelée en plein show, sans relance. Un profil reçu d'un
# collègue, ou simplement retouché à la main, suffisait.
#
# ⚠️ Même règle que plus haut : on RÉPARE, on ne refuse pas. Une valeur
# invalide retombe sur son défaut, et on le DIT dans le journal — un profil
# silencieusement « corrigé » ferait croire à une touche qui marche.
# `exec` compte double : il est inséré TEL QUEL dans la commande envoyée à MA3
# (`FaderMaster Executor {exec} At …`). Un texte à cet endroit serait une
# commande MA3 arbitraire.
#
# Contrôle test_profil_mal_type (smoke_securite.py).

# Types de fader connus. ⚠️ Doit rester égal à
# `wing_ui.FADER_KEYWORDS` ∪ {"gm", "selected", "speed", "faderspeed"} :
# le contrôle test_profil_mal_type le vérifie.
KINDS_FADER = {"executor", "crossfade", "crossfadeA", "crossfadeB", "temp",
               "rate", "time", "gm", "selected", "speed", "faderspeed"}
_KINDS_SANS_EXEC = {"gm", "selected", "speed"}
_UNITES_SPEED = {"bpm", "hz", "sec"}
ENC_STEP_MAX = 100.0       # au-delà, un cran de roue ferait sauter l'attribut


def _entier(v, lo, hi):
    """`v` si c'est un vrai entier dans [lo, hi], sinon None (bool exclu)."""
    if isinstance(v, bool) or not isinstance(v, int):
        return None
    return v if lo <= v <= hi else None


def _reel(v):
    """`v` en float s'il est un nombre fini, sinon None (bool exclu)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


def valider_types(p: dict) -> list:
    """Ramène chaque champ lu par la boucle USB à un type sûr.

    Rend la liste des corrections (déjà journalisées) — vide si le profil
    était sain. Ne lève jamais : c'est un filet, pas un juge.
    """
    corrections = []

    def corrige(champ, valeur, defaut):
        corrections.append((champ, repr(valeur)[:60], repr(defaut)[:60]))
        return defaut

    if not isinstance(p.get("name"), str):
        p["name"] = corrige("name", p.get("name"), "Sans nom")

    # Faders : un dict, un type connu, et des champs du bon type.
    for i, fx in enumerate(p.get("faders") or []):
        exe_def = wb.FADER_EXEC[i][1] if i < len(wb.FADER_EXEC) else 101
        if not isinstance(fx, dict) or fx.get("kind", "executor") not in KINDS_FADER:
            p["faders"][i] = corrige(f"faders[{i}]", fx,
                                     {"kind": "executor", "exec": exe_def})
            continue
        kind = fx.get("kind", "executor")
        if kind not in _KINDS_SANS_EXEC and "exec" in fx \
                and _entier(fx["exec"], 1, 99999) is None:
            fx["exec"] = corrige(f"faders[{i}].exec", fx["exec"], exe_def)
        if kind == "selected" and "num" in fx and _entier(fx["num"], 1, 99) is None:
            fx["num"] = corrige(f"faders[{i}].num", fx["num"], 2)
        if kind == "speed" and "num" in fx and _entier(fx["num"], 1, 99) is None:
            fx["num"] = corrige(f"faders[{i}].num", fx["num"], 1)
        if kind in ("speed", "faderspeed"):
            if "unit" in fx and fx["unit"] not in _UNITES_SPEED:
                fx["unit"] = corrige(f"faders[{i}].unit", fx["unit"], "bpm")
            for cle, defaut in (("min", 0.0), ("max", 225.0)):
                if cle in fx and _reel(fx[cle]) is None:
                    fx[cle] = corrige(f"faders[{i}].{cle}", fx[cle], defaut)
        if "suivre" in fx and not isinstance(fx["suivre"], bool):
            fx["suivre"] = corrige(f"faders[{i}].suivre", fx["suivre"], True)

    # Pas des roues : un nombre fini, strictement positif, borné.
    pas = _reel(p.get("enc_step"))
    if pas is None or not (0 < pas <= ENC_STEP_MAX):
        p["enc_step"] = corrige("enc_step", p.get("enc_step"), wb.ENC_STEP)
    else:
        p["enc_step"] = pas

    # Roues : un nom d'attribut est un texte, ou rien.
    for gi, g in enumerate(p.get("enc_groups") or []):
        if not isinstance(g, list):
            p["enc_groups"][gi] = corrige(f"enc_groups[{gi}]", g, [None] * 4)
            continue
        for i, attr in enumerate(g):
            if attr is not None and not isinstance(attr, str):
                g[i] = corrige(f"enc_groups[{gi}][{i}]", attr, None)

    # Tables texte → texte : une valeur d'un autre type est retirée (la
    # touche redevient simplement non assignée — jamais une commande forgée).
    for table in ("buttons", "executor_ref", "console_keys", "double_clic"):
        t = p.get(table)
        if not isinstance(t, dict):
            p[table] = corrige(table, t, {})
            continue
        for k, v in list(t.items()):
            if not isinstance(k, str) or not isinstance(v, str):
                corrige(f"{table}[{k!r}]", v, "—")   # « — » : entrée retirée
                del t[k]

    # Raccourcis : liste blanche (voir `raccourci_valide`). Une frappe refusée
    # retombe sur le défaut de l'app pour ce token, ou devient désassignée.
    ck = p.get("console_keys")
    if isinstance(ck, dict):
        for token, spec in list(ck.items()):
            if not raccourci_valide(spec):
                defaut = CONSOLE_KEY_DEFAULTS.get(token, "")
                ck[token] = corrige(f"console_keys[{token!r}]", spec,
                                    defaut if raccourci_valide(defaut) else "")

    noms = p.get("fader_noms")
    if isinstance(noms, list):
        for i, n in enumerate(noms):
            if not isinstance(n, str):
                noms[i] = corrige(f"fader_noms[{i}]", n, "")

    if corrections:
        try:
            import wing_ui as core
            for champ, valeur, defaut in corrections:
                core.log("journal.profil.champ_invalide", champ=champ,
                         valeur=valeur, defaut=defaut)
        except Exception:
            pass      # journaliser ne doit jamais empêcher de charger
    return corrections


def load_profile(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        p = json.load(f)
    # Champs manquants → valeurs par défaut
    base = new_profile_from_defaults()
    for k, v in base.items():
        p.setdefault(k, v)
    return migrate_profile(p)



# Le mode apprentissage EN TERMINAL (cycle(), learn_*(), menu_*(), main()) a
# été retiré : l'interface web fait tout cela, et ce CLI avait cessé de
# FONCTIONNER sans rien signaler (format de fader d'avant la migration). Ce
# module est la BIBLIOTHÈQUE des profils, sans point d'entrée exécutable.
