#!/usr/bin/env python3
"""
wing_diagnostic.py — rapport de diagnostic complet, capture des exceptions
============================================================================
Extrait de `wing_ui.py`. Lit l'état partagé via `etat.E.<champ>` (etat.py,
D1) et n'écrit jamais dedans. Les FONCTIONS de `wing_ui.py` (`core.log`,
`core._log_to_file`, `core._diag_home`…) s'appellent par attribut qualifié,
jamais par `from wing_ui import …` : le test de fumée les remplace pour
ne pas écrire sur le vrai Bureau ni dans le vrai journal.

⚠️ `import wing_ui as core` est PARESSEUX — DANS chaque fonction qui s'en
sert, jamais en tête de fichier. `wing_ui.py` importe ce module (pour
réexporter `build_diagnostic`/`install_crash_logging`), donc un `import
wing_ui` ici, au niveau module, fermerait un cycle AU CHARGEMENT. Sous
CPython nu ça passe (sys.modules coupe le cycle), mais le bootloader figé de
PyInstaller (`pyimod02_importers`) ne le voit pas de la même façon : constaté
au build, `ImportError: cannot import name
'build_diagnostic' from partially initialized module 'wing_diagnostic'` —
l'app frozen ne démarrait plus DU TOUT. Un import paresseux (dans le corps de
la fonction, exécuté bien après que les deux modules soient chargés) est sûr
dans les deux cas.
"""

import etat
import json
import os
import sys
import threading
import time
from pathlib import Path

import wing_bridge as wb
import wing_detect
import wing_mapper as wm


# ⚠️ Le rapport de diagnostic est TOUJOURS EN ANGLAIS, quelle que soit la langue
# de l'app : il part chez un mainteneur. On passe donc par `L_en` (jamais `L`) —
# le contrôle de fumée `test_i18n` sous-contrôle (i) refuse le build si un `L(`
# nu apparaît dans ce fichier.
def _LE(cle, **params):
    import wing_i18n
    return wing_i18n.L_en(cle, **params)


# Libellés lisibles pour le rapport de diagnostic (cf. ma3_reachable).
# ⚠️ NE PAS DÉSIGNER UNE CAUSE UNIQUE pour « muet » : le libellé disait
# autrefois « Cause n°1 : une machine virtuelle tourne » — affirmé quelle que
# soit la situation, et faux (symptôme relevé SANS aucune VM). Le vrai
# « pourquoi » vient de la sonde (osc_config_ma3). Ici : le constat + la liste
# de ce qu'il faut regarder, sans hiérarchiser ce qu'on n'a pas mesuré.
_LIB_MA3_CLE = {
    "ok":   "diag.ma3.ok",
    "muet": "diag.ma3.muet",
    "off":  "diag.ma3.off",
    None:   "diag.ma3.distant",
}


def _diag_home():
    """Dossier personnel de l'utilisateur, déduit du dossier des profils.

    ⚠️ Ne PAS simplifier en `Path.home()`. Le serveur tourne normalement en
    utilisateur (uid 501), mais le repli root existe encore
    (cf. run_in_user_session) — et dans ce cas `Path.home()` renvoie /var/root,
    donc un diagnostic écrit là où personne ne le trouvera.
    """
    try:
        h = wm.PROFILE_DIR.parents[3]
        if (h / "Desktop").is_dir():
            return h
    except Exception:
        pass
    return None


