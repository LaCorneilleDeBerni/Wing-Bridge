"""Désinstallation de Wing Bridge — le plan (quoi supprimer, quoi garder) et
le ménage lui-même.

Sorti de `wing_handler.py` (audit du 25/09/2026, point D3 : un Handler qui
lit, valide et délègue). La route `/api/uninstall` ne fait plus que lire
`keep`/`dry_run`, appeler `plan()` et `residu()`, répondre, puis programmer
`executer()`. Le décideur reste UNIQUE : l'endpoint réel et le test de fumée
(`test_desinstallation`) passent tous deux par `plan()`.

⚠️ Règle non négociable : RIEN de purement interne à l'app ne survit, quel que
soit le choix — `__reference__.json`, `__autosave__.json`, `wing_hw_state.json`,
`settings.json`, le jeton d'API, l'état runtime. Trois choix seulement :
profils de mapping, journal, plugin grandMA3.
→ docs/ARCHITECTURE.md, section « Désinstallation ».
"""

import os
import shutil
import sys
import time
from pathlib import Path

import wing_ma3
import wing_mapper as wm


def _L(cle, **params):
    import wing_i18n
    return wing_i18n.L(cle, **params)


_PLUGIN_NOMS = ("wingbridge.lua", "wingbridge.xml",
                "wingloader.lua", "wingloader.xml")


def sous(dossier: Path, fichier: Path) -> bool:
    """`fichier` est-il quelque part sous `dossier` ?"""
    try:
        fichier.resolve().relative_to(dossier.resolve())
        return True
    except (ValueError, OSError):
        return False


def cibles_ma3():
    """Les fichiers laissés par le plugin dans grandMA3 : plugin, état, .bak.

    `_ma3_base()` et `MA3_ETAT_FICHIER` sont pris sur `wing_ma3` (pas recopiés)
    pour que le test de fumée puisse les rediriger vers un dossier jetable.
    """
    dossier = wing_ma3._ma3_base() / "gma3_library" / "datapools" / "plugins"
    fichier_etat = wing_ma3.MA3_ETAT_FICHIER
    # Préfixes des .bak à ramasser : wingbridge, wingloader, wingbridge_state.
    prefixes = {Path(n).stem for n in _PLUGIN_NOMS} | {fichier_etat.stem}

    cibles = [dossier / n for n in _PLUGIN_NOMS]
    cibles.append(fichier_etat)
    for d in (dossier, fichier_etat.parent):
        if d.is_dir():
            cibles += [p for p in sorted(d.glob("*.bak"))
                       if any(p.name.startswith(pre) for pre in prefixes)]

    vus, uniques = set(), []
    for p in cibles:
        if p not in vus:
            vus.add(p)
            uniques.append(p)
    return uniques


def dossier_local():
    """Sur Windows, le dossier `%LOCALAPPDATA%\\Wing Bridge` où l'assistant
    clavier écrit son journal — DISTINCT de `%APPDATA%\\Wing Bridge`
    (= `PROFILE_DIR.parent`, où va le reste). `None` ailleurs : sur macOS le
    journal clavier est déjà sous `PROFILE_DIR.parent`, rien à ajouter.

    Défini comme fonction du module pour que le test de fumée puisse le
    rediriger vers un dossier jetable, comme `wing_ma3._ma3_base`.
    """
    if not sys.platform.startswith("win"):
        return None
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / "Wing Bridge"


def plan(keep):
    """`(a_supprimer, a_garder)` — deux listes de `Path`. NE TOUCHE À RIEN.

    `keep` : dict `{"profiles": bool, "log": bool, "ma3_plugin": bool}`.
    """
    a_supprimer, a_garder = [], []

    # ── b. plugin grandMA3 ────────────────────────────────────────────────
    for p in cibles_ma3():
        if not p.exists():
            continue
        (a_garder if keep.get("ma3_plugin") else a_supprimer).append(p)

    # ── c. dossier de données de l'app ───────────────────────────────────
    data = wm.PROFILE_DIR.parent
    prof = wm.PROFILE_DIR

    if prof.is_dir():
        for p in sorted(prof.iterdir()):
            if p.is_dir():
                continue
            # __reference__.json, __autosave__.json, *.avant-renum… = interne
            interne = p.name.startswith("__") or p.suffix.lower() != ".json"
            if interne or not keep.get("profiles"):
                a_supprimer.append(p)
            else:
                a_garder.append(p)

    # Racine du dossier de données, et — sur Windows seulement — le dossier
    # `%LOCALAPPDATA%\\Wing Bridge` où l'assistant clavier écrit son journal
    # (`wing_keyboard.log`), qui n'est PAS sous `PROFILE_DIR.parent`. Sans ça il
    # survivrait à la désinstallation « tout supprimer ».
    racines = [data]
    local = dossier_local()
    if local is not None and not sous(data, local):
        racines.append(local)

    vus = set()
    for racine in racines:
        if not racine.is_dir():
            continue
        for p in sorted(racine.iterdir()):
            if p.is_dir() or p in vus:
                continue
            vus.add(p)
            if ".log" in p.name:                       # journaux de l'app
                (a_garder if keep.get("log") else a_supprimer).append(p)
            else:                                      # wing_hw_state.json,
                a_supprimer.append(p)                  # settings.json, .DS_Store…

    return a_supprimer, a_garder


