#!/usr/bin/env python3
"""
wing_ma3.py — la sonde MA3 : état, attributs, mots-clés, machine virtuelle
==============================================================================
Extrait de `wing_ui.py`. L'ÉTAT PARTAGÉ se lit et s'écrit via
`etat.E.<champ>` (etat.py, audit du 25/09/2026, D1) — jamais via `wing_ui`,
dont les anciens noms lèvent. `etat.E.MA3_CHECK` = cache de `ma3_reachable()`, invalidé par
`apply_osc_target()`. Constantes lues via `core.X` : `FADER_KEYWORDS`,
`VERBES_CIBLE`, `EXEC_FUNCS`.

⚠️⚠️ CAS PARTICULIER — `ma3_etat()` : contrairement au reste de ce fichier,
TOUS les appels internes à `ma3_etat()` depuis une AUTRE fonction de ce même
module (`ma3_executor`, `_resume_sonde`, `osc_config_ma3`, `ma3_encodeurs`)
passent par `core.ma3_etat()`, jamais par un appel nu, même si `ma3_etat`
est défini juste au-dessus dans CE fichier. Raison : `smoke_test.py`
monkeypatche `ma3_etat` sur le module `wing_ui` (`wv.ma3_etat = lambda:
...`, une douzaine de fois, sections 18 à 21) pour isoler ses tests sans
sonde réelle. Un appel nu se résoudrait dans l'espace de noms DE CE FICHIER,
où le monkeypatch n'a aucun effet — le test croirait patcher la sonde et
continuerait de lire le vrai fichier `wingbridge_state.json`. `ma3_etat`
elle-même n'a pas ce problème : elle ne s'appelle pas elle-même.

⚠️ `import wing_ui as core` est PARESSEUX — DANS chaque fonction qui s'en
sert, jamais en tête de fichier (cycle d'import sûr sous CPython nu, mais
pas sous le bootloader figé de PyInstaller). Et parce que `wing_ui.py` est
le POINT D'ENTRÉE du programme
(`__name__ == "__main__"`), `wing_ui.py` s'auto-enregistre dans
`sys.modules["wing_ui"]` en tête de fichier, AVANT d'importer ce module —
sinon `import wing_ui as core` fait ici réimporterait le fichier depuis
zéro sous un second nom, un module FANTÔME jamais touché par le vrai
process (bug réel, invisible au smoke test, trouvé en cliquant dans l'app
réelle).
"""

import etat
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import wing_bridge as wb


def _L(cle, **params):
    import wing_i18n
    return wing_i18n.L(cle, **params)
import wing_mapper as wm

# ⚠️ Sans ça, chaque appel `netstat` (console) depuis le build figé `--noconsole`
# FAIT CLIGNOTER une fenêtre terminal (un `conhost` par appel). Comme
# `ma3_reachable()` sonde le port dès que MA3 est détecté, on obtenait « une
# fenêtre qui tourne en boucle quand on ouvre MA3 ».
# `CREATE_NO_WINDOW` n'existe que sous Windows ; 0 ailleurs (sans effet).
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ── Santé OSC → MA3 ───────────────────────────────────────────────────────────
# `_MA3_CHECK` (cache) est défini dans wing_ui.py et invalidé par
# `apply_osc_target()`. Voir l'en-tête « Santé OSC » de wing_ui.py : UDP sans
# accusé de réception ; « MA3 lancé » ≠ « MA3 écoute l'OSC » — on teste les
# deux.


def _port_ecoute(port: int) -> bool:
    """Quelque chose écoute-t-il en UDP sur ce port, localement ?

    Windows : `netstat` — format « UDP  0.0.0.0:8000  *:* », proto en
    MAJUSCULES, adresse en colonne 1, séparateur « : ». Vérifié sur
    Windows 11 (locale FR) : MA3 écoute bien `UDP 0.0.0.0:8000`.

    macOS : `lsof -nP -iUDP:<port>`, PAS `netstat`.
    🪤 RÉGRESSION macOS 27 (« Tahoe » et suivants), trouvée en test réel avec
    l'auteur le 17/09/2026 : `netstat -an -p udp` renvoie une sortie VIDE
    quand lancé en sous-processus par Python (venv ET Python système essayés,
    même résultat) — SANS exception, SANS code de retour non nul. L'ancien
    code prenait donc ce vide pour « personne n'écoute » : `ma3_reachable()`
    répondait « muet » alors que grandMA3 écoutait bel et bien sur le port
    (confirmé au même instant par `lsof -nP -iUDP:8000`, qui voyait la ligne
    à CHAQUE essai, 5/5). Cassait la détection OSC de toute l'app sur cette
    version de macOS, pas seulement ce contrôle-ci.
    L'argument d'origine (« netstat 2x plus rapide, 26 ms contre 54 ms ») ne
    tient plus : un outil deux fois plus rapide qui ne renvoie rien n'est pas
    plus rapide, il est faux. `ma3_sockets()` utilisait déjà `lsof` sur macOS
    pour une raison voisine — même outil ici, pour cohérence.
    ⚠️ Cause non tranchée (permission « Réseau local » macOS refusée à ce
    binaire Python precis, ou restriction plus large de `netstat` sur cette
    version) : PAS D'HYPOTHÈSE PRÉSENTÉE COMME UN FAIT ici, seul le
    remplacement par `lsof` est établi comme correctif qui marche dans les
    deux sens (testé : voit une écoute réelle, ne voit rien sur un port libre
    — code de retour 1, stdout vide).
    """
    try:
        if sys.platform.startswith("win"):
            # `errors="replace"` OBLIGATOIRE : `netstat` sort dans la codepage
            # OEM (locale FR : octets hors cp1252, ex. 0x90), et `text=True`
            # planterait au décodage — l'exception serait avalée et le port
            # signalé « muet » à tort (bug vu au test réel). On ne
            # matche que de l'ASCII (« UDP », « :8000 »), le remplacement est sans risque.
            r = subprocess.run(["netstat", "-an", "-p", "UDP"],
                               capture_output=True, text=True,
                               errors="replace", timeout=2.0,
                               creationflags=_NO_WINDOW)   # pas de fenêtre qui clignote
            cible = f":{port}"
            for ligne in r.stdout.splitlines():
                champs = ligne.split()
                if len(champs) >= 2 and champs[0].upper() == "UDP" \
                        and champs[1].endswith(cible):
                    return True
            return False
        r = subprocess.run(["lsof", "-nP", f"-iUDP:{port}"],
                           capture_output=True, text=True, timeout=2.0)
        # lsof rend le code 1 et un stdout vide quand rien n'écoute ; sinon,
        # la ligne d'en-tête ET au moins une ligne de résultat.
        return len(r.stdout.splitlines()) > 1
    except Exception:
        pass
    return False


_VM_CHECK = {"t": 0.0, "on": False}


# ── État de MA3, lu via le plugin Lua ────────────────────────────────────────
#
# Le plugin `wingbridge.lua` (dossier plugin_ma3/) tourne DANS MA3 et écrit son
# état dans un fichier JSON, une fois par seconde. C'est le seul canal
# disponible : l'OSC est unidirectionnel ici, et le Lua de MA3 n'a pas de
# sockets. Voir docs/GRANDMA3_SYNC.md pour le détail du canal et de la sonde.
#
# Ce que ça débloque : LED reflétant l'état réel, conscience de la page
# courante, rattrapage de fader, avertissement de désaccord sur la fonction
# d'un fader.
#
# ⚠️ Le plugin est une étape d'installation REQUISE (retour LED, rattrapage
# des faders, conscience de page). Mais son absence à l'exécution ne doit
# JAMAIS planter : repli silencieux, l'app pilote MA3 à l'aveugle — dégradé,
# pas cassé.

