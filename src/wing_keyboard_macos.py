#!/usr/bin/env python3
"""
Wing Keyboard — assistant clavier du mode console (macOS)
==========================================================
Tourne en UTILISATEUR normal, avec la permission Accessibilité.
Interroge le serveur Wing Bridge et tape les frappes en attente dans
grandMA3.

Injection via CGEvent (Quartz) : attribution Accessibilité propre à
« Wing Keyboard.app » et déclenchement de la vraie pop-up système au
démarrage (méthode standard macOS).

⚠️ PAS de condition de premier plan. Les frappes sont postées DIRECTEMENT au
process MA3 (CGEventPostToPid), qu'il soit devant ou non — c'est voulu : en
régie, on règle un fader ou on clique ailleurs sans que la wing devienne
muette. Cet en-tête affirmait l'inverse (« ne tape jamais si MA3 n'est pas au
premier plan »), reste d'une version antérieure ; corrigé.

La vraie garantie est ailleurs, et elle tient : rien n'est envoyé si MA3 est
introuvable ou si son PID est mort (vérifié juste avant CHAQUE envoi — voir
la boucle principale), et rien n'est envoyé sans autorisation Accessibilité.
"""

import argparse
import os
import sys
import threading
import time
import json
import urllib.error
import urllib.request
import subprocess
import tempfile
from datetime import datetime

import wing_jeton

import Quartz
from AppKit import NSWorkspace
from ApplicationServices import (
    AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt)

try:                                    # numéro de build (généré au build)
    from wing_version import BUILD, BUILD_DATE
except Exception:                       # exécution depuis les sources, hors build
    BUILD, BUILD_DATE = 0, "sources (non buildé)"

LOG_PATH = os.path.expanduser(
    "~/Library/Application Support/Wing Bridge/wing_keyboard.log")

SETTINGS_URL = ("x-apple.systempreferences:com.apple.preference.security"
                "?Privacy_Accessibility")


def flog(msg: str):
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ── Accessibilité ──────────────────────────────────────────────────────────────

def is_trusted(prompt: bool = False) -> bool:
    return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: prompt}))


def open_settings():
    subprocess.run(["open", SETTINGS_URL], capture_output=True)


def relaunch_self():
    """
    Relance une instance fraîche de l'assistant et quitte. Nécessaire car
    macOS met en cache l'état d'Accessibilité au démarrage du process : après
    un octroi, seul un redémarrage le fait voir. Le nouveau process, lui,
    lira l'autorisation fraîche.
    """
    exe = sys.executable
    # .../Wing Keyboard.app/Contents/MacOS/Wing Keyboard → remonter au .app
    app = os.path.dirname(os.path.dirname(os.path.dirname(exe)))
    try:
        if app.endswith(".app"):
            subprocess.Popen(["open", "-g", "-n", app])
        else:
            subprocess.Popen([exe] + sys.argv[1:],
                             env={**os.environ, "WING_KB_RELAUNCH": "1"})
    except Exception as e:
        flog(f"Relance impossible : {e}")
        return
    flog("Redémarrage de l'assistant pour prendre en compte l'autorisation…")
    time.sleep(0.4)
    os._exit(0)


# ── Sonde d'autorisation : la SEULE lecture fiable de l'état d'Accessibilité ──
# macOS fige l'état au démarrage du process : `is_trusted()` renvoie à vie la
# valeur lue au lancement, quelle que soit la fréquence d'appel (cache par
# process, aucune API publique pour l'invalider — confirmé par les forums
# développeurs Apple). Interroger en boucle depuis ce process ne sert donc à
# RIEN, dans les deux sens (octroi comme révocation).
#
# MAIS un process NEUF, lui, lit l'état frais. On lance donc une copie de
# nous-mêmes en mode sonde (--probe-trust) : elle lit, affiche 1/0, et quitte
# aussitôt. Même bundle → même identité TCC → sa réponse vaut pour nous.
#
# La sonde est lancée avec `open`, JAMAIS en exec direct. Raison vérifiée
# expérimentalement : un process lancé directement en enfant
# hérite de l'identité TCC de son « responsible process » (le parent) — lancée
# depuis un terminal autorisé, la sonde répondait « autorisé » alors que le
# même binaire lancé par `open` au même instant répondait « non autorisé ».
# `open` fait passer par launchd : le process est alors jugé sur sa PROPRE
# identité de bundle, comme un lancement depuis le Finder. C'est le seul mode
# dont la lecture est fiable.
#
# Vérifié aussi : autorisation réactivée dans les Réglages pendant que
# l'assistant tournait → l'assistant continuait de lire « non accordée », une
# instance fraîche lancée par `open` lisait bien « accordée ».
#
# `open` ne remonte pas le code de sortie du process lancé → la réponse
# transite par un petit fichier.
PROBE_SLOW_S = 15.0    # autorisé : simple surveillance de révocation
PROBE_FAST_S = 3.0     # non autorisé : l'utilisateur est probablement en train
                       # de cocher la case — on veut le voir tout de suite
