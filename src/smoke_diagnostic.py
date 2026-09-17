#!/usr/bin/env python3
"""
smoke_diagnostic.py — Wing Bridge
==================================
Domaine diagnostic du test de fumée : complétude du rapport de diagnostic,
trace journalisée d'un branchement raté. Voir smoke_core.py pour
ok/echec/note/section.
"""

import etat
import shutil
import tempfile
import time

from smoke_core import ok, echec, note, section


def test_diagnostic_complet(ui):
    """Le rapport de diagnostic contient-il vraiment toutes ses sections ?

    🔴 LE TROU QUE PERSONNE NE GARDAIT.

    `build_diagnostic()` isole chaque section dans un `try/except` : une section
    qui échoue est remplacée par « (section indisponible : … ) » et les autres
    sont préservées. C'est une bonne idée — c'est justement quand tout est cassé
    qu'on génère ce fichier.

    Mais ça transforme aussi une erreur franche en TROU DISCRET. Constaté ce
    jour-là : la section « MODE CONSOLE / CLAVIER » manquait depuis le build
    132, parce qu'elle lisait `WS["enabled"]`, clé supprimée avec la bascule du
    mode console. Personne ne pouvait s'en apercevoir : le fichier avait l'air
    complet, et ce qui manquait est justement la panne n°1 (assistant clavier
    absent, Accessibilité non accordée).

    🔑 Même famille que le contrôle test_encodeurs_ma3 : un DÉCALAGE DE CHAMPS entre deux
    parties du code, invisible à la syntaxe, silencieux à l'exécution. On génère
    donc un vrai rapport et on exige qu'aucune section ne se soit dérobée.

    ⚠️ Deux précautions, toutes deux imposées par les règles du projet :
      • le rapport part dans un dossier TEMPORAIRE, jamais sur le Bureau de
        l'utilisateur ni dans son journal — « un test ne laisse aucune trace » ;
      • `wing_detect.scan()` est doublé. Il lit les descripteurs texte des
        périphériques, donc il PARLE à la wing — et ce test tourne avant CHAQUE
        build, potentiellement wing branchée et tenue par l'app. Le chemin de
        code est exercé, le matériel n'est pas touché.
    """
    section("36. Le diagnostic ne perd aucune section")
    import pathlib
    # ⚠️ `_diag_home` est monkeypatché sur `ui.wing_diagnostic`, PAS sur `ui` :
    # depuis le découpage, `build_diagnostic()` vit dans
    # `wing_diagnostic.py` et y résout `_diag_home()` par nom nu — un
    # monkeypatch posé sur l'alias réexporté `ui._diag_home` n'aurait aucun
    # effet sur cet appel, et le test écrirait pour de vrai sur le Bureau.
    sauve = {"home": ui.wing_diagnostic._diag_home, "log": ui.log,
             "fic": ui._log_to_file, "pdir": ui.wm.PROFILE_DIR,
             "own": ui.wm.own_like_parent, "scan": ui.wing_detect.scan}
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="wing-smoke-diag-"))
    txt = None
    try:
        ui.wing_diagnostic._diag_home = lambda: None
        ui.log = lambda *a, **k: None
        ui._log_to_file = lambda *a, **k: None
        ui.wm.PROFILE_DIR = tmp / "profiles"
        (tmp / "profiles").mkdir(parents=True, exist_ok=True)
        ui.wm.own_like_parent = lambda p: None
        ui.wing_detect.scan = lambda: [
            {"vid": "0x03eb", "pid": "0x160b", "status": "supported",
             "product": "onPC Wing", "name": "onPC Wing"}]
        txt = ui.build_diagnostic().read_text(encoding="utf-8")
    except Exception as e:
        echec("build_diagnostic() a levé une exception",
              f"{type(e).__name__}: {e} — le bouton 🩺 ne produirait RIEN")
    finally:
        ui.wing_diagnostic._diag_home = sauve["home"]
        ui.log = sauve["log"]
        ui._log_to_file = sauve["fic"]
        ui.wm.PROFILE_DIR = sauve["pdir"]
        ui.wm.own_like_parent = sauve["own"]
        ui.wing_detect.scan = sauve["scan"]
        shutil.rmtree(tmp, ignore_errors=True)
    if txt is None:
        return

    # Une section en échec s'écrit « (section unavailable: … ) » (rapport
    # anglais). Le titre est deux lignes au-dessus (séparateur, titre, séparateur).
    lignes = txt.splitlines()
    perdues = []
    for i, l in enumerate(lignes):
        if l.startswith("(section unavailable"):
            titre = lignes[i - 2].strip() if i >= 2 else "?"
            perdues.append(f"{titre} → {l.strip()}")
    if perdues:
        echec(f"{len(perdues)} section(s) manquent au rapport de diagnostic",
              " ; ".join(perdues) + " — le fichier a l'air complet, et c'est "
              "justement ce qui rend la perte invisible")
        return

    # Et les sections attendues sont-elles seulement là ? Une section supprimée
    # par mégarde ne laisse, elle, aucune trace du tout.
    # ⚠️ Le rapport est TOUJOURS EN ANGLAIS (wing_diagnostic → L_en) : les
    # titres attendus sont donc les valeurs `diag.section.*` de en.json.
    attendues = ["IDENTITY", "CHAIN STATE", "OSC", "CONSOLE MODE / KEYBOARD",
                 "SETTINGS", "PROFILES PRESENT", "USB DEVICES",
                 "OBSERVED OSC FEEDBACK", "ENGINE LOG"]
    absentes = [a for a in attendues if a not in txt]
    if absentes:
        echec("des sections attendues ne figurent pas dans le diagnostic",
              ", ".join(absentes))
        return
    ok(f"{len(attendues)} sections présentes, aucune ne s'est dérobée")