def _ma3_base() -> Path:
    """Dossier racine grandMA3 (contient gma3_library ET gma3_<version>).

    macOS : ~/MALightingTechnology.
    Windows : %PROGRAMDATA%\\MALightingTechnology — ProgramData, PAS le dossier
    utilisateur. Vérifié sur MA3 2.4.2 : GetPath(Library) rend
    C:/ProgramData/MALightingTechnology/gma3_library, et c'est là que le plugin
    écrit wingbridge_state.json. Avant ce correctif, l'app lisait la sonde sous
    ~/… (inexistant sous Windows) → sonde jamais vue même plugin lancé.
    """
    if sys.platform == "win32":
        return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) \
            / "MALightingTechnology"
    return Path.home() / "MALightingTechnology"


MA3_ETAT_FICHIER = _ma3_base() / "gma3_library" / "wingbridge_state.json"
MA3_ETAT_PEREMPTION_S = 5.0     # au-delà, la sonde est considérée arrêtée

# 🕒 TTL du cache de relecture, ramené de 0,2 s à 0,05 s.
# Ce cache existe pour éviter de relire le fichier trop souvent (pickup à ~8 Hz,
# /api/status plus souvent encore). Mais mesuré sous Windows : la lecture coûte
# ~0,5 ms (médiane, max 11 ms) — la protection n'a donc pas besoin d'un TTL long.
# Or la sonde Lua écrit toutes les ~0,22 s : un TTL de 0,2 s EMPILAIT un quantum
# de ~0,2 s de PÉREMPTION par-dessus le cycle d'écriture (jusqu'à ~0,42 s de
# retard end-to-end selon la phase — voir docs/GRANDMA3_SYNC.md, section latence).
# 0,05 s = ~20 relectures/s au pire : négligeable en coût (≈10 ms/s), tout en
# restant bien SOUS la période d'écriture (~0,22 s) — on n'empile plus un quantum
# complet. ⚠️ Relire plus souvent augmente la contention de lecture qui fait
# rater des écritures à la sonde sous Windows (rename Windows échoue si un lecteur
# tient le fichier) ; 0,05 s reste très loin du régime où cet effet devient
# sensible (mesuré : sensible seulement vers ~200 lectures/s).
MA3_ETAT_CACHE_S = 0.05

# Tolérance à un raté de lecture TRANSITOIRE (Windows) : la sonde réécrit
# `wingbridge_state.json` de façon NON atomique (os.remove + os.rename, pas de
# remplacement atomique côté MA3) — le fichier disparaît ~0,77 ms à chaque
# écriture (~4,5 fois/s). On resert le dernier bon état pendant une courte
# grâce (1,5 s ≈ 7 cycles d'écriture) ; au-delà, état vide : un fichier
# durablement absent est une vraie panne de sonde, à ne pas masquer.
# → docs/GRANDMA3_SYNC.md, § contention `os.rename`.
MA3_ETAT_GRACE_S = 1.5

# `last_good`/`last_good_t` : dernier état `actif:True` lu, pour le resservir sur
# un raté transitoire (cf. MA3_ETAT_GRACE_S). Distinct de `data` (le cache court
# de relecture, qui peut lui contenir un état d'erreur).
_MA3_ETAT = {"t": 0.0, "data": None, "erreur": "",
             "last_good": None, "last_good_t": 0.0}

# L'âge « sonde silencieuse depuis N s » part du plus RÉCENT de deux repères :
# le fichier, ou `_MA3_ALIVE_DEPUIS` (instant où MA3 est passé de « fermé » à
# « lancé », vu par `ma3_reachable()`). Sinon, après une relance de MA3, le
# compteur repartait de la date d'un fichier d'une session passée (parfois
# des heures).
_MA3_ALIVE_DEPUIS = {"t": None, "etait_alive": False}

# `masters_note` (et consorts) : notes d'échec que la sonde publie quand une
# lecture optionnelle rate. Recopiées dans l'état mais affichées nulle part —
# on les JOURNALISE, une fois par message distinct (ma3_etat tourne ~20×/s, un
# log à chaque tour noierait le journal). Se vide au redémarrage du process,
# comme le reste — suffisant pour un signal de diagnostic.
_MA3_NOTES_VUES: set = set()


def ma3_etat() -> dict:
    """Dernier état publié par la sonde MA3. Jamais d'exception.

    Renvoie toujours un dict avec au minimum `actif` :
      actif=False  → pas de sonde (fichier absent, périmé ou illisible)
      actif=True   → `page` et `executors` exploitables
    """
    now = time.time()
    # Cache court (MA3_ETAT_CACHE_S) : borne le nombre de relectures du fichier
    # sans empiler un quantum de péremption par-dessus le cycle d'écriture Lua.
    if now - _MA3_ETAT["t"] < MA3_ETAT_CACHE_S and _MA3_ETAT["data"] is not None:
        return _MA3_ETAT["data"]
    _MA3_ETAT["t"] = now

    import wing_ui as core
    reach = core.ma3_reachable()
    # Cible distante (`None`, indéterminable en UDP) : on ne peut pas savoir
    # si MA3 vient de démarrer, donc on la traite comme « allumée » — c'est
    # le comportement d'avant ce correctif, qui reste correct dans ce cas.
    alive = reach != "off"
    if alive and not _MA3_ALIVE_DEPUIS["etait_alive"]:
        _MA3_ALIVE_DEPUIS["t"] = now      # MA3 (re)démarre : on recompte à 0
    _MA3_ALIVE_DEPUIS["etait_alive"] = alive

    def _stale_ou(base):
        """Sur un raté de lecture TRANSITOIRE (trou d'écriture de la sonde,
        Windows — cf. MA3_ETAT_GRACE_S), resert le dernier bon état si assez
        récent, marqué `stale:True` (info, pas erreur). Sinon `base` tel quel :
        c'est une vraie panne de sonde (durablement absente). Met en cache le
        résultat comme d'habitude."""
        lg = _MA3_ETAT["last_good"]
        if lg is not None and now - _MA3_ETAT["last_good_t"] < MA3_ETAT_GRACE_S:
            stale = dict(lg, stale=True)
            _MA3_ETAT["data"] = stale
            return stale
        _MA3_ETAT["data"] = base
        return base

    base = {"actif": False, "page": None, "executors": [],
            "version": None, "age": None, "erreur": ""}
    try:
        mtime = MA3_ETAT_FICHIER.stat().st_mtime
    except Exception:
        base["erreur"] = "aucune sonde (plugin MA3 non installé ou arrêté)"
        return _stale_ou(base)

    reference = max(mtime, _MA3_ALIVE_DEPUIS["t"] or 0)
    age = now - reference
    base["age"] = round(age, 1)
    if age > MA3_ETAT_PEREMPTION_S:
        if reach == "off":
            base["erreur"] = "MA3 n'est pas lancé — aucune sonde possible"
        else:
            # Message DIRECTIF, pas interrogatif : la sonde ne survit pas à un
            # redémarrage de MA3 (`_G` et le Timer meurent avec le process) et
            # MA3 n'expose aucun démarrage automatique de plugin au chargement
            # du show (vérifié dans le manuel — voir docs/GRANDMA3_SYNC.md). Le
            # geste : relancer le plugin (le numéro de slot n'est pas mentionné,
            # il varie selon l'installation ; le bouton « Relancer » de l'app
            # vise le nom, pas le numéro).
            base["erreur"] = (f"Sonde MA3 arrêtée : relance le plugin dans "
                              f"grandMA3 (silence depuis {age:.0f} s).")
        _MA3_ETAT["data"] = base
        return base

    try:
        d = json.loads(MA3_ETAT_FICHIER.read_text(encoding="utf-8"))
    except Exception as e:
        # Arrive quand on lit pendant la réécriture de la sonde : sous Windows
        # elle n'est PAS atomique (os.remove + os.rename), donc `read_text` peut
        # lever une violation de partage, ou `json.loads` tomber sur un fichier
        # à moitié écrit. Trou transitoire (~0,77 ms) → on resert le dernier bon
        # état (cf. _stale_ou). Si le fichier reste illisible au-delà de la
        # fenêtre de grâce, on le DIT au lieu de faire semblant.
        base["erreur"] = f"fichier d'état illisible : {e}"
        return _stale_ou(base)

    # ⚠️ Tout champ AJOUTÉ à la sonde doit être recopié ICI, sinon il n'atteint
    # jamais l'app. Oublié pour `raccourcis` : la sonde publiait
    # bien ses 157 entrées, et l'interface répondait « la sonde ne remonte pas
    # les raccourcis ». Une passerelle muette est indiscernable d'une sonde
    # absente.
    base.update(actif=True,
                version=d.get("version"),
                page=d.get("page"),
                executors=d.get("executors") or [],
                raccourcis=d.get("raccourcis") or [],
                raccourcis_via=d.get("raccourcis_via"),
                raccourcis_note=d.get("raccourcis_note"),
                # ⚠️ Oublié une PREMIÈRE fois pour `raccourcis`, puis une
                # SECONDE pour `encodeurs` — deux heures après avoir écrit
                # l'avertissement ci-dessus. Si tu ajoutes un champ à la
                # sonde, il ne suffit pas de le publier : il faut le recopier
                # ICI, sinon il n'atteint jamais l'app.
                encodeurs=d.get("encodeurs"),
                encodeurs_note=d.get("encodeurs_note"),
                osc_config=d.get("osc"),
                osc_config_note=d.get("osc_note"),
                # Masters (GrandMaster, Speed, Selected) — voir ma3_master().
                # Structure séparée des executors, ne casse pas
                # le format existant (docs/GRANDMA3_SYNC.md).
                masters=d.get("masters"),
                masters_note=d.get("masters_note"),
                erreurs_sonde=d.get("erreurs"),
                duree_ms=d.get("duree_ms"))

    # Notes d'échec des lectures optionnelles : journalisées une fois chacune.
    for cle in ("masters_note", "osc_note", "encodeurs_note", "raccourcis_note"):
        note = d.get(cle)
        if note and note not in _MA3_NOTES_VUES:
            _MA3_NOTES_VUES.add(note)
            core.log("journal.ma3.sonde_note", cle=cle, note=note)

    # Lecture réussie et exploitable : c'est le « dernier bon état » qu'on
    # resservira sur un trou transitoire (cf. _stale_ou / MA3_ETAT_GRACE_S).
    _MA3_ETAT["last_good"] = base
    _MA3_ETAT["last_good_t"] = now
    _MA3_ETAT["data"] = base
    return base