_probe = {"trusted": None}     # dernière réponse de la sonde (None = pas encore)
_console = {"on": False}       # mode console actif ? (renseigné par le poll)


def _app_bundle():
    """Chemin du .app qui nous contient (…/Wing Keyboard.app)."""
    return os.path.dirname(os.path.dirname(os.path.dirname(sys.executable)))


def probe_trust(fallback: bool) -> bool:
    """État d'Accessibilité RÉEL et ACTUEL. `fallback` est renvoyé si la sonde
    échoue (timeout, bundle introuvable…) — jamais d'exception vers l'appelant."""
    app = _app_bundle()
    if not app.endswith(".app"):
        return fallback          # mode dev (pas de bundle) → rien à sonder
    out = os.path.join(tempfile.mkdtemp(prefix="wingprobe-"), "trust")
    try:
        subprocess.run(["open", "-n", "-g", app, "--args",
                        "--probe-trust", "--probe-out", out],
                       capture_output=True, timeout=10)
        for _ in range(60):      # jusqu'à ~6 s (lancement d'un .app ≈ 1 s)
            if os.path.exists(out):
                with open(out) as f:
                    return f.read().strip() == "1"
            time.sleep(0.1)
        flog("⚠️  sonde d'autorisation : pas de réponse (délai dépassé)")
    except Exception as e:
        flog(f"⚠️  sonde d'autorisation indisponible ({e})")
    finally:
        try:
            os.remove(out)
            os.rmdir(os.path.dirname(out))
        except Exception:
            pass
    return fallback


def trust_watcher(launch_trusted: bool):
    """Thread de fond : sonde l'état réel toutes les PROBE_EVERY_S secondes.

    Séparé de la boucle principale exprès — la sonde lance un process (~0,2 s),
    ce qui creuserait un trou dans le traitement des frappes si c'était fait
    en ligne. Deux cas d'action :
      • accordée alors que CE process s'est lancé sans → il ne peut de toute
        façon pas taper (son propre cache dit non) : on redémarre.
      • révoquée alors qu'on s'est lancé avec → rien à redémarrer, mais on le
        signale au serveur (pastille rouge) au lieu d'afficher « prêt » à tort.
    """
    while True:
        if not _console["on"]:
            # Mode console éteint : l'app ne fait que de l'OSC, aucune frappe
            # n'est envoyée — l'autorisation ne sert à rien, on ne sonde pas.
            # Réveil fréquent pour repartir dès l'activation (1re sonde ≈ 1 s
            # après, l'utilisateur a donc la vérité tout de suite).
            time.sleep(1.0)
            continue
        prev = _probe["trusted"]
        real = probe_trust(fallback=launch_trusted if prev is None else prev)
        _probe["trusted"] = real
        if prev is not None and real != prev:
            flog("Accessibilité : " + ("✓ accordée" if real else
                 "⚠️  RÉVOQUÉE (les frappes n'atteindront plus MA3)"))
        if real and not launch_trusted:
            flog("✓ Accessibilité accordée — redémarrage pour la prendre en compte")
            relaunch_self()
            return
        # Attente fractionnée : si le mode console est coupé pendant ce laps,
        # on repasse en veille sans finir d'attendre pour rien.
        deadline = time.time() + (PROBE_SLOW_S if real else PROBE_FAST_S)
        while time.time() < deadline and _console["on"]:
            time.sleep(0.25)


