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

    # ── Assistant pas à pas : les détections d'étape et l'état de phase ──────
    # L'assistant guidé (étapes 1→5) repose sur deux détections qui débloquent
    # les étapes SANS clic. Elles doivent exister, être multiplateformes (rendre
    # False proprement hors Windows / sans matériel), et CAPTURE_STATE doit
    # exposer la progression à l'UI (barre d'étapes).
    manque = [n for n in ("gma2_onpc_lance", "wing_sur_bus", "_phase", "_attendre")
              if not callable(getattr(fwc, n, None))]
    if manque:
        echec("l'assistant pas à pas a perdu une brique",
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
        # Garde STATIQUE : le bloc étape 2 de capturer_firmware passe bien par le
        # helper (un retour à `_attendre(lambda: not wing_sur_bus(), …)` nu, un
        # seul échantillon, serait le bug de l'Asus réintroduit).
        try:
            src_cap = _inspect.getsource(fwc.capturer_firmware)
            bloc2 = src_cap.split("Étape 2/7", 1)[1].split("Étape 3/7", 1)[0]
        except (IndexError, OSError, TypeError):
            bloc2 = ""
        if "wing_absente_durablement(" not in bloc2 \
                or "_attendre(lambda: not wing_sur_bus()" in bloc2:
            echec("capturer_firmware (étape 2) ne passe pas par wing_absente_durablement()",
                  "le bloc « Étape 2/7 » doit appeler le helper, jamais _attendre() nu")
        else:
            ok("capturer_firmware (étape 2) passe par wing_absente_durablement()")
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

    # ── Délai minimum de LISIBILITÉ d'une étape ─────────────────────────────
    # L'auto-détection franchit une étape dès que sa condition est vraie —
    # parfois instantanément (wing déjà débranchée). Chaque étape doit rester
    # affichée AU MOINS _PHASE_MIN_S, et l'étape 2 (« Débranche ta wing », la
    # plus facile à manquer) au moins 10 s (retour auteur).
    # Réinjection : ramener _phase() à une simple assignation (retirer
    # l'attente) OU vider _PHASE_TENIR fait retomber ce contrôle à ROUGE.
    import time as _t
    if not hasattr(fwc, "_PHASE_MIN_S") or not hasattr(fwc, "_phase_horodate") \
            or not hasattr(fwc, "_PHASE_TENIR"):
        echec("_phase() n'a plus de garde-temps (l'étape peut « clignoter »)",
              "attendu : _PHASE_MIN_S + _PHASE_TENIR + _phase_horodate")
    elif fwc._PHASE_TENIR.get(2, 0) < 10.0:
        echec("l'étape 2 (« Débranche ta wing ») n'est plus tenue 10 s",
              f"_PHASE_TENIR[2] = {fwc._PHASE_TENIR.get(2)!r}")
    else:
        fwc._reset_state()
        t0 = _t.monotonic()
        fwc._phase(1, "première")          # jamais retardée (horodate à 0)
        premiere = _t.monotonic() - t0
        t1 = _t.monotonic()
        fwc._phase(2, "deuxième")          # doit tenir la 1re ~_PHASE_MIN_S
        seconde = _t.monotonic() - t1
        # 3e appel : doit tenir la 2e (_PHASE_TENIR[2]=10 s) — on ANNULE pour
        # ne pas bloquer le smoke 10 s : _phase() coupe son attente sur _ANNULER.
        fwc._ANNULER.set()
        t2 = _t.monotonic()
        fwc._phase(3, "troisième")
        troisieme = _t.monotonic() - t2
        fwc._reset_state()
        marge = fwc._PHASE_MIN_S - 0.4
        if premiere > 0.5:
            echec("_phase() retarde la PREMIÈRE étape", f"{premiere:.2f} s")
        elif seconde < marge:
            echec("_phase() ne tient pas l'étape précédente assez longtemps",
                  f"{seconde:.2f} s < {marge:.2f} s (l'instruction clignote)")
        elif troisieme > 2.0:
            echec("_phase() n'interrompt pas son attente sur une annulation",
                  f"{troisieme:.2f} s alors que _ANNULER est posé")
        else:
            ok(f"_phase() tient chaque étape ≥ {fwc._PHASE_MIN_S} s "
               f"(étape 2 ≥ {fwc._PHASE_TENIR[2]} s), coupe net sur annulation")

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
