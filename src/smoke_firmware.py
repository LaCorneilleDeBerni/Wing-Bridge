#!/usr/bin/env python3
"""
smoke_firmware.py — Wing Bridge
===============================
Contrôle de l'extraction du firmware depuis une capture (wing_firmware_extract).

Pourquoi ce contrôle. Le firmware n'est plus livré avec la distribution OSS :
chacun le reconstruit depuis SA capture. Si l'extracteur ressort des octets
faux, ou si `verify()` accepte un firmware qui ne correspond pas, l'utilisateur
enverrait un blob douteux à sa wing — et il n'a AUCUN moyen de s'en rendre
compte seul. Ce contrôle garde les trois promesses du module :

  • l'extracteur ressort EXACTEMENT les octets présents dans la capture ;
  • verify() REFUSE une taille fausse ET une empreinte fausse ;
  • une capture sans séquence d'upload lève une erreur CLAIRE (ExtractionError),
    jamais une exception nue.

⚠️ Ce contrôle ne dépend PAS du blob livré (`wing_firmware.bin`) : il travaille
sur une capture SYNTHÉTIQUE (motif connu, pas le firmware de MA — voir
fixtures/generer_capture_exemple.py). C'est exactement le découplage visé.
"""

import sys
from pathlib import Path

from smoke_core import HERE, ok, echec, note, section


