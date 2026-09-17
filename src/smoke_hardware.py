#!/usr/bin/env python3
"""
smoke_hardware.py — Wing Bridge
================================
Domaine hardware/USB du test de fumée : paquet POLL, envoi de firmware,
blocage persistant, poignée USB pendant le reboot, reconnexion, fenêtre après
FW_CFG. Voir smoke_core.py pour ok/echec/note/section/HERE/_page/_poster.

🔑 test_reconnexion_sans_fantomes est rattaché ici (hardware/connexion) bien
qu'il touche aussi l'état faders/MA3 (ui.wb.parse_state, ui.ma3_etat) : c'est
le contrôle le plus transversal du fichier — voir smoke_faders.py s'il
s'agissait plutôt d'y chercher une régression côté faders.
"""

import etat
import json
import re
import time
from pathlib import Path

from smoke_core import HERE, ok, echec, note, section, _page, _js_de, _poster

import wing_etat_materiel


def test_poll_pkt(wb, wi):
    section("10. Cohérence du paquet POLL")
    a = getattr(wb, "POLL", None)
    b = getattr(wi, "POLL_PKT", None)
    if a is None or b is None:
        echec("POLL introuvable", f"wing_bridge.POLL={a!r}, wing_init.POLL_PKT={b!r}")
    elif a != b:
        echec("wing_init.POLL_PKT a divergé de wing_bridge.POLL",
              f"bridge={a.hex()} / init={b.hex()} — la preuve de vie de l'init "
              f"n'utiliserait pas le paquet de la boucle de polling")
    else:
        ok(f"POLL identique dans les deux modules ({a.hex()})")

    # ── Après un envoi de firmware : attendre le DÉPART avant le RETOUR ──────
    #
    # 🐛 Cause du « ➜ DÉBRANCHE-LA 15 s » à CHAQUE premier branchement,
    # constaté comme systématique.
    #
    # La wing reboote après l'envoi du firmware, mais ne quitte pas le bus
    # instantanément : l'ANCIENNE énumération (bootloader, 480 Mb/s) reste
    # visible un moment. Guetter le retour sans avoir attendu le départ fait
    # retrouver CE bootloader-là, et conclure « le firmware n'a pas démarré ».
    # Relevé : verdict d'échec à +9 s, wing opérationnelle toute seule 25 s
    # plus tard, sans que personne touche au câble.
    #
    # ⚠️ Ce bug avait DÉJÀ été corrigé dans `_tenter_reveil` ; le
    # correctif n'avait pas été appliqué au chemin du firmware. D'où ce
    # contrôle : un remède connu doit valoir pour TOUS les chemins.
    #
    # On lit le CODE seul — un premier script de vérification s'était fait
    # piéger en trouvant le mot dans un commentaire.
    src = (HERE / "wing_init.py").read_text(encoding="utf-8").splitlines()
    code = [(n, l) for n, l in enumerate(src, 1)
            if not l.strip().startswith("#")]
    appels = [n for n, l in code
              if "upload_firmware(" in l and not l.strip().startswith("def ")]
    if not appels:
        note("aucun appel à upload_firmware trouvé — contrôle sauté")
    else:
        fautifs = []
        for n in appels:
            suite = [(m, l) for m, l in code if m > n]
            dep = next((m for m, l in suite if "attendre_disparition" in l), None)
            ret = next((m for m, l in suite if "attendre_reapparition" in l), None)
            if ret is not None and (dep is None or dep > ret):
                fautifs.append(n)
        if fautifs:
            echec(f"{len(fautifs)} envoi(s) de firmware guettent le RETOUR de "
                  f"la wing sans attendre son DÉPART",
                  f"wing_init.py ligne(s) {fautifs} — l'ancienne énumération "
                  f"sera retrouvée et l'app demandera un débranchement inutile")
        else:
            ok(f"les {len(appels)} envois de firmware attendent le départ "
               f"avant le retour")

    # ── Anti-martèlement qui survit à un redémarrage ────────────────────────
    #
    # 🔴 Une wing coincée en bootloader l'est à cause du RENVOI
    # RÉPÉTÉ de firmware, pas d'un défaut. Le verrou en mémoire ne survit pas
    # au bouton « Réinitialiser » (process neuf), pressé après chaque build :
    # d'où « ça recommence à chaque build ». La mémoire est maintenant
    # persistée (wing_init.ETAT_FICHIER). On vérifie les quatre transitions.
    import tempfile
    sauve = wing_etat_materiel.ETAT_FICHIER
    try:
        wing_etat_materiel.ETAT_FICHIER = Path(tempfile.mkdtemp()) / "hw.json"
        etapes = []
        if wing_etat_materiel._firmware_envoye_recemment():
            etapes.append("état neuf déjà « récent »")
        wing_etat_materiel._marquer_firmware_envoye()
        if not wing_etat_materiel._firmware_envoye_recemment():
            etapes.append("un envoi n'est pas vu comme récent")
        wing_etat_materiel.effacer_etat_materiel()
        if wing_etat_materiel._firmware_envoye_recemment():
            etapes.append("une coupure n'efface pas le blocage")
        # age-out
        wing_etat_materiel._marquer_firmware_envoye()
        d = json.loads(wing_etat_materiel.ETAT_FICHIER.read_text())
        d["fw_envoye_t"] -= wing_etat_materiel.FW_REHAMMER_S + 1
        wing_etat_materiel.ETAT_FICHIER.write_text(json.dumps(d))
        if wing_etat_materiel._firmware_envoye_recemment():
            etapes.append("le blocage ne vieillit pas après FW_REHAMMER_S")
        # sans fichier injecté : jamais bloquant, jamais d'exception
        wing_etat_materiel.ETAT_FICHIER = None
        if wing_etat_materiel._firmware_envoye_recemment():
            etapes.append("bloque alors qu'aucun fichier n'est injecté")
        wing_etat_materiel._marquer_firmware_envoye()      # ne doit pas lever
        wing_etat_materiel.effacer_etat_materiel()
        if etapes:
            echec("l'anti-martèlement persistant se comporte mal",
                  " ; ".join(etapes))
        else:
            ok("anti-martèlement persistant : envoi vu, coupure efface, "
               "vieillit, inactif sans fichier")
    except Exception as e:
        echec("l'anti-martèlement a levé une exception",
              f"{type(e).__name__}: {e}")
    finally:
        wing_etat_materiel.ETAT_FICHIER = sauve

    # ── JAMAIS de firmware vers une wing qui TOURNE DÉJÀ ────────────────────
    #
    # 🔴 LA CAUSE D'ENTRÉE EN BOOTLOADER. `full_init` retombait de
    # son « cas 1 » (wing opérationnelle mais muette) dans son « cas 2 »
    # (bootloader) sans revérifier l'état : 34 624 octets d'ARM déversés dans le
    # flux de commandes du firmware en marche. La wing en ressortait dans son
    # bootloader — que l'app se mettait ensuite à marteler.
    #
    # ⚠️ CONTRÔLE DE COMPORTEMENT, pas de texte. On REJOUE le scénario avec des
    # doublures USB (aucune wing branchée) et on compte les octets réellement
    # écrits. Un contrôle qui aurait cherché un mot-clé dans le source serait
    # passé au vert sur le code fautif : le `return` manquant ne s'écrit pas.
    #
    # Les deux variantes comptent : la wing peut être muette de bout en bout,
    # ou répondre au Hello (elle vit) tout en manquant les polls. C'est la
    # SECONDE qui envoyait les 34 ko — la première s'arrêtait au Hello, ce qui
    # rendait le bug intermittent, donc difficile à voir.
    ecrits = {"gros": 0, "total": 0}

    class _WingQuiTourne:
        """Wing en mode APPLICATIF : speed=2 (12 Mb/s = firmware déjà chargé)."""
        speed, bus, address = 2, 1, 18
        def write(self, ep, data, timeout=None):
            n = len(data)
            ecrits["total"] += n
            if n >= 512:
                ecrits["gros"] += 1
            return n
        def read(self, ep, size, timeout=None):
            raise RuntimeError("muette")

    # ⚠️⚠️ DEUX PIÈGES, tombés dedans en écrivant ce contrôle.
    # Ils valent d'être écrits : ce contrôle est passé VERT sur le code fautif.
    #
    # 1. `ETAT_FICHIER` doit être NEUTRALISÉ. Sinon la 1re variante horodate un
    #    envoi de firmware, et la 2nde — la seule qui déclenche vraiment les
    #    34 ko — se fait arrêter par l'anti-martèlement AVANT le point testé.
    #    Le contrôle annonçait alors « aucun firmware envoyé » sans avoir rien
    #    vérifié. C'est le « ✓ mensonger » que ce projet paie deux fois déjà.
    # 2. Sans neutralisation, ce contrôle ÉCRIT dans le vrai
    #    `wing_hw_state.json` de l'utilisateur. Or le test de fumée tourne à
    #    CHAQUE build : l'app démarrant juste après aurait cru qu'un firmware
    #    venait d'être envoyé, et refusé d'initialiser la wing pendant 30 s.
    #    Un test ne doit jamais laisser de trace dans l'état du matériel.
    faux = _WingQuiTourne()
    memo = {k: getattr(wi, k) for k in
            ("_trouver", "_open", "_liberer", "_read", "JOURNAL",
             "attendre_disparition", "attendre_reapparition")}
    # L'état matériel vit dans wing_etat_materiel depuis l'audit du 25/09/2026
    # (D3) : sauvé et restauré LÀ, sinon le test écrirait dans le vrai fichier.
    memo_em = {"ETAT_FICHIER": wing_etat_materiel.ETAT_FICHIER}
    vrai_sleep = time.sleep
    for nom, vivante in (("muette de bout en bout", False),
                         ("vivante au Hello, muette au poll", True)):
        ecrits["gros"] = ecrits["total"] = 0
        lus = {"n": 0}
        try:
            wing_etat_materiel.ETAT_FICHIER = None       # cf. les deux pièges ci-dessus
            wi.DERNIER_ECHEC["firmware_bloque"] = False
            wi._trouver = wi._open = lambda *a, **k: faux
            wi._liberer = lambda d: None
            wi.JOURNAL = lambda *a, **k: None
            wi.attendre_disparition = lambda t=3.0: True
            wi.attendre_reapparition = lambda timeout_s=8.0: (faux, "operationnelle")
            time.sleep = lambda s: None

            def _lire(dev, timeout_ms=None, _v=vivante):
                lus["n"] += 1
                # Muette pendant les sondes de polling ; ensuite, seule la
                # variante « vivante » répond — c'est elle qui déclenchait
                # l'envoi du firmware.
                return bytes(140) if (_v and lus["n"] > 20) else None
            wi._read = _lire

            wi.full_init(verbose=False)
        except Exception as e:
            echec(f"full_init a levé une exception ({nom})",
                  f"{type(e).__name__}: {e}")
            break
        finally:
            time.sleep = vrai_sleep
            for k, v in memo.items():
                setattr(wi, k, v)
            for k, v in memo_em.items():
                setattr(wing_etat_materiel, k, v)

        if ecrits["gros"]:
            echec("FIRMWARE ENVOYÉ À UNE WING QUI TOURNE DÉJÀ "
                  f"({nom})",
                  f"{ecrits['gros']} écriture(s) de 512 o, "
                  f"{ecrits['total']} octets au total, vers une wing à "
                  f"12 Mb/s (état « operationnelle »). C'est ce qui la fait "
                  f"retomber dans son bootloader. Le « cas 1 » de full_init "
                  f"doit se terminer par un `return`, jamais retomber dans "
                  f"le « cas 2 ».")
            break
    else:
        ok("aucun firmware envoyé à une wing déjà opérationnelle "
           "(les deux variantes, muette et vivante-au-Hello)")

    # ── Signatures du Hello : bootloader ≠ firmware applicatif ──────────────
    #
    # 🔑 Relevé dans `d.pcapng` (capture d'origine de MA2 onPC).
    # Le même Hello reçoit deux réponses distinctes selon l'interlocuteur. C'est
    # une preuve de PROTOCOLE — la wing dit elle-même qui elle est — là où
    # `etat_wing()` ne fait que déduire depuis la vitesse d'énumération USB.
    #
    # Ce contrôle vérifie le garde-fou qui s'appuie dessus : même avec une
    # vitesse ILLISIBLE (état « inconnu », que la vitesse seule laisse passer),
    # une wing qui répond en applicatif ne doit recevoir aucun firmware.
    sigs = {n: getattr(wi, n, None)
            for n in ("HELLO_REP_BOOTLOADER", "HELLO_REP_APPLICATIF")}
    if any(v is None for v in sigs.values()):
        echec("signatures du Hello absentes de wing_init",
              f"{sigs} — le garde-fou de protocole ne peut pas fonctionner")
    elif sigs["HELLO_REP_BOOTLOADER"] == sigs["HELLO_REP_APPLICATIF"]:
        echec("les deux signatures du Hello sont identiques",
              "elles ne distinguent plus rien : le garde-fou est inopérant")
    else:
        envoyes = {"n": 0}

        class _WingVitesseIllisible:
            """Wing dont la VITESSE ne dit rien (etat_wing → « inconnu »), mais
            qui répond en APPLICATIF au Hello. Seul le protocole la trahit."""
            speed, bus, address = None, 1, 18
            def write(self, ep, data, timeout=None):
                if len(data) >= 512:
                    envoyes["n"] += 1
                return len(data)
            def read(self, ep, size, timeout=None):
                raise RuntimeError

        d_ill = _WingVitesseIllisible()
        if wi.etat_wing(d_ill) != "inconnu":
            note(f"état attendu « inconnu », obtenu « {wi.etat_wing(d_ill)} » "
                 f"— le scénario ne teste plus le trou visé")
        memo2 = {k: getattr(wi, k) for k in ("_read", "JOURNAL")}
        try:
            wi._read = lambda dev, timeout_ms=None: wi.HELLO_REP_APPLICATIF
            wi.JOURNAL = lambda *a, **k: None
            refus = wi.upload_firmware(d_ill, verbose=False)
        finally:
            for k, v in memo2.items():
                setattr(wi, k, v)
        if refus is not False or envoyes["n"]:
            echec("firmware envoyé malgré une réponse de Hello APPLICATIVE",
                  f"upload_firmware a rendu {refus!r} et écrit "
                  f"{envoyes['n']} chunk(s) de 512 o, alors que la wing a "
                  f"répondu {wi.HELLO_REP_APPLICATIF.hex()} — c'est le "
                  f"firmware qui tourne, pas le bootloader")
        else:
            ok(f"Hello applicatif ({wi.HELLO_REP_APPLICATIF.hex()}) → envoi "
               f"refusé même avec une vitesse USB illisible")

    # ── L'anti-martèlement ne s'horodate QUE si un octet est réellement parti ──
    #
    # 🐛 `full_init` appelait `_marquer_firmware_envoye()` de façon
    # INCONDITIONNELLE après `upload_firmware()`, y compris sur les chemins où
    # celle-ci renvoie `False` AVANT d'avoir touché à un seul octet de
    # firmware (Hello resté sans réponse, Hello applicatif refusé — son propre
    # docstring le dit). Un bootloader qui n'a RIEN reçu se voyait quand même
    # frappé par le cooldown `FW_REHAMMER_S` : une reconnexion tout à fait
    # légitime quelques secondes plus tard échouait sur un « firmware déjà
    # envoyé » qui ne s'était jamais produit.
    #
    # Scénario : bootloader présent mais MUET AU HELLO — aucun octet de
    # firmware ne peut donc partir.
    import tempfile as _tempfile

    class _BootloaderMuetAuHello:
        speed, bus, address = 3, 1, 7          # 3 = bootloader (VITESSE_LIB)
        def write(self, ep, data, timeout=None):
            return len(data)
        def read(self, ep, size, timeout=None):
            raise RuntimeError("muette au Hello")

    faux_bl = _BootloaderMuetAuHello()
    memo3 = {k: getattr(wi, k) for k in
             ("_trouver", "_open", "_liberer", "_read", "JOURNAL",
              )}
    memo3_em = {k: getattr(wing_etat_materiel, k)
                for k in ("ETAT_FICHIER", "blocage_connu")}
    # `firmware_configure` vit dans wing_firmware depuis l'audit du 25/09/2026
    # (D3) : le patcher sur wing_init ne changerait plus rien à full_init.
    import wing_firmware
    fw_configure_avant = wing_firmware.firmware_configure
    # ⚠️ `DERNIER_ECHEC` À PART : c'est un DICT PARTAGÉ (pas un attribut
    # qu'une simple ré-affectation suffit à restaurer). Ce scénario le fait
    # ÉCHOUER EXPRÈS (`firmware_bloque` finit à True) : sans copie/restauration
    # complète, ce `True` fuit vers les contrôles suivants qui, eux, ne le
    # réinitialisent qu'EN PASSANT par `full_init` — donc jamais s'il est court-
    # circuité par un mock au signature différente (`_echec_init` le lisant
    # alors AVANT toute remise à zéro). Vécu : contrôle 39 rendu très lent
    # (verrou `attend_rebranchement` posé à tort) par cette fuite précise.
    dernier_echec_avant = dict(wi.DERNIER_ECHEC)
    try:
        wing_etat_materiel.ETAT_FICHIER = Path(_tempfile.mkdtemp()) / "hw.json"
        wi._trouver = wi._open = lambda *a, **k: faux_bl
        wi._liberer = lambda d: None
        wi._read = lambda dev, timeout_ms=None: None      # Hello sans réponse
        wi.JOURNAL = lambda *a, **k: None
        wing_firmware.firmware_configure = lambda: True
        wing_etat_materiel.blocage_connu = lambda: False
        wi.DERNIER_ECHEC["firmware_bloque"] = False

        resultat = wi.full_init(verbose=False)
        if resultat is not None:
            echec("full_init a rendu un device malgré un Hello sans réponse",
                  f"{resultat!r} — le scénario ne teste plus le cas visé")
        elif wing_etat_materiel._firmware_envoye_recemment():
            echec("ANTI-MARTÈLEMENT FAUSSÉ PAR UN ENVOI QUI N'A JAMAIS EU LIEU",
                  "full_init a horodaté l'anti-martèlement alors que "
                  "upload_firmware n'a pas dépassé le Hello (sans réponse) : "
                  "une reconnexion légitime quelques secondes plus tard sera "
                  "refusée pour un « firmware déjà envoyé » fictif")
        else:
            ok("un Hello sans réponse (rien envoyé) ne pose pas le cooldown "
               "anti-martèlement")
    except Exception as e:
        echec("le scénario « Hello sans réponse » a levé une exception",
              f"{type(e).__name__}: {e}")
    finally:
        for k, v in memo3.items():
            setattr(wi, k, v)
        for k, v in memo3_em.items():
            setattr(wing_etat_materiel, k, v)
        wing_firmware.firmware_configure = fw_configure_avant
        wi.DERNIER_ECHEC.clear()
        wi.DERNIER_ECHEC.update(dernier_echec_avant)


