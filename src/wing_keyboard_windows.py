#!/usr/bin/env python3
"""
Wing Keyboard — assistant clavier du mode console (Windows)
============================================================
Équivalent Windows de `wing_keyboard_macos.py`. Interroge le serveur Wing
Bridge (`/api/keystrokes`) et injecte les frappes en attente dans grandMA3
onPC.

⚠️⚠️ RÉVISION MAJEURE — pourquoi ce n'est PAS PostMessage.
Le mode réellement utilisé par la wing exige **ShCuts activé** dans MA3 (sinon
les touches ne deviennent pas des commandes : « s » s'écrit « s » au lieu de
Store). Or, mesuré sur grandMA3 onPC 2.4.2.2 :

  • ShCuts **ON**, MA3 ne réagit QU'aux **vrais événements clavier** (matériel
    / `SendInput`), **jamais** aux messages postés (`PostMessage`), et
    **seulement quand MA3 a le focus** — vérifié sur une touche SIMPLE sans
    modificateur (SendInput sans focus, et même avec AttachThreadInput :
    échec). Ce n'est donc pas propre aux combos : c'est vrai pour TOUTE frappe.

Conséquence : sous Windows, contrairement au `CGEventPostToPid` macOS (sans
premier plan), il faut **amener MA3 au premier plan le temps de la frappe**
puis **rendre le focus**. C'est un écart fonctionnel réel vs le Mac, assumé
faute d'alternative (aucune voie « arrière-plan » ne marche en ShCuts ON).

Mécanisme d'envoi :
  • Vol de focus MINIMAL : si MA3 est déjà au premier plan, on n'y touche pas ;
    sinon on mémorise la fenêtre courante, on met MA3 devant, on injecte, on
    restaure IMMÉDIATEMENT le focus précédent. `SetForegroundWindow` peut être
    refusé par Windows (anti focus-stealing) : on vérifie et on journalise.
  • **Caractères imprimables → événement TOUCHE VK** (via `VkKeyScanW`, donc la
    disposition réelle du clavier, AZERTY comprise), PAS `WM_CHAR` ni
    `KEYEVENTF_UNICODE` : en ShCuts ON, MA3 déclenche ses raccourcis sur les
    ÉVÉNEMENTS TOUCHE. Un événement caractère unicode ne les déclencherait pas
    (il ne ferait, au mieux, qu'insérer du texte — pas le verbe). Validé :
    l'événement VK « s » déclenche « Store ».
  • **Touches fonctionnelles / combos → VK + modificateurs.**

Aucune permission système à accorder sous Windows (pas d'Accessibilité). Si
MA3 tourne en ADMINISTRATEUR alors que ce process non, Windows bloque
`SetForegroundWindow` / l'injection (UIPI) — lancer le bridge élevé aussi.
"""

import argparse
import os
import sys
import threading
import time
import json
import urllib.error
import urllib.request
import ctypes
from datetime import datetime

import wing_jeton

try:                                    # numéro de build (généré au build)
    from wing_version import BUILD, BUILD_DATE
except Exception:                       # exécution depuis les sources, hors build
    BUILD, BUILD_DATE = 0, "sources (non buildé)"

LOG_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "Wing Bridge", "wing_keyboard.log")


def flog(msg: str):
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ── Couche Win32 (ctypes), initialisée PARESSEUSEMENT ─────────────────────────
# Tout l'accès Win32 est fait ici, dans des fonctions, jamais au niveau du
# module : ce fichier reste IMPORTABLE sur n'importe quelle plateforme
# (PyInstaller l'analyse statiquement au build macOS sans l'exécuter).

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_SHIFT = 0x10

_W = None            # cache de la couche Win32 (dict) une fois initialisée