def test_firmware_capture():
    """La capture intégrée du firmware (wing_firmware_capture.py, Windows).

    Trois promesses tenues SANS matériel ni USBPcap installé :
      • le module s'importe sur N'IMPORTE QUELLE plateforme (garde
        `sys.platform` — aucun appel Windows-only au niveau module) ;
      • les deux routes HTTP existent et pointent vers une méthode RÉELLE
        de Handler (un nom qui change d'un côté sans l'autre serait un
        bouton qui ne répond pas — cf. `test_boutons_honnetes`, même famille
        de piège) ;
      • la règle produit centrale — « ne désinstaller QUE ce qu'on a
        soi-même installé » — est vérifiée sur les 4 combinaisons possibles
        de _doit_garder_flag_installe(), la fonction PURE qui en décide.
    """
    section("49. Capture intégrée du firmware (USBPcap)")
    try:
        import wing_firmware_capture as fwc
    except Exception as e:
        echec("wing_firmware_capture ne s'importe pas",
              f"{type(e).__name__}: {e}")
        return
    ok("wing_firmware_capture s'importe (garde sys.platform respectée)")

    # ── Routage : les deux endpoints existent et répondent à un vrai bouton ──
    try:
        import wing_handler
    except Exception as e:
        echec("wing_handler ne s'importe pas", f"{type(e).__name__}: {e}")
        return
    routes = dict(wing_handler.Handler.ROUTES_POST)
    attendues = {
        "/api/firmware/capture": "_post_firmware_capture",
        "/api/firmware/remove_capture_component": "_post_firmware_remove_capture_component",
    }
    for chemin, methode in attendues.items():
        nom = routes.get(chemin)
        if nom is None:
            echec(f"route absente : {chemin}")
            continue
        if nom != methode:
            echec(f"route {chemin} pointe vers {nom!r}, {methode!r} attendu")
            continue
        if not callable(getattr(wing_handler.Handler, nom, None)):
            echec(f"Handler.{nom} n'existe pas — {chemin} répondrait 500")
            continue
        ok(f"{chemin} → Handler.{nom}")

    # ── La règle produit : ne désinstaller QUE ce qu'on a soi-même installé ──
    cas = [
        # (installed_by_us, uninstall_ok)              -> flag attendu
        (False, None,  False),   # jamais installé par nous : rien à garder
        (False, True,  False),   # idem, même si un uninstall_ok traîne
        (True,  True,  False),   # installé PAR NOUS, nettoyage confirmé RÉUSSI
        (True,  False, True),    # installé PAR NOUS, nettoyage confirmé ÉCHOUÉ
        (True,  None,  True),    # installé PAR NOUS, nettoyage JAMAIS confirmé
    ]
    tous_bons = True
    for installed_by_us, uninstall_ok, attendu in cas:
        obtenu = fwc._doit_garder_flag_installe(installed_by_us, uninstall_ok)
        if obtenu != attendu:
            tous_bons = False
            echec("_doit_garder_flag_installe() se trompe",
                  f"installed_by_us={installed_by_us}, uninstall_ok={uninstall_ok!r} "
                  f"→ {obtenu!r} (attendu {attendu!r})")
    if tous_bons:
        ok("_doit_garder_flag_installe() : ne garde le flag QUE si installé "
           "par nous ET nettoyage non confirmé (5/5 cas)")

    # ── Assistant à cartons : les détections et l'état de carton ─────────────
    # L'assistant (cartons 1→7) repose sur deux détections qui ACTIVENT le clic
    # « Suivant » (elles ne font plus avancer, depuis le 13/11/2026). Elles
    # doivent exister, être multiplateformes (rendre False proprement hors
    # Windows / sans matériel), et CAPTURE_STATE doit exposer la progression
    # à l'UI (cartons, pastilles, suivant_possible).
    manque = [n for n in ("gma2_onpc_lance", "wing_sur_bus", "_phase", "_attendre",
                          "_attendre_suivant", "suivant_capture", "_SondeAbsenceDurable")
              if not callable(getattr(fwc, n, None))]
    if manque:
        echec("l'assistant à cartons a perdu une brique",
              "absent(s) de wing_firmware_capture : " + ", ".join(manque))
    else:
        try:
            d1 = fwc.gma2_onpc_lance()
            d2 = fwc.wing_sur_bus()
        except Exception as e:
            echec("une détection d'étape lève au lieu de rendre un bool",
                  f"{type(e).__name__}: {e}")
        else:
            if isinstance(d1, bool) and isinstance(d2, bool):
                ok("détections d'étape OK (gma2_onpc_lance / wing_sur_bus "
                   "rendent un bool, sans matériel ni Windows)")
            else:
                echec("une détection d'étape ne rend pas un bool",
                      f"gma2_onpc_lance→{d1!r}, wing_sur_bus→{d2!r}")

    # ── Étape 2 : une absence DURABLE, pas un clignement (Asus, 12/11/2026) ──
    # Tentative 1 sur l'Asus : « Débranche ta wing » a avancé SANS aucun
    # débranchement, puis « wing revue sur le bus ». Un seul échantillon
    # « absente » suffisait — or une ré-énumération (firmware poussé par
    # grandMA2 onPC) sort la wing du bus ~1,3 s (docs/HARDWARE.md). On simule
    # wing_sur_bus() rendant T, F, T, T puis F×n : l'étape ne doit PAS avancer
    # sur le F isolé, et DOIT avancer sur la série. Timeout et annulation
    # doivent rester respectés.
    # Le seuil est ALIGNÉ sur celui de la boucle USB pour la même question
    # (wing_ui.ABSENCE_REELLE_S = 5 s) : la constante est recopiée dans
    # wing_firmware_capture (pas d'import de wing_ui au niveau module), c'est
    # donc ICI qu'on empêche les deux de dériver l'une de l'autre.
    # Réinjection : passer `consecutifs=1` dans wing_absente_durablement() (ou
    # ABSENCE_DURABLE_ECHANTILLONS = 1) fait retomber ce contrôle à ROUGE.
    import inspect as _inspect
    import wing_ui as _core
    if not callable(getattr(fwc, "wing_absente_durablement", None)) \
            or not hasattr(fwc, "ABSENCE_DURABLE_ECHANTILLONS"):
        echec("l'étape 2 n'exige plus une absence durable de la wing",
              "attendu : wing_absente_durablement() + ABSENCE_DURABLE_ECHANTILLONS")
    elif (fwc.ABSENCE_DURABLE_ECHANTILLONS - 1) * 1.0 < _core.ABSENCE_REELLE_S:
        echec("l'étape 2 exige une absence plus courte que la boucle USB (incohérence)",
              f"ABSENCE_DURABLE_ECHANTILLONS = {fwc.ABSENCE_DURABLE_ECHANTILLONS!r} "
              f"→ {fwc.ABSENCE_DURABLE_ECHANTILLONS - 1} s à 1 Hz, "
              f"< wing_ui.ABSENCE_REELLE_S = {_core.ABSENCE_REELLE_S} s")
    else:
        n = fwc.ABSENCE_DURABLE_ECHANTILLONS
        sauv_bus = fwc.wing_sur_bus
        try:
            # A — présente, UN clignement, présente ×2, puis absence franche.
            seq = [True, False, True, True] + [False] * n
            vus = []
            def faux_bus():
                v = seq[len(vus)] if len(vus) < len(seq) else False
                vus.append(v)
                return v
            fwc.wing_sur_bus = faux_bus
            fwc._ANNULER.clear()
            r_serie = fwc.wing_absente_durablement(5.0, intervalle=0.01)
            sondes = len(vus)
            # B — clignements perpétuels (T, F, T, F…) : jamais validé → timeout.
            compteur = []
            def clignote():
                compteur.append(1)
                return len(compteur) % 2 == 1
            fwc.wing_sur_bus = clignote
            r_clignote = fwc.wing_absente_durablement(0.3, intervalle=0.01)
            # C — annulation demandée : False tout de suite, wing absente ou pas.
            fwc.wing_sur_bus = lambda: False
            fwc._ANNULER.set()
            r_annule = fwc.wing_absente_durablement(5.0, intervalle=0.01)
        finally:
            fwc.wing_sur_bus = sauv_bus
            fwc._ANNULER.clear()
        attendu = len(seq)
        if r_serie is not True or sondes != attendu:
            echec("l'étape 2 valide le débranchement sur un échantillon « absente » isolé",
                  f"wing_sur_bus() sondée {sondes}× (attendu {attendu} : T, F, T, T "
                  f"puis F×{n}), rendu {r_serie!r}")
        elif r_clignote is not False:
            echec("l'étape 2 valide le débranchement sur des clignements perpétuels",
                  f"rendu {r_clignote!r} au lieu de False (timeout)")
        elif r_annule is not False:
            echec("wing_absente_durablement() ignore l'annulation (_ANNULER)",
                  f"rendu {r_annule!r}")
        else:
            ok(f"étape 2 : un échantillon « absente » isolé n'avance pas, {n} d'affilée "
               f"(≈{n - 1} s à 1 Hz, ≥ ABSENCE_REELLE_S = {_core.ABSENCE_REELLE_S} s) "
               "oui ; clignements → timeout ; annulation respectée")
        # Garde STATIQUE : les deux « débranche ta wing » de capturer_firmware
        # (cartons 1 et 5) passent par la sonde à état _SondeAbsenceDurable —
        # un retour à `_attendre(lambda: not wing_sur_bus(), …)` nu (un seul
        # échantillon) serait le bug de l'Asus réintroduit. La sonde est aussi
        # ce sur quoi repose wing_absente_durablement() : une seule règle.
        try:
            src_cap = _inspect.getsource(fwc.capturer_firmware)
            bloc1 = src_cap.split("Carton 1/7", 1)[1].split("Carton 2/7", 1)[0]
            bloc5 = src_cap.split("Carton 5/7", 1)[1].split("Carton 6/7", 1)[0]
        except (IndexError, OSError, TypeError):
            src_cap, bloc1, bloc5 = "", "", ""
        if "_attendre(lambda: not wing_sur_bus()" in src_cap:
            echec("capturer_firmware juge encore un débranchement sur UN échantillon",
                  "`_attendre(lambda: not wing_sur_bus(), …)` nu — bug de l'Asus")
        elif "_SondeAbsenceDurable()" not in bloc1 or "_SondeAbsenceDurable()" not in bloc5:
            echec("un « débranche ta wing » (carton 1 ou 5) ne passe pas par _SondeAbsenceDurable",
                  f"carton 1 : {'_SondeAbsenceDurable()' in bloc1}, carton 5 : "
                  f"{'_SondeAbsenceDurable()' in bloc5}")
        elif "_SondeAbsenceDurable()" not in _inspect.getsource(fwc.wing_absente_durablement):
            echec("wing_absente_durablement() ne repose plus sur _SondeAbsenceDurable",
                  "deux implémentations de la règle « absence durable » dériveraient")
        else:
            ok("cartons 1 et 5 + wing_absente_durablement() : une seule sonde "
               "d'absence durable (_SondeAbsenceDurable), jamais _attendre() nu")
    # ── Garde d'architecture : Windows x64 seulement, PAS Windows ARM ───────
    # USBPcap (pilote-filtre noyau) et grandMA2 onPC n'existent qu'en x64.
    # capture_supportee() sert à l'UI pour MASQUER la carte — un faux positif
    # ici = un bouton qui ne peut pas marcher (même famille que
    # `test_boutons_honnetes`).
    if not callable(getattr(fwc, "capture_supportee", None)):
        echec("wing_firmware_capture.capture_supportee absente",
              "la garde Windows-x64 / anti-ARM a disparu")
    else:
        import os as _os
        attendu = sys.platform.startswith("win") and not fwc._windows_arm()
        if fwc.capture_supportee() is not attendu:
            echec("capture_supportee() se trompe de plateforme",
                  f"→ {fwc.capture_supportee()!r} (attendu {attendu!r})")
        else:
            # Réinjection : un hôte « ARM » doit fermer la capture, quelle que
            # soit la plateforme de test (on force la variable d'env que
            # Windows pose sous émulation).
            _sauv = _os.environ.get("PROCESSOR_ARCHITEW6432")
            _os.environ["PROCESSOR_ARCHITEW6432"] = "ARM64"
            try:
                arm_vu = fwc._windows_arm()
                res = fwc.capturer_firmware()
                if sys.platform.startswith("win"):
                    if not arm_vu:
                        echec("_windows_arm() rate PROCESSOR_ARCHITEW6432=ARM64")
                    elif res.get("ok") is not False:
                        echec("capturer_firmware() ne refuse pas sur hôte ARM",
                              repr(res))
                    else:
                        ok("garde d'architecture : ARM réinjecté → capture "
                           "masquée et refusée (Windows x64 seulement)")
                else:
                    # Hors Windows _windows_arm() reste False (garde sys.platform)
                    # et capturer_firmware() refuse déjà « hors Windows ».
                    if arm_vu or res.get("ok") is not False:
                        echec("garde d'architecture incohérente hors Windows",
                              f"_windows_arm()={arm_vu!r}, capturer→{res!r}")
                    else:
                        ok("garde d'architecture : capture indisponible hors "
                           "Windows x64 (anti-ARM vérifié)")
            finally:
                if _sauv is None:
                    _os.environ.pop("PROCESSOR_ARCHITEW6432", None)
                else:
                    _os.environ["PROCESSOR_ARCHITEW6432"] = _sauv

    cle_phase = {"phase", "phase_total", "phase_titre", "chemin"}
    if cle_phase <= set(fwc.CAPTURE_STATE):
        ok("CAPTURE_STATE expose la progression de l'assistant "
           "(phase / phase_total / phase_titre / chemin)")
    else:
        echec("CAPTURE_STATE ne porte pas la progression de l'assistant",
              "manque : " + ", ".join(sorted(cle_phase - set(fwc.CAPTURE_STATE))))

    # ── Délai minimum de LISIBILITÉ d'un carton ─────────────────────────────
    # Les transitions AUTOMATIQUES (carton 7 → « Wing connectée », titres de
    # fin) ne doivent pas « clignoter » : chaque carton reste affiché AU MOINS
    # _PHASE_MIN_S. L'ancienne surcharge de 10 s sur « Débranche ta wing »
    # (_PHASE_TENIR) n'a plus d'objet : ce geste est un carton à clic.
    # Réinjection : ramener _phase() à une simple assignation (retirer
    # l'attente) fait retomber ce contrôle à ROUGE.
    import time as _t
    if not hasattr(fwc, "_PHASE_MIN_S") or not hasattr(fwc, "_phase_horodate") \
            or not hasattr(fwc, "_phase_min"):
        echec("_phase() n'a plus de garde-temps (le carton peut « clignoter »)",
              "attendu : _PHASE_MIN_S + _phase_horodate + _phase_min")
    else:
        fwc._reset_state()
        t0 = _t.monotonic()
        fwc._phase(1, "première")          # jamais retardée (horodate à 0)
        premiere = _t.monotonic() - t0
        t1 = _t.monotonic()
        fwc._phase(2, "deuxième")          # doit tenir la 1re ~_PHASE_MIN_S
        seconde = _t.monotonic() - t1
        # 3e appel : on impose 10 s de tenue au 2e carton puis on ANNULE pour
        # ne pas bloquer le smoke 10 s : _phase() coupe son attente sur _ANNULER.
        fwc._phase_min[0] = 10.0
        fwc._ANNULER.set()
        t2 = _t.monotonic()
        fwc._phase(3, "troisième")
        troisieme = _t.monotonic() - t2
        fwc._reset_state()
        marge = fwc._PHASE_MIN_S - 0.4
        if premiere > 0.5:
            echec("_phase() retarde le PREMIER carton", f"{premiere:.2f} s")
        elif seconde < marge:
            echec("_phase() ne tient pas le carton précédent assez longtemps",
                  f"{seconde:.2f} s < {marge:.2f} s (la consigne clignote)")
        elif troisieme > 2.0:
            echec("_phase() n'interrompt pas son attente sur une annulation",
                  f"{troisieme:.2f} s alors que _ANNULER est posé")
        else:
            ok(f"_phase() tient chaque carton ≥ {fwc._PHASE_MIN_S} s, "
               "coupe net sur annulation")

    # ── Annuler la démarche « à tout moment » ──────────────────────────────
    # Le bouton pose _ANNULER ; la capture s'arrête proprement (et retire
    # USBPcap si besoin). Route + fonction publique doivent exister.
    routes2 = dict(wing_handler.Handler.ROUTES_POST)
    if routes2.get("/api/firmware/capture/cancel") != "_post_firmware_capture_cancel":
        echec("route d'annulation absente",
              f"table : {routes2.get('/api/firmware/capture/cancel')!r}")
    elif not callable(getattr(wing_handler.Handler, "_post_firmware_capture_cancel", None)):
        echec("Handler._post_firmware_capture_cancel n'existe pas")
    elif not callable(getattr(fwc, "annuler_capture", None)):
        echec("wing_firmware_capture.annuler_capture absente")
    else:
        fwc._reset_state()
        r_inactif = fwc.annuler_capture()          # rien en cours
        fwc.CAPTURE_STATE["actif"] = True
        r_actif = fwc.annuler_capture()            # simulate capture en cours
        pose = fwc._ANNULER.is_set()
        fwc._reset_state()
        if not r_inactif.get("ok"):
            echec("annuler_capture() sans capture en cours devrait être un no-op OK",
                  repr(r_inactif))
        elif not (r_actif.get("ok") and r_actif.get("annulation") and pose):
            echec("annuler_capture() ne pose pas le drapeau d'arrêt", repr(r_actif))
        else:
            ok("annuler la démarche : route + drapeau _ANNULER, no-op si rien "
               "en cours, arrêt propre demandé sinon")

    _controle_messages_capture(fwc)
    _controle_assistant_cartons(fwc, wing_handler)
    _controle_chantier_f(fwc)