def residu():
    """Ce que l'app ne peut PAS faire elle-même — à finir à la main.

    Adapté à la plateforme. ⚠️ Jamais de nom de script ici (règle
    `test_messages_actionnables`).
    """
    r = []
    if sys.platform == "darwin":
        r.append(_L("err.desinstall.accessibilite_mac"))
    elif sys.platform.startswith("win"):
        r.append(_L("err.desinstall.winusb_windows"))
    r.append(_L("err.desinstall.plugin_ma3"))
    if sys.platform == "darwin":
        r.append(_L("err.desinstall.corbeille_mac"))
    elif sys.platform.startswith("win"):
        r.append(_L("err.desinstall.corbeille_windows"))
    return r


# Le ménage réel — lancé par /api/uninstall dans un Timer, APRÈS la réponse.
def executer(a_supprimer, a_garder):
    """Supprime, puis `os._exit(0)` — atteint quoi qu'il arrive."""
    # try/finally : le commentaire promettait déjà « atteint quoi qu'il
    # arrive » — une exception avant les boucles (verrou du journal,
    # import) laissait pourtant le process debout, à moitié désinstallé.
    try:
        import wing_ui as core
        # ⚠️ `os._exit(0)` DOIT être atteint quoi qu'il arrive.
        # 🔑 On coupe l'écriture disque du journal AVANT toute suppression :
        # sinon un fil de fond qui journalise recrée `LOG_FILE.parent`
        # (`mkdir`) juste après le rmtree et laisse une coquille vide du
        # dossier de données. La console garde les lignes ci-dessous.
        import wing_reglages
        wing_reglages._arret_en_cours = True
        # Le journal s'écrit désormais sur un fil à part : un lot peut être
        # EN COURS d'écriture au moment où on lève le drapeau. Prendre son
        # verrou une fois garantit qu'il est terminé avant tout rmtree.
        with wing_reglages._log_file_lock:
            pass
        try:
            core.etat_poser(want_connected=False, mode="idle")
            core.arreter_usb()           # attend la lecture en vol
        except Exception as e:
            core.log("journal.desinstall.usb_imparfaite", err=e)
        try:
            core.stop_keyboard_helper()  # tue l'assistant clavier
        except Exception as e:
            core.log("journal.desinstall.kbd_imparfait", err=e)
        for p in a_supprimer:
            try:
                p.unlink(missing_ok=True)
            except Exception as e:
                core.log("journal.desinstall.fichier_ko", p=p, err=e)
        # Plus rien d'utile dans le dossier de données → on le retire en
        # entier ; sinon on ne laisse que les fichiers gardés. On applique le
        # même raisonnement au dossier %LOCALAPPDATA%\Wing Bridge de Windows,
        # qui vit à part (journal de l'assistant clavier).
        data = wm.PROFILE_DIR.parent
        dossiers = [data]
        local = dossier_local()
        if local is not None and not sous(data, local):
            dossiers.append(local)
        for d in dossiers:
            garde_dedans = any(sous(d, p) for p in a_garder)
            try:
                if garde_dedans:
                    # On garde le dossier (un journal/profil y survit) mais on
                    # retire le sous-dossier profiles/ s'il est devenu vide.
                    if d is data and wm.PROFILE_DIR.is_dir() \
                            and not any(wm.PROFILE_DIR.iterdir()):
                        wm.PROFILE_DIR.rmdir()
                    continue
                # Retrait complet, avec quelques essais : sous Windows un
                # fichier tout juste fermé (journal de l'assistant clavier
                # qu'on vient de tuer) peut rester « delete-pending » un
                # instant et faire échouer le rmdir de la coquille vide.
                for _ in range(5):
                    if not d.is_dir():
                        break
                    shutil.rmtree(d, ignore_errors=True)
                    if not d.exists():
                        break
                    time.sleep(0.1)
            except Exception as e:
                core.log("journal.desinstall.dossier_ko", d=d, err=e)
    finally:
        os._exit(0)