# ── Repérage du process grandMA3 ──────────────────────────────────────────────
#
# NOTE : une fonction `frontmost()` vivait ici, du temps où l'assistant
# n'écrivait que dans l'app au premier plan. Elle n'était plus appelée nulle
# part depuis le passage à CGEventPostToPid. Retirée — du code
# mort qui laissait croire à une condition de focus inexistante.

def find_ma3_pid():
    """PID du process grandMA3 qui reçoit le clavier (app_gma3 en priorité).

    ⚠️ NE PAS revenir à NSWorkspace comme source PRINCIPALE.
    Bug vécu : dans un process de longue durée SANS boucle
    d'exécution — exactement notre cas — la liste de
    `NSWorkspace.runningApplications()` reste FIGÉE. MA3 avait redémarré
    (pid 11483 → 84499), l'assistant détectait bien « pid 11483 n'existe
    plus », relançait la détection… et **retrouvait le même pid mort**. Il
    envoyait alors les frappes à un process inexistant : `CGEventPostToPid`
    échoue en SILENCE, sans exception ni message. Le journal affichait
    « ✓ 1 frappe(s) → MA3 » alors que rien n'arrivait — le pire des cas.
    (Même famille de piège que le cache d'autorisation Accessibilité.)

    `pgrep` lance un process EXTERNE neuf à chaque appel : aucun cache
    possible. Vérifié : NSWorkspace interrogé depuis un process neuf donnait
    la bonne réponse, depuis l'assistant la mauvaise.
    """
    try:
        # app_gma3 = le process de rendu/entrée, celui qui reçoit le clavier.
        r = subprocess.run(["pgrep", "-f", "app_gma3"],
                           capture_output=True, text=True, timeout=2)
        pids = [int(x) for x in r.stdout.split() if x.isdigit()]
        if pids:
            return pids[0]
        r = subprocess.run(["pgrep", "-i", "gma3"],
                           capture_output=True, text=True, timeout=2)
        pids = [int(x) for x in r.stdout.split() if x.isdigit()]
        if pids:
            return pids[0]
        return None
    except Exception as e:
        flog(f"⚠️  recherche du pid MA3 impossible ({e}) — repli NSWorkspace")

    # Repli uniquement si pgrep est indisponible : sujet au cache décrit plus haut.
    fallback = None
    for a in NSWorkspace.sharedWorkspace().runningApplications():
        n = (a.localizedName() or "").lower()
        b = (a.bundleIdentifier() or "").lower()
        if "gma3" in n or "gma3" in b or "grandma3" in n or "grandma3" in b:
            pid = a.processIdentifier()
            if "app_gma3" in n or "gma3" in n:
                return pid
            fallback = pid
    return fallback


def pid_is_alive(pid) -> bool:
    """True si ce PID correspond à un process vivant. N'ENVOIE aucun signal
    (signal 0 = test d'existence pur, standard Unix) — juste une vérification.
    """
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True   # existe mais appartient à un autre user → vivant quand même
    except Exception:
        return False


MA3_PID = None   # rafraîchi périodiquement dans la boucle


# ── Caractère → (key code, shift) selon la DISPOSITION RÉELLE du clavier ───────
# Les key codes sont des positions physiques : sur AZERTY, la position du "a"
# QWERTY donne "q". On lit donc la disposition active (UCKeyTranslate) pour
# taper le bon caractère quel que soit le clavier (AZERTY, QWERTY, QWERTZ…).

import ctypes
import ctypes.util
from ctypes import (c_void_p, c_uint16, c_uint32, c_ulong, byref, POINTER)

_Carbon = ctypes.cdll.LoadLibrary(ctypes.util.find_library("Carbon"))
_CF = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
_Carbon.TISCopyCurrentKeyboardInputSource.restype = c_void_p
_Carbon.TISGetInputSourceProperty.restype = c_void_p
_Carbon.TISGetInputSourceProperty.argtypes = [c_void_p, c_void_p]
_Carbon.LMGetKbdType.restype = c_uint32
_Carbon.UCKeyTranslate.restype = c_uint32
_Carbon.UCKeyTranslate.argtypes = [c_void_p, c_uint16, c_uint16, c_uint32,
                                   c_uint32, c_uint32, POINTER(c_uint32),
                                   c_ulong, POINTER(c_ulong), POINTER(c_uint16)]