def _controle_assistant_cartons(fwc, wing_handler):
    """L'assistant est SEMI-AUTOMATIQUE : 7 cartons validés par un clic.

    Décision de l'auteur (13/11/2026) : les deux échecs connus (Dell, Asus
    12/11) viennent d'un assistant qui AVANÇAIT TOUT SEUL sur une détection
    fausse ou trop tôt. Quatre promesses, chacune vue ROUGE par réinjection
    (sorties dans le rapport du chantier E, docs/WINDOWS.md) :
      (1) `_attendre_suivant()` ne rend la main QUE sur un clic vu alors que
          la détection est verte : un clic au rouge est ignoré (et journalisé),
          l'annulation coupe net, `abandon()` aussi, et le filet de temps
          finit par rendre False sans jamais valider ;
      (2) dans `capturer_firmware`, chaque partie AUTOMATIQUE (élévation /
          installation, extraction, retrait d'USBPcap) est précédée de
          l'attente du clic du carton qui la déclenche (1 → 2, 2 → 3, 5 → 6) ;
          et la fenêtre passée au script élevé couvre les filets Python (sinon
          le script retire USBPcap seul, 360 s après la fin de sa capture) ;
      (3) la route POST /api/firmware/capture/suivant existe, refuse (409) sans
          capture active ou hors attente, et pose l'événement sinon ;
      (4) côté interface, « Suivant » n'est actif que sur suivant_possible
          (fwSuivantActif, exécutée dans node) et l'état des cartons suit
          `phase` / `interrompu_au` (fwEtatCarton).
    """
    import inspect
    import json
    import re as _re
    import subprocess
    import time as _t

    # ── (1) _attendre_suivant : clic au rouge ignoré, clic au vert rend la main
    journal = []
    sauv_log = fwc._log
    fwc._log = lambda cle, **p: journal.append((cle, p))
    try:
        fwc._reset_state()
        fwc.CAPTURE_STATE["actif"] = True
        appels = []

        def detection():
            # 1er tour : ROUGE + un clic posé → doit être IGNORÉ.
            # 2e tour : rouge, pas de clic.  3e tour : VERT + clic → rend la main.
            n = len(appels) + 1
            appels.append(n)
            if n == 1:
                fwc._SUIVANT.set()
                return [fwc._pastille("x", "rouge", "firmware.pastille.ma2_ko")]
            if n == 2:
                return [fwc._pastille("x", "rouge", "firmware.pastille.ma2_ko")]
            fwc._SUIVANT.set()
            return [fwc._pastille("x", "vert", "firmware.pastille.ma2_ok")]

        r_clic = fwc._attendre_suivant(1, detection, timeout_s=5.0, intervalle=0.01)
        nb_appels = len(appels)
        cles = [c for c, _ in journal]
        attente_apres = fwc.CAPTURE_STATE["attente_utilisateur"]
        possible_apres = fwc.CAPTURE_STATE["suivant_possible"]
        # Filet : détection verte mais PERSONNE ne clique → False, jamais True.
        journal.clear()
        r_filet = fwc._attendre_suivant(
            2, lambda: [fwc._pastille("x", "vert", "firmware.pastille.ma2_ok")],
            timeout_s=0.05, intervalle=0.01)
        cles_filet = [c for c, _ in journal]
        # Annulation : False tout de suite, même détection verte + clic posé.
        fwc._ANNULER.set()
        fwc._SUIVANT.set()
        t0 = _t.monotonic()
        r_annule = fwc._attendre_suivant(
            3, lambda: [fwc._pastille("x", "vert", "firmware.pastille.ma2_ok")],
            timeout_s=5.0, intervalle=0.01)
        d_annule = _t.monotonic() - t0
        fwc._ANNULER.clear()
        # Abandon : la condition extérieure rend le carton caduc → False.
        journal.clear()
        r_abandon = fwc._attendre_suivant(
            4, lambda: [fwc._pastille("x", "vert", "firmware.pastille.ma2_ok")],
            timeout_s=5.0, intervalle=0.01, abandon=lambda: True)
        cles_abandon = [c for c, _ in journal]
    finally:
        fwc._log = sauv_log
        fwc._reset_state()
    if r_clic is not True or nb_appels != 3:
        echec("(1) _attendre_suivant : le clic au ROUGE a été accepté (ou le vert refusé)",
              f"rendu {r_clic!r} après {nb_appels} détection(s) — attendu True après 3 "
              "(rouge+clic ignoré, rouge, vert+clic pris)")
    elif "journal.fw.capture_suivant_ignore" not in cles \
            or "journal.fw.capture_suivant_clic" not in cles:
        echec("(1) _attendre_suivant : clic ignoré / clic pris non journalisés", repr(cles))
    elif attente_apres or possible_apres:
        echec("(1) _attendre_suivant laisse attente_utilisateur / suivant_possible à vrai en sortant",
              f"attente={attente_apres!r}, possible={possible_apres!r}")
    elif r_filet is not False or "journal.fw.capture_suivant_expire" not in cles_filet:
        echec("(1) _attendre_suivant : le filet de temps ne rend pas False (ou sans journal)",
              f"rendu {r_filet!r}, journal {cles_filet!r}")
    elif r_annule is not False or d_annule > 1.0:
        echec("(1) _attendre_suivant ignore l'annulation",
              f"rendu {r_annule!r} en {d_annule:.2f} s")
    elif r_abandon is not False or "journal.fw.capture_carton_abandon" not in cles_abandon:
        echec("(1) _attendre_suivant : `abandon()` n'interrompt pas l'attente",
              f"rendu {r_abandon!r}, journal {cles_abandon!r}")
    else:
        ok("(1) _attendre_suivant : clic au rouge ignoré + journalisé, clic au vert "
           "rend la main, filet → False, annulation et abandon coupent net")

    # ── (2) audit de source : chaque partie automatique attend SON clic ─────
    src = inspect.getsource(fwc.capturer_firmware)

    def _bloc(n):
        try:
            return src.split(f"Carton {n}/7", 1)[1].split(f"Carton {n + 1}/7", 1)[0]
        except IndexError:
            return ""
    blocs = {n: _bloc(n) for n in range(1, 7)}
    attendu = {
        # carton : (clic attendu dans ce carton, partie automatique du suivant)
        1: ("_attendre_suivant(1,", "_lancer_eleve("),
        2: ("_attendre_suivant(2,", "extract_from_pcapng("),
        5: ("_attendre_suivant(5,", "_feu_vert_nettoyage()"),
    }
    defauts = []
    for n, (clic, auto) in attendu.items():
        b_clic, b_auto = blocs[n], blocs[n + 1]
        if not b_clic or not b_auto:
            defauts.append(f"marqueur « Carton {n}/7 » ou « Carton {n + 1}/7 » introuvable")
            continue
        if clic not in b_clic:
            defauts.append(f"carton {n} : aucun `{clic}` avant la partie automatique "
                           f"du carton {n + 1} ({auto})")
        if auto not in b_auto:
            defauts.append(f"carton {n + 1} : `{auto}` attendu dans ce bloc")
    for n in (3, 4, 6):
        if f"_attendre_suivant({n}," not in blocs[n]:
            defauts.append(f"carton {n} : pas d'attente du clic « Suivant »")
    # Le script élevé ne doit jamais retirer USBPcap de lui-même pendant qu'on
    # attend un clic : sa fenêtre couvre 4 cartons × TIMEOUT_CLIC_S.
    f_fen = getattr(fwc, "_fenetre_script_s", None)
    if not callable(f_fen):
        defauts.append("_fenetre_script_s absente (TimeoutS du script élevé non dimensionné)")
    elif f_fen(150.0) < 4 * fwc.TIMEOUT_CLIC_S + 150.0 + fwc.GRACE_APRES_WING_S:
        defauts.append(f"_fenetre_script_s(150) = {f_fen(150.0)} s < 4 × TIMEOUT_CLIC_S "
                       f"+ 150 + grâce : le script retirerait USBPcap avant les filets Python")
    elif '"TimeoutS": str(_fenetre_script_s(timeout_s))' not in src:
        defauts.append("le script élevé ne reçoit pas _fenetre_script_s(timeout_s) en TimeoutS")
    if fwc.TIMEOUT_CLIC_S < 600.0:
        defauts.append(f"TIMEOUT_CLIC_S = {fwc.TIMEOUT_CLIC_S} s : un filet, pas un moteur — "
                       "au moins 10 min")
    if defauts:
        echec("(2) une partie automatique de capturer_firmware part sans le clic « Suivant »",
              " ; ".join(defauts))
    else:
        ok("(2) capturer_firmware : élévation, extraction et retrait d'USBPcap sont "
           "chacun précédés de l'attente du clic du carton qui les déclenche ; "
           f"fenêtre du script ≥ 4 × {int(fwc.TIMEOUT_CLIC_S)} s")

    # ── (3) la route « Suivant » : 409 sans capture / hors attente, événement sinon
    routes = dict(wing_handler.Handler.ROUTES_POST)
    nom = routes.get("/api/firmware/capture/suivant")
    if nom != "_post_firmware_capture_suivant" \
            or not callable(getattr(wing_handler.Handler, nom or "", None)):
        echec("(3) route /api/firmware/capture/suivant absente ou sans méthode",
              f"table : {nom!r}")
    else:
        def _poster_suivant():
            h = wing_handler.Handler.__new__(wing_handler.Handler)
            rendu = {}
            h._json = lambda d, code=200: rendu.update(d, _code=code)
            h._post_firmware_capture_suivant({})
            return rendu
        fwc._reset_state()
        # Aucune capture active — avec un `attente_utilisateur` résiduel à
        # vrai, pour que ce cas ne soit pas confondu avec « hors attente » :
        # réinjection (retirer le test `actif` de suivant_capture) → 200 → ROUGE.
        fwc.CAPTURE_STATE["attente_utilisateur"] = True
        r_inactif = _poster_suivant()                       # aucune capture
        fwc.CAPTURE_STATE["actif"] = True
        fwc.CAPTURE_STATE["attente_utilisateur"] = False
        r_auto = _poster_suivant()                          # partie automatique
        pose_auto = fwc._SUIVANT.is_set()
        fwc.CAPTURE_STATE["attente_utilisateur"] = True
        fwc.CAPTURE_STATE["suivant_possible"] = True
        r_attente = _poster_suivant()                       # en attente du clic
        pose_attente = fwc._SUIVANT.is_set()
        fwc._reset_state()
        if r_inactif.get("_code") != 409 or r_inactif.get("ok") is not False:
            echec("(3) /api/firmware/capture/suivant sans capture active ne répond pas 409",
                  repr(r_inactif))
        elif r_auto.get("_code") != 409 or pose_auto:
            echec("(3) /api/firmware/capture/suivant pendant une partie automatique "
                  "ne répond pas 409 (ou pose l'événement)", f"{r_auto!r}, posé={pose_auto}")
        elif r_attente.get("_code") != 200 or not r_attente.get("ok") or not pose_attente:
            echec("(3) /api/firmware/capture/suivant en attente ne pose pas l'événement",
                  f"{r_attente!r}, posé={pose_attente}")
        else:
            ok("(3) /api/firmware/capture/suivant : 409 sans capture, 409 hors attente, "
               "200 + événement _SUIVANT posé en attente")

    # ── (4) l'interface n'active « Suivant » que sur suivant_possible ───────
    js = (HERE / "ui" / "parametres.js").read_text(encoding="utf-8")
    m_actif = _re.search(r"^function fwSuivantActif\(cap\) \{.*?^\}", js, _re.S | _re.M)
    m_etat = _re.search(r"^function fwEtatCarton\(i, cap\) \{.*?^\}", js, _re.S | _re.M)
    if not m_actif or not m_etat:
        echec("(4) fwSuivantActif / fwEtatCarton introuvables dans ui/parametres.js")
        return
    if "btn.disabled = !fwSuivantActif(cap)" not in js:
        echec("(4) le bouton « Suivant » n'est pas piloté par fwSuivantActif",
              "attendu : `btn.disabled = !fwSuivantActif(cap)` dans _fwCaptureCartons")
        return
    node = None
    for cand in ("node", "/opt/homebrew/bin/node", "/usr/local/bin/node"):
        try:
            subprocess.run([cand, "--version"], capture_output=True, timeout=5)
            node = cand
            break
        except Exception:
            continue
    if not node:
        note("(4) node introuvable — fwSuivantActif non exécutée (audit statique seul)")
        return
    etats = {
        "vert":        {"actif": True,  "attente_utilisateur": True,  "suivant_possible": True},
        "rouge":       {"actif": True,  "attente_utilisateur": True,  "suivant_possible": False},
        "automatique": {"actif": True,  "attente_utilisateur": False, "suivant_possible": True},
        "fini":        {"actif": False, "attente_utilisateur": True,  "suivant_possible": True},
    }
    script = (m_actif.group(0) + "\n" + m_etat.group(0) + "\nconst E = " + json.dumps(etats)
              + ";\nconst R = {}; for (const k in E) R[k] = fwSuivantActif(E[k]);"
              "\nR.nul = fwSuivantActif(null);"
              "\nR.cartons = [1,2,3,4,5,6,7].map(i => fwEtatCarton(i, {phase: 6, interrompu_au: 3}));"
              "\nprocess.stdout.write(JSON.stringify(R));")
    r = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        echec("(4) fwSuivantActif a planté dans node", r.stderr[:300])
        return
    res = json.loads(r.stdout)
    attendu_cartons = ["fait", "fait", "fait", "saute", "saute", "en_cours", "a_venir"]
    if res.get("vert") is not True:
        echec("(4) « Suivant » reste inactif alors que le serveur dit suivant_possible", repr(res))
    elif any(res.get(k) for k in ("rouge", "automatique", "fini", "nul")):
        echec("(4) « Suivant » s'active sans suivant_possible (détection rouge, partie "
              "automatique, capture finie ou état nul)", repr(res))
    elif res.get("cartons") != attendu_cartons:
        echec("(4) fwEtatCarton se trompe (phase 6, interrompu au 3)",
              f"{res.get('cartons')!r} ≠ {attendu_cartons!r}")
    else:
        ok("(4) interface : « Suivant » actif sur suivant_possible seulement (4 états + nul, "
           "exécutés dans node) ; cartons fait / sauté / en cours / à venir cohérents")