def build_diagnostic() -> Path:
    """Rassemble TOUT ce qu'il faut pour diagnostiquer à distance, en un seul
    fichier texte que l'utilisateur n'a plus qu'à envoyer.

    Chaque section est isolée : une section qui échoue ne doit pas priver des
    autres — c'est justement quand quelque chose est cassé qu'on génère ça.
    """
    import datetime, platform
    import wing_ui as core

    def section(titre, fn):
        out = [f"\n{'─' * 62}\n{titre}\n{'─' * 62}"]
        try:
            out.append(str(fn()).rstrip())
        except Exception as e:
            out.append(_LE("diag.section_indispo", type=type(e).__name__, err=e))
        return "\n".join(out)

    def _identite():
        # os.geteuid() n'existe QUE sur les OS POSIX (macOS, Linux) : sous
        # Windows l'attribut est absent et l'appel direct lève AttributeError,
        # ce qui faisait disparaître TOUTE la section IDENTITÉ du rapport (le
        # fichier paraissait complet — panne muette, cf. docs/WINDOWS.md).
        # On lit l'uid une seule fois, en le laissant à None hors POSIX : le
        # comportement macOS reste identique au bit près (mêmes « uid N » et
        # « (root) »), et Windows affiche un champ cohérent au lieu de rien.
        _uid = os.geteuid() if hasattr(os, "geteuid") else None
        diff = _LE("diag.identite.kbd_different") if (
            etat.E.WS['helper_build'] and etat.E.WS['helper_build'] != core.BUILD) else ""
        return (f"{_LE('diag.identite.date')} {datetime.datetime.now():%d/%m/%Y %H:%M:%S}\n"
                f"{_LE('diag.identite.build_moteur')} #{core.BUILD} ({core.BUILD_DATE})\n"
                f"{_LE('diag.identite.build_clavier')} #{etat.E.WS['helper_build']}{diff}\n"
                f"{_LE('diag.identite.macos')} {platform.mac_ver()[0]} ({platform.machine()})\n"
                f"{_LE('diag.identite.execution')} "
                f"{_LE('diag.identite.fige') if getattr(sys, 'frozen', False) else _LE('diag.identite.sources')}\n"
                f"{_LE('diag.identite.utilisateur')} uid {_uid if _uid is not None else _LE('diag.identite.non_posix')}"
                f"{_LE('diag.identite.root') if _uid == 0 else ''}")

    def _etat():
        with etat.E.LOCK:
            wing = _LE("diag.etat.wing_oui") if etat.E.STATE['wing'] else _LE("diag.etat.wing_non")
            dirty = _LE("diag.etat.dirty") if etat.E.STATE['dirty'] else ""
            return (f"{_LE('diag.etat.bridge')} {etat.E.STATE['mode']}\n"
                    f"{_LE('diag.etat.wing_usb')} {wing}"
                    f"  ({_LE('diag.etat.souhaitee')} {etat.E.STATE['want_connected']})\n"
                    f"{_LE('diag.etat.profil')} {etat.E.PROFILE['name']}{dirty}\n"
                    f"{_LE('diag.etat.recuperation')} {etat.E.RECOVERY['available'] or _LE('diag.etat.aucune')}")

    def _osc():
        vm = _LE("diag.osc.vm_oui") if core.vm_active() else _LE("diag.osc.vm_non")
        err = (_LE("diag.osc.erreur") + " " + core.OSC_IN['error']) if core.OSC_IN['error'] else ""
        return (f"{_LE('diag.osc.cible')} {wb.MA3_IP}:{wb.MA3_PORT}\n"
                f"{_LE('diag.osc.liaison')} {_LE(_LIB_MA3_CLE.get(core.ma3_reachable(), 'diag.ma3.distant'))}\n"
                f"{_LE('diag.osc.vm')} {vm}\n"
                f"{_LE('diag.osc.ecoute')} "
                f"{core.OSC_IN['port'] or _LE('diag.osc.desactivee')}{err}\n"
                f"{_LE('diag.osc.recus')} {core.OSC_IN['count']}")

    def _console():
        # ⚠️ Ne pas réintroduire de drapeau « activé » (il n'y a plus de bascule) :
        # l'état réel se DÉDUIT de l'assistant. Une clé disparue (`WS["enabled"]`)
        # avait fait remplacer TOUTE cette section par « (section indisponible) » — en
        # silence, alors que c'est la panne n°1 (assistant absent, Accessibilité).
        vivant, autorise = core.console_helper_alive(), etat.E.WS["helper_trusted"]
        etat_console = (_LE("diag.console.actif") if vivant and autorise else
                _LE("diag.console.non_autorise") if vivant
                else _LE("diag.console.inactif"))
        vu = etat.E.WS["helper_seen"]
        # Sans ce cas, un assistant jamais vu affichait « il y a 1786000000.0s »
        # (soustraction sur un horodatage à zéro) — un chiffre absurde dans le
        # fichier même qui doit servir à diagnostiquer.
        depuis = (_LE("diag.console.il_y_a", s=round(time.time() - vu, 1))
                  if vu else _LE("diag.console.jamais_vu"))
        return (f"{_LE('diag.console.mode')} {etat_console}\n"
                f"{_LE('diag.console.comportement')}\n"
                f"{_LE('diag.console.assistant_vu')} "
                f"{_LE('diag.console.oui') if vivant else _LE('diag.console.non')}  ({depuis})\n"
                f"{_LE('diag.console.accessibilite')} "
                f"{_LE('diag.console.accordee') if autorise else _LE('diag.console.non_accordee')}\n"
                f"{_LE('diag.console.file', n=len(etat.E.WS['queue']))}")

    def _osc_recu():
        with core.OSC_IN["lock"]:
            if not core.OSC_IN["seen"]:
                return _LE("diag.osc_recu.rien")
            lignes = sorted(core.OSC_IN["seen"].items(), key=lambda kv: -kv[1]["n"])
            return "\n".join(f"{a:34s} n={e['n']:<6d} [{e['last']}]  ({e['types']})"
                             for a, e in lignes[:40])

    def _usb():
        r = wing_detect.scan()
        if isinstance(r, dict):
            return r.get("error", str(r))
        return "\n".join(
            f"{d.get('vid','?')}:{d.get('pid','?')}  {d.get('status','?'):10s} "
            f"{d.get('name', d.get('product',''))}" for d in r) or _LE("diag.usb.aucun")

    def _profils():
        return "\n".join(f"{p.name}  ({p.stat().st_size} o)"
                         for p in sorted(wm.PROFILE_DIR.glob("*.json")))

    def _queue_fin(chemin: Path, n: int):
        if not chemin.exists():
            return _LE("diag.fichier_absent", chemin=chemin)
        lignes = chemin.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lignes[-n:])

    parties = [
        "═" * 62,
        "  " + _LE("diag.entete.titre"),
        "  " + _LE("diag.entete.ligne1"),
        "  " + _LE("diag.entete.ligne2"),
        "═" * 62,
        section(_LE("diag.section.identite"), _identite),
        section(_LE("diag.section.etat"), _etat),
        section(_LE("diag.section.osc"), _osc),
        section(_LE("diag.section.console"), _console),
        section(_LE("diag.section.reglages"), lambda: json.dumps(etat.E.SETTINGS, indent=2)),
        section(_LE("diag.section.profils"), _profils),
        section(_LE("diag.section.usb"), _usb),
        section(_LE("diag.section.osc_recu"), _osc_recu),
        section(_LE("diag.section.journal_moteur"),
                lambda: _queue_fin(core.LOG_FILE, 300)),
        # L'assistant écrit son journal à côté du nôtre, dans le dossier de
        # données (cf. LOG_PATH dans wing_keyboard.py).
        section(_LE("diag.section.journal_clavier"),
                lambda: _queue_fin(wm.PROFILE_DIR.parent / "wing_keyboard.log", 150)),
    ]

    nom = f"wing-bridge-diagnostic-{datetime.datetime.now():%Y%m%d-%H%M}.txt"
    home = _diag_home()
    dest = (home / "Desktop" / nom) if home else (wm.PROFILE_DIR.parent / nom)
    dest.write_text("\n".join(parties) + "\n", encoding="utf-8")
    wm.own_like_parent(dest)
    core.log("journal.diag.ecrit", dest=dest)
    return dest