def test_boutons_honnetes(ui):
    section("23. Les boutons ne mentent pas")

    sauve = {k: etat.E.STATE.get(k) for k in ("wing", "mode", "connecting",
                                          "resume_mode", "want_connected")}
    journal, vrai_log = [], ui.log
    ui.log = lambda *a, **k: journal.append(str(ui._rendre_appel(*a, **k)))
    try:
        # ── a) « Démarrer le bridge » sans wing ──────────────────────────────
        etat.E.STATE.update(wing=False, mode="idle", connecting=False,
                        resume_mode=None)
        rep = _poster(ui, "/api/mode", {"mode": "bridge"})
        if rep.get("ok"):
            echec("« Démarrer » répond OK alors qu'aucune wing n'est connectée",
                  f"réponse {rep!r} — l'utilisateur croit le bridge actif")
        elif etat.E.STATE["mode"] == "bridge":
            echec("le mode est passé à « bridge » sans wing",
                  "la boucle USB n'a aucun device : rien ne partira vers MA3")
        elif any("Bridge DÉMARRÉ" in l for l in journal):
            echec("« ═══ Bridge DÉMARRÉ ═══ » journalisé sans wing",
                  "c'est le message mensonger déjà relevé")
        else:
            ok("sans wing, « Démarrer » refuse, le dit, et arme le bridge "
               f"(resume_mode={etat.E.STATE['resume_mode']!r})")

        # ── b) l'intention est bien mémorisée, et consommée à la connexion ───
        if etat.E.STATE.get("resume_mode") != "bridge":
            echec("l'intention de démarrer n'est pas mémorisée",
                  "le bridge ne repartira pas tout seul au branchement")
        else:
            ok("l'intention est gardée : le bridge partira à la connexion")

        # ── c) « Démarrer » AVEC wing : doit marcher normalement ─────────────
        journal.clear()
        etat.E.STATE.update(wing=True, mode="idle", resume_mode=None)
        rep = _poster(ui, "/api/mode", {"mode": "bridge"})
        if not rep.get("ok") or etat.E.STATE["mode"] != "bridge":
            echec("« Démarrer » ne marche plus AVEC une wing connectée",
                  f"réponse {rep!r}, mode={etat.E.STATE['mode']!r} — régression")
        elif not any("Bridge DÉMARRÉ" in l for l in journal):
            echec("le démarrage réel n'est plus journalisé")
        else:
            ok("avec wing, « Démarrer » démarre et le journalise")

        # ── d) « Connecter » pendant une connexion en cours ──────────────────
        journal.clear()
        etat.E.STATE.update(wing=False, connecting=True)
        rep = _poster(ui, "/api/wing/connect", {})
        if rep.get("ok"):
            echec("« Connecter » répond OK pendant une connexion en cours",
                  "connect_wing sort aussitôt : le clic est avalé en silence")
        elif not journal:
            echec("« Connecter » refuse mais n'explique rien à l'utilisateur")
        else:
            ok("« Connecter » pendant une init : refus explicite et journalisé")

        # ── e) « Désinstaller » : l'aperçu ne ment pas sur ce qu'il fera ─────
        # Le modal promet que « Conserver certaines informations » ne fait que
        # SOUSTRAIRE des suppressions — jamais en ajouter. On le vérifie sur
        # l'endpoint en dry-run (aucune suppression réelle) : deleted(keep=tout)
        # doit être inclus dans deleted(keep=rien).
        tout = _poster(ui, "/api/uninstall",
                       {"keep": {"profiles": True, "log": True, "ma3_plugin": True},
                        "dry_run": True})
        rien = _poster(ui, "/api/uninstall", {"keep": {}, "dry_run": True})
        d_tout, d_rien = set(tout.get("deleted", [])), set(rien.get("deleted", []))
        if not (tout.get("dry_run") and rien.get("dry_run")):
            echec("le dry-run de désinstallation n'est pas signalé comme tel",
                  f"tout={tout!r}, rien={rien!r}")
        elif not d_tout <= d_rien:
            echec("« Désinstaller » : conserver des infos AJOUTE des suppressions",
                  f"{sorted(d_tout - d_rien)[:3]} — le modal promet l'inverse")
        elif not rien.get("residue") or any(".py" in t for t in rien["residue"]):
            echec("« Désinstaller » : résidu manuel vide ou citant un script")
        else:
            ok("« Désinstaller » : cocher « conserver » ne fait que retirer des "
               "suppressions, et le résidu manuel est donné")
    except Exception as e:
        echec("le contrôle des boutons a levé une exception",
              f"{type(e).__name__}: {e}")
    finally:
        ui.log = vrai_log
        etat.E.STATE.update(sauve)