_CF.CFDataGetBytePtr.restype = c_void_p
_CF.CFDataGetBytePtr.argtypes = [c_void_p]
_kLayoutProp = c_void_p.in_dll(_Carbon, "kTISPropertyUnicodeKeyLayoutData")


def build_layout_map():
    """{caractère: (key code, shift)} pour la disposition clavier active."""
    m = {}
    try:
        src = _Carbon.TISCopyCurrentKeyboardInputSource()
        data = _Carbon.TISGetInputSourceProperty(src, _kLayoutProp)
        layout = _CF.CFDataGetBytePtr(data)
        kbd = _Carbon.LMGetKbdType()
        if not layout:
            return m
        for shift in (0, 1):
            modstate = 2 if shift else 0     # shiftKey >> 8 = 2
            for kc in range(128):
                dead = c_uint32(0); length = c_ulong(0); buf = (c_uint16 * 4)()
                r = _Carbon.UCKeyTranslate(layout, kc, 0, modstate, kbd, 0,
                                           byref(dead), 4, byref(length), buf)
                if r == 0 and length.value >= 1:
                    ch = "".join(chr(buf[i]) for i in range(length.value))
                    if len(ch) == 1 and ch not in m:
                        m[ch] = (kc, bool(shift))
    except Exception:
        pass
    return m


LAYOUT = {}   # rempli au démarrage + rafraîchi périodiquement

# Lettre/chiffre → key code position QWERTY/US (standard ANSI).
# MA3 range ses raccourcis PAR DÉFAUT selon ces positions → pour les
# raccourcis à modificateur (Ctrl+Z…), on envoie la position US, pas AZERTY.
US_KEYCODES = {
    "a": 0,  "b": 11, "c": 8,  "d": 2,  "e": 14, "f": 3,  "g": 5,  "h": 4,
    "i": 34, "j": 38, "k": 40, "l": 37, "m": 46, "n": 45, "o": 31, "p": 35,
    "q": 12, "r": 15, "s": 1,  "t": 17, "u": 32, "v": 9,  "w": 13, "x": 7,
    "y": 16, "z": 6,
    "1": 18, "2": 19, "3": 20, "4": 21, "5": 23, "6": 22, "7": 26, "8": 28,
    "9": 25, "0": 29,
}

# Touches nommées → key code (positions physiques, indépendantes de la dispo)
NAMED_KEYS = {
    "enter": 36, "return": 36, "please": 36,
    "escape": 53, "esc": 53,
    "delete": 117, "clear": 117, "del": 117,       # ⌦ forward delete = Clear MA3
    "forwarddelete": 117, "fwddelete": 117,
    "backspace": 51,
    "tab": 48, "space": 49,
    "left": 123, "right": 124, "down": 125, "up": 126,
    "pageup": 116, "pagedown": 121, "home": 115, "end": 119,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97,
    "f7": 98, "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
    # Noms de position US, tels qu'affichés par la table de raccourcis MA3.
    # Règle d'or : ce que MA3 affiche = ce qu'on écrit dans l'app.
    "semicolon": 41, "comma": 43, "period": 47, "slash": 44,
    "quote": 39, "apostrophe": 39, "minus": 27, "equal": 24,
    "leftbracket": 33, "rightbracket": 30, "backslash": 42, "grave": 50,
}

MOD_FLAGS = {
    "ctrl": Quartz.kCGEventFlagMaskControl,   "control": Quartz.kCGEventFlagMaskControl,
    "ctl":  Quartz.kCGEventFlagMaskControl,
    "cmd":  Quartz.kCGEventFlagMaskCommand,   "command": Quartz.kCGEventFlagMaskCommand,
    "alt":  Quartz.kCGEventFlagMaskAlternate, "option":  Quartz.kCGEventFlagMaskAlternate,
    "opt":  Quartz.kCGEventFlagMaskAlternate,
    "shift": Quartz.kCGEventFlagMaskShift,
}

# masque de flag → key code de la touche modificateur physique (gauche)
MOD_KEYCODES = [
    (Quartz.kCGEventFlagMaskCommand,   55),
    (Quartz.kCGEventFlagMaskShift,     56),
    (Quartz.kCGEventFlagMaskAlternate, 58),
    (Quartz.kCGEventFlagMaskControl,   59),
]