def _controle_chantier_f(fwc):
    """Chantier F (16/11/2026) : retours du test réel de l'assistant sur l'Asus.

    Cinq promesses, chacune vue ROUGE par réinjection (rapport du chantier F) :
      (a) `button.btn:disabled` existe (grisé, curseur interdit) — « Suivant »
          bloqué restait jaune plein ;
      (b) le panneau se FERME dès que actif=false sans échec à montrer
          (succès, annulation) ; modal seulement pendant la capture ; le bouton
          « Capturer » disparaît pendant ;
      (c) l'import manuel n'est masqué QUE si s.capture est non null ;
      (d) une annulation voulue a sa clé de journal, distincte de l'échec ;
      (e) « firmware manquant » renvoie vers « Capturer » si s.capture non null,
          vers l'import sinon — et toutes les clés existent en fr ET en en.
    """
    import json
    import re as _re
    import subprocess
    html = (HERE / "wing_ui.html").read_text(encoding="utf-8")
    js = (HERE / "ui" / "parametres.js").read_text(encoding="utf-8")
    jsb = (HERE / "ui" / "bridge.js").read_text(encoding="utf-8")
    fr = json.loads((HERE / "locales" / "fr.json").read_text(encoding="utf-8"))
    en = json.loads((HERE / "locales" / "en.json").read_text(encoding="utf-8"))

    # (a) règle CSS
    m = _re.search(r"button\.btn:disabled[^{]*\{[^}]*\}", html)
    if not m or "not-allowed" not in m.group(0) or "opacity" not in m.group(0):
        echec("(5a) pas de règle `button.btn:disabled` (grisé + not-allowed) dans wing_ui.html")
    else:
        ok("(5a) règle `button.btn:disabled` présente (opacité réduite, curseur interdit)")

    # (d) clé de journal d'annulation
    h = (HERE / "wing_handler.py").read_text(encoding="utf-8")
    cle = "journal.fw.capture_annulee_utilisateur"
    i_ann = h.find('elif res.get("annule")')
    i_ko = h.find('core.log("journal.fw.capture_ko"')
    if not (0 < i_ann < i_ko) or cle not in h[i_ann:i_ko]:
        echec("(5d) une annulation voulue n'a pas sa propre clé de journal (avant le « capture_ko »)")
    elif cle not in fr or cle not in en or fr[cle] == fr.get("journal.fw.capture_ko") \
            or "échou" in fr[cle] or "failed" in en[cle]:
        echec("(5d) clé de journal d'annulation absente en fr/en ou qui parle d'échec")
    else:
        ok("(5d) annulation voulue : clé de journal distincte et neutre (fr + en)")

    # (b)(c)(e) en node
    node = None
    for cand in ("node", "/opt/homebrew/bin/node", "/usr/local/bin/node"):
        try:
            subprocess.run([cand, "--version"], capture_output=True, timeout=5)
            node = cand
            break
        except Exception:
            continue
    m_aff = _re.search(r"^function fwAffichageCapture\(cap, manuelDeplie\) \{.*?^\}", js, _re.S | _re.M)
    m_cles = _re.search(r"^function clesFirmwareManquant\(s\) \{.*?^\}", jsb, _re.S | _re.M)
    if not m_aff or not m_cles:
        echec("(5) fwAffichageCapture / clesFirmwareManquant introuvables")
        return
    if not node:
        note("(5) node introuvable — décisions d'affichage non exécutées")
        return
    script = (m_aff.group(0) + "\n" + m_cles.group(0) + """
const cas = {
  actif:   {actif: true,  phase: 3, ok: null},
  succes:  {actif: false, phase: 7, ok: true},
  annule:  {actif: false, phase: 2, ok: false, annule: true},
  echec:   {actif: false, phase: 4, ok: false, annule: false},
  neuf:    {actif: false, phase: 0, ok: null},
};
const R = {};
for (const k in cas) R[k] = fwAffichageCapture(cas[k], false);
R.nul = fwAffichageCapture(null, false);
R.deplie = fwAffichageCapture(cas.neuf, true);
const fw = {configure: false};
R.cles = {
  win_sans: clesFirmwareManquant({firmware: fw, wing: false, capture: {}}),
  win_ram:  clesFirmwareManquant({firmware: fw, wing: true,  capture: {}}),
  mac_sans: clesFirmwareManquant({firmware: fw, wing: false, capture: null}),
  mac_ram:  clesFirmwareManquant({firmware: fw, wing: true,  capture: null}),
};
process.stdout.write(JSON.stringify(R));""")
    r = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        echec("(5) décisions d'affichage : plantage node", r.stderr[:300])
        return
    R = json.loads(r.stdout)
    if not (R["actif"]["modal"] and R["actif"]["progress"]) or R["actif"]["capturer"]:
        echec("(5b) pendant la capture : modal absent, ou bouton « Capturer » encore visible", repr(R["actif"]))
    elif R["succes"]["progress"] or R["annule"]["progress"] or R["annule"]["modal"] or R["neuf"]["progress"]:
        echec("(5b) le panneau reste ouvert alors que actif=false sans échec à montrer", repr(R))
    elif not R["echec"]["progress"] or R["echec"]["modal"]:
        echec("(5b) après un échec : cartons (pastille rouge + Réessayer) attendus, non modaux", repr(R["echec"]))
    else:
        ok("(5b) panneau modal pendant la capture seulement ; fermé après succès/annulation, "
           "gardé (non modal) après échec ; « Capturer » masqué pendant (node)")
    if R["nul"]["manuel"] is not True or R["nul"]["lienManuel"] is not False:
        echec("(5c) s.capture null (macOS/Linux) : l'import manuel DOIT rester affiché", repr(R["nul"]))
    elif R["neuf"]["manuel"] is not False or R["neuf"]["lienManuel"] is not True \
            or R["deplie"]["manuel"] is not True:
        echec("(5c) s.capture non null : import manuel masqué par défaut, dépliable par le lien",
              repr((R["neuf"], R["deplie"])))
    else:
        ok("(5c) import manuel : masqué par défaut si s.capture non null (dépliable), "
           "affiché si null (node)")
    c = R["cles"]
    attendu = {
        "win_sans": ("ui.sante.wing.fw_manque_capture", "ui.bridge.fw_banniere.txt_capture"),
        "win_ram": ("ui.sante.wing.fw_manque_en_ram_capture", "ui.bridge.fw_banniere.txt_en_ram_capture"),
        "mac_sans": ("ui.sante.wing.fw_manque", "ui.bridge.fw_banniere.txt"),
        "mac_ram": ("ui.sante.wing.fw_manque_en_ram", "ui.bridge.fw_banniere.txt_en_ram"),
    }
    faux = [k for k, (p_, b_) in attendu.items() if (c[k]["pastille"], c[k]["banniere"]) != (p_, b_)]
    manquantes = [k for p_b in attendu.values() for k in p_b if k not in fr or k not in en]
    if faux or manquantes:
        echec("(5e) « firmware manquant » ne renvoie pas vers Capturer (Windows) / l'import (ailleurs), "
              "ou clés absentes en fr/en", f"faux={faux} manquantes={manquantes}")
    elif "ui.param.fw.aucun_capture" not in fr or "ui.param.fw.aucun_capture" not in en \
            or 'cap ? "ui.param.fw.aucun_capture"' not in js:
        echec("(5e) message « Aucun firmware » : variante capture absente")
    else:
        ok("(5e) « firmware non configuré » : renvoie vers « Capturer » si s.capture non null, "
           "vers l'import sinon (4 cas dans node, clés fr + en)")