def _win():
    """Charge et prototypie une fois les appels user32/kernel32 nécessaires."""
    global _W
    if _W is not None:
        return _W
    from ctypes import wintypes

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = (("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", wintypes.WPARAM))

    class _INUNION(ctypes.Union):
        # padding pour que sizeof(INPUT) == 40 sur x64 (taille réelle de INPUT,
        # dimensionnée par MOUSEINPUT) — sinon SendInput rejette (renvoie 0).
        _fields_ = (("ki", KEYBDINPUT), ("_pad", ctypes.c_byte * 32))

    class INPUT(ctypes.Structure):
        _fields_ = (("type", wintypes.DWORD), ("u", _INUNION))

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    user32.EnumWindows.argtypes = [ENUMPROC, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                                ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    user32.MapVirtualKeyW.restype = wintypes.UINT
    user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
    user32.VkKeyScanW.restype = ctypes.c_short
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    # ── focus ──
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    user32.AttachThreadInput.restype = wintypes.BOOL
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD)]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

    _W = {"user32": user32, "kernel32": kernel32, "ENUMPROC": ENUMPROC,
          "wintypes": wintypes, "INPUT": INPUT}
    return _W


# ── Repérage de la fenêtre grandMA3 — À CHAUD à chaque appel ───────────────────
# Même règle qu'en macOS avec `pgrep` : on RE-ÉNUMÈRE les fenêtres à chaque fois.

MA3_IMAGE = "app_gma3.exe"     # process de rendu/entrée, celui qui reçoit le clavier
MA3_WINDOW_CLASS = "GLFW30"    # classe des fenêtres MA3 (GLFW/OpenGL)
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _proc_image_basename(pid: int):
    if not pid:
        return None
    w = _win(); k = w["kernel32"]
    h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = w["wintypes"].DWORD(len(buf))
        if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
    finally:
        k.CloseHandle(h)
    return None


def _enum_top_windows():
    w = _win(); handles = []

    @w["ENUMPROC"]
    def _cb(hwnd, _lparam):
        handles.append(int(hwnd))
        return True

    w["user32"].EnumWindows(_cb, 0)
    return handles


def _hwnd_pid(hwnd) -> int:
    w = _win()
    pid = w["wintypes"].DWORD(0)
    w["user32"].GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _class_name(hwnd) -> str:
    w = _win(); buf = ctypes.create_unicode_buffer(256)
    w["user32"].GetClassNameW(hwnd, buf, 256)
    return buf.value


def _window_text(hwnd) -> str:
    w = _win(); buf = ctypes.create_unicode_buffer(512)
    w["user32"].GetWindowTextW(hwnd, buf, 512)
    return buf.value


def find_ma3_windows():
    """Fenêtres MA3 pertinentes, À CHAUD : (hwnd, titre, pid) — GLFW30 visibles
    et titrées appartenant à `app_gma3.exe`."""
    out = []
    try:
        w = _win()
        for hwnd in _enum_top_windows():
            if not w["user32"].IsWindowVisible(hwnd):
                continue
            if _class_name(hwnd) != MA3_WINDOW_CLASS:
                continue
            title = _window_text(hwnd)
            if not title:
                continue
            pid = _hwnd_pid(hwnd)
            if (_proc_image_basename(pid) or "").lower() != MA3_IMAGE:
                continue
            out.append((hwnd, title, pid))
    except Exception as e:
        flog(f"⚠️  énumération des fenêtres MA3 impossible ({e})")
    return out


def find_ma3_target():
    """HWND de la fenêtre MA3 qui reçoit le clavier, À CHAUD, ou None.
    Préfère « Display 1 »."""
    wins = find_ma3_windows()
    if not wins:
        return None
    for hwnd, title, _pid in wins:
        if "Display 1" in title:
            return hwnd
    return wins[0][0]


def find_ma3_pid():
    wins = find_ma3_windows()
    return wins[0][2] if wins else None


# ── Table des touches (codes virtuels Windows) ────────────────────────────────

NAMED_VK = {
    "enter": 0x0D, "return": 0x0D, "please": 0x0D,
    "escape": 0x1B, "esc": 0x1B,
    "delete": 0x2E, "clear": 0x2E, "del": 0x2E,
    "forwarddelete": 0x2E, "fwddelete": 0x2E,
    "backspace": 0x08,
    "tab": 0x09, "space": 0x20,
    "left": 0x25, "right": 0x27, "up": 0x26, "down": 0x28,
    "pageup": 0x21, "pagedown": 0x22, "home": 0x24, "end": 0x23,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "semicolon": 0xBA, "comma": 0xBC, "period": 0xBE, "slash": 0xBF,
    "quote": 0xDE, "apostrophe": 0xDE, "minus": 0xBD, "equal": 0xBB,
    "leftbracket": 0xDB, "rightbracket": 0xDD, "backslash": 0xDC, "grave": 0xC0,
}