# Keycodes des touches F : macOS les traite comme volume/média (réglage par
# défaut « touches F multimédia »). En ajoutant le flag Fn, elles redeviennent
# de vraies touches F qui atteignent MA3 au lieu de changer le volume.
FKEY_CODES = {122, 120, 99, 118, 96, 97, 98, 100, 101, 109, 103, 111,
              105, 107, 113, 106, 64, 79, 80, 90}


def _src():
    return Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)


def _emit(ev):
    """Envoie l'event DIRECTEMENT au process MA3 (peu importe le premier plan),
    ou au tap système en dernier recours."""
    if MA3_PID:
        Quartz.CGEventPostToPid(MA3_PID, ev)
    else:
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def _press_keycode(keycode: int, flags: int = 0):
    """Presse modificateurs + touche, NE RELÂCHE RIEN — moitié "appui" de
    post_keycode, réutilisée telle quelle pour le tap normal et l'appui
    long (hold). Retourne (flags, mods) pour que l'appelant relâche ensuite
    exactement ce qui a été pressé (via _release_keycode)."""
    if keycode in FKEY_CODES:
        flags |= Quartz.kCGEventFlagMaskSecondaryFn
    src = _src()
    mods = [(m, kc) for (m, kc) in MOD_KEYCODES if flags & m]
    acc = 0
    for m, kc in mods:
        acc |= m
        ev = Quartz.CGEventCreateKeyboardEvent(src, kc, True)
        Quartz.CGEventSetFlags(ev, acc)
        _emit(ev)
        time.sleep(0.02)
    ev = Quartz.CGEventCreateKeyboardEvent(src, keycode, True)
    Quartz.CGEventSetFlags(ev, flags)
    _emit(ev)
    return flags, mods


def _release_keycode(keycode: int, flags: int, mods):
    """Relâche touche + modificateurs — moitié "relâchement" de post_keycode,
    symétrique de _press_keycode (mods = ce qui a été explicitement pressé)."""
    src = _src()
    ev = Quartz.CGEventCreateKeyboardEvent(src, keycode, False)
    Quartz.CGEventSetFlags(ev, flags)
    _emit(ev)
    time.sleep(0.02)
    acc = 0
    for m, kc in mods:
        acc |= m
    for m, kc in reversed(mods):
        acc &= ~m
        ev = Quartz.CGEventCreateKeyboardEvent(src, kc, False)
        Quartz.CGEventSetFlags(ev, acc)
        _emit(ev)
        time.sleep(0.01)


def post_keycode(keycode: int, flags: int = 0):
    """
    Poste une touche vers MA3 (coup sec complet), en pressant/relâchant
    EXPLICITEMENT les modificateurs autour d'elle (sinon un modificateur
    peut rester "coincé"). Minutage identique au comportement historique.
    """
    flags, mods = _press_keycode(keycode, flags)
    time.sleep(0.03)
    _release_keycode(keycode, flags, mods)


def post_unicode(ch: str):
    src = _src()
    for down in (True, False):
        ev = Quartz.CGEventCreateKeyboardEvent(src, 0, down)
        Quartz.CGEventKeyboardSetUnicodeString(ev, len(ch), ch)
        _emit(ev)


def parse_spec(spec: str):
    s = (spec or "").strip()
    if not s:
        return None
    parts = [s] if len(s) == 1 else s.split("+")
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        return None
    flags, base = 0, parts[-1]
    for p in parts[:-1]:
        flags |= MOD_FLAGS.get(p.lower(), 0)
    return flags, base


def resolve_spec(spec: str):
    """Résout un spec en (keycode, flags, message_log|None) — même logique de
    dispatch que type_spec (NAMED_KEYS / US_KEYCODES / LAYOUT), réutilisée
    pour le tap normal ET l'appui long (key_down/key_up). None si seul un
    fallback unicode est possible (pas de vrai maintien possible alors,
    CGEventKeyboardSetUnicodeString n'a pas de press/release séparé)."""
    parsed = parse_spec(spec)
    if not parsed:
        return None
    flags, base = parsed
    low = base.lower()
    if low in NAMED_KEYS:                        # Enter, Delete, F5, semicolon… (position)
        msg = f"combo « {spec} » → keycode {NAMED_KEYS[low]} (position US)" if flags else None
        return NAMED_KEYS[low], flags, msg
    elif flags and low in US_KEYCODES:            # raccourci à modificateur →
        msg = f"combo « {spec} » → keycode {US_KEYCODES[low]} (position US)"
        return US_KEYCODES[low], flags, msg       # position QWERTY (défauts MA3)
    elif low in LAYOUT:                           # sans modificateur → dispo réelle
        kc, shift = LAYOUT[low]
        if shift:
            flags |= Quartz.kCGEventFlagMaskShift
        return kc, flags, None
    return None


