#!/usr/bin/env python3
"""
wing_profils.py — gestion des profils : config sûre, sauvegarde auto, import
==============================================================================
Extrait de `wing_ui.py`. L'ÉTAT PARTAGÉ (profil, réglages, verrou, liaison USB…) se lit et s'écrit
via `etat.E.<champ>` (etat.py, audit du 25/09/2026, D1) — jamais via
`wing_ui` : ses anciens noms lèvent. `core.X` ne sert plus qu'aux FONCTIONS
et CONSTANTES que `wing_ui.py` réexporte.
Chemins lus via `core.X` (configuration, redirigés par les tests) :
`REFERENCE_FILE`, `AUTOSAVE_FILE`, `SEED_PROFILE`.

⚠️ `import wing_ui as core` est PARESSEUX — DANS chaque fonction qui s'en
sert, jamais en tête de fichier. Un import de `wing_ui` au niveau module
fermerait un cycle (`wing_ui` importe aussi ce module) : sous CPython nu ça
passe, mais le bootloader figé de PyInstaller ne coupe pas le cycle de la
même façon — vécu et corrigé sur `wing_diagnostic.py` : l'app frozen
refusait de démarrer. Un import paresseux,
résolu au premier appel réel bien après le chargement des deux modules, est
sûr dans les deux cas.
"""

import etat
import json
import os
import time
from pathlib import Path

import wing_mapper as wm


def _L(cle, **params):
    import wing_i18n
    return wing_i18n.L(cle, **params)


def _profil_de_secours(nom_fichier: str) -> bool:
    """Ce profil est-il le filet de secours livré ? (donc non supprimable)

    Comparaison SANS accent ni casse, singulier ou pluriel : c'est un nom écrit
    à la main, il ne faut pas qu'une lettre décide qu'un filet n'en est plus un.
    """
    import unicodedata
    base = unicodedata.normalize("NFD", Path(nom_fichier).stem.lower())
    base = "".join(c for c in base if not unicodedata.combining(c))
    return base.replace("_", "-") in ("defaut-securite", "defauts-securite")


def _profile_snapshot():
    import wing_ui as core
    with etat.E.LOCK:
        return json.loads(json.dumps(etat.E.PROFILE)), etat.E.STATE["dirty"]


def autosave_loop():
    """Écrit le fichier de récupération quand le profil a changé depuis le
    dernier enregistrement. Thread de fond, jamais bloquant pour l'USB."""
    import datetime
    import wing_ui as core
    dernier = None
    while True:
        time.sleep(core.AUTOSAVE_EVERY_S)
        try:
            snap, dirty = _profile_snapshot()
            if not dirty:
                # Plus rien en attente : le fichier de récupération n'a plus
                # d'objet (l'utilisateur a enregistré, ou rien n'a bougé).
                # ⚠️ SAUF si une récupération est justement proposée : au
                # démarrage, dirty vaut False alors que le fichier contient le
                # travail à récupérer. Le supprimer ici l'effacerait 5 s après
                # le lancement, sous le nez de l'utilisateur.
                if etat.E.RECOVERY["available"] is None and core.AUTOSAVE_FILE.exists():
                    core.AUTOSAVE_FILE.unlink(missing_ok=True)
                dernier = None
                continue
            if snap == dernier:
                continue                     # rien de neuf, pas d'écriture
            data = {"saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
                    "profile": snap}
            tmp = core.AUTOSAVE_FILE.with_suffix(".part")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            os.replace(tmp, core.AUTOSAVE_FILE)   # écriture atomique
            wm.own_like_parent(core.AUTOSAVE_FILE)
            dernier = snap
        except Exception:
            pass          # une sauvegarde de confort ne doit jamais tuer l'app


def detect_recovery():
    """Au démarrage : un fichier de récupération présent = sortie non propre."""
    import wing_ui as core
    try:
        if not core.AUTOSAVE_FILE.exists():
            return
        d = json.load(open(core.AUTOSAVE_FILE, encoding="utf-8"))
        p = d.get("profile") or {}
        etat.E.RECOVERY["available"] = {"when": d.get("saved_at"),
                                      "name": p.get("name", "?")}
        core.log("journal.profil.recovery_trouvee",
                 nom=p.get('name', '?'), quand=d.get('saved_at', '?'))
    except Exception as e:
        core.log("journal.profil.recovery_illisible", err=e)
        core.AUTOSAVE_FILE.unlink(missing_ok=True)


def save_reference(profile: dict):
    """Écrit la config sûre : snapshot verrouillé + horodatage."""
    import datetime
    import wing_i18n
    import wing_ui as core
    wm.PROFILE_DIR.mkdir(exist_ok=True)
    data = json.loads(json.dumps(profile))   # copie profonde
    # Nom affiché dans la liste des profils (ui/profils.js : `p.name` est
    # rendu tel quel) — résolu dans la langue courante au moment de l'écrire,
    # comme les autres textes construits côté serveur (voir docs/I18N.md).
    data["name"]     = wing_i18n.L("ui.profils.config_sure_nom")
    data["locked"]   = True
    data["saved_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    # Écriture ATOMIQUE (temp-file + os.replace) — même motif que
    # `autosave_loop()` un peu plus haut dans ce fichier : une coupure en
    # plein milieu de l'écriture DIRECTE laissait un `__reference__.json`
    # tronqué à la place du filet de secours — le pire moment pour le perdre.
    tmp = core.REFERENCE_FILE.with_suffix(".part")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, core.REFERENCE_FILE)
    wm.own_like_parent(core.REFERENCE_FILE)