# ⚠️ Pas de « Command » sous Windows : « cmd » rabattu sur Ctrl.
MOD_VK = {
    "ctrl": 0x11, "control": 0x11, "ctl": 0x11,
    "shift": 0x10,
    "alt": 0x12, "option": 0x12, "opt": 0x12,
    "cmd": 0x11, "command": 0x11,
}


def _letter_digit_vk(base: str):
    """VK d'une lettre/chiffre à sa position US (défauts de raccourcis MA3)."""
    if len(base) == 1:
        c = base.upper()
        if "A" <= c <= "Z" or "0" <= c <= "9":
            return ord(c)
    return None


def parse_spec(spec: str):
    """('a', 'Ctrl+Z', 'Enter'…) → (liste de VK modificateurs, base). None si vide."""
    s = (spec or "").strip()
    if not s:
        return None
    parts = [s] if len(s) == 1 else s.split("+")
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        return None
    mods, base = [], parts[-1]
    for p in parts[:-1]:
        vk = MOD_VK.get(p.lower())
        if vk is not None:
            mods.append(vk)
    return mods, base


def resolve_spec(spec: str):
    """Résout un spec en (vk, [vk modificateurs], message_log|None), ou None si
    seul un caractère imprimable sans modificateur (→ type_char via VkKeyScan)."""
    parsed = parse_spec(spec)
    if not parsed:
        return None
    mods, base = parsed
    low = base.lower()
    if low in NAMED_VK:
        msg = (f"combo « {spec} » → VK {NAMED_VK[low]:#04x} (position)"
               if mods else None)
        return NAMED_VK[low], mods, msg
    vk = _letter_digit_vk(base)
    if mods and vk is not None:
        return vk, mods, f"combo « {spec} » → VK {vk:#04x} (position US)"
    return None


# ── Disposition clavier (compat. d'API + test de fumée) ───────────────────────
LAYOUT = {}


def build_layout_map():
    """{caractère: (vk, shift)} pour les imprimables ASCII de la disposition
    active. Non vide sur toute machine Windows normale."""
    m = {}
    try:
        w = _win()
        for code in range(0x20, 0x7F):
            ch = chr(code)
            r = w["user32"].VkKeyScanW(ch)
            if r == -1:
                continue
            vk = r & 0xFF
            shift = bool((r >> 8) & 1)
            m.setdefault(ch, (vk, shift))
    except Exception:
        pass
    return m


# ── Injection bas niveau : SendInput (vrais événements clavier) ────────────────

def _scan(vk: int) -> int:
    return _win()["user32"].MapVirtualKeyW(vk, 0)


def _send_events(events):
    """events : liste de (wVk, wScan, dwFlags). Un seul appel SendInput."""
    if not events:
        return 0
    w = _win()
    INPUT = w["INPUT"]
    arr = (INPUT * len(events))()
    for i, (vk, scan, flags) in enumerate(events):
        arr[i].type = INPUT_KEYBOARD
        arr[i].u.ki.wVk = vk
        arr[i].u.ki.wScan = scan
        arr[i].u.ki.dwFlags = flags
        arr[i].u.ki.time = 0
        arr[i].u.ki.dwExtraInfo = 0
    return w["user32"].SendInput(len(events), arr, ctypes.sizeof(INPUT))


def _ev_down(vk):
    return (vk, _scan(vk), 0)


def _ev_up(vk):
    return (vk, _scan(vk), KEYEVENTF_KEYUP)


def _tap(vk: int, mods=()):
    """Coup sec d'une touche VK, modificateurs enfoncés autour."""
    ev = [_ev_down(m) for m in mods]
    ev += [_ev_down(vk), _ev_up(vk)]
    ev += [_ev_up(m) for m in reversed(list(mods))]
    _send_events(ev)


def _send_unicode(ch: str):
    """Repli pour un caractère sans VK sur la disposition (rare) : événement
    caractère unicode. ⚠️ NE déclenche PAS les raccourcis ShCuts — insertion de
    texte seulement."""
    cp = ord(ch)
    _send_events([(0, cp, KEYEVENTF_UNICODE),
                  (0, cp, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)])