def test_sorties_rendent_la_wing(ui):
    """Les DEUX sorties du moteur rendent la wing proprement.

    🐛 `restart_self()` appelait `arreter_usb()` — qui attend la fin
    d'une lecture en vol avant de libérer — mais `/api/quit` faisait `os._exit`
    sec. Deux sorties, deux comportements, et c'est la brutale qui servait le
    plus souvent. L'utilisateur compensait en cliquant « ⏏ Déconnecter » avant
    de quitter, ce qui l'exposait au close→reopen (état lent).

    ⚠️ Contrôle de SOURCE et non de comportement, assumé : appeler pour de vrai
    un chemin qui finit par `os._exit(0)` tuerait le test de fumée lui-même.
    On vérifie donc que chaque sortie mentionne la libération, ce qui attrape la
    régression « quelqu'un remet un os._exit sec ».
    """
    section("24. Les deux sorties rendent la wing")
    # ⚠️⚠️ ON LIT LE CODE SEUL, COMMENTAIRES RETIRÉS.
    #
    # Première version de ce contrôle : passée VERTE sur le bug réinjecté,
    # parce que « arreter_usb() » figurait dans le COMMENTAIRE qui explique le
    # correctif, juste au-dessus du code. Le piège est pourtant écrit noir sur
    # blanc dans le contrôle test_poll_pkt : « on lit le CODE seul — un premier
    # script de vérification s'était fait piéger en trouvant le mot dans un
    # commentaire ». Tombé dedans quand même.
    #
    # ⚠️ SOURCE = les modules `wing_*.py`, pas seulement wing_ui.py. `restart_self`
    # vit dans wing_connexion.py, `arret_propre` dans wing_ui.py, `_post_quit`
    # dans wing_handler.py — un scan limité à un fichier serait aveugle à ces
    # déplacements (même principe que test_messages_actionnables, élargi en glob).
    # ⚠️ On EXCLUT les smoke_*.py : ce fichier-ci contient la chaîne littérale
    # « def _post_quit( » (dans la table d'ancres juste en dessous) et
    # `src.find` la trouvait AVANT wing_handler.py — le contrôle se satisfaisait
    # alors de sa propre source. Anchor sur un nom de fonction ne suffit pas si
    # ce nom traîne aussi ailleurs.
    lignes = []
    for f in sorted(HERE.glob("wing_*.py")):
        lignes.extend(l for l in f.read_text(encoding="utf-8").splitlines()
                       if not l.strip().startswith("#"))
    src = "\n".join(lignes)
    manques = []
    # ⚠️ ANCRER SUR UN NOM DE FONCTION, JAMAIS SUR LA FORME DU CODE.
    # Ce contrôle visait `self.path == "/api/quit"`. Le passage du if/elif à une
    # table de routage a fait disparaître la chaîne : le contrôle a échoué —
    # alors que le code était juste. C'est la DEUXIÈME fois qu'un déplacement de
    # code casse un garde-fou qui lisait sa mise en page (six l'ont fait au
    # découpage du JS). Un nom de fonction, lui, survit au déménagement.
    #
    # `arret_propre` est LE chemin d'arrêt commun depuis le chantier « cycle de
    # vie » : « ⏻ Quitter » comme la fermeture d'onglet le délèguent. `_post_quit`
    # doit donc soit libérer lui-même, soit passer par lui.
    for nom, ancre, besoins in (
            ("/api/quit",    "def _post_quit(",
             ("arret_propre", "arreter_usb(", "_release_device(")),
            ("arret_propre", "def arret_propre(",
             ("arreter_usb(", "_release_device(")),
            ("restart_self", "def restart_self(",
             ("arreter_usb(", "_release_device(")),
    ):
        i = src.find(ancre)
        if i < 0:
            manques.append(f"{nom} : introuvable dans le source")
            continue
        bloc = src[i:i + 1200]
        if not any(b in bloc for b in besoins):
            manques.append(f"{nom} : ne libère PAS la wing avant de sortir")
    if manques:
        echec("une sortie du moteur ne rend pas la wing", " ; ".join(manques))
    else:
        ok("« Quitter » et « Réinitialiser » libèrent tous deux l'USB")


def test_boutons_wing_uniques(html):
    """Un seul geste « wing » dans l'interface, et aucun bouton mort.

    🧹 Il y avait trois boutons pour la liaison USB :
    « Connecter la wing », « ↻ Reconnecter » et « ⏏ Déconnecter ». Les deux
    premiers ne s'affichaient JAMAIS ensemble (un test sur `s.wing` les
    excluait mutuellement) : deux libellés pour un seul geste, qui ne
    différaient que par `force`. Le troisième n'avait plus d'usage, et son
    enchaînement avec « Connecter » est un close→reopen — le déclencheur
    documenté de l'état LENT, et la cause d'une panne réelle.

    ⚠️ Ce contrôle EMPÊCHE la réintroduction. Si un jour un besoin réel de
    « Déconnecter » apparaît, il faudra le justifier ici, pas le rajouter en
    silence.
    """
    section("25. Un seul bouton pour la wing")
    interdits = [("disconnectWing", "⏏ Déconnecter"),
                 ("connectWing(",   "« Connecter » séparé de « Reconnecter »"),
                 ("reconnectWing(", "« ↻ Reconnecter » séparé de « Connecter »")]
    # ⚠️ `_page` et non `html` : ces noms sont des FONCTIONS, elles vivent
    # dans ui/*.js. Les chercher dans le seul balisage rendait ce garde-fou
    # incapable de voir un retour de « ⏏ Déconnecter ».
    _tout = _page(html)
    revenus = [libelle for fn, libelle in interdits if fn in _tout]
    if revenus:
        echec(f"{len(revenus)} bouton(s) retiré(s) sont revenus",
              " ; ".join(revenus) + " — voir le commentaire de /api/wing/connect "
              "dans wing_ui.py avant de les réintroduire")
    elif "wingAction()" not in _tout:
        echec("le bouton unique « wingAction » a disparu de l'interface",
              "plus aucun moyen de (re)connecter la wing depuis l'interface")
    elif 'id="wingBtn"' not in html:
        echec("l'identifiant wingBtn est absent",
              "le libellé ne pourra pas suivre l'état (Connecter / Reconnecter)")
    else:
        ok("un seul bouton wing, au libellé piloté par l'état")

    # Les infobulles doivent DIRE ce que font les boutons — « vérifie que tous
    # les labels sont les bons ».
    #
    # ⚠️ i18n : le texte des infobulles est passé dans le catalogue
    # (data-i18n-title="clé", valeur dans locales/fr.json). On vérifie donc le
    # MOT-CLÉ dans fr.json (la référence), plus que le bouton porte bien ce
    # data-i18n-title dans le balisage. Chercher le texte inline marcherait
    # aussi (on le garde en clair) mais casserait à la 1re retouche de libellé.
    attendus = [
        # 🔴 Ce contrôle EXIGEAIT « REND LA WING proprement », et cette promesse
        # s'est révélée FAUSSE : mesuré 3 fois sur 3, la wing repart dans son
        # bootloader et le lancement suivant doit renvoyer le firmware (qui
        # échoue ~2 fois sur 3). Un contrôle qui garde une phrase rassurante la
        # PROTÈGE : celui-ci a maintenu le mensonge en place.
        # ⚠️ Ce qu'un contrôle d'infobulle doit exiger, c'est la CONSÉQUENCE
        # pour l'utilisateur — ici : qu'il y aura un renvoi de firmware.
        ("quitApp()", "ui.entete.bouton.quitter_tip", "RENVOYER SON FIRMWARE",
         "quitter remet la wing en veille"),
        # Le bouton de démarrage porte le nom du produit (décision auteur).
        ("toggleBridge()", "ui.bridge.bouton.demarrer_tip", "ARMÉ",
         "il peut refuser et rester en attente"),
    ]
    import json as _json
    from pathlib import Path as _P
    fr_p = _P(__file__).resolve().parent / "locales" / "fr.json"
    fr = _json.loads(fr_p.read_text(encoding="utf-8")) if fr_p.is_file() else {}
    faux = []
    for onclick, tip_key, mot, pourquoi in attendus:
        i = html.find(onclick)
        if i < 0:
            faux.append(f"bouton {onclick} introuvable")
            continue
        deb, fin = html.rfind("<button", 0, i), html.find(">", i)
        balise = html[deb:fin] if deb >= 0 and fin > deb else ""
        if f'data-i18n-title="{tip_key}"' not in balise:
            faux.append(f"{onclick} n'a pas data-i18n-title=\"{tip_key}\"")
        elif tip_key not in fr:
            faux.append(f"clé {tip_key} absente de fr.json")
        elif mot not in fr[tip_key]:
            faux.append(f"l'infobulle {tip_key} ne dit pas « {mot} » ({pourquoi})")
    if faux:
        echec("des infobulles ne décrivent plus le comportement réel",
              " ; ".join(faux))
    else:
        ok("les infobulles de « Quitter » et « Démarrer » sont à jour "
           "(mot-clé vérifié dans fr.json)")


