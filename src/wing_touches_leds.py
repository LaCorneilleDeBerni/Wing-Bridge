#!/usr/bin/env python3
"""
wing_touches_leds.py — file de frappes clavier et retour LED des boutons
==============================================================================
Extrait de `wing_ui.py`. L'ÉTAT PARTAGÉ (profil, réglages, verrou, liaison USB…) se lit et s'écrit
via `etat.E.<champ>` (etat.py, audit du 25/09/2026, D1) — jamais via
`wing_ui` : ses anciens noms lèvent. `core.X` ne sert plus qu'aux FONCTIONS
et CONSTANTES que `wing_ui.py` réexporte.
Constantes lues via `core.X` : `LED_BASE`, `LED_GLOW`, `LED_FULL`. Seul
`LED_MID` est exclusif à ce fichier.

⚠️ `import wing_ui as core` est PARESSEUX — DANS chaque fonction qui s'en
sert, jamais en tête de fichier (cycle d'import sûr sous CPython nu, mais
pas sous le bootloader figé de PyInstaller). Et parce que `wing_ui.py` est
le POINT D'ENTRÉE du programme, `wing_ui.py` s'auto-enregistre dans
`sys.modules["wing_ui"]` en tête de fichier, AVANT d'importer ce module.
"""

import etat
import re
import time


# ── Appui long : TOUTES les touches, sans réglage ────────────────────────────
#
# 🔑 Décision : l'appui long est implémenté par défaut pour toutes les touches,
# sans case à cocher — le comportement doit être transparent.
#
# Le principe était déjà écrit dans ce projet : **le comportement de maintien
# est NATIF à la touche côté MA3** (Clear maintenu =
# ClearAll, Oops maintenu = historique — pages officielles Clear Key / Oops
# Key). On ne choisit donc PAS une commande différente : on relaie fidèlement
# la vraie durée d'appui, et MA3 décide seul.
#
# Si MA3 ajoute un jour un comportement de maintien sur une autre touche,
# **c'est déjà implémenté** — rien à cocher, rien à mettre à jour.


def enqueue_key(spec: str) -> bool:
    """
    Met une frappe dans la file pour l'assistant clavier.
    spec : 's', '1', '.', 'Enter', 'Clear', 'F5'…
    Chiffres/lettres/ponctuation → saisie littérale ; noms → touche spéciale.
    """
    import wing_ui as core
    s = (spec or "").strip()
    if not s:
        return False

    # TEXTE LITTÉRAL entre guillemets : "If", 'Ifo'… tapé caractère par caractère
    # dans la ligne de commande de MA3. Lève les ambiguïtés d'auto-complétion : la
    # lettre « i » seule donnait IfOutput au lieu de If.
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        with etat.E.WS["lock"]:
            etat.E.WS["queue"].append({"type": "string", "value": s[1:-1]})
        return True

    with etat.E.WS["lock"]:
        if len(s) == 1 and s not in ("\\", '"'):
            etat.E.WS["queue"].append({"type": "string", "value": s})
        else:
            etat.E.WS["queue"].append({"type": "key", "value": s})
    return True


def drain_keys():
    """Retourne et vide la file (appelé par l'assistant via l'API)."""
    import wing_ui as core
    with etat.E.WS["lock"]:
        items = list(etat.E.WS["queue"])
        etat.E.WS["queue"].clear()
    return items


def enqueue_key_down(spec: str) -> bool:
    """Appui SEUL (garde la touche enfoncée côté MA3) — pour l'appui long :
    contrairement à enqueue_key() qui tape un coup sec, ici on relaie la VRAIE
    durée de maintien et on laisse MA3 décider du comportement (ex. Clear
    maintenu = ClearAll, Oops maintenu = historique — comportement natif de
    la touche, pas une commande différente qu'on choisirait nous-mêmes)."""
    import wing_ui as core
    s = (spec or "").strip()
    if not s:
        return False
    with etat.E.WS["lock"]:
        etat.E.WS["queue"].append({"type": "hold_down", "value": s})
    return True


def enqueue_key_up(spec: str) -> bool:
    """Relâche la touche précédemment maintenue par enqueue_key_down (même spec)."""
    import wing_ui as core
    s = (spec or "").strip()
    if not s:
        return False
    with etat.E.WS["lock"]:
        etat.E.WS["queue"].append({"type": "hold_up", "value": s})
    return True


LED_MID = 0x0200         # séquence chargée mais pas en lecture