def _controle_messages_capture(fwc):
    """Les messages de la capture ne se contredisent plus (Asus, 12/11/2026).

    Trois constats sur un journal réel, trois promesses :
      (1) la fenêtre de grâce ne CONCLUT pas avant la dernière passe
          d'extraction : le bloc vient APRÈS l'extraction dans la boucle, se
          signale UNE fois, et son texte annonce ce qui se passe (arrêt
          demandé, extraction qui continue) — plus « sans transfert
          exploitable — arrêt de la capture » suivi de « blob valide extrait » ;
      (2) la raison d'un échec « aucun transfert » est choisie d'après ce que
          la capture a VU (`_cle_aucun_transfert`, fonction pure) : wing déjà
          sur le bus à l'ouverture de l'enregistrement d'abord, grandMA2 onPC
          en dernier — plus « vérifie que grandMA2 onPC tourne » alors qu'il
          tournait ;
      (3) à la reprise (étape 7), « firmware pas démarré » dit que la wing
          peut encore démarrer seule AVANT de faire débrancher — plus
          « débranche » suivi la même seconde de « auto-démarrage tardif ».
    Réinjection : remettre l'ancien ordre / l'ancienne clé / l'un des anciens
    textes fait retomber le sous-contrôle correspondant à ROUGE (vérifié le
    13/11/2026, voir docs/WINDOWS.md).
    """
    import inspect
    import json
    import re as _re
    try:
        fr = json.loads((HERE / "locales" / "fr.json").read_text(encoding="utf-8"))
        en = json.loads((HERE / "locales" / "en.json").read_text(encoding="utf-8"))
    except Exception as e:
        echec("catalogues fr/en illisibles pour le contrôle des messages de capture",
              f"{type(e).__name__}: {e}")
        return
    src = inspect.getsource(fwc.capturer_firmware)

    # ── (1) fenêtre de grâce : après l'extraction, une fois, texte honnête ──
    cle_grace = "journal.fw.capture_fenetre_ecoulee"
    i_ext = src.find("extract_from_pcapng")
    i_grace = src.find(cle_grace)
    une_fois = _re.search(
        r"if not grace_signalee:\s*\n\s*grace_signalee = True\s*\n\s*_log\(\s*\""
        + _re.escape(cle_grace), src)
    ancienne = "journal.fw.capture_sans_transfert"
    if ancienne in src or ancienne in fr or ancienne in en:
        echec("la fenêtre de grâce annonce encore « sans transfert — arrêt de la "
              "capture » (clé journal.fw.capture_sans_transfert)",
              "ce message précédait « blob valide extrait » sur l'Asus le 12/11/2026")
    elif i_grace < 0 or cle_grace not in fr or cle_grace not in en:
        echec("clé journal.fw.capture_fenetre_ecoulee absente (code ou catalogues)")
    elif i_ext < 0 or i_ext > i_grace:
        echec("la fenêtre de grâce conclut AVANT la passe d'extraction du tour",
              f"extract_from_pcapng à {i_ext}, {cle_grace} à {i_grace} — "
              "l'extraction doit précéder")
    elif not une_fois:
        echec("la fenêtre de grâce n'est pas signalée UNE seule fois",
              "attendu : `if not grace_signalee: grace_signalee = True; _log(…)`")
    elif any(mot in fr[cle_grace] for mot in ("sans transfert", "arrêt de la capture")) \
            or "continue" not in fr[cle_grace]:
        echec("le texte fr de la fenêtre de grâce conclut encore (ou ne dit pas "
              "que l'extraction continue)", fr[cle_grace])
    elif "no usable transfer" in en[cle_grace] or "keeps running" not in en[cle_grace]:
        echec("le texte en de la fenêtre de grâce conclut encore", en[cle_grace])
    else:
        ok("(1) fenêtre de grâce : après l'extraction, signalée une fois, "
           "texte qui ne conclut pas avant le verdict")

    # ── (2) raison d'échec « aucun transfert » : d'après ce qui a été vu ─────
    f = getattr(fwc, "_cle_aucun_transfert", None)
    cas = [
        # (enregistrement_ouvert, wing_deja_la, wing_vue, ma2_tourne) → clé
        ((True, True, True, True), "firmware.echec.aucun_transfert_wing_deja_la"),
        ((True, True, True, False), "firmware.echec.aucun_transfert_wing_deja_la"),
        ((True, False, False, True), "firmware.echec.aucun_transfert_wing_jamais_vue"),
        ((True, False, True, False), "firmware.echec.aucun_transfert_ma2_ferme"),
        ((True, False, True, True), "firmware.echec.aucun_transfert"),
        ((False, None, False, False), "firmware.echec.aucun_transfert"),
    ]
    gen_fr = fr.get("firmware.echec.aucun_transfert", "")
    gen_en = en.get("firmware.echec.aucun_transfert", "")
    if not callable(f):
        echec("wing_firmware_capture._cle_aucun_transfert absente",
              "la raison d'échec doit être choisie d'après ce que la capture a vu")
    elif "_cle_aucun_transfert(" not in src:
        echec("capturer_firmware() n'utilise pas _cle_aucun_transfert()")
    else:
        faux = [f"{args} → {f(*args)!r} (attendu {att!r})"
                for args, att in cas if f(*args) != att]
        manque = [k for _, k in cas if k not in fr or k not in en]
        if faux:
            echec("_cle_aucun_transfert() se trompe de message", " ; ".join(faux))
        elif manque:
            echec("clé(s) d'échec « aucun transfert » absente(s) des catalogues",
                  ", ".join(sorted(set(manque))))
        elif "Vérifie que grandMA2 onPC tourne" in gen_fr \
                or "AVANT de lancer grandMA2" not in gen_fr:
            echec("le message générique fr envoie encore vérifier grandMA2 onPC en "
                  "premier (ou ne dit pas de débrancher AVANT de le lancer)", gen_fr)
        elif "Check that grandMA2 onPC is running" in gen_en \
                or "BEFORE launching grandMA2" not in gen_en:
            echec("le message générique en envoie encore vérifier grandMA2 onPC en "
                  "premier", gen_en)
        elif "AVANT de lancer grandMA2" not in fr["firmware.echec.aucun_transfert_wing_deja_la"]:
            echec("le message « wing déjà là » ne dit pas de débrancher AVANT de "
                  "lancer grandMA2 onPC")
        else:
            ok(f"(2) raison « aucun transfert » : {len(cas)} cas vus → bonne clé ; "
               "textes fr/en : débrancher AVANT grandMA2 onPC d'abord, onPC en dernier")

    # ── (3) étape 7 : « peut encore démarrer seule » AVANT « débranche » ────
    k_bl, k_susp = "journal.init.bootloader_fw_pas_demarre", "journal.wing.suspendu"
    t_fr, t_en = fr.get(k_bl, ""), en.get(k_bl, "")
    i_fr_auto, i_fr_deb = t_fr.find("toute seule"), t_fr.lower().find("débranche")
    i_en_auto, i_en_deb = t_en.find("on its own"), t_en.lower().find("unplug")
    if i_fr_auto < 0 or i_fr_deb < 0 or i_fr_auto > i_fr_deb:
        echec("fr : « Wing en bootloader » fait débrancher sans dire d'abord que "
              "la wing peut encore démarrer seule",
              f"{t_fr} — sur l'Asus, « auto-démarrage tardif… reprise » suivait "
              "la même seconde")
    elif i_en_auto < 0 or i_en_deb < 0 or i_en_auto > i_en_deb:
        echec("en : « Wing in bootloader » makes you unplug before saying it may "
              "still boot on its own", t_en)
    elif "seule" not in fr.get(k_susp, "") or "itself" not in en.get(k_susp, ""):
        echec("« Tentatives suspendues » ne dit pas qu'elles reprennent aussi si la "
              "wing finit de démarrer seule", fr.get(k_susp, ""))
    else:
        ok("(3) étape 7 : « peut encore démarrer seule (~30 s) » précède "
           "« débranche » (fr + en), « suspendues » le dit aussi")


