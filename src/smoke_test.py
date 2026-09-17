#!/usr/bin/env python3
"""
Test de fumée — Wing Bridge
===========================
Vérifie SANS MATÉRIEL et SANS LANCER L'APP que rien d'évident n'est cassé.
Conçu pour tourner AVANT chaque build (les deux scripts de build l'appellent) :
un build ne doit jamais partir avec une interface morte.

CE QU'IL SURVEILLE, ET POURQUOI. Chaque contrôle vient d'une panne réelle. Le
fil commun : dans ce projet, une erreur se manifeste rarement par une
exception. Elle se manifeste par du SILENCE — une interface figée sans erreur
en console, un nom d'attribut que MA3 refuse sur sa propre ligne de commande,
un executor qui reste allumé parce que son « Off » n'est jamais parti. C'est
ce silence que ce fichier casse.

  test_js                       un `\\n` mal échappé a tué toute l'interface
  test_attributs                « Focus » au lieu de « Focus1 » : roue morte
  test_faders                   un mot-clé faux part sans erreur et ne fait rien
  test_poll_pkt                 deux copies qui divergent = preuve de vie sans valeur
  test_plugin_lua               il tourne dans MA3, pas ici : la faute se voit trop tard
  test_executor_symetrie        les deux moitiés d'un geste doivent suivre la même
                                 règle, sinon l'executor reste bloqué allumé
  test_types_fader_documentes   une option proposée sans explication nulle part
  test_verbe_executor           la ligne de commande de MA3 n'est PAS un champ de
                                 texte : y taper un mot insère des mots-clés
  test_casse_motscles           « off » n'est pas « Off » : MA3 refuse en silence
  test_assistant                il DICTE quoi assigner : aucune étape ne doit proposer
                                 une commande que l'app ne sait pas envoyer
  test_raccourcis_uniques       deux touches sur la MÊME frappe = l'une fait le travail
                                 de l'autre. « Set » envoyait la touche de « Off »
  test_forme_profil             la boucle USB indexe 8 faders et 4 roues SANS vérifier :
                                 un profil plus court tuait le thread en silence
  test_shcuts                   l'app écrit son fichier ET applique par Set … Property ;
                                 ne rien réécrire si déjà bon, jamais de copies
  test_shcuts_sonde             la sonde DANS MA3 confirme ou dément l'envoi — le
                                 démenti est ce qui a de la valeur
  test_encodeurs_ma3            chaque « e.X » lu par le JS doit exister côté serveur :
                                 un champ renommé fait disparaître le header
  test_i18n                     une clé de traduction sans entrée au catalogue =
                                 clé brute à l'écran ; fr.json/en.json qui divergent =
                                 clés brutes selon la machine ; phrases assemblées =
                                 intraduisibles ; balisage FR qui dérive du catalogue =
                                 l'écran change après la 1re bascule
  test_xss_profil_importe       un profil importé exécutait son JavaScript dans
                                 l'interface — donc avec accès à toute l'API
  test_profil_mal_type          un fader "x" ou un pas "1" dans un profil importé
                                 tuait la boucle USB, sans relance
  test_pas_de_route_debug       une route qui tuait la boucle USB a été livrée
  test_une_seule_boucle_usb     une reconnexion lente laissait DEUX boucles USB :
                                 chaque geste partait deux fois vers MA3
  test_empreinte_firmware_a_l_envoi  un firmware abîmé ou remplacé partait vers
                                 le bootloader : l'empreinte n'était vue qu'à l'import
  test_jeton_api                tout programme local pouvait poster sur l'API
                                 (désinstaller, quitter, taper dans MA3)
  test_raccourcis_filtres       une frappe de raccourci corrompait le XML de MA3
                                 ou sortait de la chaîne d'une commande OSC
  test_amorce_elevee_verifiee   Windows : un script élevé et l'installeur USBPcap
                                 pouvaient être substitués entre vérification et exécution
  test_journal_hors_boucle      le journal écrivait sur disque depuis la boucle
                                 USB, à chaque cran de roue
  test_ecritures_etat_sous_verrou  STATE/SETTINGS écrits hors verrou : la doc
                                 promettait un invariant que le code ne tenait pas
  test_handler_robuste          une requête mal formée coupait la connexion sans
                                 réponse (voire bloquait le fil)
  test_profil_load_confine      /api/profile/load chargeait n'importe quel JSON
                                 du disque
  test_ecritures_usb_comptees   écritures DMX/LED refusées avalées en silence
  test_part_unique              deux sauvegardes simultanées partageaient le
                                 même fichier temporaire
  test_dmx_local                n'importe quel poste du réseau pilotait les XLR
  test_validation_entrees       chaque route lisait ses paramètres à la main :
                                 index sans borne, "false" lu vrai, exec texte
  test_handler_mince            le Handler construisait des commandes MA3, lisait
                                 ses paramètres à la main, portait la désinstallation
  test_etat_injecte             l'état vivait en variables de wing_ui, placées
                                 selon ce que les tests patchaient

Usage :  ~/wing-env/bin/python3 smoke_test.py
Sortie :  code 0 si tout passe, 1 sinon (et la liste des échecs).
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from smoke_core import (
    HERE, ECHECS, NOTES, SECTIONS, ok, echec, note, section,
    _blocs_js, _js_manquants, _page, _js_de, _poster,
)
from smoke_leds import test_carte_led
from smoke_hardware import (
    test_poll_pkt, test_boutons_honnetes, test_sorties_rendent_la_wing,
    test_boutons_wing_uniques, test_messages_actionnables,
    test_blocage_jamais_definitif, test_poignee_pendant_reboot,
    test_reconnexion_sans_fantomes, test_fenetre_apres_fw_cfg,
    test_desinstallation, test_connect_wing_verrou_et_boucle,
    test_cycle_dmx_classificateur_partage, test_get_status_verrou_minimal,
    test_lock_sans_appel_lent,
)
from smoke_faders import (
    test_attributs, test_faders, test_executor_symetrie,
    test_types_fader_documentes, test_encodeurs_ma3,
    test_groupe_encodeur_applique, test_pickup_auto_repos,
    test_encodeurs_et_migration_casse_corrigees,
)
from smoke_ma3_sync import (
    test_plugin_lua, test_verbe_executor, test_casse_motscles,
    test_diagnostic_osc, test_diagnostic_reseau, test_ma3_etat_transitoire,
    test_plugin_install, test_plugin_slot, test_port_ecoute_macos,
)
from smoke_raccourcis import (
    test_raccourcis, test_raccourcis_uniques, test_shcuts,
    test_shcuts_sonde, test_appui_long_universel,
    test_cmd_buf_verrouille, test_double_clic_casse,
)
from smoke_profils import (
    test_profil, test_assistant, test_forme_profil,
    test_profil_favori, test_import_profil, test_ecritures_atomiques,
)
from smoke_diagnostic import test_diagnostic_complet, test_branchement_laisse_trace
from smoke_doc import test_renvois_doc
from smoke_firmware import test_firmware_extract, test_firmware_capture
from smoke_interface import (
    test_js, test_balises, test_ids, test_onclick, test_onglets,
    test_js_execute, test_aides_completes, test_reglages_sappliquent,
)
from smoke_i18n import test_i18n
from smoke_securite import (
    test_xss_profil_importe, test_profil_mal_type, test_pas_de_route_debug,
    test_une_seule_boucle_usb, test_empreinte_firmware_a_l_envoi,
    test_jeton_api, test_raccourcis_filtres,
    test_amorce_elevee_verifiee,
    test_journal_hors_boucle,
    test_ecritures_etat_sous_verrou,
    test_handler_robuste,
    test_profil_load_confine,
    test_ecritures_usb_comptees,
    test_part_unique,
    test_dmx_local,
    test_validation_entrees,
    test_handler_mince,
    test_etat_injecte,
)

sys.path.insert(0, str(HERE))


# ── 1. Les modules s'importent ────────────────────────────────────────────────

def test_imports():
    section("1. Import des modules")
    mods = {}
    # ⚠️ wing_diagnostic APRÈS wing_ui, dans cet ordre précis : les deux
    # s'importent l'un l'autre (wing_diagnostic lit l'état de wing_ui via
    # `core.X`), et en production wing_ui.py est TOUJOURS le point d'entrée
    # — c'est cet ordre qui rend le cycle sûr (wing_diagnostic.py, importé en
    # second, trouve wing_ui déjà réellement présent dans sys.modules).
    # Importé en premier, wing_diagnostic déclenche l'import de wing_ui, qui
    # tente alors de reprendre `build_diagnostic` sur un wing_diagnostic
    # encore à moitié exécuté — `ImportError`.
    for nom in ("wing_version", "wing_bridge", "wing_detect", "wing_mapper",
                "wing_init", "wing_ui", "wing_diagnostic", "wing_profils",
                "wing_ma3", "wing_raccourcis", "wing_touches_leds",
                "wing_faders", "wing_boutons", "wing_reglages",
                "wing_connexion", "wing_handler", "wing_keyboard",
                "wing_firmware_capture"):
        try:
            mods[nom] = __import__(nom)
            ok(f"{nom}")
        except Exception as e:
            echec(f"{nom} ne s'importe pas", f"{type(e).__name__}: {e}")
    return mods


def test_cycle_de_vie(ui):
    """Chantier « cycle de vie » : réutilisation d'onglet + arrêt à la fermeture.

    Trois pannes possibles, une assertion chacune :
      • une route disparaît de la table de routage → le navigateur poste dans le
        vide (l'onglet ne se réutilise plus, la fermeture n'éteint plus rien) ;
      • la logique d'arrêt différé est fausse → soit F5 tue l'app, soit un
        process serveur fantôme survit à la fermeture ;
      • RÉINJECTION ROUGE : sans fenêtre de grâce (grace=0), l'annulation d'un
        rechargement ne peut plus se produire — le verdict DOIT basculer sur
        'arret', sinon le contrôle serait vert sur du code qui ne s'annule
        jamais dans le temps imparti.
    """
    import wing_handler
    section("53. Cycle de vie : réutilisation d'onglet, arrêt à la fermeture")

    # 1. Les deux routes existent, câblées à une méthode RÉELLE.
    gets = dict(wing_handler.Handler.ROUTES_GET)
    posts = dict(wing_handler.Handler.ROUTES_POST)
    manque = []
    for table, chemin, methode in (
            (gets, "/api/instance", "_get_instance"),
            (posts, "/api/fermeture-onglet", "_post_fermeture_onglet")):
        if table.get(chemin) != methode:
            manque.append(f"{chemin} → table : {table.get(chemin)!r}")
        elif not callable(getattr(wing_handler.Handler, methode, None)):
            manque.append(f"{chemin} → méthode {methode} absente")
    if manque:
        echec("route(s) du cycle de vie manquante(s)", " ; ".join(manque)
              + " — sans elles, ni la réutilisation d'onglet ni l'extinction "
              "à la fermeture ne fonctionnent")
    else:
        ok("routes /api/instance (GET) et /api/fermeture-onglet (POST) câblées")

    # 2. La décision d'arrêt différé (fonction pure _vie_verdict).
    v = getattr(ui, "_vie_verdict", None)
    if not callable(v):
        echec("wing_ui._vie_verdict absente",
              "la décision d'arrêt différé doit être pure et testable")
        return
    #  armé à t0=100 ; grâce 5 s.
    cas = {
        "désarmé":            v(999.0, 0.0,   0.0,   5.0),   # rien d'armé
        "en attente":         v(100.2, 100.0, 0.0,   5.0),   # ni ping ni échéance
        "page revenue (F5)":  v(101.0, 100.0, 100.5, 5.0),   # ping après l'armement
        "grâce écoulée":      v(106.0, 100.0, 0.0,   5.0),   # échéance dépassée
    }
    attendu = {"désarmé": "rien", "en attente": "rien",
               "page revenue (F5)": "annule", "grâce écoulée": "arret"}
    if cas != attendu:
        echec("la logique d'arrêt différé est fausse",
              f"obtenu {cas} — attendu {attendu}")
        return

    #  RÉINJECTION ROUGE : grâce = 0 → un F5 ne peut plus sauver l'app.
    rouge = v(101.0, 100.0, 100.5, 0.0)
    if rouge != "arret":
        echec("le contrôle d'annulation ne voit pas sa propre panne",
              f"avec grâce=0, un rechargement a donné '{rouge}' au lieu de "
              "'arret' — l'annulation resterait verte alors qu'elle n'a plus "
              "aucune fenêtre pour s'exercer")
        return
    ok("arrêt différé : annulé si la page revient, honoré sinon "
       "(réinjection grâce=0 vue rouge)")

    # 4. 🐛 CORRIGÉ (27/09/2026) : launcher.sh sondait /api/status pour savoir
    # si un serveur tournait déjà — cette route est aussi le battement de
    # cœur de l'onglet (`_get_status` pose `UI_VIE["dernier_ping"]` à CHAQUE
    # appel, sans exception). Chaque relance rafraîchissait donc elle-même le
    # ping juste avant de demander « un onglet est-il ouvert ? » : la réponse
    # était toujours oui, même onglet fermé depuis longtemps, et le
    # navigateur ne se rouvrait jamais. `/api/instance` ne modifie rien
    # (wing_handler._get_instance) : c'est la seule route à utiliser pour une
    # simple sonde de présence.
    lch = (HERE / ".." / "src" / "launcher.sh")
    if not lch.exists():
        lch = HERE / "launcher.sh"
    if not lch.exists():
        note("launcher.sh introuvable — contrôle de la sonde sauté")
    else:
        texte = lch.read_text(encoding="utf-8")
        fautifs = [l.strip() for l in texte.splitlines()
                   if "curl" in l and "api/status" in l
                   and not l.strip().startswith("#")]
        if fautifs:
            echec("launcher.sh sonde /api/status (rafraîchit le battement de "
                  "cœur de l'onglet à chaque lancement)",
                  " ; ".join(fautifs) + " — utiliser /api/instance")
        else:
            ok("launcher.sh sonde /api/instance, jamais /api/status "
               "(ne perturbe pas le battement de cœur de l'onglet)")
        # Réinjection : l'ancienne ligne fautive doit être détectée.
        fautif_reinjecte = texte.replace(
            'curl -s -m 1 "$URL/api/instance"', 'curl -s -m 1 "$URL/api/status"')
        fautifs_reinjectes = [l.strip() for l in fautif_reinjecte.splitlines()
                              if "curl" in l and "api/status" in l
                              and not l.strip().startswith("#")]
        if not fautifs_reinjectes:
            echec("réinjection de la sonde /api/status non détectée",
                  "le contrôle ne verrait pas revenir le bug corrigé le "
                  "27/09/2026")
        else:
            ok("réinjection (sonde /api/status remise) → détectée")


# ── 22. Le numéro de build est exploitable ────────────────────────────────────

def test_build(wv):
    section("22. Numéro de build")
    if not isinstance(getattr(wv, "BUILD", None), int):
        echec("wing_version.BUILD absent ou non entier")
    elif wv.BUILD <= 0:
        note(f"BUILD = {wv.BUILD} (jamais buildé — normal avant le 1er build)")
    else:
        ok(f"build #{wv.BUILD} ({getattr(wv, 'BUILD_DATE', '?')})")


def _controle_doc_a_jour():
    """La doc annonce-t-elle le bon nombre de contrôles ?

    🧹 Ce chiffre a dérivé DEUX fois (22 annoncés pour 23, puis 25).
    Broutille en soi, mais symptôme que la doc décroche du code — et ce projet
    se fie beaucoup à sa doc. On le fait garder par la machine plutôt que par
    la vigilance.

    ⚠️ Appelé en FIN de main(), quand toutes les sections ont été jouées : le
    mettre au milieu compte les contrôles pas encore exécutés (erreur faite en
    l'écrivant).

    ⚠️ Seuls les fichiers qui annoncent l'état COURANT sont regardés.
    `HISTORIQUE.md` a le droit de porter un chiffre daté : c'est son rôle.
    """
    import re as _re
    section(f"{len(SECTIONS) + 1}. Doc à jour")
    reel = len(SECTIONS)
    faux = []

    # ⚠️ FAUX POSITIF déjà corrigé. La 1re version
    # lisait `RELEASES.md` en entier et s'étranglait sur sa propre entrée, qui
    # CITE l'ancien chiffre faux (« 22 contrôles annoncés partout ») pour
    # raconter le correctif. Une feuille de release est faite de phrases au
    # passé : on n'y vérifie donc QUE la ligne d'état courant.
    def _nombres(txt):
        return {int(n) for n in _re.findall(r"(\d+) contrôles", txt)}

    for nom in ("../GUIDE_PROJET.md", "../README.md"):
        f = HERE / nom
        if f.exists():
            faux += [f"{f.name} annonce {n}"
                     for n in _nombres(f.read_text(encoding="utf-8")) if n != reel]

    rel = HERE / ".." / "docs" / "RELEASES.md"   # tenu hors dépôt public
    if rel.exists():
        etat_doc = [l for l in rel.read_text(encoding="utf-8").splitlines()
                if l.startswith("| **Test de fumée**")]
        for l in etat_doc:
            faux += [f"RELEASES.md (ligne d'état) annonce {n}"
                     for n in _nombres(l) if n != reel]
    if faux:
        echec(f"la doc annonce un nombre de contrôles faux (réel : {reel})",
              " ; ".join(faux) + " — corriger, ou dater le chiffre comme "
              "historique s'il décrit le passé")
    else:
        ok(f"la doc annonce bien {reel} contrôles")

    # ── Numérotation des sections : ni trou, ni doublon ──────────────────────
    #
    # 🐛 Les numéros sont écrits EN DUR dans chaque `section(...)`. En ajoutant
    # un contrôle, « 27 » a été tapé alors qu'il était le 26e : le « 26 » a
    # disparu et le « 27 » est apparu deux fois. Personne ne l'aurait vu, et
    # une doc qui renvoie à « le contrôle nᵒX » aurait pointé vers rien.
    # (C'est justement ce que corrige la référence par nom de fonction, ex.
    # `test_boutons_wing_uniques`, plutôt que par numéro de section : elle ne
    # peut pas dériver silencieusement de la même façon.)
    nums = []
    for t in SECTIONS:
        m = _re.match(r"\s*(\d+)\.", t)
        if m:
            nums.append(int(m.group(1)))
    doublons = sorted({n for n in nums if nums.count(n) > 1})
    trous = [n for n in range(1, (max(nums) if nums else 0) + 1)
             if n not in nums]
    if doublons or trous:
        echec("la numérotation des contrôles est incohérente",
              (f"numéro(s) en double : {doublons} ; " if doublons else "")
              + (f"numéro(s) manquant(s) : {trous}" if trous else "")
              + " — les numéros sont écrits en dur dans chaque section()")
    else:
        ok(f"numérotation continue de 1 à {max(nums) if nums else 0}")

    # ── Le statut « OÙ ON EN EST » suit-il le build en service ? ─────────────
    #
    # 🔴 Règle : « il faut obligatoirement statuer où on en est, pour avoir un
    # suivi propre ».
    #
    # Ce projet a perdu des heures parce qu'une session repartait d'un état
    # SUPPOSÉ : une cause « confirmée » qui n'était que la moitié de l'histoire,
    # un correctif « fait » qui ne l'était pas. Un statut daté est ce qui évite
    # de re-débattre du tranché et de re-tenter l'échoué.
    #
    # ⚠️ TOLÉRANCE ASSUMÉE. On n'exige pas une mise à jour à chaque build : une
    # journée de mise au point en enchaîne dix, et bloquer là-dessus rendrait la
    # règle insupportable donc contournée. On exige que le statut ne prenne pas
    # plus de STATUT_RETARD_MAX builds de retard — assez pour travailler,
    # assez peu pour qu'une session ne se termine jamais sans statuer.
    #
    # 🔓 Le journal de bord daté ETAT_PROJET.md est tenu hors du dépôt public :
    # il reste EN LOCAL, où ce contrôle continue de faire son travail. Sur un
    # clone public il est simplement absent — on saute proprement, comme pour
    # ../GUIDE_PROJET.md plus haut, au lieu d'échouer.
    STATUT_RETARD_MAX = 6
    etat_doc = HERE / ".." / "docs" / "ETAT_PROJET.md"
    build_actuel = 0
    try:
        import wing_version as _wv
        build_actuel = int(getattr(_wv, "BUILD", 0))
    except Exception:
        pass
    if not etat_doc.exists():
        note("journal de bord ETAT_PROJET.md absent (tenu hors dépôt "
             "public) — contrôle du statut sauté")
    elif not build_actuel:
        note("build inconnu — contrôle du statut sauté")
    else:
        txt = etat_doc.read_text(encoding="utf-8")
        m = _re.search(r"##\s*📍\s*OÙ ON EN EST\s*—\s*build\s*(\d+)", txt)
        if not m:
            echec("le bloc « 📍 OÙ ON EN EST » est absent d'ETAT_PROJET.md",
                  "il doit être en tête et nommer le build en service — "
                  "voir la règle dans GUIDE_PROJET.md")
        else:
            statue = int(m.group(1))
            retard = build_actuel - statue
            if retard > STATUT_RETARD_MAX:
                echec(f"le statut a {retard} builds de retard "
                      f"(statué : {statue}, compilé : {build_actuel})",
                      "mettre à jour « 📍 OÙ ON EN EST » dans le journal de "
                      "bord ETAT_PROJET.md : build, ce qui marche (avec "
                      "preuve), ce qui ne marche pas, ce qui reste inconnu")
            else:
                # ⚠️ « compilé », PAS « en service ». Ce contrôle lit
                # wing_version.BUILD : ce qui a été BUILDÉ. Le moteur en
                # mémoire peut être plus vieux — c'est même le cas normal juste
                # après un build, et ce fichier passe son temps à prévenir que
                # les deux se confondent. Un contrôle ne peut pas dire ce qu'il
                # n'a pas vérifié : seul /api/status connaît le build en
                # service, et le test de fumée tourne sans app lancée.
                ok(f"statut à jour (build {statue}, compilé {build_actuel})")


# ── Point d'entrée ────────────────────────────────────────────────────────────

def main():
    print("\033[1m═══ Test de fumée — Wing Bridge ═══\033[0m")
    mods = test_imports()

    ui = mods.get("wing_ui")
    if ui is not None:
        html = ui.HTML
        test_js(html)
        test_balises(html)
        test_ids(html)
        test_onclick(html)
    else:
        echec("wing_ui absent — contrôles d'interface sautés")

    if mods.get("wing_mapper"):
        test_profil(mods["wing_mapper"])
        if mods.get("wing_keyboard"):
            test_raccourcis(mods["wing_mapper"], mods["wing_keyboard"])
    if mods.get("wing_bridge") and mods.get("wing_ui"):
        test_attributs(mods["wing_bridge"], mods["wing_ui"])
    if mods.get("wing_ui"):
        test_faders(mods["wing_ui"])
    if mods.get("wing_bridge") and mods.get("wing_init"):
        test_poll_pkt(mods["wing_bridge"], mods["wing_init"])
    test_plugin_lua()
    if ui is not None:
        test_executor_symetrie(ui)
        test_types_fader_documentes(ui, html)
        test_verbe_executor(ui)
        test_casse_motscles(ui)
        if mods.get("wing_mapper"):
            test_assistant(ui, mods["wing_mapper"])
            test_raccourcis_uniques(mods["wing_mapper"])
            if mods.get("wing_bridge"):
                test_forme_profil(mods["wing_mapper"], mods["wing_bridge"], ui)
            test_shcuts(ui, mods["wing_mapper"])
            test_shcuts_sonde(ui, mods["wing_mapper"])
        test_encodeurs_ma3(ui, html)
    if mods.get("wing_version"):
        test_build(mods["wing_version"])

    if ui is not None:
        test_boutons_honnetes(ui)
        test_sorties_rendent_la_wing(ui)
        test_boutons_wing_uniques(html)
        test_messages_actionnables(html)
        test_onglets(html)
        test_js_execute(html)
        test_diagnostic_osc(html)
    test_poignee_pendant_reboot()
    if ui is not None:
        test_appui_long_universel(ui)
        test_carte_led(ui)
        test_profil_favori(ui)
        test_import_profil(ui)
    if mods.get('wing_init'):
        test_blocage_jamais_definitif(mods['wing_init'])
    # ⚠️ APRÈS test_blocage_jamais_definitif, pour que l'ordre d'exécution suive
    # la numérotation des sections affichées : test_diagnostic_complet (36)
    # affiché avant test_blocage_jamais_definitif (35) donne l'impression d'un
    # contrôle sauté.
    if mods.get('wing_ui'):
        test_diagnostic_complet(mods['wing_ui'])
        test_reconnexion_sans_fantomes(mods['wing_ui'])
        test_groupe_encodeur_applique(mods['wing_ui'])
        test_branchement_laisse_trace(mods['wing_ui'])
    test_aides_completes(html)
    test_reglages_sappliquent(html)
    test_diagnostic_reseau(html)
    test_renvois_doc(html)
    if mods.get('wing_init'):
        test_fenetre_apres_fw_cfg(mods['wing_init'])
    if ui is not None:
        test_pickup_auto_repos(ui)
    if mods.get("wing_ma3"):
        test_ma3_etat_transitoire(mods["wing_ma3"])
    if ui is not None:
        test_desinstallation(ui)
    test_firmware_extract()
    test_firmware_capture()
    if mods.get("wing_ma3"):
        test_plugin_install(mods["wing_ma3"])

    # ⚠️ test_i18n numérote ses sections « 51 » et « 52 » en dur ; test_cycle_de_vie
    # « 53 ». Elles doivent rester dans cet ordre pour que l'affichage suive la
    # numérotation. test_plugin_slot (54) vient APRÈS elles : ajouter une
    # section entre 50 et 51 forcerait à renuméroter i18n/cycle_de_vie, alors
    # que 54 est libre — doc-à-jour s'auto-numérote juste au-dessus, en « 55 ».
    if ui is not None:
        test_i18n(html)
        test_cycle_de_vie(ui)
    if mods.get("wing_ma3"):
        test_plugin_slot(mods["wing_ma3"])
    if mods.get("wing_ui") and mods.get("wing_connexion"):
        test_connect_wing_verrou_et_boucle(mods["wing_ui"], mods["wing_connexion"])
    if mods.get("wing_connexion"):
        test_cycle_dmx_classificateur_partage(mods["wing_connexion"])
    if mods.get("wing_ui"):
        test_get_status_verrou_minimal(mods["wing_ui"])
    test_cmd_buf_verrouille()
    if mods.get("wing_ui"):
        test_double_clic_casse(mods["wing_ui"])

    # ── Audit Lot C (14/09/2026) : les 3 motifs systémiques repérés à la 2e
    # revue de code, au-delà des occurrences déjà listées ci-dessus ────────────
    test_lock_sans_appel_lent()
    if ui is not None:
        test_encodeurs_et_migration_casse_corrigees(ui)
        test_ecritures_atomiques(ui)
    if mods.get("wing_ma3"):
        test_port_ecoute_macos(mods["wing_ma3"])

    # ── Audit de sécurité et de robustesse (25/09/2026) — smoke_securite.py.
    # Chaque contrôle réinjecte le défaut qu'il garde et exige de le voir rouge.
    if ui is not None:
        test_xss_profil_importe(html)
    if mods.get("wing_ui") and mods.get("wing_connexion"):
        test_profil_mal_type(mods["wing_ui"], mods["wing_connexion"])
    if ui is not None:
        test_pas_de_route_debug(ui)
    if mods.get("wing_ui") and mods.get("wing_connexion"):
        test_une_seule_boucle_usb(mods["wing_ui"], mods["wing_connexion"])
    if mods.get("wing_init"):
        test_empreinte_firmware_a_l_envoi(mods["wing_init"])
    if ui is not None:
        test_jeton_api(ui)
        test_raccourcis_filtres(ui)

    test_amorce_elevee_verifiee()
    if ui is not None:
        test_journal_hors_boucle(ui)
    test_ecritures_etat_sous_verrou()
    if ui is not None:
        test_handler_robuste(ui)
    if ui is not None:
        test_profil_load_confine(ui)
    if ui is not None:
        test_ecritures_usb_comptees(ui)
    test_part_unique()
    test_dmx_local()
    if ui is not None:
        test_validation_entrees(ui)
    test_handler_mince()
    test_etat_injecte()
    _controle_doc_a_jour()

    print()
    if ECHECS:
        print(f"\033[31m\033[1m✗ {len(ECHECS)} ÉCHEC(S)\033[0m — build à ne PAS "
              f"lancer tant que ce n'est pas corrigé :")
        for e in ECHECS:
            print(f"    • {e}")
        return 1
    if NOTES:
        # 🐛 CE RÉSUMÉ DÉGUISAIT LES AVERTISSEMENTS.
        #
        # Il affichait « ({len(NOTES)} contrôle(s) sauté(s)) ». Or NOTES
        # collecte TOUTE remarque, pas les contrôles réellement sautés. Relevé :
        # les deux « contrôles sautés » annoncés étaient en fait
        # zéro contrôle sauté et deux constats à lire, dont celui-ci —
        #     « 4/64 écart(s) NON documenté(s) avec WingBridge.xml »
        # rebaptisé en un mot rassurant, en dernière ligne d'une sortie longue.
        #
        # 🔑 C'est le piège du projet appliqué à l'outil qui garde le projet :
        # un message qui affirme plus (ou moins) que ce qu'il a constaté. On
        # nomme donc ce que c'est, et on REMET les remarques sous les yeux —
        # sans quoi elles ont défilé cinquante lignes plus haut.
        print(f"\033[32m\033[1m✓ Tout passe\033[0m — "
              f"{len(NOTES)} remarque(s) à lire :")
        for n in NOTES:
            court = " ".join(str(n).split())
            print(f"    \033[33m•\033[0m "
                  f"{court[:150]}{'…' if len(court) > 150 else ''}")
        print("    (une remarque n'est pas un échec : c'est soit un contrôle "
              "non exécutable ici,\n     soit un constat à vérifier. Les deux "
              "méritent un coup d'œil avant de builder.)")
    else:
        print("\033[32m\033[1m✓ Tout passe\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