def install_crash_logging():
    """Écrit les exceptions non rattrapées DANS notre journal.

    On ne peut pas compter sur la sortie standard : vérifié, le binaire figé
    n'écrit rien dans le fichier de redirection du launcher, même
    avec PYTHONUNBUFFERED=1 et en lisant pendant l'exécution (donc ce n'est pas
    du tamponnage — cause exacte non identifiée). Sans ce filet, un plantage
    dans un thread de fond disparaîtrait sans laisser la moindre trace.
    """
    import traceback
    import wing_ui as core

    def _ecrire(cle_titre, exc_type, exc, tb, **p):
        try:
            texte = "".join(traceback.format_exception(exc_type, exc, tb))
        except Exception:
            texte = f"{exc_type}: {exc}"
        core.log(cle_titre, exc=f"{exc_type.__name__}: {exc}", **p)
        # Trace complète : dump brut, jamais traduit — destination toujours
        # anglaise (wing_server.log), donc texte anglais directement, sans clé.
        core._log_to_file("--- full trace ---\n" + texte.rstrip() + "\n---")

    def _hook(exc_type, exc, tb):
        _ecrire("journal.diag.crash", exc_type, exc, tb)

    def _hook_thread(args):
        # Un thread qui meurt en silence (USB, DMX, sonde…) est le pire cas :
        # l'app a l'air vivante alors qu'une de ses fonctions est morte.
        _ecrire("journal.diag.thread_mort", args.exc_type, args.exc_value,
                args.exc_traceback, nom=args.thread.name)
        # Auparavant, la ligne ci-dessus était TOUT ce qui se passait :
        # journalisé, jamais reflété dans l'interface. Posé ici,
        # à l'instant exact de la mort, pour que core.threads_morts() (lu
        # par /api/status) puisse le dire honnêtement. Ne se remet à vide
        # QUE par un redémarrage complet (`restart_self()`, os.execv) — un
        # thread réellement mort ne ressuscite pas tout seul.
        etat.E.THREAD_MORT[args.thread.name] = (
            f"{args.exc_type.__name__}: {args.exc_value}")

    sys.excepthook = _hook
    if hasattr(threading, "excepthook"):
        threading.excepthook = _hook_thread