def ma3_executor(no: int):
    """L'executor `no` tel que MA3 le voit, ou None si la sonde ne l'a pas."""
    import wing_ui as core
    for e in core.ma3_etat().get("executors", []):
        if e.get("no") == no:
            return e
    return None


def ma3_master(pool: str, no: int):
    """Valeur 0..100 d'un master individuel (GrandMaster, Speed, Selected),
    ou None si la sonde ne l'a pas.

    `pool` : "grand" (GrandMaster, un seul, `no=1`), "speed" (Speed Masters,
    `no` = 1..15), "selected" (masters de la séquence sélectionnée, `no` =
    1..11 — 1=Master, 2=XFade… voir MASTERS_SELECTION dans wing_bridge.py).
    Établi par sonde réelle — voir docs/GRANDMA3_SYNC.md.
    """
    import wing_ui as core
    masters = core.ma3_etat().get("masters") or {}
    valeur = (masters.get(pool) or {}).get(str(no))
    return float(valeur) if valeur is not None else None


def _resume_sonde() -> dict:
    """Résumé compact de la sonde MA3, pour le panneau de santé."""
    import wing_ui as core
    e = core.ma3_etat()
    page = e.get("page") or {}
    return {"actif": e["actif"],
            # Fichiers du plugin posés sur le disque MA3 : distingue
            # « installé mais arrêté » de « pas installé » (bridge.js /
            # parametres.js — les 4 états de la sonde).
            "present": plugin_present(),
            "executors": len(e.get("executors") or []),
            "page": page.get("nom") or page.get("addr"),
            "duree_ms": e.get("duree_ms"),
            # Compteur d'erreurs INTERNE de la sonde (pcall ratés côté Lua) —
            # distinct de `erreur` (le message d'état de CE côté-ci). Un
            # compteur qui monte en silence est exactement ce que ce projet
            # veut voir : la pastille santé l'affiche (bridge.js).
            "erreurs": e.get("erreurs_sonde"),
            # `stale` : True quand on resert le dernier bon état pendant un trou
            # d'écriture transitoire de la sonde (Windows, cf. ma3_etat). Une
            # info de diagnostic, PAS une erreur — le panneau santé peut la
            # montrer sans crier à la panne.
            "stale": bool(e.get("stale")),
            "erreur": e.get("erreur", "")}


# ── Installation automatique du plugin dans grandMA3 ─────────────────────────
#
# Étape de mise en route, au même titre que le firmware. Copie les 4 fichiers de
# PRODUCTION (jamais verif_encodeur.lua, banc de test) dans
# <base MA3>/gma3_library/datapools/plugins/, puis envoie en OSC la séquence
# d'import + SaveShow, attend ~3 s et vérifie que la sonde répond.
#
# Tout chemin d'échec renvoie {"ok": False, "raison": <message ACTIONNABLE>} :
# l'UI bascule alors sur la procédure manuelle (le <details> de la carte
# grandMA3). Jamais d'exception qui remonte.
_PLUGIN_PROD = ("wingbridge.lua", "wingbridge.xml",
                "wingloader.lua", "wingloader.xml")

# Bornes du réglage SETTINGS["plugin_slot"] (wing_ui.py). PRATIQUES, pas
# documentées par MA3 : le manuel installé (keyword_plugin.html, plugins.html)
# ne donne aucun plafond numérique du pool Plugins — ne pas présenter 9999
# comme une limite MA3, seulement comme un garde-fou de saisie.
PLUGIN_SLOT_MIN, PLUGIN_SLOT_MAX, PLUGIN_SLOT_DEFAUT = 1, 9999, 3


def _plugin_osc(slot: int) -> tuple:
    """Séquence OSC d'import, pour le SLOT donné du pool Plugins de MA3.

    Slot en dur à 3 jusqu'ici ; devenu un paramètre parce qu'OSC est à sens
    unique — l'app ne peut pas lire quels slots sont déjà occupés avant
    d'importer, donc pas de détection fiable d'une collision. Un slot déjà
    pris ouvre dans MA3 un dialogue Overwrite/Merge/Cancel qui bloque l'import
    en silence (voir err.ma3.sonde_muette_install et docs/GRANDMA3_SYNC.md).
    """
    return (f'Import Plugin Library "wingloader.xml" At {slot}',
            f'Set Plugin {slot}.1 Property "Installed" "Yes"',
            f'Plugin {slot}',
            'SaveShow')

# Fichiers .lua qui doivent être posés sur le disque pour que « Plugin 3 »
# charge quelque chose. On teste les DEUX .lua (amorce + sonde) : les .xml
# décrivent l'entrée du pool, mais c'est le code Lua qui manque quand un show
# a été importé sans copier les fichiers sur cette machine.
_PLUGIN_MARQUEURS = ("wingloader.lua", "wingbridge.lua")


def plugin_present() -> bool:
    """Les fichiers du plugin sont-ils posés dans le pool de grandMA3 ?

    Vrai si `wingloader.lua` ET `wingbridge.lua` existent dans
    `<base MA3>/gma3_library/datapools/plugins/`. Test de FICHIERS seulement —
    ne dit rien sur le fait que la sonde TOURNE (ça, c'est `ma3_etat()["actif"]`).
    Les deux ensemble départagent quatre états : sonde active / installée mais
    arrêtée / pas installée / MA3 éteint. Jamais d'exception.
    """
    try:
        d = _ma3_base() / "gma3_library" / "datapools" / "plugins"
        return all((d / n).is_file() for n in _PLUGIN_MARQUEURS)
    except Exception:
        return False