def test_messages_actionnables(html):
    """Aucun message utilisateur ne renvoie vers un script, ne crie, ni ne répète.

    🔴 Exigence : *« je ne veux pas d'une app qui me dit "il faut essayer un
    script pour espérer quelque chose", j'aimerai de la fiabilité »*. La
    pastille de santé disait littéralement : « QUITTE Wing Bridge, lance
    essai_wing_propre.py, puis relance l'app ».

    Trois règles, toutes issues de là :
      1. **jamais de nom de script** dans un texte affiché — l'app doit faire
         elle-même ce que le script faisait ;
      2. **pas de CAPITALES d'insistance** dans une consigne — elles font
         paraître grave ce qui est ordinaire ;
      3. la consigne « débranche » se dit **une fois**, pas deux de suite.
    """
    section("26. Messages actionnables, sans script")

    # ⚠️ ON LIT L'AST, PAS LE TEXTE.
    #
    # La 1re version cherchait les mots dans les lignes source, en excluant
    # seulement les commentaires `#`. Elle s'est étranglée sur une DOCSTRING qui
    # cite un vieux journal — texte historique, jamais affiché. Même famille de
    # faux positif que le contrôle test_sorties_rendent_la_wing (mot trouvé dans un commentaire).
    #
    # On extrait donc les littéraux réellement passés à `log(...)` / `_msg(...)`.
    # Précis, et insensible aux commentaires comme aux docstrings.
    import ast as _ast

    def textes_affiches(chemin):
        out = []
        arbre = _ast.parse(Path(chemin).read_text(encoding="utf-8"))
        for n in _ast.walk(arbre):
            if not isinstance(n, _ast.Call):
                continue
            f = n.func
            nom = getattr(f, "id", None) or getattr(f, "attr", None)
            if nom not in ("log", "_msg"):
                continue
            for m in _ast.walk(n):
                if isinstance(m, _ast.Constant) and isinstance(m.value, str):
                    out.append(m.value)
        return out

    ennuis = []
    # ⚠️ GLOB, PAS UNE LISTE FIXE — même principe que
    # test_renvois_doc : une liste fixe de fichiers devient aveugle en
    # silence dès qu'un contrôle est déplacé vers un nouveau module (c'est
    # exactement ce qui est arrivé à `install_crash_logging`, sorti de
    # wing_ui.py vers wing_diagnostic.py). Un glob reste vrai après chaque
    # future extraction.
    affiches = {f.name: textes_affiches(f) for f in sorted(HERE.glob("*.py"))}

    # 1. aucun script cité dans un texte affiché
    html_visible = "\n".join(l for l in html.splitlines()
                             if not l.strip().startswith("//"))
    if "essai_wing_propre" in html_visible or ".py »" in html_visible:
        ennuis.append("wing_ui.html cite un script dans un texte affiché")
    for nom, textes in affiches.items():
        if any("essai_wing_propre" in t or ".py »" in t for t in textes):
            ennuis.append(f"{nom} cite un script dans un message")
    # i18n : le texte des messages est passé dans le catalogue — on le scanne
    # aussi (une consigne fautive pourrait s'y cacher).
    import json as _json
    fr_p = HERE / "locales" / "fr.json"
    fr_cat = _json.loads(fr_p.read_text(encoding="utf-8")) if fr_p.is_file() else {}
    for cle, val in fr_cat.items():
        if isinstance(val, str) and ("essai_wing_propre" in val or ".py »" in val):
            ennuis.append(f"locales/fr.json ({cle}) cite un script")
        if isinstance(val, str) and any(c in val for c in
                                        ("DÉBRANCHE", "REBRANCHE-LA", "DÉBRANCHE-LA")):
            ennuis.append(f"locales/fr.json ({cle}) crie une consigne en capitales")

    # 2. pas de capitales d'insistance dans les consignes
    for nom, textes in affiches.items():
        for t in textes:
            for cri in ("DÉBRANCHE", "REBRANCHE-LA", "DÉBRANCHE-LA"):
                if cri in t:
                    ennuis.append(f"{nom} crie « {cri} » dans un message")

    if ennuis:
        echec("des messages ne respectent pas les règles de formulation",
              " ; ".join(sorted(set(ennuis))))
    else:
        ok("aucun script cité, aucune consigne en capitales")

    # 3. la pastille « bootloader » doit donner LE geste, court
    # ⚠️ Ce texte est posé par setHealth() depuis ui/bridge.js, et depuis l'i18n
    # sa CHAÎNE vit dans le catalogue (bridge.js n'a plus que la clé). On vérifie
    # donc les deux : bridge.js utilise bien t("ui.sante.wing.bootloader"), et
    # fr.json donne le geste.
    js_all = _js_de(html)
    cle_boot = "ui.sante.wing.bootloader"
    if f't("{cle_boot}")' not in js_all and f"t('{cle_boot}')" not in js_all:
        echec("la pastille « bootloader » n'est plus posée via "
              f"t(\"{cle_boot}\")",
              "soit la clé a changé, soit ce contrôle ne regarde plus au bon "
              "endroit — dans les deux cas il ne garde plus rien")
    elif cle_boot not in fr_cat:
        echec(f"clé {cle_boot} absente de fr.json")
    elif "bootloader" not in fr_cat[cle_boot] \
            or "rebranche" not in fr_cat[cle_boot]:
        echec("la pastille « bootloader » ne dit plus quoi faire",
              f"« {fr_cat[cle_boot]} » — elle doit nommer le bootloader ET "
              "donner le geste (débrancher/rebrancher le câble)")
    else:
        ok("la pastille « bootloader » donne le geste, en une phrase")


def test_blocage_jamais_definitif(wi):
    """Le blocage persistant se lève par CHACUN de ses quatre chemins.

    🔑 Le blocage « ce bootloader a déjà refusé » est passé d'un
    minuteur de 30 s à un ÉTAT persistant — parce qu'un minuteur ne protégeait
    pas du cas réel (app relancée 14 min après un échec, verrou expiré, unique
    tentative regaspillée).

    ⚠️ Mais un verrou qui ne se lève pas serait BIEN PIRE que le bug corrigé :
    l'app refuserait d'initialiser une wing saine, sans recours. Ce contrôle
    vérifie les trois sorties, une par une — et qu'il TIENT quand il doit.
    """
    section("35. Le blocage ne peut pas devenir définitif")
    import tempfile, json as _json
    sauve_f, sauve_t = wing_etat_materiel.ETAT_FICHIER, wi._trouver
    ennuis = []
    try:
        wing_etat_materiel.ETAT_FICHIER = Path(tempfile.mkdtemp()) / "hw.json"

        class _Faux:
            def __init__(s, bus, adr): s.bus, s.address, s.speed = bus, adr, 3

        # Wing présente en 1.7 : on bloque.
        wi._trouver = lambda *a, **k: _Faux(1, 7)
        wing_etat_materiel._marquer_blocage()
        if not wing_etat_materiel.blocage_connu():
            ennuis.append("un blocage tout juste posé n'est pas vu")

        # 1) la wing quitte le bus → plus rien à bloquer
        wi._trouver = lambda *a, **k: None
        if wing_etat_materiel.blocage_connu():
            ennuis.append("wing absente : le blocage devrait être sans objet")

        # ❌ Il y avait ici un 4e chemin — « adresse USB différente = la wing a
        # été rebranchée ». RÉFUTÉ : la wing re-énumère toute
        # seule à chaque tentative (l'envoi de firmware la fait rebooter), donc
        # son adresse change à chaque essai et le blocage se levait tout seul.
        # Ne pas le réintroduire — l'adresse ne distingue pas un geste humain
        # d'un reboot. Le contrôle vérifie donc les TROIS chemins réels.
        wi._trouver = lambda *a, **k: _Faux(1, 7)
        wi.JOURNAL = lambda *a, **k: None
        if not wing_etat_materiel.blocage_connu():
            ennuis.append("wing présente et bloquée : le blocage devrait tenir")

        # 2) un init réussi efface tout
        wi._trouver = lambda *a, **k: _Faux(1, 7)
        wing_etat_materiel._marquer_blocage()
        wing_etat_materiel.effacer_etat_materiel()
        if wing_etat_materiel.blocage_connu():
            ennuis.append("effacer_etat_materiel ne lève pas le blocage")

        # 4) un clic délibéré (force=True) passe outre
        wing_etat_materiel._marquer_blocage()
        src = (HERE / "wing_init.py").read_text(encoding="utf-8")
        code = "\n".join(l for l in src.splitlines()
                         if not l.strip().startswith("#"))
        if "if wing_etat_materiel.blocage_connu() and not force:" not in code:
            ennuis.append("full_init n'accepte plus le contournement par force")
        # ⚠️ LE DEUXIÈME VERROU DOIT AVOIR LA MÊME DÉROGATION.
        #
        # 🐛 `full_init` a DEUX verrous distincts avant d'envoyer le firmware :
        # `blocage_connu()` (ci-dessus) ET `_firmware_envoye_recemment()` (le
        # cooldown anti-martèlement). Seul le premier avait `and not force` —
        # le second retenait donc encore un clic délibéré sur « Connecter la
        # wing », alors que `connect_wing()` le documente comme LE DERNIER
        # RECOURS GARANTI. Un recours qui ne l'est qu'à moitié ne vaut rien.
        if "if wing_etat_materiel._firmware_envoye_recemment() and not force:" not in code:
            ennuis.append("full_init n'accepte plus le contournement de "
                          "_firmware_envoye_recemment() par force — le "
                          "dernier recours (bouton Connecter) resterait "
                          "bloqué par le cooldown anti-martèlement")
    except Exception as e:
        ennuis.append(f"exception : {type(e).__name__}: {e}")
    finally:
        wing_etat_materiel.ETAT_FICHIER, wi._trouver = sauve_f, sauve_t

    if ennuis:
        echec("le blocage persistant peut rester coincé", " ; ".join(ennuis))
    else:
        ok("blocage tenu quand il faut, levé par : absence · init réussi · force")


def test_poignee_pendant_reboot():
    """On ne ferme pas la liaison USB pendant que la wing reboote.

    🔎 Mesuré dans `d.pcapng` — la capture de MA2 onPC, seule
    implémentation connue qui marche. Après l'End packet :

        17 paquets / 17 408 o lus en 25 ms, puis 1,29 s de SILENCE
        pendant lesquelles le host ne ferme RIEN (aucun transfert de contrôle,
        aucune libération) jusqu'à ce que la wing quitte le bus.

    Notre code appelait `_liberer(dev)` juste après l'envoi, donc EN PLEIN
    REBOOT. C'était le seul écart net avec la référence.

    ⚠️ Hypothèse, pas une cause démontrée. Ce contrôle ne dit pas « ça répare » ;
    il empêche de re-diverger sans s'en apercevoir.

    Lecture du CODE seul (commentaires retirés) : le mot `_liberer` figure
    aussi dans les commentaires qui expliquent la règle — piège déjà rencontré
    aux contrôles test_poll_pkt et test_sorties_rendent_la_wing.
    """
    section("30. La liaison n'est pas fermée pendant le reboot de la wing")
    lignes = [l for l in (HERE / "wing_init.py").read_text(encoding="utf-8").splitlines()
              if not l.strip().startswith("#")]
    src = "\n".join(lignes)
    # Ancre volontairement SANS la parenthèse fermante : l'appel réel porte
    # aussi `force_operateur=...` — exiger `)` ici a déjà fait sauter ce
    # contrôle en silence quand la signature a gagné un argument.
    i = src.find("ok = upload_firmware(dev, verbose=verbose")
    if i < 0:
        echec("appel `ok = upload_firmware(dev, verbose=verbose…` introuvable "
              "dans wing_init.py — la séquence d'envoi du firmware a changé de forme")
        return
    j = src.find("attendre_disparition", i)
    if j < 0:
        echec("aucune attente de départ après l'envoi du firmware",
              "la wing doit avoir quitté le bus avant qu'on rende la liaison")
        return
    entre = src[i:j]
    # Un `_liberer` est légitime dans la branche d'échec (rien n'a démarré) ;
    # il ne doit PAS y en avoir sur le chemin nominal, hors de ce `if not ok`.
    lignes_entre = [l.strip() for l in entre.splitlines() if "_liberer(" in l]
    hors_echec = []
    for l in lignes_entre:
        # la seule tolérée est celle indentée sous `if not ok:`
        if "_liberer(dev)" in l:
            hors_echec.append(l)
    bloc_echec = entre[entre.find("if not ok:"):] if "if not ok:" in entre else ""
    tolerees = bloc_echec.count("_liberer(dev)")
    if len(hors_echec) > tolerees:
        echec("la liaison USB est fermée pendant le reboot de la wing",
              f"{len(hors_echec) - tolerees} appel(s) à _liberer entre l'envoi du "
              f"firmware et l'attente de départ — MA2 onPC garde la poignée "
              f"1,29 s, jusqu'à ce que la wing quitte le bus (d.pcapng)")
    elif "_liberer" not in src[j:j + 400]:
        echec("la liaison n'est jamais rendue après le départ de la wing",
              "règle : tout chemin doit rendre ce qu'il tient")
    else:
        ok("poignée gardée pendant le reboot, rendue après le départ du bus")