_FIXTURES = HERE / "fixtures"


def _charger_fixture():
    """Rend (module_extract, module_generateur, chemin_capture)."""
    sys.path.insert(0, str(_FIXTURES))
    import wing_firmware_extract as fwx
    import generer_capture_exemple as gen
    capture = _FIXTURES / "capture_exemple.pcapng"
    return fwx, gen, capture


def test_firmware_extract():
    section("48. Extraction du firmware depuis une capture")
    try:
        fwx, gen, capture = _charger_fixture()
    except Exception as e:
        echec("module d'extraction ou fixture introuvable",
              f"{type(e).__name__}: {e}")
        return

    if not capture.exists():
        echec("capture d'exemple absente",
              f"{capture} — la régénérer : python fixtures/generer_capture_exemple.py")
        return

    attendu = gen.firmware_exemple()

    # 1. L'extracteur ressort EXACTEMENT les octets d'exemple.
    try:
        obtenu = fwx.extract_from_pcapng(str(capture))
    except Exception as e:
        echec("l'extraction de la capture d'exemple a échoué",
              f"{type(e).__name__}: {e}")
        return
    if obtenu == attendu:
        ok(f"extraction fidèle ({len(obtenu)} o, octets identiques au motif d'exemple)")
    else:
        echec("l'extracteur ne rend pas les octets attendus",
              f"{len(obtenu)} o obtenus, {len(attendu)} o attendus ; "
              f"identiques : {obtenu == attendu}")

    # 2. verify() refuse une TAILLE fausse.
    ok_court, _ = fwx.verify(b"\x00" * 100)
    if ok_court is False:
        ok("verify() refuse une taille fausse")
    else:
        echec("verify() a accepté une taille fausse (100 o)")

    # 3. verify() refuse une EMPREINTE fausse (bonne taille, mauvais contenu).
    #    Les octets d'exemple ont justement la bonne longueur (34 624 o) mais PAS
    #    l'empreinte du vrai firmware — c'est le cas idéal pour ce test.
    ok_hash, msg_hash = fwx.verify(attendu)
    if ok_hash is False and "sha256" in msg_hash:
        ok("verify() refuse une empreinte fausse (bonne taille, mauvais hash)")
    else:
        echec("verify() a accepté une empreinte fausse",
              f"retour : ({ok_hash!r}, {msg_hash!r})")

    # 4. Une capture SANS séquence d'upload → ExtractionError claire (pas nue).
    #    On fabrique un pcapng minimal avec un seul paquet USB anodin (pas le
    #    Hello), pour prouver que le parseur va au bout mais ne trouve rien.
    try:
        sans_seq = (gen._shb() + gen._idb()
                    + gen._epb(gen._usbpcap(gen.DEVICE, fwx.EP_OUT, False,
                                            b"\x05\x90\x00\x00"), ts=0))
        chemin_sans = _FIXTURES / "_smoke_sans_sequence.tmp.pcapng"
        chemin_sans.write_bytes(sans_seq)
    except Exception as e:
        note(f"impossible de fabriquer la capture sans-séquence : {e}")
        return
    try:
        try:
            fwx.extract_from_pcapng(str(chemin_sans))
            echec("une capture sans séquence n'a PAS levé d'erreur")
        except fwx.ExtractionError as e:
            if str(e):
                ok("capture sans séquence → ExtractionError avec message clair")
            else:
                echec("ExtractionError levée mais sans message")
        except Exception as e:
            echec("capture sans séquence → exception NUE (pas ExtractionError)",
                  f"{type(e).__name__}: {e}")
    finally:
        try:
            chemin_sans.unlink()
        except OSError:
            pass