# Relance PAR NOM (« WingLoader »), pas par numéro de slot (variable d'une
# installation à l'autre) : `Plugin ["Plugin_Name" or Plugin_Number]`, manuel
# MA3 2.5, keyword_plugin.html. WingLoader relit et exécute wingbridge.lua.
#
# ⚠️ `Plugin "WingLoader"` est une BASCULE : un envoi unique ARRÊTE une sonde
# qui tournait déjà (vérifié sur grandMA3 2.5). `relancer_plugin()` renvoie
# donc jusqu'à deux fois, en s'appuyant sur le SEUL témoin fiable : le compteur
# `tours` qui AVANCE (`_sonde_avance`). La fraîcheur du fichier ne prouve rien
# (un fichier abandonné reste « frais » 5 s, MA3_ETAT_PEREMPTION_S).
_PLUGIN_RELANCE_CMD = 'Plugin "WingLoader"'


def _sonde_tours():
    """Compteur de relevés publié par la sonde (`tours`), ou None si illisible.

    C'est le seul témoin fiable qu'elle TOURNE : à l'arrêt, le fichier d'état
    reste « frais » cinq secondes (MA3_ETAT_PEREMPTION_S) — le lire ne dit donc
    rien, il faut voir le compteur AVANCER.
    """
    try:
        d = json.loads(MA3_ETAT_FICHIER.read_text(encoding="utf-8"))
        t = d.get("tours")
        return int(t) if isinstance(t, (int, float)) else None
    except Exception:
        return None


def _sonde_avance(fenetre: float = 2.0) -> bool:
    """La sonde progresse-t-elle sur `fenetre` secondes ? (compteur `tours`)."""
    t0 = _sonde_tours()
    time.sleep(fenetre)
    t1 = _sonde_tours()
    return t0 is not None and t1 is not None and t1 > t0


def relancer_plugin() -> dict:
    """Garantit que la sonde DÉJÀ installée TOURNE — sans re-copie ni ré-import,
    en exécutant l'amorce par son NOM (`Plugin "WingLoader"`). Jamais d'exception.

    ⚠️ `Plugin "WingLoader"` est une bascule marche/arrêt (cf. commentaire au-
    dessus). On envoie, on vérifie que le compteur `tours` AVANCE, et sinon on
    renvoie pour rebasculer sur marche. Deux essais suffisent : chaque envoi
    inverse l'état, donc dès qu'on renvoie tant que ça n'avance pas, le second
    envoi ramène forcément sur « marche ».

    Retour : {"ok": True, "message": …} ou {"ok": False, "raison": <actionnable>}.
    """
    import wing_ui as core

    reach = ma3_reachable()
    if reach not in ("ok", "muet"):
        return {"ok": False, "raison": _L("err.ma3.injoignable_relance")}

    for essai in (1, 2):
        try:
            etat.E.OSC.send_message("/cmd", _PLUGIN_RELANCE_CMD)
        except Exception as e:
            return {"ok": False, "raison": _L("err.ma3.osc_ko_relance", err=e)}
        core.log("journal.ma3.plugin_relance", cmd=_PLUGIN_RELANCE_CMD, essai=essai)

        time.sleep(1.5)                   # laisse le Timer redémarrer
        _MA3_ETAT["t"] = 0.0
        _MA3_ETAT["data"] = None          # force une relecture fraîche du fichier
        if _sonde_avance():
            core.log("journal.ma3.sonde_ok")
            return {"ok": True, "message": _L("err.ma3.sonde_relancee")}

    return {"ok": False, "raison": _L("err.ma3.sonde_muette_relance")}


def _plugin_source_dir() -> Path:
    """Dossier des fichiers du plugin livrés avec l'app (bundle figé ou sources)."""
    import wing_ui as core
    return core._RES_DIR / "plugin_ma3"


def installer_plugin() -> dict:
    """Copie les fichiers, envoie l'import OSC, vérifie la sonde.

    Retour : {"ok": True, "message": …} ou {"ok": False, "raison": <actionnable>}.
    """
    import wing_ui as core

    reach = ma3_reachable()
    if reach not in ("ok", "muet"):
        return {"ok": False, "raison": _L("err.ma3.injoignable_install")}

    src = _plugin_source_dir()
    manquants = [n for n in _PLUGIN_PROD if not (src / n).is_file()]
    if manquants:
        return {"ok": False,
                "raison": _L("err.ma3.plugin_fichiers_absents",
                             manquants=", ".join(manquants))}

    dest = _ma3_base() / "gma3_library" / "datapools" / "plugins"
    try:
        dest.mkdir(parents=True, exist_ok=True)
        for n in _PLUGIN_PROD:
            shutil.copy2(src / n, dest / n)
            wm.own_like_parent(dest / n)
    except Exception as e:
        return {"ok": False, "raison": _L("err.ma3.copie_ko", err=e)}
    core.log("journal.ma3.plugin_copie", n=len(_PLUGIN_PROD), dest=dest)

    slot = etat.E.SETTINGS.get("plugin_slot", PLUGIN_SLOT_DEFAUT)
    try:
        slot = int(slot)
        if not (PLUGIN_SLOT_MIN <= slot <= PLUGIN_SLOT_MAX):
            raise ValueError
    except (TypeError, ValueError):
        core.log("journal.ma3.plugin_slot_invalide", slot=slot,
                 defaut=PLUGIN_SLOT_DEFAUT)
        slot = PLUGIN_SLOT_DEFAUT
        core.reglage_poser(plugin_slot=slot)

    for cmd in _plugin_osc(slot):
        try:
            etat.E.OSC.send_message("/cmd", cmd)
        except Exception as e:
            return {"ok": False, "raison": _L("err.ma3.osc_ko_install", cmd=cmd, err=e)}
        core.log(f"   → {cmd}")
        time.sleep(0.4)

    # Vérifie une vraie PROGRESSION (`_sonde_avance` : `tours` qui avance), pas la
    # fraîcheur du fichier — un fichier abandonné reste « frais » 5 s et a déjà
    # donné un faux « ok » (compteur figé depuis 3 minutes).
    time.sleep(1.0)
    if _sonde_avance():
        core.log("journal.ma3.sonde_ok")
        return {"ok": True, "message": _L("err.ma3.plugin_installe")}

    return {"ok": False, "raison": _L("err.ma3.sonde_muette_install", slot=slot)}


def osc_config_ma3() -> dict:
    """Configuration OSC LUE DANS MA3 par la sonde. Jamais d'exception.

    🎯 L'app détectait très bien que MA3 n'écoutait pas (aucun socket sur le
    port visé) mais accusait une machine virtuelle… alors
    qu'aucune ne tournait. Diagnostic juste, explication fausse.

    Relevé ce jour-là : MA3 lancé (pid 3101), zéro socket UDP sur 8000, aucune
    VM. L'entrée OSC était réellement inactive — restait à savoir si elle était
    coupée ou réglée sur un autre port. Seule la sonde, qui tourne DANS MA3,
    peut le dire.

    `actif=False` → on ne sait pas, et l'interface le dit au lieu d'inventer.
    """
    import wing_ui as core
    vide = {"actif": False, "entree": None, "sortie": None,
            "port_attendu": wb.MA3_PORT, "configs": [], "note": None}
    e = core.ma3_etat()
    if not e.get("actif"):
        return vide
    c = e.get("osc_config")
    if not c:
        return dict(vide, note=e.get("osc_config_note")
                    or "la sonde ne remonte pas la configuration OSC "
                       "(relance le plugin dans grandMA3)")
    return {"actif": True,
            "entree":  c.get("entree"),
            "sortie":  c.get("sortie"),
            "via":     c.get("via"),
            "port_attendu": wb.MA3_PORT,
            "configs": c.get("configs") or [],
            "note":    c.get("note")}