def test_reconnexion_sans_fantomes(ui):
    """Une reconnexion n'envoie RIEN à MA3 avant d'avoir repris sa ligne de base.

    🔴 TROUVÉ DANS UN JOURNAL, pas par une relecture.
    Juste après une reconnexion automatique, personne ne touchant à la wing :

        18:29:01  ✓ Wing connectée
        18:29:01  FADER F1 → Master 1.1 At 0
        18:29:01  ENC1 Dimmer +52
        18:29:01  ENC2 Iris -56

    Ces commandes sont parties vers MA3. `prev_faders` / `prev_encs` gardaient
    l'état d'AVANT la coupure, et le premier paquet du retour était comparé à
    cet état périmé. Le garde-fou `startup_skip` n'était réarmé que sur un
    changement de MODE — que la boucle ne voit jamais lors d'une reconnexion.

    Ce contrôle fait tourner la VRAIE `usb_loop` avec des doublures : wing à
    une position, décrochage, retour à une position DIFFÉRENTE. Rien ne doit
    partir vers MA3 — la nouvelle position est une ligne de base, pas un geste
    de l'utilisateur.

    ⚠️ Il vérifie AUSSI que la boucle a réellement tourné. Un scénario qui
    n'exécute rien passerait au vert sans rien prouver — c'est exactement ce
    qui est arrivé au contrôle test_ids le même jour.
    """
    section("37. Reconnexion : aucune valeur fantôme vers MA3")
    import threading as _th

    sauv = {"OSC": etat.E.OSC, "cycle": ui.cycle_dmx, "pstate": ui.wb.parse_state,
            "pevents": ui.wb.parse_events, "absente": ui.wing_init.wing_absente,
            "connect": ui.connect_wing, "etat": ui.ma3_etat, "log": ui.log,
            "mode": etat.E.STATE["mode"], "want": etat.E.STATE["want_connected"],
            "dev": etat.E.DEV[0], "ledma3": etat.E.LED["ma3"],
            "interval": etat.E.AUTO["interval"], "wing": etat.E.STATE["wing"]}

    envois = []
    devA, devB = object(), object()
    scene = {"n": 0, "val": 500, "enc": 1000}
    MAX_TOURS = 40

    def faux_cycle(dev):
        scene["n"] += 1
        if scene["n"] > MAX_TOURS:
            ui.USB_ARRET.set()
            return None
        if scene["n"] == 8:                 # la wing décroche du bus
            raise ui.WingUnplugged()
        return b"\x00" * 96

    def faux_connect(force=False, quiet=False):
        # La wing revient — DANS UNE AUTRE POSITION que celle d'avant.
        etat.E.DEV[0] = devB
        etat.E.STATE["wing"] = True
        scene["val"], scene["enc"] = 900, 1500

    class _Osc:
        def send_message(self, adresse, msg):
            envois.append(msg)

    try:
        etat.E.OSC = _Osc()
        ui.cycle_dmx = faux_cycle
        ui.wb.parse_state = lambda d: {"faders": [scene["val"]] * 8,
                                       "encoders": [scene["enc"]] * 4}
        ui.wb.parse_events = lambda d: []
        ui.wing_init.wing_absente = lambda: False
        ui.connect_wing = faux_connect
        ui.ma3_etat = lambda: {"actif": False}   # sans sonde : envoi direct
        ui.log = lambda *a, **k: None
        etat.E.LED["ma3"] = False
        etat.E.AUTO["interval"] = 0.0
        etat.E.FADER_LAST.clear(); etat.E.FADER_T.clear(); etat.E.FADER_ATTENTE.clear()
        etat.E.PICKUP.clear()
        etat.E.STATE["mode"] = "bridge"
        etat.E.STATE["want_connected"] = True
        etat.E.STATE["connecting"] = False
        etat.E.STATE["wing"] = True
        etat.E.DEV[0] = devA
        ui.USB_ARRET.clear(); ui.USB_SORTIE.clear()

        fil = _th.Thread(target=ui.usb_loop, daemon=True)
        fil.start()
        fil.join(timeout=20)
        vivant = fil.is_alive()
    finally:
        ui.USB_ARRET.set()
        time.sleep(0.05)
        etat.E.OSC = sauv["OSC"]; ui.cycle_dmx = sauv["cycle"]
        ui.wb.parse_state = sauv["pstate"]; ui.wb.parse_events = sauv["pevents"]
        ui.wing_init.wing_absente = sauv["absente"]
        ui.connect_wing = sauv["connect"]; ui.ma3_etat = sauv["etat"]
        ui.log = sauv["log"]; etat.E.LED["ma3"] = sauv["ledma3"]
        etat.E.AUTO["interval"] = sauv["interval"]
        etat.E.STATE["mode"] = sauv["mode"]
        etat.E.STATE["want_connected"] = sauv["want"]
        etat.E.STATE["wing"] = sauv["wing"]
        etat.E.DEV[0] = sauv["dev"]
        etat.E.FADER_LAST.clear(); etat.E.FADER_T.clear(); etat.E.FADER_ATTENTE.clear()
        ui.USB_ARRET.clear(); ui.USB_SORTIE.clear()

    if vivant:
        echec("la boucle USB simulée ne s'est pas arrêtée",
              "scénario ou stub fautif — résultat non concluant")
        return
    # ⚠️ Un scénario qui n'a rien exécuté « passerait » sans rien prouver.
    if scene["n"] < 12:
        echec("le scénario n'a pas tourné assez pour conclure",
              f"{scene['n']} tour(s) de boucle — attendu > 12")
        return
    if scene["val"] != 900:
        echec("la reconnexion simulée n'a jamais eu lieu",
              "connect_wing n'a pas été appelée : le scénario ne teste rien")
        return
    if envois:
        echec(f"{len(envois)} commande(s) parties vers MA3 après la reconnexion",
              " · ".join(envois[:4]) + " — la wing est revenue dans une autre "
              "position et l'app l'a prise pour un geste de l'utilisateur. "
              "En régie : un niveau qui saute tout seul au retour d'un câble")
        return
    ok(f"{scene['n']} tours joués, décrochage + retour en position différente : "
       f"rien n'est parti vers MA3")


def test_fenetre_apres_fw_cfg(wi):
    """La fenêtre d'après FW_CFG est mesurée, et la mesure sait dire quoi.

    🔭 Ce qui manque à l'enquête sur l'entrée en bootloader n'est pas une idée
    de plus : c'est une grandeur qui SÉPARE un démarrage réussi d'un refus. La
    seule connue est la fenêtre de ~25 ms qui suit `FW_CFG_PKT`, dernier moment
    où la wing parle avant de rebooter. `d.pcapng` y montre 17 paquets de
    1024 o à la signature bootloader, le dernier à +25,3 ms.

    Ce contrôle garde les TROIS propriétés sans lesquelles la mesure ne vaut
    rien — chacune correspond à un défaut réel du code de ce matin :

    1. **Un timeout ≠ un device parti.** La trace disait « refusée (USBError) »
       et on en avait conclu que la wing avait quitté le bus. Non fondé : un
       délai dépassé de 500 ms donne le même mot.
    2. **On ne dort pas les yeux fermés dans la fenêtre.** Le délai avant la
       carte des LEDs était un `sleep(6,6 ms)` — soit le premier quart de la
       fenêtre, non observé, là où la référence a quatre paquets.
    3. **La mesure part aussi quand ça MARCHE.** Sinon il n'y a pas de témoin,
       et dix relevés de panne ne se comparent à rien.
    """
    section("44. La fenêtre après FW_CFG")
    src = (HERE / "wing_init.py").read_text(encoding="utf-8")

    # 1. Les erreurs USB sont départagées, pas amalgamées
    class _E(Exception):
        def __init__(s, c): s.backend_error_code = c; s.errno = None
    try:
        parti, delai = wi._err_usb(_E(-4)), wi._err_usb(_E(-7))
        if parti == delai:
            echec("un device PARTI et un délai dépassé donnent le même texte",
                  f"les deux disent « {parti} » — c'est exactement l'amalgame "
                  "qui a fait conclure à tort que la wing avait quitté le bus")
        elif wi._partie_du_bus(_E(-7)) or not wi._partie_du_bus(_E(-4)):
            echec("_partie_du_bus se trompe de verdict",
                  f"délai dépassé → {wi._partie_du_bus(_E(-7))}, "
                  f"device parti → {wi._partie_du_bus(_E(-4))}")
        else:
            ok(f"erreurs USB départagées : « {parti} » ≠ « {delai} », "
               "seule la première prouve une sortie du bus")
    except Exception as e:
        echec("le classement des erreurs USB a levé une exception",
              f"{type(e).__name__}: {e}")

    # 2. On lit pendant l'attente au lieu de dormir
    bloc = src[src.find("if ENVOYER_CARTE_LED"):][:600]
    if "time.sleep(FW_LED_DELAI)" in bloc:
        echec("la fenêtre redort les yeux fermés avant la carte des LEDs",
              "`time.sleep(FW_LED_DELAI)` est de retour : les 6,6 premières ms "
              "de la fenêtre ne sont plus observées, or `d.pcapng` y montre "
              "4 paquets entrants. Utiliser `_attendre_en_lisant`")
    elif "_attendre_en_lisant" not in bloc:
        echec("l'attente avant la carte des LEDs ne mesure rien",
              "ni sommeil ni lecture identifiés dans le bloc — vérifier")
    else:
        ok("l'attente avant la carte des LEDs LIT le bus au lieu de dormir")

    # 3. Le compteur existe, et il est comparé à la référence de la capture
    manque = [k for k in ("paquets", "dernier_ms", "partie_ms", "signature")
              if k not in wi._DRAIN]
    if manque:
        echec("la fenêtre n'est plus mesurée", f"_DRAIN a perdu : {manque}")
    elif wi.DRAIN_REF.get("paquets") != 17 or wi.DRAIN_REF.get("dernier_ms") != 25.3:
        echec("la référence de d.pcapng a été modifiée",
              f"DRAIN_REF = {wi.DRAIN_REF} — ces chiffres viennent de la "
              "capture (tshark). Ne pas les « corriger » sans "
              "re-dériver depuis d.pcapng")
    else:
        wi._DRAIN.update(paquets=3, octets=3072, premier_ms=1.0, dernier_ms=4.2,
                         signature="0400079101000100", partie_ms=4.3,
                         partie_par="device parti", cfg_erreur="")
        t = wi._trace_drain()
        absents = [x for x in ("3 paquet", "réf. 17", "4.2", "25.3", "4.3")
                   if x not in t]
        if absents:
            echec("la trace de la fenêtre ne dit pas ce qu'il faut",
                  f"« {t} » — manquent : {absents}. Une mesure sans son étalon "
                  "ne se relit pas dans six mois")
        else:
            ok("la fenêtre est comptée et rapportée AVEC la référence "
               f"(exemple : « {t} »)")
        wi._DRAIN.update(paquets=0, octets=0, premier_ms=None, dernier_ms=None,
                         signature="", partie_ms=None, partie_par="")

    # 4. Le TRAJET de l'attente est relevé, pas seulement l'état final
    #
    # ⚠️ D'ABORD la SOURCE, ensuite l'affichage. Première version de ce contrôle
    # : elle remplissait `trajet` elle-même et ne vérifiait que
    # `_trace_envoi`. Résultat, elle est restée VERTE alors que
    # `attendre_reapparition` avait été amputée de l'enregistrement — le relevé
    # n'existait plus, et rien ne le disait. Un contrôle qui fabrique sa propre
    # donnée d'entrée ne teste que lui-même.
    faux_dev, etapes = object(), ["bootloader", "bootloader", "operationnelle"]
    memo = (wi._trouver, wi.etat_wing)
    try:
        wi._trouver = lambda *a, **k: faux_dev
        wi.etat_wing = lambda d: etapes.pop(0) if etapes else "operationnelle"
        wi.attendre_reapparition(timeout_s=3.0)
        trace = list(wi.DERNIER_ENVOI.get("trajet") or [])
    finally:
        wi._trouver, wi.etat_wing = memo
    if len(trace) < 2 or [e for _, e in trace] != ["bootloader", "operationnelle"]:
        echec("attendre_reapparition n'enregistre plus le trajet de l'attente",
              f"relevé : {trace} — attendu bootloader puis operationnelle. "
              "Sans cet enregistrement on ne peut savoir ni si prolonger "
              "l'attente servirait, ni si on peut trancher plus tôt")
    else:
        ok(f"attendre_reapparition enregistre les changements d'état "
           f"({len(trace)} étape(s) relevées sur un trajet simulé)")

    wi.DERNIER_ENVOI.update(octets=1, depart_s=None, retour_s=15.6,
                            etat="bootloader", carte_led=None, vue_s=0.8,
                            trajet=[(0.8, "bootloader")])
    t = wi._trace_envoi()
    if "JAMAIS bougé" not in t:
        echec("le trajet de l'attente n'est plus rapporté",
              f"« {t} » — sans lui on ne peut pas savoir si prolonger l'attente "
              "servirait, ni si on peut trancher plus tôt. Neuf échecs ont "
              "consommé 15,6 s chacun sans qu'on sache si l'état bougeait")
    else:
        wi.DERNIER_ENVOI["trajet"] = [(0.8, "bootloader"), (11.0, "operationnelle")]
        if "JAMAIS bougé" in wi._trace_envoi():
            echec("« JAMAIS bougé » s'affiche même quand l'état a changé",
                  "le relevé mentirait exactement là où il compte")
        else:
            ok("le trajet de l'attente est tracé, et « JAMAIS bougé » ne "
               "s'affiche que si l'état est resté figé")
    wi.DERNIER_ENVOI["trajet"] = []

    # 5. Le verdict anticipé rend la main tôt — SANS rater un réveil tardif
    #
    # ⚠️ Les deux moitiés comptent. Trancher tôt fait gagner 10 s par échec ;
    # trancher tôt SUR UNE WING QUI ALLAIT SE RÉVEILLER envoie l'utilisateur
    # débrancher pour rien — le pire message de cette app.
    def _rejoue(suite, fige):
        t0, pas = time.perf_counter(), 0.2
        i = lambda: min(int((time.perf_counter() - t0) / pas), len(suite) - 1)
        memo2 = (wi._trouver, wi.etat_wing)
        try:
            wi._trouver = lambda *a, **k: None if suite[i()] == "absente" else object()
            wi.etat_wing = lambda d: suite[i()]
            d0 = time.perf_counter()
            _, e = wi.attendre_reapparition(timeout_s=6.0, fige_s=fige)
            return e, time.perf_counter() - d0
        finally:
            wi._trouver, wi.etat_wing = memo2

    fige, mous = [], ["absente"] * 3 + ["bootloader"] * 200
    etat_fige, duree_fige = _rejoue(mous, 1.0)
    if duree_fige > 3.0:
        fige.append(f"état figé : {duree_fige:.1f} s au lieu de ~1,6 s "
                    "— le verdict anticipé ne coupe plus rien")
    tardif = ["absente"] * 3 + ["bootloader"] * 5 + ["operationnelle"] * 200
    etat_tardif, _ = _rejoue(tardif, 1.0)
    if etat_tardif != "operationnelle":
        fige.append(f"réveil tardif MANQUÉ : rendu « {etat_tardif} » alors que "
                    "la wing devenait opérationnelle — on enverrait débrancher "
                    "pour rien")
    if fige:
        echec("le verdict anticipé ne se comporte pas comme prévu",
              " ; ".join(fige))
    else:
        ok(f"verdict anticipé : tranche en {duree_fige:.1f} s sur un état figé, "
           "et laisse passer un réveil tardif")

    # 6. La mesure part aussi sur un démarrage RÉUSSI, pas seulement en panne
    # (le message est passé en clé i18n `journal.init.fw_reussi` — on cherche
    # l'appel à `_trace_envoi()` sur CETTE ligne, pas le mot « réussi »).
    reussi = re.search(r"journal\.init\.fw_reussi[^\n]*_trace_envoi\(\)", src)
    if not reussi:
        echec("la mesure ne part QUE sur les échecs",
              "aucun appel à `_trace_envoi()` sur le chemin de réussite de "
              "`full_init` — sans témoin, les relevés de panne ne se comparent "
              "à rien et l'enquête sur l'entrée en bootloader ne peut pas avancer")
    else:
        ok("le chemin de RÉUSSITE trace la fenêtre lui aussi — il y a un témoin")