def type_spec(spec: str):
    """Tape un raccourci nommé ou une touche avec modificateurs (coup sec)."""
    resolved = resolve_spec(spec)
    if resolved:
        kc, flags, msg = resolved
        if msg:
            flog(msg)
        post_keycode(kc, flags)
        return
    parsed = parse_spec(spec)
    if parsed and len(parsed[1]) == 1:
        post_unicode(parsed[1])


# ── Appui long : maintien réel d'une touche entre press et release wing ────
# Filet de sécurité : une touche maintenue trop longtemps sans relâchement
# reçu (release perdu, app redémarrée en plein maintien…) est auto-relâchée —
# une touche/modificateur qui reste bloquée casse toute la frappe ensuite.
HOLD_MAX_S = 8.0
_held = {}          # spec → {"keycode","flags","mods","t"}
_held_lock = threading.Lock()


def key_down(spec: str):
    """Presse une touche et la GARDE enfoncée (appui long) — relâchée par
    key_up(spec) avec le MÊME spec, ou automatiquement après HOLD_MAX_S."""
    with _held_lock:
        if spec in _held:
            return   # déjà maintenue (double appui / glitch) — ignore
    resolved = resolve_spec(spec)
    if not resolved:
        flog(f"⚠️  appui long impossible pour « {spec} » (pas de vrai keycode) — tap normal")
        type_spec(spec)
        return
    kc, flags, msg = resolved
    if msg:
        flog(msg)
    pflags, mods = _press_keycode(kc, flags)
    with _held_lock:
        _held[spec] = {"keycode": kc, "flags": pflags, "mods": mods, "t": time.time()}
    flog(f"⬇ « {spec} » maintenue")


def key_up(spec: str):
    """Relâche une touche précédemment maintenue par key_down(spec)."""
    with _held_lock:
        held = _held.pop(spec, None)
    if not held:
        return   # rien à relâcher (déjà relâchée, ou jamais pressée)
    _release_keycode(held["keycode"], held["flags"], held["mods"])
    flog(f"⬆ « {spec} » relâchée")


def release_stuck_holds():
    """Filet de sécurité, appelé périodiquement depuis la boucle principale :
    relâche toute touche maintenue depuis trop longtemps sans relâchement
    reçu — évite qu'une touche/modificateur reste bloquée indéfiniment."""
    now = time.time()
    with _held_lock:
        stuck = [s for s, h in _held.items() if now - h["t"] > HOLD_MAX_S]
    for spec in stuck:
        flog(f"⚠️  « {spec} » maintenue > {HOLD_MAX_S:.0f}s sans relâchement reçu — auto-relâchée")
        key_up(spec)


def type_char(ch: str):
    """Tape un caractère littéral selon la disposition clavier active."""
    key = ch if ch in LAYOUT else ch.lower()
    if key in LAYOUT:
        kc, shift = LAYOUT[key]
        flags = Quartz.kCGEventFlagMaskShift if (shift or ch.isupper()) else 0
        post_keycode(kc, flags)
    else:
        post_unicode(ch)


def type_items(items):
    for it in items:
        t = it.get("type")
        if t == "string":
            for ch in str(it.get("value", "")):
                type_char(ch)
                time.sleep(0.004)
        elif t == "hold_down":
            key_down(str(it.get("value", "")))
        elif t == "hold_up":
            key_up(str(it.get("value", "")))
        else:
            type_spec(str(it.get("value", "")))
        time.sleep(0.004)