def _vpn_actif() -> bool:
    """Un VPN est-il monté ? (interface utun* AVEC une adresse IPv4)

    🔎 Le symptôme cherché n'est pas « une VM tourne », c'est « des
    interfaces réseau se sont ajoutées sous MA3 ». Un VPN en ajoute exactement
    comme une VM.

    Constaté ce jour-là : MA3 lancé, Enable Input activé, une ligne OSCData sur
    le port 8000 avec Receive ET Receive Command à Yes — et pourtant AUCUN
    socket sur 8000 (`lsof -p <ma3> -a -iUDP` : 8005, 53020, 59592, 10669,
    61541). Présents : `utun4` en 10.5.0.2, et un « Preferred IP » réglé sur
    10.0.0.0/8 — donc pointant vers le VPN, pendant que l'Interface disait lo0.

    ⚠️ TESTER L'ADRESSE, PAS LE NOM. Une 1re version cherchait « une interface
    utun existe ». Faux signal : `utun0` à `utun3` sont présents sur TOUT Mac,
    VPN ou non (vérifié sur celui-ci — seul `utun4` portait une adresse). Une
    heuristique qui crie toujours ne sert à rien.

    ⚠️ CORRÉLATION, PAS CAUSALITÉ DÉMONTRÉE. On le signale pour éviter de
    chercher ailleurs ; on n'écrit pas que c'est la cause.
    """
    try:
        noms = subprocess.run(["ifconfig", "-l"], capture_output=True,
                              text=True, timeout=1.0).stdout.split()
        for n in (x for x in noms if x.startswith("utun")):
            d = subprocess.run(["ifconfig", n], capture_output=True,
                               text=True, timeout=1.0).stdout
            if any(l.strip().startswith("inet ") for l in d.splitlines()):
                return True
    except Exception:
        pass
    return False


def vm_active() -> bool:
    """Une machine virtuelle (Parallels, VMware…) tourne-t-elle ?

    Pourquoi c'est ici : à chaque fois que MA3 s'est retrouvé « lancé mais
    n'écoute pas l'OSC », Parallels tournait — constaté plusieurs fois.
    MA3 ne rebinde pas son port d'entrée quand les interfaces réseau bougent
    sous lui — et une VM en ajoute plusieurs (vmenet0/1, bridge100…102).

    Ça ne DÉMONTRE pas la causalité, mais la corrélation est constante et
    l'information vaut d'être affichée : elle évite de chercher ailleurs.
    """
    now = time.time()
    if now - _VM_CHECK["t"] < 5.0:
        return _VM_CHECK["on"]
    _VM_CHECK["t"] = now
    on = False
    try:
        r = subprocess.run(["pgrep", "-f", "prl_disp_service|vmware-vmx"],
                           capture_output=True, text=True, timeout=1.0)
        on = bool(r.stdout.strip())
        if not on:
            # La VM peut être éteinte mais ses interfaces rester montées.
            r = subprocess.run(["ifconfig", "-l"], capture_output=True,
                               text=True, timeout=1.0)
            on = "vmenet" in r.stdout or _vpn_actif()
    except Exception:
        on = _VM_CHECK["on"]
    _VM_CHECK["on"] = on
    return on


# ── Combien de sockets réseau MA3 a-t-il ouverts ? ───────────────────────────
#
# MA3 tourne mais n'écoute pas le port OSC : deux causes, deux remèdes —
#   • configuration OSC fausse  → Menu → In & Out → OSC
#   • RÉSEAU GLOBAL coupé       → Menu → Network, bouton en bas à droite
# Le compte de sockets les départage : réseau coupé → AUCUN socket ; réseau
# actif mais OSC mal réglé → plusieurs (MA-Net, web remote…) sauf celui visé.
#
# ⚠️ C'est une SIGNATURE, pas une preuve (le manuel ne dit pas « aucun
# socket ») : on rapporte la mesure et ce qu'elle évoque, jamais « ton réseau
# est coupé ». Mesuré seulement quand il y a un problème à expliquer (`lsof`
# coûte cher).
_MA3_SOCKETS = {"t": 0.0, "n": None}


def ma3_sockets():
    """Nombre de sockets réseau ouverts par MA3, ou None si on ne sait pas.

    Même signature diagnostique sur les deux OS (réseau MA3 coupé ⇒ 0 socket ;
    réseau actif ⇒ plusieurs), obtenue par des outils différents :
      • macOS : `pgrep` (PID) puis `lsof -i` (sockets réseau du PID).
      • Windows : le PID vient de `wing_keyboard_windows.find_ma3_windows()`
        (même repérage à chaud que l'assistant clavier — fenêtre GLFW30 de
        `app_gma3.exe`), puis `netstat -ano` compte les lignes TCP/UDP de ce PID.
    """
    now = time.time()
    if now - _MA3_SOCKETS["t"] < 5.0:
        return _MA3_SOCKETS["n"]
    _MA3_SOCKETS["t"] = now
    _MA3_SOCKETS["n"] = None
    try:
        if sys.platform.startswith("win"):
            import wing_keyboard_windows as kbd
            pids = {str(pid) for _h, _t, pid in kbd.find_ma3_windows() if pid}
            if not pids:
                return None
            r = subprocess.run(["netstat", "-ano"],
                               capture_output=True, text=True,
                               errors="replace", timeout=3.0,
                               creationflags=_NO_WINDOW)  # cf. _port_ecoute + _NO_WINDOW
            # Lignes « TCP/UDP  <local>  <foreign>  [ÉTAT]  <PID> » : le PID est
            # toujours le dernier champ (l'ÉTAT n'existe que pour TCP).
            n = 0
            for ligne in r.stdout.splitlines():
                champs = ligne.split()
                if len(champs) >= 4 and champs[0].upper() in ("TCP", "UDP") \
                        and champs[-1] in pids:
                    n += 1
            _MA3_SOCKETS["n"] = n
            return _MA3_SOCKETS["n"]
        pids = []
        for pat in ("gma3", "grandma3"):
            r = subprocess.run(["pgrep", "-i", pat], capture_output=True,
                               text=True, timeout=1.0)
            pids += [x for x in r.stdout.split() if x.isdigit()]
        if not pids:
            return None
        r = subprocess.run(["lsof", "-nP", "-p", ",".join(pids), "-a", "-i"],
                           capture_output=True, text=True, timeout=3.0)
        _MA3_SOCKETS["n"] = len([l for l in r.stdout.splitlines()[1:] if l.strip()])
    except Exception:
        pass                      # outil absent ou refusé : on ne sait pas
    return _MA3_SOCKETS["n"]


def ma3_reachable():
    """État de la liaison OSC vers MA3, pour le panneau de santé :
        None    → cible distante : indéterminable en UDP
        "off"   → MA3 pas lancé
        "muet"  → MA3 lancé mais AUCUNE écoute sur le port OSC
        "ok"    → MA3 lancé et le port écoute
    """
    import wing_ui as core
    ip = wb.MA3_IP
    if ip not in ("127.0.0.1", "localhost", "::1"):
        return None
    now = time.time()
    if now - etat.E.MA3_CHECK["t"] >= 2.0:     # cache : au plus une mesure / 2 s
        etat.E.MA3_CHECK["t"] = now
        alive = False
        try:
            if sys.platform.startswith("win"):
                # Réutilise le repérage à chaud de l'assistant clavier (fenêtre
                # GLFW30 de `app_gma3.exe`, ré-énumérée à chaque appel — pas de
                # cache de PID/handle, même principe que `pgrep` sous macOS).
                import wing_keyboard_windows as kbd
                alive = kbd.find_ma3_pid() is not None
            else:
                for pat in ("gma3", "grandma3"):
                    r = subprocess.run(["pgrep", "-i", pat],
                                       stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, timeout=1.0)
                    if r.returncode == 0:
                        alive = True
                        break
        except Exception:
            alive = etat.E.MA3_CHECK["alive"]  # en cas d'échec, on garde l'état précédent
        etat.E.MA3_CHECK["alive"] = alive
        # Inutile de sonder le port si le process est absent.
        etat.E.MA3_CHECK["listening"] = _port_ecoute(wb.MA3_PORT) if alive else False
    if not etat.E.MA3_CHECK["alive"]:
        return "off"
    return "ok" if etat.E.MA3_CHECK["listening"] else "muet"