def test_desinstallation(ui):
    """La désinstallation efface-t-elle ce qu'elle annonce, et RIEN d'autre ?

    🔑 L'endpoint /api/uninstall est destructif :
    il finit par `os._exit(0)`. On ne l'appelle donc JAMAIS pour de vrai ici —
    on l'appelle en `dry_run: true`, qui renvoie les listes sans rien toucher
    ni quitter, et on vérifie trois choses :

      a. les fichiers PUREMENT INTERNES (__reference__, __autosave__,
         wing_hw_state, settings) sont TOUJOURS dans `deleted`, quel que soit
         `keep` — rien d'interne ne survit ;
      b. `keep.profiles` bascule les *.json utilisateur entre `kept` et
         `deleted` (idem `keep.log` pour le journal, `keep.ma3_plugin` pour le
         plugin MA3) ;
      c. le dry-run ne touche pas au disque.

    Réinjection : rendre un fichier interne « conservable » dans
    `_desinstall_plan` doit faire passer ce contrôle ROUGE.
    """
    section("47. Désinstallation : le dry-run dit vrai, sans rien toucher")
    import tempfile
    import shutil as _sh
    import wing_mapper as wm
    import wing_ma3
    import wing_handler
    import wing_desinstall

    tmp = Path(tempfile.mkdtemp())
    data = tmp / "Wing Bridge"
    prof = data / "profiles"
    prof.mkdir(parents=True)
    # Sous Windows, l'assistant clavier écrit son journal dans
    # %LOCALAPPDATA%\Wing Bridge, un dossier À PART de PROFILE_DIR.parent
    # (= %APPDATA%). On le modélise ici pour vérifier que le plan l'y trouve.
    local = tmp / "Local" / "Wing Bridge"
    local.mkdir(parents=True)
    plugdir = tmp / "MA" / "gma3_library" / "datapools" / "plugins"
    plugdir.mkdir(parents=True)
    fichier_etat = tmp / "MA" / "gma3_library" / "wingbridge_state.json"

    def _mk(p):
        p.write_text("x", encoding="utf-8")
        return p.name

    # Fichiers internes : dans profiles/ (préfixe __, ou suffixe non-.json) ET
    # à la racine du dossier de données (état, réglages).
    INTERNES = {_mk(prof / "__reference__.json"),
                _mk(prof / "__autosave__.json"),
                _mk(prof / "mini-wing.json.avant-renum"),
                _mk(data / "wing_hw_state.json"),
                _mk(data / "settings.json"),
                _mk(data / ".DS_Store")}
    USER = {_mk(prof / "mini-wing.json"), _mk(prof / "défauts-sécurité.json")}
    LOGS = {_mk(data / "wing_server.log"),
            _mk(data / "wing_server-20260101-000000.log"),
            _mk(local / "wing_keyboard.log")}       # journal clavier : dossier à part
    PLUGIN = {_mk(plugdir / "wingbridge.lua"), _mk(plugdir / "wingbridge.xml"),
              _mk(plugdir / "wingloader.lua"), _mk(plugdir / "wingloader.xml"),
              _mk(plugdir / "wingbridge.lua.v8.bak"),
              _mk(fichier_etat)}

    sv_dir, sv_base, sv_etat = wm.PROFILE_DIR, wing_ma3._ma3_base, wing_ma3.MA3_ETAT_FICHIER
    sv_local = wing_desinstall.dossier_local
    ennuis = []
    try:
        wm.PROFILE_DIR = prof
        wing_ma3._ma3_base = lambda: tmp / "MA"
        wing_ma3.MA3_ETAT_FICHIER = fichier_etat
        wing_desinstall.dossier_local = lambda: local

        def plan(keep):
            r = _poster(ui, "/api/uninstall", {"keep": keep, "dry_run": True})
            return ({Path(p).name for p in r.get("deleted", [])},
                    {Path(p).name for p in r.get("kept", [])}, r)

        # a. tout conserver — les internes partent quand même
        dele, kept, r = plan({"profiles": True, "log": True, "ma3_plugin": True})
        if not r.get("dry_run"):
            ennuis.append("dry_run non signalé dans la réponse")
        if not (prof / "__reference__.json").exists():
            ennuis.append("le dry-run a EFFACÉ un fichier — il ne doit RIEN toucher")
        if not INTERNES <= dele:
            ennuis.append(f"keep=tout : fichiers internes hors de deleted : {sorted(INTERNES - dele)}")
        if not (USER <= kept and LOGS <= kept and PLUGIN <= kept):
            ennuis.append("keep=tout : profils/journal/plugin devraient être conservés")
        if dele & (USER | LOGS | PLUGIN):
            ennuis.append(f"keep=tout mais supprime : {sorted(dele & (USER | LOGS | PLUGIN))}")

        # b. ne rien conserver — tout part
        dele, kept, _ = plan({})
        if not (INTERNES | USER | LOGS | PLUGIN) <= dele:
            ennuis.append(f"keep=rien : il reste des fichiers hors de deleted : "
                          f"{sorted((INTERNES | USER | LOGS | PLUGIN) - dele)}")
        if kept:
            ennuis.append(f"keep=rien mais des fichiers conservés : {sorted(kept)}")

        # c. chaque case isolément
        for cle, groupe, nom in (("profiles", USER, "profils"),
                                 ("log", LOGS, "journal"),
                                 ("ma3_plugin", PLUGIN, "plugin MA3")):
            dele, kept, _ = plan({cle: True})
            if not groupe <= kept:
                ennuis.append(f"keep.{cle} : {nom} pas dans kept ({sorted(groupe - kept)})")
            if groupe & dele:
                ennuis.append(f"keep.{cle} : {nom} supprimés malgré la case")
            if not INTERNES <= dele:
                ennuis.append(f"keep.{cle} : un fichier interne survit")

        # d. résidu manuel non vide, sans nom de script
        _, _, r = plan({})
        res = r.get("residue", [])
        if not res or any(".py" in t for t in res):
            ennuis.append("résidu manuel vide ou citant un script")
    finally:
        wm.PROFILE_DIR = sv_dir
        wing_ma3._ma3_base = sv_base
        wing_ma3.MA3_ETAT_FICHIER = sv_etat
        wing_desinstall.dossier_local = sv_local
        _sh.rmtree(tmp, ignore_errors=True)

    if ennuis:
        echec("la désinstallation ne fait pas ce qu'elle annonce",
              " ; ".join(ennuis))
    else:
        ok("dry-run fidèle : internes toujours supprimés, profils/journal/plugin "
           "suivent leur case, disque intact")