# ── Boucle principale ──────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    args = ap.parse_args()

    base = args.url.rstrip("/")
    poll_url = base + "/api/keystrokes"
    action_done_url = base + "/api/console/action_done"

    flog(f"=== Wing Keyboard démarré — build #{BUILD} ({BUILD_DATE}) ===")

    # Lire la disposition clavier réelle (AZERTY/QWERTY/…) pour taper les bons
    # caractères. Rafraîchie périodiquement si l'utilisateur change de dispo.
    global LAYOUT, MA3_PID
    LAYOUT = build_layout_map()
    flog(f"Disposition clavier : {len(LAYOUT)} caractères mappés")
    MA3_PID = find_ma3_pid()
    flog(f"grandMA3 : {'pid '+str(MA3_PID) if MA3_PID else 'pas encore lancé'}")
    last_layout_refresh = time.time()

    # PAS de pop-up d'autorisation au démarrage : l'assistant redémarre souvent, et
    # macOS ne ferme pas la fenêtre de l'instance tuée — elles s'empilaient. La
    # pop-up n'est déclenchée QUE par le bouton 🔓 (action "open_settings") : une
    # action délibérée = exactement une fenêtre. Tant que ce n'est pas autorisé,
    # c'est l'interface qui guide.
    if not is_trusted(prompt=False):
        flog("Accessibilité non accordée (bouton 🔓 dans l'interface pour l'accorder)")

    warned = False
    # 🔒 Jeton d'API (audit du 25/09/2026) : le serveur refuse désormais la file
    # de frappes à qui ne le présente pas. Relu à chaque refus 403 — l'app a été
    # relancée et en a publié un neuf. Voir wing_jeton.py.
    jeton = wing_jeton.lire_jeton()
    refus_signale = False

    # Notre PROPRE capacité à taper est figée à cet instant précis et ne
    # changera plus de toute la vie du process (cache macOS). Tout le reste de
    # la surveillance passe par la sonde, seule à lire l'état actuel.
    launch_trusted = is_trusted(prompt=False)
    _probe["trusted"] = launch_trusted     # en attendant la 1re sonde
    threading.Thread(target=trust_watcher, args=(launch_trusted,),
                     daemon=True).start()

    while True:
        release_stuck_holds()   # filet de sécurité anti-touche-bloquée (appui long)
        # État remonté au serveur = ce que la sonde a vu en dernier (la vérité
        # actuelle), PAS notre cache figé : c'est ce qui évite d'afficher
        # « clavier console : prêt » alors que l'autorisation a été retirée.
        # Pour taper, il faut les DEUX : autorisation actuelle ET ce process
        # lancé avec (sinon macOS refuse silencieusement l'injection).
        trusted = bool(_probe["trusted"]) and launch_trusted
        # Rafraîchir disposition clavier + PID de MA3 toutes les 3 s. Filet de
        # sécurité en plus du contrôle de vivacité juste avant l'envoi
        # (ci-dessous) : celui-ci couvre le cas où MA3 change de PID SANS
        # jamais passer par "introuvable" entre les deux (ex. redémarrage très
        # rapide), ce que la vérification de vivacité seule ne détecterait pas
        # puisque l'ancien PID redevient parfois libre puis réattribué à un
        # AUTRE process avant notre prochain envoi.
        if time.time() - last_layout_refresh > 3:
            new = build_layout_map()
            if new:
                LAYOUT = new
            fresh = find_ma3_pid()
            if fresh != MA3_PID:
                flog(f"grandMA3 : PID changé {MA3_PID} → {fresh} (rafraîchissement périodique)")
                MA3_PID = fresh
            last_layout_refresh = time.time()
        try:
            # `build` : permet au serveur d'afficher les DEUX numéros et de
            # rendre visible un écart (build serveur seul, ou bundle mélangé).
            url = f"{poll_url}?trusted={1 if trusted else 0}&build={BUILD}"
            with wing_jeton.ouvrir(url, jeton, timeout=2) as r:
                data = json.loads(r.read().decode())
            refus_signale = False
        except urllib.error.HTTPError as e:
            if e.code == 403:
                jeton = wing_jeton.lire_jeton()
                if not refus_signale:
                    flog(f"🔒 Jeton d'API refusé — relu dans {wing_jeton.chemin_jeton()}")
                    refus_signale = True
            time.sleep(1.0)
            continue
        except Exception:
            time.sleep(1.0)
            continue

        # Pilote la mise en veille de la sonde (cf. trust_watcher). Défaut à
        # True si absent : face à un serveur plus ancien, on préfère surveiller
        # pour rien plutôt que de rater une révocation.
        _console["on"] = bool(data.get("console", True))

        # Action demandée par l'UI (ex. ouvrir les réglages)
        if data.get("action") == "open_settings":
            flog("Ouverture des réglages d'Accessibilité (demande UI)")
            open_settings()
            # SEUL endroit du programme qui déclenche la pop-up système : une
            # action délibérée de l'utilisateur (bouton 🔓) = exactement une
            # fenêtre à l'écran. Voir le commentaire au démarrage de main().
            # C'est aussi ce qui (ré)inscrit l'app dans la liste Accessibilité
            # après le `tccutil reset` fait juste avant côté serveur.
            is_trusted(prompt=True)
            # Rien à programmer pour la suite : la sonde (thread
            # trust_watcher) voit l'octroi en quelques secondes et redémarre.
            try:
                wing_jeton.ouvrir(action_done_url, jeton, data=b"{}", timeout=2)
            except Exception:
                pass

        keys = data.get("keys", [])
        if keys:
            if not trusted:
                if not warned:
                    flog("⚠️  ACCESSIBILITÉ REFUSÉE — active « Wing Keyboard » dans "
                         "Réglages → Confidentialité et sécurité → Accessibilité.")
                    warned = True
            else:
                warned = False
                # Vérif de vivacité JUSTE AVANT l'envoi (pas seulement le
                # minuteur périodique 3 s ci-dessus) : CGEventPostToPid vers
                # un PID mort échoue SILENCIEUSEMENT (aucune exception, aucun
                # log d'erreur) — sans ce contrôle, les frappes semblent
                # "réussir" indéfiniment sans jamais atteindre MA3. Cause
                # racine du bug de juillet 2026 (PID resté périmé après un
                # redémarrage de MA3). Re-résolution IMMÉDIATE si mort, sans
                # attendre le prochain cycle du minuteur.
                if MA3_PID and not pid_is_alive(MA3_PID):
                    ancien = MA3_PID
                    MA3_PID = find_ma3_pid()
                    flog(f"grandMA3 : pid {ancien} disparu → {MA3_PID or 'introuvable'}")
                    last_layout_refresh = time.time()
                # Ne JAMAIS annoncer un succès sans avoir revérifié que la
                # cible est vivante : `CGEventPostToPid` sur un pid mort échoue
                # en SILENCE. Déjà vu : le journal affichait
                # « ✓ frappe(s) → MA3 » pendant que rien n'arrivait — un
                # message de succès mensonger coûte des heures de diagnostic.
                if MA3_PID and pid_is_alive(MA3_PID):
                    type_items(keys)      # envoyé DIRECTEMENT au process MA3
                    flog(f"✓ {len(keys)} frappe(s) → MA3 (pid {MA3_PID}, sans condition de focus)")
                else:
                    flog(f"⨯ {len(keys)} frappe(s) PERDUE(S) — grandMA3 introuvable "
                         f"(lancé ?). Rien n'a été envoyé.")

        time.sleep(0.05)