def test_branchement_laisse_trace(ui):
    """Un branchement qui échoue laisse-t-il une trace dans le journal ?

    🔴 L'AVEUGLEMENT LE PLUS COÛTEUX POSSIBLE POUR CE PROJET.
    Un branchement raté signalé ; le journal est VIDE. Pas « ✗ init
    échouée », pas « wing détectée » : rien. Impossible de distinguer « l'app ne
    l'a pas vue » de « l'init a échoué ».

    Cause : la boucle appelle `connect_wing(quiet=True)` pour ne pas noyer le
    journal quand la wing est absente — et `quiet` finissait par cacher l'échec
    LUI-MÊME. Aucune ligne ne marquait non plus l'apparition sur le bus.

    ⚠️ CE N'EST PAS UN DÉTAIL DE CONFORT. Le chantier n°1 (refus de démarrage
    du firmware) est EN OBSERVATION : on compte les occurrences avant de
    conclure. L'événement à compter était précisément celui qui n'écrivait
    rien — l'observation ne pouvait rien accumuler.

    Règle gardée ici : **une ligne à l'apparition, une à l'échec, puis
    silence.** Ni zéro (aveugle), ni une par tentative (illisible).
    """
    section("39. Un branchement raté laisse une trace")
    import threading as _th
    sauv = (ui.log, ui._log_to_file, ui.wing_init.JOURNAL,
            ui.wing_init.wing_absente, ui.full_init, etat.E.DEV[0],
            dict(etat.E.AUTO), dict(etat.E.STATE))
    journal = []
    scene = {"n": 0}
    try:
        ui.log = lambda *a, **k: journal.append(str(ui._rendre_appel(*a, **k)))
        ui._log_to_file = lambda *a, **k: None
        ui.wing_init.JOURNAL = ui.log_init
        def absente():
            scene["n"] += 1
            if scene["n"] > 40: ui.USB_ARRET.set()
            return scene["n"] < 4          # absente, puis PRÉSENTE
        def init_rate(verbose=False, force=False):
            ui.wing_init._msg("✗ Wing en bootloader : le firmware n'a pas démarré.")
            ui.wing_init.DERNIER_ECHEC["firmware_bloque"] = False
            return None
        ui.wing_init.wing_absente = absente
        ui.full_init = init_rate
        etat.E.STATE.update(want_connected=True, connecting=False, wing=False,
                        mode="idle")
        etat.E.DEV[0] = None
        etat.E.AUTO.update(last_try=0.0, interval=0.0, echecs=0,
                       attend_rebranchement=False, absente_depuis=0.0,
                       essais_presence=0)
        ui._INIT_MSG.update(dernier="", n=0)
        ui.USB_ARRET.clear(); ui.USB_SORTIE.clear()
        fil = _th.Thread(target=ui.usb_loop, daemon=True)
        fil.start(); fil.join(timeout=20)
        vivant = fil.is_alive()
    finally:
        ui.USB_ARRET.set(); time.sleep(0.05)
        (ui.log, ui._log_to_file, ui.wing_init.JOURNAL,
         ui.wing_init.wing_absente, ui.full_init, etat.E.DEV[0]) = sauv[:6]
        etat.E.AUTO.clear(); etat.E.AUTO.update(sauv[6])
        etat.E.STATE.clear(); etat.E.STATE.update(sauv[7])
        ui.USB_ARRET.clear(); ui.USB_SORTIE.clear()

    if vivant or scene["n"] < 10:
        echec("le scénario n'a pas tourné", f"{scene['n']} tour(s)"); return
    essais = etat.E.AUTO.get("essais_presence", 0)
    texte = "\n".join(journal)
    if not journal:
        echec("un branchement raté n'écrit RIEN dans le journal",
              "ni l'apparition, ni l'échec — impossible de distinguer « pas "
              "vue » de « init ratée »")
        return
    if "détectée sur le bus" not in texte:
        echec("rien ne marque l'apparition de la wing sur le bus", texte[:160])
        return
    if "Init échouée" not in texte:
        echec("l'échec d'une init AUTOMATIQUE n'est pas journalisé",
              "`quiet=True` le cachait — l'utilisateur voit un journal vide")
        return
    # …et il ne faut pas non plus une ligne par tentative.
    if len(journal) > 8:
        echec(f"le journal est noyé : {len(journal)} lignes pour un branchement",
              "une ligne à l'apparition, une à l'échec, puis silence")
        return
    ok(f"branchement raté : {len(journal)} ligne(s) pour de nombreuses "
       f"tentatives — apparition et échec tracés, sans noyer le journal")

    # Battement de cœur : une boucle USB morte doit être visible.
    if not etat.E.BOUCLE.get("t_tour"):
        echec("la boucle USB n'horodate pas ses tours",
              "une boucle MORTE serait indiscernable d'une wing débranchée")
    else:
        ok("la boucle horodate chaque tour (boucle morte = visible)")