def test_connect_wing_verrou_et_boucle(ui, wc):
    """connect_wing() : verrou atomique (#1) et arrêt propre de usb_loop (#4).

    🐛 Deux bugs jumeaux trouvés par relecture, dans la zone la plus critique
    du projet (connexion USB / renvoi de firmware — « un plantage pendant un
    show coûte plus cher que dix fonctions manquantes »).

    1. Le test-et-pose de `STATE["connecting"]` n'était protégé par AUCUN
       verrou, alors que `usb_loop`, un thread lancé par `_flux_muet` et la
       route HTTP `/api/wing/connect` peuvent tous appeler `connect_wing()`
       EN MÊME TEMPS. Deux appels concurrents pouvaient tous les deux lire
       `connecting=False` avant que l'un des deux ne le pose, et passer TOUS
       LES DEUX — deux `full_init()` sur le même device au même instant.

    2. `connect_wing()` appelait `_release_device()` SANS JAMAIS signaler à
       `usb_loop` de s'arrêter — alors que celui-ci continue ses
       `dev.write()`/`dev.read()` indépendamment tant qu'il tient un `dev`.
       Contrairement à `arreter_usb()`, qui pose `USB_ARRET` et attend
       `USB_SORTIE` AVANT de relâcher, `connect_wing()` relâchait tout de
       suite : deux threads sur le même device au même instant.

    Vérifié SANS matériel : `full_init` et `usb_loop` sont remplacés par des
    doublures contrôlables (aucune vraie E/S USB). `wing_absente` et
    `DERNIER_ECHEC` sont neutralisés pour ne dépendre d'AUCUN état réel —
    y compris celui d'une wing effectivement branchée pendant le test.
    """
    section("55. connect_wing() : verrou atomique et arrêt propre de usb_loop")
    import threading as _th

    # ── (1) Le test-et-pose de STATE["connecting"] est ATOMIQUE ─────────────
    sauv1 = {"full_init": ui.full_init, "log": ui.log, "dev": etat.E.DEV[0],
             "state": dict(etat.E.STATE), "auto": dict(etat.E.AUTO),
             "absente": ui.wing_init.wing_absente,
             "dernier_echec": dict(ui.wing_init.DERNIER_ECHEC)}
    compteur = {"en_cours": 0, "max": 0}
    verrou = _th.Lock()

    def faux_full_init(verbose=False, force=False, force_operateur=False):
        with verrou:
            compteur["en_cours"] += 1
            compteur["max"] = max(compteur["max"], compteur["en_cours"])
        time.sleep(0.1)
        with verrou:
            compteur["en_cours"] -= 1
        return None       # échec simulé : simplifie, aucun succès à gérer

    try:
        ui.full_init = faux_full_init
        ui.log = lambda *a, **k: None
        ui.wing_init.wing_absente = lambda: False   # déterministe, sans matériel
        ui.wing_init.DERNIER_ECHEC["firmware_bloque"] = False
        etat.E.DEV[0] = None                        # bug #4 hors périmètre ici
        etat.E.STATE.update(connecting=False, wing=False, want_connected=False,
                        mode="idle", resume_mode=None)
        etat.E.AUTO.update(interval=999.0)          # n'entrave pas ce sous-test

        fils = [_th.Thread(target=lambda: wc.connect_wing(force=True, quiet=True))
                for _ in range(6)]
        for f in fils:
            f.start()
        for f in fils:
            f.join(timeout=5)

        if any(f.is_alive() for f in fils):
            echec("un appel concurrent à connect_wing() ne s'est pas terminé",
                  "interblocage possible introduit par le verrou")
        elif compteur["max"] > 1:
            echec("DEUX APPELS CONCURRENTS À connect_wing() ONT TRAVERSÉ LE "
                  "VERROU",
                  f"{compteur['max']} exécutions simultanées de full_init() "
                  f"pour {len(fils)} threads concurrents — le test-et-pose de "
                  f"STATE['connecting'] n'est plus atomique")
        else:
            ok(f"{len(fils)} appels concurrents à connect_wing() : jamais "
               f"plus d'un full_init() à la fois")
    except Exception as e:
        echec("le scénario de concurrence a levé une exception",
              f"{type(e).__name__}: {e}")
    finally:
        ui.full_init = sauv1["full_init"]
        ui.log = sauv1["log"]
        ui.wing_init.wing_absente = sauv1["absente"]
        ui.wing_init.DERNIER_ECHEC.clear()
        ui.wing_init.DERNIER_ECHEC.update(sauv1["dernier_echec"])
        etat.E.DEV[0] = sauv1["dev"]
        etat.E.STATE.clear(); etat.E.STATE.update(sauv1["state"])
        etat.E.AUTO.clear(); etat.E.AUTO.update(sauv1["auto"])

    # ── Audit de source : le test-et-pose reste bien SOUS core.LOCK ─────────
    #
    # 🔑 Le contrôle comportemental ci-dessus NE SUFFIT PAS SEUL. Vérifié :
    # une réinjection du bug (retirer le `with core.LOCK:` et redonner au
    # test et à la pose leur indentation d'origine, séparés) fait TOUJOURS
    # PASSER le contrôle comportemental — la fenêtre de course tient en
    # quelques instructions, bien trop étroite pour que le GIL l'expose de
    # façon fiable avec seulement 6 threads. Un contrôle qui ne peut pas
    # rougir sur le bug qu'il prétend surveiller ne sert à rien : on vérifie
    # donc AUSSI, dans le texte, que le test-et-pose reste groupé sous le
    # même verrou.
    src_cnx = (HERE / "wing_connexion.py").read_text(encoding="utf-8") \
        .replace("etat.E.", "core.")  # etat.E.X ramené à core.X : mêmes motifs d'audit (D1, 25/09/2026)
    i_def = src_cnx.find("def connect_wing(")
    bloc_cnx = src_cnx[i_def:i_def + 2500] if i_def != -1 else ""
    i_lock = bloc_cnx.find("with core.LOCK:")
    apres_lock = bloc_cnx[i_lock:i_lock + 400] if i_lock != -1 else ""
    if i_def == -1:
        echec("connect_wing() introuvable dans wing_connexion.py", "")
    elif i_lock == -1:
        echec("LE TEST-ET-POSE DE connecting N'EST PLUS SOUS core.LOCK",
              "connect_wing() ne contient plus `with core.LOCK:` — le "
              "contrôle comportemental juste au-dessus ne peut PAS garantir "
              "de voir passer la course, sa fenêtre étant trop étroite pour "
              "le GIL")
    elif ('if core.STATE["connecting"]:' not in apres_lock
          or 'core.STATE["connecting"] = True' not in apres_lock):
        echec("LE TEST-ET-POSE DE connecting N'EST PLUS ATOMIQUE",
              "le test et la pose de STATE['connecting'] ne sont plus "
              "regroupés sous le MÊME `with core.LOCK:`")
    else:
        ok("le test-et-pose de STATE['connecting'] reste sous core.LOCK "
           "(audit de source — un contrôle comportemental seul ne peut pas "
           "garantir de voir passer une course aussi étroite)")

    # ── (2) usb_loop est mis en pause AVANT que le device soit relâché ──────
    sauv2 = {"full_init": ui.full_init, "log": ui.log, "dev": etat.E.DEV[0],
             "state": dict(etat.E.STATE), "auto": dict(etat.E.AUTO),
             "absente": ui.wing_init.wing_absente,
             "dernier_echec": dict(ui.wing_init.DERNIER_ECHEC),
             "usb_loop": wc.usb_loop}
    preuve = {"libere_apres_sortie": None, "appels_liberation": 0}
    vrai_release = wc._release_device

    class _FauxBoucle:
        """Remplace `usb_loop` : au lieu de vraiment parler à l'USB, boucle
        sur `USB_ARRET` comme la vraie boucle, et compte ses démarrages."""
        def __init__(self):
            self.demarrages = 0
            self.a_vu_arret = _th.Event()

        # `gen` : connect_wing() passe désormais la génération de la boucle
        # (voir test_une_seule_boucle_usb) — la doublure l'accepte et l'ignore.
        def __call__(self, gen=None):
            self.demarrages += 1
            self.a_vu_arret.clear()
            while not wc.USB_ARRET.is_set():
                time.sleep(0.005)
            self.a_vu_arret.set()
            wc.USB_SORTIE.set()

    faux_boucle = _FauxBoucle()

    def release_espionne():
        preuve["appels_liberation"] += 1
        # 🔑 LA PREUVE : au moment où le device est VRAIMENT relâché, la fausse
        # boucle a-t-elle déjà VU passer USB_ARRET ? Si non, `connect_wing()`
        # a relâché sans attendre — exactement le bug #4.
        preuve["libere_apres_sortie"] = faux_boucle.a_vu_arret.is_set()
        return vrai_release()

    try:
        wc.usb_loop = faux_boucle
        wc._release_device = release_espionne
        ui.full_init = lambda verbose=False, force=False, force_operateur=False: None
        ui.log = lambda *a, **k: None
        ui.wing_init.wing_absente = lambda: False
        ui.wing_init.DERNIER_ECHEC["firmware_bloque"] = False
        etat.E.STATE.update(connecting=False, wing=True, want_connected=False,
                        mode="bridge", resume_mode=None)
        etat.E.AUTO.update(interval=999.0)
        etat.E.DEV[0] = object()                    # un device "actif" à protéger
        wc.USB_ARRET.clear(); wc.USB_SORTIE.clear()

        fil_boucle = _th.Thread(target=faux_boucle, daemon=True, name="usb_loop")
        fil_boucle.start()
        time.sleep(0.02)          # laisse la fausse boucle vraiment démarrer

        fil_connect = _th.Thread(
            target=lambda: wc.connect_wing(force=True, quiet=True))
        fil_connect.start()
        fil_connect.join(timeout=5)

        if fil_connect.is_alive():
            echec("connect_wing() ne s'est pas terminé",
                  "interblocage possible avec la fausse boucle usb_loop")
        elif preuve["appels_liberation"] != 1:
            echec("_release_device() n'a pas été appelé exactement une fois",
                  f"{preuve['appels_liberation']} appel(s)")
        elif not preuve["libere_apres_sortie"]:
            echec("LE DEVICE A ÉTÉ RELÂCHÉ AVANT QUE usb_loop AIT CONFIRMÉ SA "
                  "SORTIE",
                  "connect_wing() a appelé _release_device() sans attendre "
                  "USB_SORTIE — deux threads pourraient toucher le même "
                  "device USB en même temps")
        elif faux_boucle.demarrages < 2:
            echec("usb_loop n'a pas été relancé après la reconnexion",
                  f"{faux_boucle.demarrages} démarrage(s) — plus personne ne "
                  f"piloterait la wing ni l'auto-reconnexion après un "
                  f"connect_wing()")
        elif wc.USB_ARRET.is_set() or wc.USB_SORTIE.is_set():
            echec("les drapeaux d'arrêt ne sont pas nettoyés après le "
                  "redémarrage de usb_loop",
                  f"USB_ARRET={wc.USB_ARRET.is_set()} "
                  f"USB_SORTIE={wc.USB_SORTIE.is_set()}")
        else:
            ok("connect_wing() arrête usb_loop et ATTEND sa sortie avant de "
               "relâcher le device, puis le relance")
    except Exception as e:
        echec("le scénario usb_loop/connect_wing a levé une exception",
              f"{type(e).__name__}: {e}")
    finally:
        # Le redémarrage de connect_wing() a lancé une DEUXIÈME fausse boucle
        # (la même doublure, réutilisée) : il faut aussi l'arrêter, sans quoi
        # elle continuerait à consommer un fil pour le reste de la suite.
        wc.USB_ARRET.set()
        time.sleep(0.05)
        wc._release_device = vrai_release
        wc.usb_loop = sauv2["usb_loop"]
        ui.full_init = sauv2["full_init"]
        ui.log = sauv2["log"]
        ui.wing_init.wing_absente = sauv2["absente"]
        ui.wing_init.DERNIER_ECHEC.clear()
        ui.wing_init.DERNIER_ECHEC.update(sauv2["dernier_echec"])
        etat.E.DEV[0] = sauv2["dev"]
        etat.E.STATE.clear(); etat.E.STATE.update(sauv2["state"])
        etat.E.AUTO.clear(); etat.E.AUTO.update(sauv2["auto"])
        wc.USB_ARRET.clear(); wc.USB_SORTIE.clear()