def cli():
    """Point d'entrée de l'assistant macOS — appelé par le dispatcher
    wing_keyboard.py (ou directement si ce fichier est lancé seul). Contenu
    IDENTIQUE à l'ancien bloc `if __name__ == "__main__"` de wing_keyboard.py
    (déplacé tel quel lors du découpage par plateforme)."""
    if sys.platform != "darwin":
        print("wing_keyboard : macOS uniquement.")
        sys.exit(1)
    if "--probe-trust" in sys.argv:
        # Mode sonde : instance jetable lancée par trust_watcher via `open`.
        # Volontairement placé AVANT tout le reste — pas de journal, pas de
        # disposition clavier, pas de réseau : lit l'état frais et disparaît.
        # La réponse passe par un fichier (`open` ne remonte ni stdout ni code
        # de sortie) ; l'écriture est atomique pour que l'appelant ne puisse
        # jamais lire un fichier à moitié écrit.
        try:
            dest = sys.argv[sys.argv.index("--probe-out") + 1]
            with open(dest + ".part", "w") as f:
                f.write("1" if is_trusted(prompt=False) else "0")
            os.replace(dest + ".part", dest)
        except Exception:
            pass
        sys.exit(0)
    try:
        main()
    except KeyboardInterrupt:
        print("\nArrêt.")


if __name__ == "__main__":
    cli()