def type_char(ch: str):
    """Tape un caractère via un ÉVÉNEMENT TOUCHE VK (disposition réelle du
    clavier). En ShCuts ON, c'est ce qui permet à MA3 de déclencher le raccourci
    (« s » → Store). Repli unicode seulement si le caractère n'a pas de VK.

    ⚠️ CHIFFRES = position US SANS Shift, validé. Sur AZERTY,
    `VkKeyScanW('8')` réclame Shift (le 8 est en second niveau) ; or en ShCuts,
    « Shift = touche MA » → « MA+8 » au lieu de « 8 », et rien ne s'écrit. MA3
    lit la POSITION de la touche, pas le caractère produit : on envoie donc le
    VK de la rangée du haut (0x30–0x39) tel quel. Même principe « position US »
    que pour les raccourcis à modificateur (cf. KEYBOARD_MAPPING.md). Les
    LETTRES, elles, partagent leur VK sur AZERTY/QWERTY (`s`→0x53…) : VkKeyScan
    suffit et déclenche le bon mot-clé (validé « s » → Store)."""
    if len(ch) == 1 and ch.isdigit():
        _tap(0x30 + int(ch), [])
        return
    w = _win()
    r = w["user32"].VkKeyScanW(ch)
    if r == -1:
        _send_unicode(ch)
        return
    vk = r & 0xFF
    hi = (r >> 8) & 0xFF
    if hi & 0x06:            # nécessite Ctrl et/ou Alt (AltGr…) → repli unicode
        _send_unicode(ch)
        return
    mods = [VK_SHIFT] if (hi & 1) else []
    _tap(vk, mods)


def type_spec(spec: str):
    """Tape un raccourci nommé / une touche avec modificateurs, ou à défaut le
    caractère littéral."""
    resolved = resolve_spec(spec)
    if resolved:
        vk, mods, msg = resolved
        if msg:
            flog(msg)
        _tap(vk, mods)
        return
    parsed = parse_spec(spec)
    if parsed and len(parsed[1]) == 1:
        type_char(parsed[1])


# ── Appui long : maintien réel d'une touche entre press et release wing ────────
# ⚠️ Le vol de focus complique le maintien (le focus est rendu entre le
# hold_down et le hold_up, la touche reste « enfoncée » au niveau système). On
# le garde fonctionnel mais imparfait ; ce n'est pas le cœur des cas validés.
HOLD_MAX_S = 8.0
_held = {}
_held_lock = threading.Lock()


def key_down(spec: str):
    with _held_lock:
        if spec in _held:
            return
    resolved = resolve_spec(spec)
    if not resolved:
        flog(f"⚠️  appui long impossible pour « {spec} » (pas de vrai VK) — tap normal")
        type_spec(spec)
        return
    vk, mods, msg = resolved
    if msg:
        flog(msg)
    ev = [_ev_down(m) for m in mods] + [_ev_down(vk)]
    _send_events(ev)
    with _held_lock:
        _held[spec] = {"vk": vk, "mods": list(mods), "t": time.time()}
    flog(f"⬇ « {spec} » maintenue")


def key_up(spec: str):
    with _held_lock:
        held = _held.pop(spec, None)
    if not held:
        return
    ev = [_ev_up(held["vk"])] + [_ev_up(m) for m in reversed(held["mods"])]
    _send_events(ev)
    flog(f"⬆ « {spec} » relâchée")


def release_stuck_holds():
    now = time.time()
    with _held_lock:
        stuck = [s for s, h in _held.items() if now - h["t"] > HOLD_MAX_S]
    for spec in stuck:
        flog(f"⚠️  « {spec} » maintenue > {HOLD_MAX_S:.0f}s sans relâchement reçu — auto-relâchée")
        key_up(spec)


def type_items(items):
    """Consomme une liste de frappes (même format que macOS). Le vol de focus
    est géré par l'appelant (send_batch) : MA3 est déjà au premier plan ici."""
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


# ── Vol de focus MINIMAL ──────────────────────────────────────────────────────
# MA3 en ShCuts ON ne réagit qu'au vrai clavier, et seulement s'il a le focus.
# On amène donc MA3 devant le temps d'injecter, puis on rend le focus.