def test_cycle_dmx_classificateur_partage(wc):
    """cycle_dmx() détecte-t-il un débranchement par le MÊME classificateur
    que le reste du code (wing_init._partie_du_bus), pas par un tuple errno
    étroit codé en dur ici ?

    🐛 `except usb.core.USBError as e: if e.errno in (19, 5) or "No such
    device" in str(e):` ne regardait QUE `errno`. Or `wing_init._err_usb()`
    (le classificateur PARTAGÉ, utilisé partout ailleurs dans le projet)
    regarde AUSSI `backend_error_code` — macOS le peuple parfois à la place
    d'`errno`, exactement le piège documenté dans wing_init.py : « USBError
    tout court ne dit rien ». Une wing débranchée PENDANT l'écriture DMX
    pouvait donc ne JAMAIS lever `WingUnplugged` ici, selon lequel des deux
    champs libusb portait le code — la boucle serait restée bloquée sur un
    device mort au lieu de basculer proprement en reconnexion.
    """
    section("56. cycle_dmx() : classificateur d'erreur USB partagé")
    import usb.core

    class _DevQuiLeve:
        """Double USB : écrire lève TOUJOURS l'exception fournie."""
        def __init__(self, exc):
            self.exc = exc
        def write(self, ep, data, timeout=None):
            raise self.exc

    # ⚠️ Les trois formes de « la wing a quitté le bus », au sens de
    # wing_init._partie_du_bus() — deux d'entre elles n'ont PAS d'errno
    # exploitable, exactement le cas que l'ancien test manquait.
    cas_partis = [
        ("errno=19, device parti (ancien format, déjà couvert)",
         usb.core.USBError("gone", errno=19)),
        ("backend_error_code=-5, introuvable (format macOS, PAS d'errno)",
         usb.core.USBError("gone", error_code=-5)),
        ("backend_error_code=-9, pipe (stall) (PAS d'errno)",
         usb.core.USBError("stall", error_code=-9)),
    ]
    # Erreur transitoire, PAS une preuve de départ du bus — ne doit jamais
    # être prise pour un débranchement (elle ne l'était déjà pas avant).
    cas_transitoires = [
        ("backend_error_code=-7, délai dépassé",
         usb.core.USBError("timeout", error_code=-7)),
    ]

    manques = []
    for nom, exc in cas_partis:
        try:
            wc.cycle_dmx(_DevQuiLeve(exc))
        except wc.WingUnplugged:
            continue
        except Exception as e:
            manques.append(f"{nom} : exception inattendue "
                           f"{type(e).__name__}: {e}")
        else:
            manques.append(f"{nom} : WingUnplugged n'a PAS été levée")

    faux_positifs = []
    for nom, exc in cas_transitoires:
        try:
            wc.cycle_dmx(_DevQuiLeve(exc))
        except wc.WingUnplugged:
            faux_positifs.append(f"{nom} : WingUnplugged levée À TORT")
        except Exception as e:
            faux_positifs.append(f"{nom} : exception inattendue "
                                 f"{type(e).__name__}: {e}")

    if manques:
        echec("cycle_dmx() ne détecte plus certains débranchements",
              " ; ".join(manques))
    elif faux_positifs:
        echec("cycle_dmx() traite une erreur transitoire comme un débranchement",
              " ; ".join(faux_positifs))
    else:
        ok(f"{len(cas_partis)} formes de « device parti » détectées (errno ET "
           f"backend_error_code), {len(cas_transitoires)} erreur transitoire "
           f"correctement PAS traitée comme un débranchement")


def test_get_status_verrou_minimal(ui):
    """/api/status ne doit tenir core.LOCK QUE pour l'instantané de STATE/
    SETTINGS — jamais pendant un appel lent.

    🐛 `_get_status` tenait `core.LOCK` — LE MÊME verrou qu'`usb_loop` prend à
    chaque tour (~30 Hz) en mode bridge pour lire faders/roues — pendant TOUTE
    la construction de la réponse, y compris `core.ma3_sockets()` qui enchaîne
    `pgrep`/`lsof` et peut prendre jusqu'à ~5 s. Si MA3 devenait injoignable
    PILE pendant qu'un onglet poll `/api/status` (toutes les 400 ms), `usb_loop`
    pouvait se retrouver bloqué sur ce verrou pendant ces 5 s : faders, boutons
    et roues ignorés, en pleine régie.
    """
    section("57. /api/status : le verrou ne couvre pas les appels lents")
    import threading as _th
    import wing_handler

    class _FauxHandler:
        def _json(self, obj, code=200):
            pass
        def _capture_statut(self):
            return None

    entree = _th.Event()

    def faux_ma3_sockets():
        entree.set()
        time.sleep(0.4)             # simule la lenteur pgrep+lsof
        return 0

    sauv = (ui.ma3_reachable, ui.ma3_sockets)
    try:
        ui.ma3_reachable = lambda: "muet"   # sinon ma3_sockets() n'est jamais appelé
        ui.ma3_sockets = faux_ma3_sockets

        fil = _th.Thread(target=wing_handler.Handler._get_status,
                         args=(_FauxHandler(),), daemon=True)
        fil.start()

        if not entree.wait(2.0):
            echec("ma3_sockets() n'a jamais été appelé",
                  "le scénario ne teste plus le cas visé — vérifier que "
                  "ma3_reachable() est bien lu comme « muet » dans _get_status")
        else:
            # ma3_sockets() est EN COURS (0,4 s simulées). Le verrou doit être
            # LIBRE maintenant — sinon usb_loop, qui prend le même core.LOCK
            # à chaque tour en mode bridge, serait bloqué pour toute cette durée.
            acquis = etat.E.LOCK.acquire(timeout=0.2)
            if not acquis:
                echec("core.LOCK EST ENCORE TENU PENDANT ma3_sockets()",
                      "usb_loop, qui prend le même verrou à 30 Hz en mode "
                      "bridge, serait bloqué pendant tout l'appel lent — "
                      "faders/boutons/roues ignorés")
            else:
                etat.E.LOCK.release()
                ok("core.LOCK est libre pendant ma3_sockets() — usb_loop "
                   "n'est plus bloqué par un /api/status malchanceux")
        fil.join(timeout=3.0)
        if fil.is_alive():
            note("le thread de test _get_status ne s'est pas terminé à temps "
                 "(sans conséquence sur le verdict ci-dessus)")
    except Exception as e:
        echec("le scénario a levé une exception", f"{type(e).__name__}: {e}")
    finally:
        ui.ma3_reachable, ui.ma3_sockets = sauv


def test_lock_sans_appel_lent():
    """`core.LOCK` ne doit JAMAIS envelopper un appel bloquant (réseau, disque,
    socket, sous-processus) — règle documentée depuis longtemps
    (wing_faders.py::faders_instantane) mais jamais VÉRIFIÉE PAR LA MACHINE.

    🔑 2e revue de code (Lot C, 14/09/2026) : la MÊME faute — tenir `core.LOCK`
    pendant un appel lent — se répétait à plusieurs endroits en dehors de
    `_get_status` (§57, déjà corrigé) : `usb_loop` lui-même tenait le verrou
    pendant `enc_attr_selon_ma3()` → `ma3_reachable()` → un `pgrep` (le plus
    grave, cette boucle tournant à 30 Hz), `_get_profile` l'écriture SOCKET de
    `self._json()`, `_post_profile_save`/`_post_reference_set` une écriture
    DISQUE. Plutôt que corriger cette liste au coup par coup, ce contrôle fait
    le sweep AUTOMATIQUE et PERMANENT que la revue a fait à la main : aucun
    `with core.LOCK:`, dans AUCUN fichier `wing_*.py`, ne doit contenir
    (directement, texte du bloc) un appel de la liste noire ci-dessous.

    ⚠️ Audit de SOURCE, par construction : un contrôle comportemental ne peut
    couvrir qu'un point de lecture à la fois (voir §57) — celui-ci couvre TOUT
    le projet d'un coup, y compris les régressions futures dans un fichier pas
    encore écrit aujourd'hui.
    """
    section("60. core.LOCK : jamais d'appel bloquant à l'intérieur (sweep complet)")
    import ast
    import io
    import tokenize

    # Chaque motif : (sous-chaîne cherchée, ce qu'elle prouve si trouvée).
    LISTE_NOIRE = [
        "subprocess.run(", "subprocess.Popen(", "subprocess.call(",
        "self._json(", "self.wfile", "open(", ".write_text(", ".read_text(",
        "json.dump(", "wm.save_profile(", "save_profile(",
        "core.save_reference(", "save_reference(", "save_settings(",
        "enc_attr_selon_ma3(", "ma3_reachable(", "ma3_sockets(", "ma3_etat(",
        "dev.read(", "dev.write(", "pgrep", "time.sleep(",
    ]

    def _sans_commentaires(segment: str) -> str:
        """Un commentaire qui NOMME un appel lent (ex. « pendant
        `ma3_sockets()` ») ne doit pas déclencher le contrôle — seul du code
        RÉELLEMENT exécuté sous le verrou compte.

        ⚠️ Retire UNIQUEMENT le texte des commentaires, sans reconstruire la
        ligne : un premier essai rejoignait les tokens avec des espaces
        (`" ".join(...)`), ce qui séparait `self._json(` en `self . _json (`
        et rendait la recherche de sous-chaîne AVEUGLE au bug qu'elle est
        censée surveiller — trouvé en réinjectant le bug d'usb_loop, resté
        vert à tort avant ce correctif."""
        lignes = segment.splitlines(keepends=True)
        try:
            for tok in tokenize.generate_tokens(io.StringIO(segment).readline):
                if tok.type != tokenize.COMMENT:
                    continue
                (l1, c1), (l2, c2) = tok.start, tok.end
                if l1 != l2:
                    continue
                ligne = lignes[l1 - 1]
                lignes[l1 - 1] = ligne[:c1] + ligne[c2:]
        except (tokenize.TokenizeError, IndentationError):
            return segment
        return "".join(lignes)

    manques = []
    for chemin in sorted(HERE.glob("wing_*.py")):
        try:
            src = chemin.read_text(encoding="utf-8")
            arbre = ast.parse(src, filename=str(chemin))
        except Exception as e:
            manques.append(f"{chemin.name} : illisible ({type(e).__name__}: {e})")
            continue
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.With):
                continue
            est_lock = any(
                isinstance(it.context_expr, ast.Attribute)
                and it.context_expr.attr == "LOCK"
                for it in noeud.items
            )
            if not est_lock:
                continue
            segment = ast.get_source_segment(src, noeud)
            if not segment:
                continue
            propre = _sans_commentaires(segment)
            for motif in LISTE_NOIRE:
                if motif in propre:
                    manques.append(f"{chemin.name}:{noeud.lineno} — « {motif} » "
                                   f"sous un with core.LOCK:")
    if manques:
        echec(f"{len(manques)} bloc(s) core.LOCK tiennent un appel bloquant",
              " ; ".join(manques[:10])
              + (" …" if len(manques) > 10 else ""))
    else:
        ok("aucun with core.LOCK: (tous fichiers wing_*.py) ne contient "
           "d'appel réseau/disque/socket/sous-processus")