# ── Attributs d'encodeur reconnus par MA3 ─────────────────────────────────────
#
# MA3 installe la liste complète de ses attributs sur le disque. On la lit
# plutôt que de la recopier : elle suit ainsi la version de MA3 installée, sans
# rien à maintenir ici. Voir le bug « Focus » dans docs/FADERS_ENCODERS.md :
# un nom faux échoue en SILENCE, MA3 refuse sur SA ligne de commande et rien ne
# remonte en OSC. D'où l'intérêt de montrer les noms valides dans l'interface.

# Repli quand MA3 n'est pas installé sur CETTE machine (console séparée, ou
# MA3 rangé ailleurs) : les attributs courants, et rien de plus.
# ⚠️ Chaque nom ci-dessous a été vérifié contre attribute_definitions.xml de
# gma3 2.4.2 — ne JAMAIS en ajouter un de mémoire (deux l'ont été à l'écriture
# de cette liste, `ColorRGB_A` et `ColorMacro1` : ni l'un ni l'autre n'existe).
ATTRS_REPLI = [
    ("Dimmer",   ["Dimmer"]),
    ("Position", ["Pan", "Tilt", "PanRotate", "TiltRotate",
                  "XYZ_X", "XYZ_Y", "XYZ_Z"]),
    ("Focus",    ["Focus1", "Focus2", "Zoom"]),
    ("Beam",     ["Shutter1", "Shutter1Strobe", "StrobeRate", "StrobeDuration",
                  "Iris", "Frost1", "Prism1", "Prism1Pos", "Prism1PosRotate"]),
    ("Gobo",     ["Gobo1", "Gobo1Pos", "Gobo1PosRotate",
                  "Gobo2", "Gobo2Pos", "Gobo2PosRotate", "Gobo3",
                  "AnimationWheel1"]),
    ("Color",    ["ColorRGB_R", "ColorRGB_G", "ColorRGB_B", "ColorRGB_W",
                  "ColorRGB_C", "ColorRGB_M", "ColorRGB_Y", "ColorRGB_UV",
                  "ColorRGB_WW", "ColorRGB_CW",
                  "HSB_Hue", "HSB_Saturation", "HSB_Brightness",
                  "CTO", "CTC", "CTB", "Color1", "Color2", "ColorMacro"]),
    ("Shapers",  ["Blade1A", "Blade1B", "Blade2A", "Blade2B",
                  "Blade3A", "Blade3B", "Blade4A", "Blade4B",
                  "Blade1Rot", "Blade2Rot", "Blade3Rot", "Blade4Rot",
                  "ShaperRot", "ShaperMacros"]),
]

_ATTRS_CACHE = {"t": 0.0, "data": None}


def _lire_attributs_ma3():
    """Lit les attributs du MA3 installé. Retourne (groupes, chemin) ou None.

    Groupes = [(nom_du_FeatureGroup, [attributs…]), …], dans l'ordre du fichier
    (Dimmer, Position, Gobo, Color, Beam, Focus, Control, Shapers, Video) —
    c'est l'ordre de MA3, autant s'y tenir.

    ⚠️ Seules les balises <Attribute> sont retenues. <FeatureGroup> et
    <Feature> portent des noms très proches (« Focus » existe comme les deux)
    mais ne sont PAS adressables par « Attribute <nom> at + N ».
    """
    base = _ma3_base()
    if not base.is_dir():
        return None
    # Plusieurs versions cohabitent souvent — on prend la plus récente.
    fichiers = sorted(base.glob("gma3_*/shared/resource/attribute_definitions.xml"))
    if not fichiers:
        return None
    src = fichiers[-1]
    try:
        texte = src.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    groupes, index = [], {}
    for balise in re.findall(r"<Attribute\b[^>]*>", texte):
        nom = re.search(r'\bName="([^"]*)"', balise)
        if not nom:
            continue
        feat = re.search(r'\bFeature="([^"]*)"', balise)
        grp = feat.group(1).split(".")[0] if feat else "Autres"
        if grp not in index:
            index[grp] = []
            groupes.append((grp, index[grp]))
        index[grp].append(nom.group(1))
    return (groupes, str(src)) if groupes else None


_FEATURE_PAR_ATTR_CACHE = {"t": 0.0, "data": None}


def _feature_par_attribut() -> dict:
    """{nom_attribut: "FeatureGroup.Feature"} — diagnostic de l'ordre des roues.

    Même fichier, même regex que `_lire_attributs_ma3()`, mais on garde le
    champ `Feature` ENTIER au lieu de ne prendre que la partie avant le point
    (`_lire_attributs_ma3()` jette la Feature fine pour ne garder que le
    FeatureGroup). Sert à observer, sans passer par MA3, à quelle Feature
    appartient chaque `subattribut` déjà remonté par la sonde — voir
    `docs/FADERS_ENCODERS.md`, « `h.name` ≠ le canal ». Purement une lecture du
    fichier XML installé, aucun appel Lua, aucune commande OSC.
    """
    now = time.time()
    cache = _FEATURE_PAR_ATTR_CACHE["data"]
    if cache is not None and now - _FEATURE_PAR_ATTR_CACHE["t"] < 60.0:
        return cache
    _FEATURE_PAR_ATTR_CACHE["t"] = now
    table = {}
    base = _ma3_base()
    fichiers = sorted(base.glob("gma3_*/shared/resource/attribute_definitions.xml")) \
        if base.is_dir() else []
    if fichiers:
        try:
            texte = fichiers[-1].read_text(encoding="utf-8", errors="replace")
            for balise in re.findall(r"<Attribute\b[^>]*>", texte):
                nom = re.search(r'\bName="([^"]*)"', balise)
                feat = re.search(r'\bFeature="([^"]*)"', balise)
                if nom and feat:
                    table[nom.group(1)] = feat.group(1)
        except Exception:
            pass
    _FEATURE_PAR_ATTR_CACHE["data"] = table
    return table


def ma3_attributes():
    """Liste des attributs valides, pour l'interface. Jamais d'exception."""
    import wing_ui as core
    now = time.time()
    cache = _ATTRS_CACHE["data"]
    # Une lecture réussie est définitive (le fichier ne bouge pas). Un échec est
    # réessayé toutes les 60 s : MA3 peut être installé après coup.
    if cache and cache["source"] == "ma3":
        return cache
    if cache and now - _ATTRS_CACHE["t"] < 60.0:
        return cache
    _ATTRS_CACHE["t"] = now
    lu = None
    try:
        lu = _lire_attributs_ma3()
    except Exception as e:
        core.log("journal.ma3.attrs_ko", err=e)
    if lu:
        groupes, chemin = lu
        data = {"source": "ma3", "chemin": chemin,
                "groupes": [[g, noms] for g, noms in groupes]}
    else:
        data = {"source": "repli", "chemin": None,
                "groupes": [[g, list(noms)] for g, noms in ATTRS_REPLI]}
    data["total"] = sum(len(n) for _, n in data["groupes"])
    _ATTRS_CACHE["data"] = data
    return data


# ── Fonctions de fader reconnues par MA3 ──────────────────────────────────────
#
# Lues dans le manuel installé (pages keyword_fader*.html) : la liste
# officielle, à la version installée. Un fader d'executor accepte EXACTEMENT 8
# fonctions — Master, X, XA, XB, Temp, Rate, Speed, Time (manuel 2.4, « Select
# Function for faders », executor_assign.html). Highlight / Lowlight / Solo
# sont des fonctions de TOUCHE, pas de fader. S'y ajoutent trois mécanismes
# qui ne sont PAS des fonctions de fader : le grandmaster, le Speed Master du
# pool, et les masters de la séquence sélectionnée (Master 1.x).
# ⚠️ Toute option offerte par l'interface doit être documentée dans ce tableau.