def importer_profil(nom_brut: str, contenu) -> dict:
    """Range un profil venu d'ailleurs dans le dossier des profils.

    🔑 `/api/profile/load` ne lit QUE dans le dossier des profils :
    un profil reçu d'un collègue devait être déplacé À LA MAIN dans ~/Library,
    dossier caché par défaut dans le Finder.

    ⚠️ Le nom vient de l'EXTÉRIEUR (navigateur ou disque). Les trois refus
    ci-dessous comptent autant que l'import lui-même.
    """
    import wing_ui as core
    if not isinstance(contenu, dict):
        return {"ok": False, "raison": _L("err.profil_pas_un_profil")}
    # Un profil doit ressembler à un profil : sinon la boucle USB plante plus
    # tard, loin de la cause (même famille que le contrôle test_forme_profil).
    if not any(k in contenu for k in ("buttons", "faders", "console_keys")):
        return {"ok": False, "raison": _L("err.profil_json_pas_wb")}
    base = wm.slugify(Path(nom_brut or "profil-importé").stem) or "profil-importe"
    cible = wm.PROFILE_DIR / f"{base}.json"
    if cible.name in (core.REFERENCE_FILE.name, core.AUTOSAVE_FILE.name):
        return {"ok": False, "raison": _L("err.nom_reserve")}
    n = 2
    while cible.exists():               # ne JAMAIS écraser un profil existant
        cible = wm.PROFILE_DIR / f"{base}-{n}.json"
        n += 1
    try:
        prof = wm.migrate_profile(contenu)
        prof.setdefault("name", cible.stem)
        wm.save_profile(prof, cible)
    except Exception as e:
        return {"ok": False, "raison": _L("err.import_impossible", err=e)}
    core.log("journal.profil.importe", nom=prof['name'], fichier=cible.name)
    return {"ok": True, "file": cible.name, "name": prof["name"]}


def charger_favori():
    """Charge le profil marqué favori, s'il y en a un. Ne lève jamais."""
    import wing_ui as core
    nom = (etat.E.SETTINGS.get("profil_favori") or "").strip()
    if not nom:
        # ⭐ Voulu : « le profil défaut doit être chargé par défaut s'il n'y a
        # pas de profil favori sélectionné ».
        #
        # Sans favori, l'app démarrait sur les défauts d'usine en mémoire —
        # corrects, mais ce n'est pas la « config sûre » que l'utilisateur a
        # figée comme sa référence. On charge donc celle-ci quand elle existe.
        if core.REFERENCE_FILE.exists():
            try:
                ref = wm.load_profile(core.REFERENCE_FILE)
            except Exception as e:
                core.log("journal.profil.config_sure_ko", err=e)
                return
            with etat.E.LOCK:
                etat.E.PROFILE.clear()
                etat.E.PROFILE.update(ref)
            core.reset_enc_attr()
            core.log("journal.profil.pas_favori_config_sure")
        else:
            core.log("journal.profil.pas_favori_pas_config")
        return
    chemin = wm.PROFILE_DIR / nom
    if not chemin.exists():
        core.log("journal.profil.favori_introuvable", nom=nom)
        core.reglage_poser(profil_favori="")
        core.save_settings()
        return
    try:
        prof = wm.load_profile(chemin)
    except Exception as e:
        core.log("journal.profil.favori_illisible", nom=nom, err=e)
        return
    with etat.E.LOCK:
        etat.E.PROFILE.clear()
        etat.E.PROFILE.update(prof)
        etat.E.STATE["profile_name"] = chemin.stem
    core.reset_enc_attr()
    core.log("journal.profil.favori_charge", nom=chemin.stem)


def ensure_reference():
    """Crée la config sûre au 1er lancement si elle n'existe pas encore."""
    import wing_ui as core
    if core.REFERENCE_FILE.exists():
        return
    src, seed = None, wm.PROFILE_DIR / core.SEED_PROFILE
    if seed.exists():
        try:
            src = wm.load_profile(seed)
        except Exception:
            src = None
    if src is None:
        src = wm.new_profile_from_defaults()
    save_reference(src)


def reference_info() -> dict:
    """{exists, when} pour l'UI (badge « dernière config sûre »)."""
    import wing_ui as core
    if not core.REFERENCE_FILE.exists():
        return {"exists": False, "when": None}
    try:
        d = json.load(open(core.REFERENCE_FILE, encoding="utf-8"))
        return {"exists": True, "when": d.get("saved_at")}
    except Exception:
        return {"exists": True, "when": None}


# Confinement d'un nom de profil au dossier des profils — sorti de
# wing_handler.py (D3). Utilisé par /api/profile/load.
def chemin_profil(fname):
    """Chemin d'un profil DANS le dossier des profils, ou None.

    Refuse : non-texte, chemin absolu, `..`, séparateur, et tout ce qui,
    une fois résolu (liens compris), sort de `wm.PROFILE_DIR`."""
    if not isinstance(fname, str) or not fname or "/" in fname \
            or "\\" in fname or fname in (".", ".."):
        return None
    racine = wm.PROFILE_DIR.resolve()
    chemin = (wm.PROFILE_DIR / fname).resolve()
    return chemin if chemin.parent == racine else None