def niveau_led_ma3(key: str, attente=None) -> int:
    """Niveau de repos d'une LED de bouton, d'après ce que MA3 raconte.

    C'était LA différence la plus visible avec une vraie wing : les LED ne
    disaient rien de l'état réel. Le retour OSC ne contient aucun booléen
    running/stopped (vérifié par observation) — c'est la sonde Lua qui le
    donne, via `ex.object:IsRunningPlayback()`.

    Sans sonde, ou pour un bouton qui n'est pas un executor : veilleuse, soit
    exactement le comportement d'avant.
    """
    import wing_ui as core
    if not etat.E.LED["ma3"]:
        return core.LED_GLOW
    ref = etat.E.PROFILE.get("executor_ref", {}).get(key)
    if not ref:
        return core.LED_GLOW
    m = re.search(r"(\d+)", str(ref))
    if not m:
        return core.LED_GLOW
    no = int(m.group(1))
    e = core.ma3_executor(no)
    if not e:
        return core.LED_GLOW

    # Fader pas encore rattrapé → clignotement, comme sur une command wing MA2.
    # C'est le signal le plus utile : il dit OÙ est le désaccord, sans avoir à
    # regarder l'écran.
    if attente is None:
        attente = core.executors_en_attente()
    if no in attente:
        return core.LED_FULL if int(time.time() * 2) % 2 else core.LED_GLOW

    if e.get("tourne") or e.get("active"):
        return core.LED_FULL          # la cue tourne : plein feu
    # Quelque chose est posé sur l'executor, mais rien ne tourne. `nom` reprend
    # le nom de l'objet assigné ; un emplacement vide se nomme "Executor <n>".
    nom = str(e.get("nom") or "")
    if nom and not nom.startswith("Executor "):
        return LED_MID
    return core.LED_GLOW


def rafraichir_leds_ma3():
    """Repose toutes les LED d'executor sur l'état courant de MA3.

    🐛 Un bouton ENFONCÉ est laissé tranquille. Sans ça, le
    rafraîchissement périodique (8 Hz) écrasait l'allumage de l'appui moins de
    0,12 s après, et la LED retombait au niveau MA3 — qui n'a pas encore vu la
    commande passer (sonde à 0,2 s + temps de réaction de MA3).
    Résultat : la lumière clignotait au mauvais moment et l'ensemble donnait
    l'impression que l'app « ramait », alors que la commande partait bien.

    ⚠️ Le retour d'appui est IMMÉDIAT et local ; l'état MA3 arrive forcément
    après. Ne jamais laisser le second écraser le premier.
    """
    import wing_ui as core
    if not etat.E.LED["ma3"] or etat.E.VEGAS["on"]:
        return
    attente = core.executors_en_attente()          # une seule fois, pas par bouton
    for key in list(etat.E.PROFILE.get("executor_ref", {})):
        try:
            btn = int(key, 16)
            if btn in etat.E.BOUTONS_ENFONCES:       # l'appui prime, toujours
                continue
            set_btn_led(btn, niveau_led_ma3(key, attente))
        except Exception:
            pass


def set_led_offset(offset: int, value: int):
    """Écrit une valeur 0-2047 dans un slot LED (offset pair 0-258)."""
    import wing_ui as core
    if 0 <= offset <= 258:
        etat.E.LED["buf"][offset]     = value & 0xFF
        etat.E.LED["buf"][offset + 1] = (value >> 8) & 0xFF


def slot_led(btn_id: int):
    """Slot LED d'un bouton, ou None s'il n'en a pas.

    🔑 CARTE DÉRIVÉE DE LA CAPTURE, plus aucune configuration.

    Avant, seuls les executors s'allumaient : les autres touches dépendaient
    d'une cartographie manuelle (`PROFILE["leds"]`) que **personne n'avait
    jamais remplie** — aucune entrée dans les profils réels. D'où
    « quand j'appuie sur un bouton, il ne s'allume pas ».

    La carte a été retrouvée dans `a-1.pcapng` en corrélant les événements
    d'appui avec les paquets LED de 264 o. Sur les **7 boutons** pressés dans
    la capture, le même slot passe de 64 (veilleuse) à 2040 (plein feu) :

        0x0e → 28    0x26 → 76    0x2a → 84    0x2b → 86
        0x3b → 118   0x3c → 120   0x42 → 132

    Soit **slot = 2 × btn_id**, vérifié 7 fois sur 7, sans exception.

    ⚠️ Les executors gardent leur formule propre (bloc 196-222, vérifié sur les
    12 executors en juillet) : `2 × 0x70` vaudrait 224 et sortirait du bloc.
    Aucune collision : tous les boutons connus hors executors ont `2 × id < 196`
    (contrôlé sur les 49 boutons des profils).
    """
    if 0x70 <= btn_id <= 0x7d:
        return 196 + 2 * (btn_id - 0x70)
    slot = 2 * btn_id
    return slot if 6 <= slot <= 194 else None


def set_btn_led(btn_id: int, value: int):
    """Allume/éteint la LED d'un bouton. Aucune configuration requise."""
    off = slot_led(btn_id)
    if off is not None:
        set_led_offset(off, value)


# ── Chenillard de test (mode "Vegas") ─────────────────────────────────────────


def vegas_loop():
    """Fait défiler une tête lumineuse avec traîne sur tous les slots LED."""
    import wing_ui as core
    slots = list(range(6, 244, 2))
    tail  = (2040, 1200, 600, 250, 90, 30)
    i = 0
    while True:
        if not etat.E.VEGAS["on"]:
            time.sleep(0.2)
            continue
        n = len(slots)
        for k, off in enumerate(slots):
            d = (i - k) % n
            set_led_offset(off, tail[d] if d < len(tail) else 0)
        i = (i + 1) % n
        time.sleep(0.04)