# ⚠️ Les libellés/descriptions ne sont PLUS écrits ici : ils vivent dans les
# catalogues i18n (`fader_func.<kind>.nom` / `.desc` dans locales/fr.json et
# en.json), résolus via `wing_i18n.L()` au moment de l'envoi JSON — même
# surface, même mécanique que `journal.*`/`err.*`/`firmware.*` (voir
# docs/I18N.md § « Côté serveur »). Recopier la prose ici l'aurait fait
# diverger du catalogue.
#
# L'ORDRE d'affichage, lui, reste ici : c'est la seule chose que le catalogue
# (un dict plat, sans notion d'ordre entre namespaces) ne peut pas porter.
FADER_FUNC_KINDS = ("executor", "crossfade", "crossfadeA", "crossfadeB",
                    "temp", "rate", "time", "faderspeed", "gm", "speed",
                    "selected")

# Gabarit de commande réellement envoyé, pour affichage dans l'interface.
# `{valeur}` — le seul mot de prose du lot (« valeur »/« value ») — est résolu
# via `fader_func.valeur` au moment de l'envoi ; `.format()` sur un gabarit
# qui n'a pas ce trou l'ignore simplement, sans erreur.
FADER_FUNC_CMD = {
    "executor":   "FaderMaster Executor N At %",
    "crossfade":  "FaderCrossFade Executor N At %",
    "crossfadeA": "FaderCrossFadeA Executor N At %",
    "crossfadeB": "FaderCrossFadeB Executor N At %",
    "temp":       "FaderTemp Executor N At %",
    "rate":       "FaderRate Executor N At %",
    "time":       "FaderTime Executor N At %",
    "faderspeed": "FaderSpeed Executor N At BPM|Hz|Seconds {valeur}",
    "gm":         "Master 2.1 At %",
    "speed":      "Master 3.N At BPM|Hz|Seconds {valeur}",
    "selected":   "Master 1.N At %",
}

_FADERF_CACHE = {"t": 0.0, "data": None}


def _lire_fonctions_fader_ma3():
    """Mots-clés Fader* du manuel MA3 installé. Retourne (dict, chemin, version).

    dict : {"FaderMaster": "Faderm", …} — mot-clé complet → raccourci frappé.
    """
    base = _ma3_base()
    if not base.is_dir():
        return None
    dossiers = sorted(base.glob("gma3_*/shared/language/HTML"))
    if not dossiers:
        return None
    rep = dossiers[-1]
    trouve, version = {}, None
    for page in sorted(rep.glob("keyword_fader*.html")):
        try:
            brut = page.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        texte = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", brut))
        nom = re.search(r"\b(Fader[A-Za-z]*) Keyword grandMA3 User Manual", texte)
        if not nom:
            continue
        court = re.search(r"Type the shortcut ([A-Za-z0-9]+)", texte)
        trouve[nom.group(1)] = court.group(1) if court else ""
        if version is None:
            v = re.search(r"\bVersion ([\d.]+)", texte)
            version = v.group(1) if v else None
    return (trouve, str(rep), version) if trouve else None


def ma3_fader_functions():
    """Fonctions de fader, pour l'interface. Jamais d'exception.

    Renvoie toujours la liste complète de ce que Wing Bridge sait envoyer ;
    `confirme` dit si MA3 confirme le mot-clé sur CETTE machine. Quand le
    manuel n'est pas lisible, `confirme` vaut None partout — surtout pas
    False, qui laisserait croire à une fonction invalide.

    ⚠️ Seule la partie qui dépend du manuel MA3 (motcle/court/confirme) est
    mise en cache — PAS `libelle`/`desc`/`cmd` : ces trois-là suivent la
    LANGUE courante et sont résolus À CHAQUE appel via `wing_i18n.L()`. Les
    mettre en cache aurait figé la traduction au premier appel : le cache
    `source == "ma3"` est PERMANENT (le manuel ne bouge pas en cours de
    session), un changement de langue via `POST /api/lang` ne se serait donc
    jamais vu ici tant que le process tourne. Même logique que le journal
    (`journal_affiche()` re-résout à chaque `/api/status` — voir
    docs/I18N.md § « Côté serveur »).
    """
    import wing_ui as core
    import wing_i18n
    now = time.time()
    brut = _FADERF_CACHE["data"]
    if not (brut and (brut["source"] == "ma3" or now - _FADERF_CACHE["t"] < 60.0)):
        _FADERF_CACHE["t"] = now
        lu = None
        try:
            lu = _lire_fonctions_fader_ma3()
        except Exception as e:
            core.log("journal.ma3.fader_funcs_ko", err=e)
        connus, chemin, version = (lu if lu else (None, None, None))

        # Mot-clé MA3 par type, y compris ceux traités hors de
        # core.FADER_KEYWORDS. Les trois derniers n'ont volontairement PAS de
        # mot-clé Fader* : ils passent par « Master », un mécanisme différent
        # malgré le nom proche.
        # ⚠️ Recalculé à chaque (re)lecture du manuel (pas de constante
        # module) : FADER_KEYWORDS reste dans wing_ui.py (utilisé aussi par
        # les faders/pickup et les routes Handler) — au chargement de CE
        # module, il n'existe pas encore forcément.
        fader_keyword_by_kind = dict(core.FADER_KEYWORDS, faderspeed="FaderSpeed",
                                     gm=None, speed=None, selected=None)

        infos = []
        for kind in FADER_FUNC_KINDS:
            mot = fader_keyword_by_kind.get(kind)
            infos.append({
                "kind": kind, "motcle": mot,
                "court": (connus or {}).get(mot or "", ""),
                # None = on ne sait pas ; True = confirmé par le manuel MA3.
                # Les types sans mot-clé Fader* (gm, speed) ne sont pas
                # concernés.
                "confirme": None if (connus is None or mot is None)
                            else (mot in connus),
            })
        # Un mot-clé Fader* que MA3 connaît et que Wing Bridge n'offre pas :
        # ça n'existe pas aujourd'hui (8/8), mais une version future de MA3
        # pourrait en ajouter un — autant le montrer plutôt que de le
        # découvrir par hasard.
        offerts = {m for m in fader_keyword_by_kind.values() if m}
        manquants = sorted((connus or {}).keys() - offerts)

        brut = {"source": "ma3" if connus else "repli", "chemin": chemin,
                "version": version, "infos": infos, "manquants": manquants}
        _FADERF_CACHE["data"] = brut

    valeur = wing_i18n.L("fader_func.valeur")
    fonctions = [
        dict(info,
             libelle=wing_i18n.L(f"fader_func.{info['kind']}.nom"),
             desc=wing_i18n.L(f"fader_func.{info['kind']}.desc"),
             cmd=FADER_FUNC_CMD.get(info["kind"], "").format(valeur=valeur))
        for info in brut["infos"]
    ]
    return {"source": brut["source"], "chemin": brut["chemin"],
            "version": brut["version"], "fonctions": fonctions,
            "manquants": brut["manquants"]}


# ── Répertoire des mots-clés de commande MA3 ─────────────────────────────────
#
# Lu dans le manuel installé (suit la version de MA3). Deux usages :
#   1. proposer les mots dans l'interface (aide à la saisie) ;
#   2. CORRIGER LA CASSE côté serveur — le vrai filet : un mot-clé mal
#      capitalisé (« off ») échoue en SILENCE sur la ligne de commande de MA3,
#      et rien ne remonte en OSC. Même famille que « Focus » pour « Focus1 ».

_MOTSCLES_CACHE = {"t": 0.0, "data": None}


def _lire_motscles_ma3():
    """Mots-clés de commande du manuel MA3 installé. (liste, chemin) ou None.

    Une page `keyword_<nom>.html` par mot-clé ; le nom exact, avec sa casse,
    est dans le fil d'Ariane (« … » Off Version 2.4 »).
    """
    base = _ma3_base()
    if not base.is_dir():
        return None
    dossiers = sorted(base.glob("gma3_*/shared/language/HTML"))
    if not dossiers:
        return None
    rep = dossiers[-1]
    noms = set()
    for page in rep.glob("keyword_*.html"):
        try:
            brut = page.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        texte = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", brut))
        m = re.search(r"» ([A-Za-z0-9+\-]+) Version [\d.]+", texte)
        if m:
            noms.add(m.group(1))
    return (sorted(noms), str(rep)) if noms else None