SETTLE_S = 0.02   # laisse MA3 traiter l'entrée injectée avant de rendre le focus


def _set_foreground(hwnd) -> bool:
    """Amène `hwnd` au premier plan de façon robuste (AttachThreadInput), et
    VÉRIFIE le résultat. Renvoie False si Windows a refusé (anti focus-stealing)."""
    w = _win(); u = w["user32"]; k = w["kernel32"]
    hwnd = int(hwnd)
    cur = k.GetCurrentThreadId()
    fg = int(u.GetForegroundWindow() or 0)
    if fg == hwnd:
        return True
    d = w["wintypes"].DWORD(0)
    fgT = u.GetWindowThreadProcessId(fg, ctypes.byref(d)) if fg else 0
    tgtT = u.GetWindowThreadProcessId(hwnd, ctypes.byref(d))
    try:
        if tgtT:
            u.AttachThreadInput(cur, tgtT, True)
        if fgT:
            u.AttachThreadInput(cur, fgT, True)
        u.BringWindowToTop(hwnd)
        u.SetForegroundWindow(hwnd)
    finally:
        if tgtT:
            u.AttachThreadInput(cur, tgtT, False)
        if fgT:
            u.AttachThreadInput(cur, fgT, False)
    return int(u.GetForegroundWindow() or 0) == hwnd


def send_batch(items):
    """Injecte une salve de frappes dans MA3 avec vol de focus minimal, puis
    restaure le focus. Journalise le temps du cycle."""
    w = _win(); u = w["user32"]
    target = find_ma3_target()                 # à chaud
    if not target:
        flog(f"⨯ {len(items)} frappe(s) PERDUE(S) — grandMA3 introuvable "
             f"(lancé ?). Rien n'a été envoyé.")
        return
    fg = int(u.GetForegroundWindow() or 0)
    need_restore = (fg != int(target))
    t0 = time.perf_counter()
    if need_restore:
        if not _set_foreground(target):
            flog("⚠️  SetForegroundWindow refusé (restriction anti focus-stealing "
                 "de Windows) — frappe NON envoyée. Cliquer une fois sur MA3, ou "
                 "le laisser au premier plan.")
            return
    type_items(items)
    if need_restore:
        time.sleep(SETTLE_S)                   # MA3 traite avant qu'on rende le focus
        _set_foreground(fg)
    dt = (time.perf_counter() - t0) * 1000
    if need_restore:
        flog(f"✓ {len(items)} frappe(s) → MA3 (vol+restauration focus {dt:.1f} ms)")
    else:
        flog(f"✓ {len(items)} frappe(s) → MA3 (déjà au premier plan, {dt:.1f} ms)")


# ── Boucle principale ──────────────────────────────────────────────────────────

def main():
    global LAYOUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    args = ap.parse_args()

    base = args.url.rstrip("/")
    poll_url = base + "/api/keystrokes"

    flog(f"=== Wing Keyboard (Windows) démarré — build #{BUILD} ({BUILD_DATE}) ===")
    LAYOUT = build_layout_map()
    flog(f"Disposition clavier : {len(LAYOUT)} caractères mappés")
    tgt = find_ma3_target()
    flog(f"grandMA3 : {'fenêtre ' + hex(tgt) if tgt else 'pas encore lancé'}")

    # 🔒 Jeton d'API (audit du 25/09/2026) — même mécanisme que l'assistant
    # macOS : relu à chaque refus 403. Voir wing_jeton.py.
    jeton = wing_jeton.lire_jeton()
    refus_signale = False

    while True:
        release_stuck_holds()

        try:
            # Sous Windows, aucune permission à sonder : on se déclare « trusted »
            # (la vraie garantie est la présence de la fenêtre, vérifiée à chaque
            # envoi). Le focus est géré au moment de l'injection.
            url = f"{poll_url}?trusted=1&build={BUILD}"
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

        keys = data.get("keys", [])
        if keys:
            send_batch(keys)

        time.sleep(0.05)


def cli():
    if not sys.platform.startswith("win"):
        print("wing_keyboard_windows : Windows uniquement.")
        sys.exit(1)
    try:
        main()
    except KeyboardInterrupt:
        print("\nArrêt.")


if __name__ == "__main__":
    cli()