def ma3_motscles():
    """Mots-clés valides, pour l'interface. Jamais d'exception.

    Repli quand MA3 n'est pas sur cette machine : les mots que l'app connaît
    déjà (table des raccourcis console + verbes + fonctions d'executor). Moins
    complet, mais tous vérifiés.
    """
    import wing_ui as core
    now = time.time()
    cache = _MOTSCLES_CACHE["data"]
    if cache and cache["source"] == "ma3":
        return cache
    if cache and now - _MOTSCLES_CACHE["t"] < 60.0:
        return cache
    _MOTSCLES_CACHE["t"] = now
    lu = None
    try:
        lu = _lire_motscles_ma3()
    except Exception as e:
        core.log("journal.ma3.motscles_ko", err=e)
    if lu:
        noms, chemin = lu
        data = {"source": "ma3", "chemin": chemin, "mots": noms}
    else:
        replis = set(wm.CONSOLE_KEY_DEFAULTS) | core.VERBES_CIBLE | set(core.EXEC_FUNCS)
        data = {"source": "repli", "chemin": None,
                "mots": sorted(m for m in replis if m and m[0].isalpha())}
    data["index"] = {m.lower(): m for m in data["mots"]}
    _MOTSCLES_CACHE["data"] = data
    return data


def corriger_casse(commande: str):
    """Remet chaque mot-clé dans la casse exacte de MA3.

    Renvoie (commande corrigée, [corrections faites]). Les nombres et tout ce
    qui n'est pas un mot-clé connu sont laissés STRICTEMENT tels quels : on
    corrige une capitalisation, on ne réécrit pas la commande de l'utilisateur.
    """
    index = ma3_motscles()["index"]
    sortie, corrections = [], []
    for mot in commande.split():
        exact = index.get(mot.lower())
        if exact and exact != mot:
            corrections.append(f"{mot} → {exact}")
            sortie.append(exact)
        else:
            sortie.append(mot)
    return " ".join(sortie), corrections


def corriger_casse_attribut(nom: str) -> str:
    """Remet un nom d'ATTRIBUT (roues encodeuses) dans la casse exacte de MA3.

    ⚠️ RÉPERTOIRE DISJOINT de `corriger_casse()`. Un nom d'attribut
    ("Dimmer", "Pan"…) n'est PAS un mot-clé de commande — chercher "Dimmer"
    dans l'index de `ma3_motscles()` (verbes, fonctions d'executor, raccourcis
    console) ne le trouverait jamais. On le cherche dans `ma3_attributes()`,
    le répertoire lu depuis `attribute_definitions.xml` (ou son repli figé).

    Laisse `nom` STRICTEMENT tel quel s'il n'est pas reconnu, même casse
    comprise : un nom inconnu doit rester visible comme tel (case rouge côté
    UI, cf. `ui/faders_encodeurs.js::markAttr`), pas être maquillé.
    """
    if not nom:
        return nom
    index = {n.lower(): n for _, liste in ma3_attributes()["groupes"] for n in liste}
    return index.get(str(nom).strip().lower(), nom)


# ── Roues encodeuses : suivre l'Encoder Bar de MA3 ───────────────────────────
#
# Comportement d'une vraie console : les roues font ce que l'Encoder Bar
# affiche. Le PILOTAGE se décide dans `enc_attr_selon_ma3()` (wing_faders.py),
# sous `SETTINGS["encodeurs_ma3"]` (défaut False) ; `ma3_encodeurs()` ne fait
# que RAPPORTER ce que la sonde voit.
#
# Les attributs sont ceux du projecteur sélectionné (`GetUIChannels`), pas une
# table globale (chaque projecteur a les siens) — mais du PREMIER seulement
# (`SelectionFirst()`) : limitation connue sur une sélection mélangée.
#
# 🔑 Le champ à lire est `subattribut` (h.SUBATTRIBUTE), jamais `nom` (h.name),
# qui vaut le nom du FIXTURE pour tous les canaux. → docs/FADERS_ENCODERS.md.

ROUES = 4                       # la wing en a 4


def ma3_encodeurs() -> dict:
    """Ce que la sonde voit sous les encodeurs de MA3.

    Renvoie toujours un dict avec `actif` : True dès que la sonde publie
    quelque chose d'exploitable. `pilote` reflète le réglage réel
    (`SETTINGS["encodeurs_ma3"]`) — PAS si cette sélection
    précise pilote effectivement les roues en ce moment (une sélection vide
    avec le suivi coché reste `pilote: True`, c'est l'intention qui est
    rapportée, pas l'instant). Le pilotage lui-même se décide dans
    `enc_attr_selon_ma3()` (wing_faders.py), pas ici — cette fonction ne
    fait toujours QUE rapporter ce que la sonde voit.
    """
    import wing_ui as core
    pilote = bool(etat.E.SETTINGS.get("encodeurs_ma3", False))
    vide = {"actif": False, "pilote": pilote, "feature": None, "attribut": None,
            "fixture": None, "selection": None, "canaux": [],
            "canaux_par_feature": {}, "note": None}
    e = core.ma3_etat()
    enc = e.get("encodeurs") if e.get("actif") else None
    if not enc:
        return vide

    # Observation seule (étape 0 du suivi de l'Encoder Bar) : chaque canal remonte `nom`
    # (h.name), `subattribut` (h.SUBATTRIBUTE) et `index` (h.INDEX) côte à
    # côte, en observation seule — voir le commentaire de `lire_encodeurs()`
    # dans wingbridge.lua pour le pourquoi (l'exemple officiel du manuel MA3
    # lit SUBATTRIBUTE, pas .name, et un piège identique a déjà coûté cher).
    # Aucune commande OSC ne part de cette lecture.
    #
    # 🔎 `feature_reel` = le "FeatureGroup.Feature" de `attribute_definitions.xml`
    # pour ce `subattribut` (via `_feature_par_attribut()`, PURE LECTURE DE
    # FICHIER, aucun appel Lua). Sert à observer si trier/filtrer par Feature
    # reproduit l'ordre réel de l'Encoder Bar — voir docs/FADERS_ENCODERS.md,
    # « `h.name` ≠ le canal ».
    feat_par_attr = _feature_par_attribut()
    canaux = [{"nom": c.get("nom"),
               "subattribut": c.get("subattribut"),
               "index": c.get("index"),
               "feature_reel": feat_par_attr.get(c.get("subattribut"))}
              for c in (enc.get("canaux") or [])
              if isinstance(c, dict) and c.get("nom")]

    # Regroupement PUREMENT côté app (Python), trié par INDEX croissant à
    # l'intérieur de chaque Feature — c'est CETTE liste qu'il faut comparer,
    # Feature par Feature, à ce que l'écran de MA3 affiche réellement.
    canaux_par_feature = {}
    for c in canaux:
        cle = c["feature_reel"] or "?"
        canaux_par_feature.setdefault(cle, []).append(c)
    for liste in canaux_par_feature.values():
        liste.sort(key=lambda c: (c["index"] is None, c["index"]))

    return {"actif": True, "pilote": pilote,
            "feature":   enc.get("feature"),
            "attribut":  enc.get("attribut"),
            "fixture":   enc.get("fixture"),
            "selection": enc.get("selection"),
            "canaux": canaux,
            "canaux_par_feature": canaux_par_feature,
            # `encodeurs_note` est publié par la sonde à la RACINE de l'état
            # (d["encodeurs_note"]), pas dans le sous-dict `encodeurs` : il se
            # lit donc sur `e`, pas sur `enc` (corrigé — cherché
            # au mauvais niveau, donc jamais remonté).
            "note":      enc.get("note") or e.get("encodeurs_note")}
