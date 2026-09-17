#!/usr/bin/env python3
"""
smoke_ma3_sync.py — Wing Bridge
================================
Domaine synchronisation MA3 du test de fumée : syntaxe du plugin Lua, verbe +
executor en mode console, casse des mots-clés, diagnostic OSC, diagnostic
réseau. Voir smoke_core.py pour ok/echec/note/section/HERE/_page/_js_de.
"""

import etat
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from smoke_core import HERE, ok, echec, note, section, _page, _js_de


# Contrôle sauté proprement si `luac` n'est pas installé.

def test_plugin_lua():
    section("11. Syntaxe du plugin Lua MA3")
    plugin = HERE / "plugin_ma3" / "wingbridge.lua"
    if not plugin.exists():
        note("plugin_ma3/wingbridge.lua absent — contrôle sauté")
        return
    luac = None
    for cand in ("luac", "/opt/homebrew/bin/luac", "/usr/local/bin/luac"):
        try:
            subprocess.run([cand, "-v"], capture_output=True, timeout=5)
            luac = cand
            break
        except Exception:
            continue
    if not luac:
        note("luac introuvable — contrôle sauté (brew install lua pour l'activer)")
        return
    r = subprocess.run([luac, "-p", str(plugin)],
                       capture_output=True, text=True, timeout=20)
    if r.returncode == 0:
        lignes = plugin.read_text(encoding="utf-8").count("\n") + 1
        ok(f"wingbridge.lua valide ({lignes} lignes)")
    else:
        echec("erreur de syntaxe dans le plugin Lua", r.stderr or r.stdout)
        return

    # L'encodeur JSON du plugin est fait maison — ExportJson de MA3 produit du
    # JSON invalide (clés sans guillemets, vérifié). Un encodeur
    # maison non testé, ce serait remplacer un format cassé par un autre.
    # Le test EXTRAIT le code du plugin réel : il suit donc ses évolutions.
    lua = luac[:-1] if luac.endswith("luac") else "lua"
    banc = plugin.parent / "verif_encodeur.lua"
    if not banc.exists():
        note("verif_encodeur.lua absent — encodeur JSON non vérifié")
        return
    r = subprocess.run([lua, banc.name], capture_output=True, text=True,
                       timeout=20, cwd=str(plugin.parent))
    if r.returncode != 0:
        echec("le banc d'essai de l'encodeur Lua échoue", r.stderr or r.stdout)
        return
    try:
        d = json.loads(r.stdout)
    except Exception as e:
        echec("l'encodeur du plugin produit du JSON INVALIDE",
              f"{e}\n{r.stdout[:200]}")
        return
    if d.get("page", {}).get("nom") != 'Page "2"':
        echec("échappement des guillemets incorrect dans l'encodeur Lua",
              repr(d.get("page")))
    # Précision des entiers : `%.6g` écrase tout entier de 7+ chiffres en
    # scientifique tronquée (1787944439 -> 1.78794e+09 = 1787940000). Le banc
    # envoie exprès un epoch et un gros compteur. Bug réel.
    elif d.get("horodate") != 1787944439 or d.get("tours") != 1234567:
        echec("l'encodeur Lua perd la précision des grands entiers "
              "(horodate/tours écrasés par %.6g)",
              f"horodate={d.get('horodate')!r} (attendu 1787944439), "
              f"tours={d.get('tours')!r} (attendu 1234567)")
    else:
        ok(f"encodeur JSON du plugin valide ({len(d.get('executors', []))} "
           f"executors, entiers exacts)")


# ── Verbe + executor : rien ne doit être TAPÉ au clavier ─────────────────────
#
# 🐛 Bug signalé « ça fait n'importe quoi » et corrigé. La cible (« Executor
# 105 ») était tapée caractère par caractère
# dans la ligne de commande de MA3. Or celle-ci n'est PAS un champ de texte :
# chaque lettre y insère un MOT-CLÉ (E → Edit, c → Channel, u → Update,
# t → Thru…).
#
# Un « Store » suivi de la cible tapée donnait donc une rafale de mots-clés au
# lieu du texte voulu. (Ce commentaire donnait « o → Set » : faux, et la même
# erreur avait contaminé la table des raccourcis — voir le contrôle test_raccourcis_uniques.)
#
# Le contrôle vérifie qu'un appui « verbe puis executor » produit UNE commande
# OSC complète et AUCUNE frappe clavier.

def test_verbe_executor(wv):
    section("14. Verbe + executor (mode console)")
    envoyes, frappes = [], []

    class _OSCespion:
        def send_message(self, addr, valeur):
            envoyes.append(valeur)

    sauve = (etat.E.OSC, wv.console_helper_alive, json.loads(json.dumps(etat.E.PROFILE)),
             wv.ma3_etat, etat.E.SETTINGS.get("suivre_ma3", True))
    try:
        etat.E.OSC = _OSCespion()
        wv.console_helper_alive = lambda: True   # assistant présent
        etat.E.WS["helper_seen"] = wv.time.time()      # assistant « présent »
        etat.E.PROFILE["buttons"]["0x40"] = "Store"
        etat.E.PROFILE["buttons"]["0x7c"] = "Go+ Executor 105"
        etat.E.PROFILE["executor_ref"]["0x7c"] = "Executor 105"
        etat.E.CONSOLE_CIBLES["cmd"] = ""
        etat.E.VERBE["token"] = None
        wv._btn_last_event.clear()
        wv.DERNIER_APPUI.clear()
        wv.drain_keys()                            # file clavier au propre

        wv.handle_button_bridge(0x40)              # Store
        wv._btn_last_event.clear()
        wv.handle_button_bridge(0x7c)              # executor 105
        frappes = wv.drain_keys()

        # L'envoi OSC part via un minuteur (le temps que l'effacement de la
        # ligne de commande soit tapé avant) — on lui laisse le temps.
        wv.time.sleep(0.6)

        litteral = [f for f in frappes if f.get("type") == "string"
                    and len(str(f.get("value", ""))) > 1]
        if litteral:
            echec("la cible est TAPÉE dans la ligne de commande de MA3",
                  f"frappes littérales : {litteral}\n"
                  f"MA3 lirait chaque lettre comme un mot-clé (E=Edit, "
                  f"c=Channel, u=Update…)")
        elif "Store Executor 105" in envoyes:
            ok("« Store » + executor → « Store Executor 105 » en OSC")
        else:
            echec("verbe + executor n'a pas produit la bonne commande",
                  f"OSC envoyé : {envoyes}\nfrappes : {frappes}")

        # Appuis répétés : Assign Assign = Label (manuel MA3). Le cycle est
        # suivi CÔTÉ APP pour que la commande OSC corresponde à ce que la
        # console affiche — s'il se désynchronise, on enverrait « Assign »
        # là où MA3 montre « Label ».
        envoyes.clear()
        etat.E.CONSOLE_CIBLES["cmd"] = ""
        etat.E.VERBE["token"] = None
        wv.CYCLE["btn"] = None
        etat.E.PROFILE["buttons"]["0x27"] = "Assign"
        for btn in (0x27, 0x27, 0x7c):
            wv._btn_last_event.clear()
            wv.DERNIER_APPUI.clear()
            wv.handle_button_bridge(btn)
        wv.time.sleep(0.6)
        if "Label Executor 105" in envoyes:
            ok("« Assign » ×2 + executor → « Label Executor 105 »")
        else:
            echec("le cycle d'appuis répétés ne suit pas MA3",
                  f"attendu « Label Executor 105 », obtenu : {envoyes}")

        # ── Mode console : reconnaissance par REGEX, pas par liste figée ────
        #
        # 🐛 Cette branche comparait `token` à une liste figée de préfixes
        # ("Go+", "Go-", "Pause", "Top") au lieu de `core._RE_EXEC_CMD` — la
        # regex générale déjà utilisée par `handle_button_release` et par la
        # branche bridge. Une commande libre comme « Flash Executor 105 »
        # échappait donc à `token_selon_ma3` en mode console : elle partait en
        # OSC BRUTE, sans le suffixe On/Off que MA3 exige pour une fonction
        # MAINTENUE — alors qu'elle y serait passée normalement ailleurs.
        #
        # Scénario : bouton (hors table executor_ref) réglé sur
        # « Flash Executor 105 », sonde MA3 ACTIVE et rapportant que
        # l'executor 105 est réellement câblé sur « Flash » (maintenue) →
        # `token_selon_ma3` DOIT ajouter le suffixe « On ». Avec la liste
        # figée, « Flash Executor 105 » ne matche aucun préfixe et part
        # tel quel, sans le « On ».
        envoyes.clear()
        etat.E.CONSOLE_CIBLES["cmd"] = ""
        etat.E.VERBE["token"] = None
        wv._btn_last_event.clear()
        wv.DERNIER_APPUI.clear()
        wv.drain_keys()
        wv.ma3_etat = lambda: {"actif": True,
                               "executors": [{"no": 105, "touche": "Flash"}]}
        etat.E.SETTINGS["suivre_ma3"] = True
        etat.E.PROFILE["buttons"]["0x50"] = "Flash Executor 105"
        etat.E.PROFILE["executor_ref"].pop("0x50", None)
        wv.handle_button_bridge(0x50)
        wv.time.sleep(0.6)
        if "Flash Executor 105" in envoyes and "Flash On Executor 105" not in envoyes:
            echec("MODE CONSOLE : « Flash Executor 105 » ÉCHAPPE À token_selon_ma3",
                  f"envoyé tel quel ({envoyes}) au lieu de « Flash On "
                  f"Executor 105 » — la reconnaissance ne suit plus la même "
                  f"regex qu'ailleurs (core._RE_EXEC_CMD)")
        elif "Flash On Executor 105" in envoyes:
            ok("mode console : « Flash Executor 105 » reconnu par regex, "
               "suffixe On ajouté comme en mode bridge")
        else:
            echec("mode console : la commande d'executor n'est pas partie du tout",
                  f"OSC envoyé : {envoyes}")
    except Exception as e:
        echec("le contrôle verbe + executor a levé une exception",
              f"{type(e).__name__}: {e}")
    finally:
        etat.E.OSC, wv.console_helper_alive = sauve[0], sauve[1]
        etat.E.PROFILE.clear()
        etat.E.PROFILE.update(sauve[2])
        wv.ma3_etat = sauve[3]
        etat.E.SETTINGS["suivre_ma3"] = sauve[4]
        etat.E.CONSOLE_CIBLES["cmd"] = ""
        etat.E.VERBE["token"] = None
        wv._btn_last_event.clear()
        wv.DERNIER_APPUI.clear()
        wv.drain_keys()


# ── La casse des mots-clés est corrigée à l'assignation ──────────────────────
#
# 🐛 Signalé : « j'ai voulu écrire "off" et j'ai pas mis "Off",
# donc ça ne fonctionnait pas ». Un mot-clé mal capitalisé échoue en SILENCE —
# MA3 refuse sur SA ligne de commande, rien ne remonte en OSC, et la touche
# paraît simplement morte. Même famille que « Focus » au lieu de « Focus1 ».

def test_casse_motscles(wv):
    section("15. Casse des mots-clés de commande")
    try:
        d = wv.ma3_motscles()
    except Exception as e:
        echec("ma3_motscles() échoue", f"{type(e).__name__}: {e}")
        return
    if d["source"] != "ma3":
        note(f"manuel MA3 introuvable — liste de repli ({len(d['mots'])} mots)")
    else:
        ok(f"{len(d['mots'])} mots-clés lus dans le manuel installé")

    cas = [("off", "Off"), ("store", "Store"), ("go+", "Go+"),
           ("FLASH", "Flash"), ("Off Executor 105", "Off Executor 105")]
    faux = []
    for saisi, attendu in cas:
        obtenu, _ = wv.corriger_casse(saisi)
        if obtenu != attendu:
            faux.append(f"« {saisi} » → « {obtenu} » (attendu « {attendu} »)")
    if faux:
        echec("la correction de casse ne fait pas son travail", "\n".join(faux))
    else:
        ok(f"{len(cas)} saisies corrigées ou laissées intactes correctement")

    # ⚠️ Ce qui n'est PAS un mot-clé doit rester STRICTEMENT tel quel : on
    # corrige une capitalisation, on ne réécrit pas la commande de l'utilisateur.
    intact, _ = wv.corriger_casse("Go+ Executor 105")
    if intact != "Go+ Executor 105":
        echec("une commande valide a été modifiée", f"→ « {intact} »")
    else:
        ok("les nombres et mots inconnus sont laissés intacts")


def test_diagnostic_osc(html):
    """Le diagnostic OSC ne doit pas accuser une configuration correcte.

    🐛 Signalé, capture d'écran à l'appui. Le
    diagnostic testait `.some(x => x.rec_cmd === false)` — « si UNE SEULE ligne
    OSCData a Receive Command à No ». Or MA3 en a normalement plusieurs :

        OSCData 1 · port 8001 · Receive No  · Receive Command No   ← MA3 envoie
        OSCData 2 · port 8000 · Receive Yes · Receive Command Yes  ← MA3 reçoit

    La ligne de SORTIE n'a pas besoin de Receive Command. L'app criait quand
    même, et grandMA3 a été redémarré plusieurs fois pour rien.

    ⚠️ On rejoue la vraie config dans node : un contrôle textuel (« est-ce que
    `.some(` a disparu ») ne prouverait pas que le remplaçant est correct.
    """
    section("29. Diagnostic OSC : ne pas accuser une config correcte")
    node = None
    for cand in ("node", "/opt/homebrew/bin/node", "/usr/local/bin/node"):
        try:
            subprocess.run([cand, "--version"], capture_output=True, timeout=5)
            node = cand
            break
        except Exception:
            continue
    if not node:
        note("node introuvable — contrôle sauté")
        return

    # ⚠️ Extraction par COMPTAGE D'ACCOLADES, pas par regex. Une première
    # version coupait la fonction en plein milieu (le motif `\n  }` tombait sur
    # une accolade interne) et node échouait sur du code tronqué.
    html = _page(html)          # oscPourquoi vit dans ui/bridge.js
    deb = html.find("function oscPourquoi(s) {")
    if deb < 0:
        echec("fonction oscPourquoi introuvable dans le JS de l'interface")
        return
    prof, fin = 0, None
    for i in range(deb, len(html)):
        if html[i] == "{":
            prof += 1
        elif html[i] == "}":
            prof -= 1
            if prof == 0:
                fin = i + 1
                break
    if fin is None:
        echec("accolades non équilibrées dans oscPourquoi")
        return

    class _M:
        def group(self, _n): return html[deb:fin]
    m = _M()

    cas = [
        # (libellé, configs, entree, doit_contenir_une_alerte)
        ("config réelle relevée (2 lignes, la bonne est réglée)",
         [{"nom": "OSCData 1", "port": 8001, "recoit": False, "rec_cmd": False},
          {"nom": "OSCData 2", "port": 8000, "recoit": True,  "rec_cmd": True}],
         True, False),
        ("Receive Command coupé SUR LA LIGNE DU PORT 8000",
         [{"nom": "OSCData 1", "port": 8001, "recoit": False, "rec_cmd": False},
          {"nom": "OSCData 2", "port": 8000, "recoit": True,  "rec_cmd": False}],
         True, True),
        ("aucune ligne sur le port attendu",
         [{"nom": "OSCData 1", "port": 9000, "recoit": True, "rec_cmd": True}],
         True, True),
        ("Enable Input désactivé",
         [{"nom": "OSCData 2", "port": 8000, "recoit": True, "rec_cmd": True}],
         False, True),
    ]
    # ⚠️ oscPourquoi() résout ses phrases via t() (locales/fr.json, i18n
    # Phase 3) — absent de ce bout de JS isolé. Un t() minimal, lu dans le
    # VRAI fr.json (pas une recopie), suffit : ce contrôle vérifie la LOGIQUE
    # de oscPourquoi (quel cas déclenche une alerte), pas le texte affiché —
    # texte que test_i18n (côté catalogue) garde déjà cohérent.
    fr_json = json.dumps(
        json.loads((HERE / "locales" / "fr.json").read_text(encoding="utf-8")))
    t_shim = (
        f"const _CAT = {fr_json};\n"
        "function t(cle, params) {\n"
        "  let s = _CAT[cle]; if (s === undefined) return cle;\n"
        "  if (params) for (const k in params) s = s.split('{' + k + '}').join(String(params[k]));\n"
        "  return s;\n"
        "}\n")
    js = t_shim + m.group(0) + "\n" + "\n".join(
        f"console.log(JSON.stringify(oscPourquoi({{osc:{{ma3:{{actif:true,"
        f"entree:{str(e).lower()},port_attendu:8000,configs:{json.dumps(cfg)}}}}}}})));"
        for _, cfg, e, _a in cas)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                     encoding="utf-8") as f:
        f.write(js)
        chemin = f.name
    try:
        r = subprocess.run([node, chemin], capture_output=True, text=True,
                           timeout=10)
    finally:
        os.unlink(chemin)
    if r.returncode != 0:
        echec("oscPourquoi ne s'exécute pas", r.stderr.strip()[:200])
        return

    sorties = [l for l in r.stdout.strip().split("\n") if l]
    if len(sorties) != len(cas):
        echec("sorties inattendues du diagnostic OSC",
              f"{len(sorties)} réponses pour {len(cas)} cas")
        return
    faux = []
    for (libelle, _cfg, _e, alerte_attendue), out in zip(cas, sorties):
        alerte = "la sonde a lu MA3" in out
        if alerte != alerte_attendue:
            faux.append(f"{libelle} → {'alerte' if alerte else 'aucune alerte'} "
                        f"(attendu : {'alerte' if alerte_attendue else 'aucune'})")
    if faux:
        echec("le diagnostic OSC se trompe", " ; ".join(faux))
    else:
        ok("4 configurations jugées correctement, dont une config réelle")


def test_diagnostic_reseau(html):
    """Le diagnostic sait-il départager « OSC mal réglé » de « réseau coupé » ?

    🎯 Abouti autrement que prévu. La piste de départ disait « chercher la
    propriété dans l'API Lua de MA3 » : AUCUNE des
    320 pages d'API Lua du manuel installé ne mentionne « network ». Cette voie
    est fermée.

    La voie qui marche ne demande ni plugin ni Lua : **compter les sockets
    réseau de MA3**.

      • 0 socket        → signature d'un réseau global coupé (Menu → Network)
      • n > 0, sans 8000 → le réseau va bien, c'est la config OSC

    Mesuré sur une installation réelle, MA3 sain : **13 sockets**, dont 8000
    et 8001. Relevé dans le cas « OSC mal réglé » : 5 sockets, pas de 8000.

    ⚠️ SIGNATURE, PAS PREUVE. Le manuel dit que le réseau doit être activé
    « pour communiquer » ; il ne dit pas littéralement « aucun socket ». Le
    texte affiché doit donc rapporter la MESURE et ce qu'elle évoque — jamais
    affirmer la cause. C'est exactement la faute déjà payée : diagnostic
    juste, explication fausse, une dizaine de redémarrages pour rien.
    """
    section("42. Diagnostic réseau : départager les deux causes")
    js = _js_de(html)
    if "osc.sockets" not in js and "s.osc && s.osc.sockets" not in js:
        echec("le diagnostic n'utilise pas le compte de sockets",
              "il ne peut donc pas distinguer « réseau coupé » de « OSC mal "
              "réglé » — et proposera les deux, comme avant")
        return
    ok("le compte de sockets est utilisé pour départager")

    # ⚠️ Le texte ne doit pas AFFIRMER la cause : on cherche une formulation
    #    de constat (« signature de »), pas un verdict.
    # Phase 3 : le texte n'est plus dans le JS mais dans locales/fr.json
    # (err.osc.aucun_socket) — résolu via t() au moment de l'affichage.
    try:
        fr = json.loads((HERE / "locales" / "fr.json").read_text(encoding="utf-8"))
    except Exception as e:
        echec("catalogue i18n illisible", str(e))
        return
    texte = fr.get("err.osc.aucun_socket", "")
    m = re.search(r"AUCUN socket réseau ouvert(.{0,200})", texte, re.S)
    if not m:
        echec("le cas « aucun socket » n'est plus expliqué", "formulation changée ?")
        return
    suite = m.group(1)
    if "signature" not in suite.lower():
        echec("le diagnostic AFFIRME la cause au lieu de la nommer comme signature",
              suite[:120] + " — le manuel ne prouve pas « aucun socket = réseau "
              "coupé ». Dire ce qu'on mesure, pas ce qu'on suppose")
    else:
        ok("le cas « aucun socket » est présenté comme une signature, pas un verdict")


# ── _port_ecoute() sur macOS : lsof, jamais netstat ───────────────────────────
#
# 🐛 RÉGRESSION macOS 27 (« Tahoe » et suivants), trouvée en test réel avec
# l'auteur le 17/09/2026 : `netstat -an -p udp` renvoie une sortie VIDE en
# sous-processus sur cette version — sans exception, sans code de retour non
# nul. `_port_ecoute()` prenait donc ce vide pour « personne n'écoute » :
# `ma3_reachable()` répondait « muet » alors que grandMA3 écoutait bel et
# bien sur le port 8000 (confirmé au même instant par `lsof -nP -iUDP:8000`,
# qui voyait la ligne à CHAQUE essai, 5/5). Toute la détection OSC de l'app
# était donc cassée en permanence sur cette version de macOS. Corrigé :
# `lsof`, comme le fait déjà `ma3_sockets()` pour une raison voisine.
#
# Ce contrôle ne dépend PAS du vrai `netstat`/`lsof` du système (leur
# comportement varie justement d'une version de macOS à l'autre — c'est le
# problème qu'on vient de découvrir) : il MOCKE `subprocess.run` pour rejouer
# exactement le bug constaté (netstat = sortie vide) et vérifie que le code
# ne l'utilise plus du tout sur macOS — RÉINJECTION intégrée : un
# `_port_ecoute()` qui reviendrait à `netstat` retomberait sur ce mock et
# échouerait, pile comme en réel.
def test_port_ecoute_macos(wm3):
    section("63. Détection du port OSC (macOS) : lsof, pas netstat")
    if not sys.platform.startswith("darwin"):
        note("pas macOS — contrôle sauté (la branche Windows reste couverte "
             "par lecture de code + test réel sur machine Windows)")
        return

    appels = []

    def _faux_run(cmd, **kwargs):
        appels.append(cmd)
        import types
        r = types.SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[0] == "netstat":
            # 🎯 LE BUG EXACT constaté sur macOS 27 : sortie vide, sans
            # exception, MÊME QUAND un port est réellement occupé.
            r.stdout = ""
        elif cmd[0] == "lsof":
            port_cible = cmd[-1].split(":")[-1]
            if port_cible == "8000":
                r.stdout = ("COMMAND   PID USER   FD   TYPE  DEVICE SIZE/OFF "
                            "NODE NAME\napp_gma3 111 x 24u  IPv4  0x0  0t0 "
                            "UDP *:8000\n")
            else:
                r.returncode = 1
                r.stdout = ""
        return r

    sauve = wm3.subprocess.run
    try:
        wm3.subprocess.run = _faux_run
        occupe = wm3._port_ecoute(8000)
        libre = wm3._port_ecoute(9999)
        a_utilise_netstat = any(c[0] == "netstat" for c in appels)
        if a_utilise_netstat:
            echec("_port_ecoute() appelle encore netstat sur macOS",
                  "netstat renvoie une sortie vide sur macOS 27 même quand le "
                  "port est occupé (bug constaté en réel) — réinjecté ici : "
                  f"appels observés {appels}")
        elif occupe is not True or libre is not False:
            echec("_port_ecoute() ne distingue plus port occupé / port libre",
                  f"occupé→{occupe} (attendu True), libre→{libre} (attendu "
                  f"False)")
        else:
            ok("port occupé détecté via lsof, port libre aussi (netstat "
               "jamais appelé — réinjection : un netstat qui renverrait vide "
               "casserait ce contrôle)")
    finally:
        wm3.subprocess.run = sauve


# ── Un raté de lecture transitoire ne doit pas couper l'état MA3 ──────────────
#
# 🐛 Sous Windows, la sonde Lua réécrit son JSON de façon NON
# atomique (os.remove + os.rename) : le fichier disparaît ~0,77 ms à chaque
# écriture (~4,5×/s). Une lecture de `ma3_etat()` tombée dans ce trou rendait
# `actif:False`, `executors:[]` → `niveau_led_ma3()` retombait sur LED_GLOW →
# scintillement d'un executor allumé ~1×/min. Correctif : garder le dernier bon
# état et le resservir (marqué `stale`) pendant MA3_ETAT_GRACE_S. AU-DELÀ, on
# retombe sur l'état vide — une sonde durablement absente est une vraie panne,
# à NE PAS masquer. Voir docs/GRANDMA3_SYNC.md, § contention os.rename.
#
# Ce contrôle rejoue les trois cas SANS matériel (monkeypatch du chemin fichier
# et de la fenêtre de grâce), et vérifie sa propre RÉINJECTION : grâce = 0
# (logique last-good neutralisée) → le raté DOIT recouper l'état, sinon le
# contrôle passerait vert sur du code fautif et ne prouverait rien.

def test_ma3_etat_transitoire(wm3):
    section("46. Sonde MA3 : un raté transitoire ne coupe pas l'état")
    import json as _j, tempfile, time as _t, os as _os
    from pathlib import Path as _P

    fichier_orig = wm3.MA3_ETAT_FICHIER
    grace_orig = wm3.MA3_ETAT_GRACE_S
    etat_orig = dict(wm3._MA3_ETAT)
    alive_orig = dict(wm3._MA3_ALIVE_DEPUIS)

    d = tempfile.mkdtemp(prefix="wb_ma3_etat_")
    f = _P(d) / "wingbridge_state.json"
    f_abs = _P(d) / "absent.json"          # simule le fichier disparu (trou)
    bon = {"version": 13, "page": {"no": 1, "nom": "Page 1"},
           "executors": [{"no": 201, "nom": "Sequence 1", "tourne": True}]}
    f.write_text(_j.dumps(bon), encoding="utf-8")

    def _reset():
        # État neuf entre deux scénarios : pas de cache, pas de last_good.
        wm3._MA3_ETAT.update(t=0.0, data=None, erreur="",
                             last_good=None, last_good_t=0.0)
        wm3._MA3_ALIVE_DEPUIS.update(t=None, etait_alive=False)

    try:
        # 1) Lecture nominale : peuple le « dernier bon état », sans stale.
        wm3.MA3_ETAT_FICHIER = f
        wm3.MA3_ETAT_GRACE_S = grace_orig
        _reset()
        e1 = wm3.ma3_etat()
        if not e1.get("actif") or e1.get("stale"):
            echec("état nominal non lu (actif attendu, sans stale)", repr(e1))
            return

        # 2) Raté transitoire (fichier absent) avec last_good récent → on resert
        #    le dernier bon état, marqué stale — PAS l'état vide.
        wm3._MA3_ETAT["t"] = 0.0           # forcer la relecture (hors cache court)
        wm3.MA3_ETAT_FICHIER = f_abs
        e2 = wm3.ma3_etat()
        if not (e2.get("actif") and e2.get("stale") and e2.get("executors")):
            echec("un raté transitoire coupe l'état au lieu de resservir le "
                  "dernier bon état (logique last-good absente ?)", repr(e2))
            return

        # 3) Même raté, mais last_good plus vieux que la grâce → vraie panne :
        #    état vide + message, jamais de stale.
        wm3._MA3_ETAT["t"] = 0.0
        wm3._MA3_ETAT["last_good_t"] = _t.time() - (grace_orig + 1.0)
        e3 = wm3.ma3_etat()
        if e3.get("actif") or e3.get("stale") or not e3.get("erreur"):
            echec("au-delà de la fenêtre de grâce, la panne réelle doit "
                  "ressortir (état vide + message, sans stale)", repr(e3))
            return

        # 4) RÉINJECTION du bug : grâce = 0 neutralise la logique last-good, le
        #    raté (2) DOIT alors recouper l'état. Sans ce contrôle-ci, retirer
        #    le correctif passerait inaperçu.
        _reset()
        wm3.MA3_ETAT_FICHIER = f
        wm3.ma3_etat()                     # repeuple last_good
        wm3._MA3_ETAT["t"] = 0.0
        wm3.MA3_ETAT_GRACE_S = 0.0
        wm3.MA3_ETAT_FICHIER = f_abs
        e4 = wm3.ma3_etat()
        if e4.get("actif") or e4.get("stale"):
            echec("réinjection ratée : le contrôle reste vert sans la logique "
                  "last-good — il ne prouverait rien", repr(e4))
            return

        ok("raté transitoire → dernier bon état (stale) ; panne durable → état "
           "vide ; réinjection (grâce = 0) rouvre bien le bug")
    finally:
        wm3.MA3_ETAT_FICHIER = fichier_orig
        wm3.MA3_ETAT_GRACE_S = grace_orig
        wm3._MA3_ETAT.clear()
        wm3._MA3_ETAT.update(etat_orig)
        wm3._MA3_ALIVE_DEPUIS.clear()
        wm3._MA3_ALIVE_DEPUIS.update(alive_orig)
        try:
            f.unlink()
            _os.rmdir(d)
        except Exception:
            pass


def test_plugin_install(wm3):
    """L'auto-installation du plugin grandMA3 : routage, garde-fous, message actionnable.

    🔑 Nouvelle étape de mise en route (au même niveau que le firmware).
    Paramètres → Firmware → « Installer automatiquement » : copie les 4 fichiers
    de production dans le pool de MA3, envoie l'import OSC + SaveShow, vérifie
    que la sonde répond.

    Ce contrôle tourne SANS MA3 et SANS toucher au vrai dossier MA3 : il
    redirige `_ma3_base` et `_plugin_source_dir` vers des dossiers jetables et
    neutralise `ma3_reachable` / `OSC.send_message`. Il vérifie :
      1. le routage /api/plugin/install → _post_plugin_install → installer_plugin ;
      2. MA3 injoignable → refus, ET AUCUN fichier écrit, AUCUN OSC envoyé
         (la copie ne part pas dans le vide) ;
      3. fichiers du plugin absents de l'app → refus, aucun OSC ;
      4. tout message d'échec est ACTIONNABLE (repli manuel nommé), sans citer
         de script ni crier en capitales.
    """
    section("50. Auto-installation du plugin grandMA3")
    import wing_handler
    import wing_ui as core

    routes = dict(wing_handler.Handler.ROUTES_POST)
    for chemin, methode, fonc in (
            ("/api/plugin/install", "_post_plugin_install", "installer_plugin"),
            ("/api/plugin/relaunch", "_post_plugin_relaunch", "relancer_plugin")):
        if routes.get(chemin) != methode:
            echec(f"{chemin} non routé",
                  f"table de routage : {routes.get(chemin)!r}")
            return
        if not hasattr(wing_handler.Handler, methode):
            echec(f"Handler.{methode} manquant")
            return
        if not callable(getattr(wm3, fonc, None)):
            echec(f"wing_ma3.{fonc} manquant")
            return
    if not callable(getattr(wm3, "plugin_present", None)):
        echec("wing_ma3.plugin_present manquant")
        return
    ok("routage install + relaunch → Handler → wing_ma3 ; plugin_present présent")

    # ── plugin_present() : les 4 combinaisons (fichiers dans un tmp) ──────────
    # Départage « installé mais arrêté » de « pas installé » (bridge.js /
    # parametres.js). Test de FICHIERS pur, aucun MA3.
    base_pp = Path(tempfile.mkdtemp(prefix="wb_pp_base_"))
    pool_pp = base_pp / "gma3_library" / "datapools" / "plugins"
    pool_pp.mkdir(parents=True)
    sauve_base = wm3._ma3_base
    try:
        wm3._ma3_base = lambda: base_pp
        # a. rien → absent
        if wm3.plugin_present():
            echec("plugin_present() vrai sans aucun fichier"); return
        # b. un seul .lua → toujours absent (il faut les DEUX)
        (pool_pp / "wingbridge.lua").write_text("-- factice\n", encoding="utf-8")
        if wm3.plugin_present():
            echec("plugin_present() vrai avec un seul .lua sur deux",
                  "réinjection : un all() devenu any() rouvrirait ce trou"); return
        # c. les deux .lua → présent, ET _resume_sonde() le remonte
        (pool_pp / "wingloader.lua").write_text("-- factice\n", encoding="utf-8")
        if not wm3.plugin_present():
            echec("plugin_present() faux avec les deux .lua posés"); return
        resume = wm3._resume_sonde()
        if "present" not in resume or resume["present"] is not True:
            echec("_resume_sonde() ne remonte pas present=True",
                  "l'UI ne pourrait pas distinguer arrêté / pas installé"); return
        # d. _ma3_base qui lève → absent, sans exception
        wm3._ma3_base = lambda: (_ for _ in ()).throw(RuntimeError("boum"))
        if wm3.plugin_present():
            echec("plugin_present() n'absorbe pas une exception de _ma3_base"); return
        ok("plugin_present() : absent / un seul .lua / les deux / _ma3_base qui lève — 4/4")
    finally:
        wm3._ma3_base = sauve_base
        shutil.rmtree(base_pp, ignore_errors=True)

    # ── relancer_plugin() : vise l'amorce PAR SON NOM, et REBASCULE si besoin ──
    # Deux exigences réunies ici :
    #  1. Nom, pas numéro de slot : l'emplacement varie d'une install à l'autre,
    #     un « Plugin 3 » en dur casserait la relance sur un plugin installé
    #     ailleurs. Réinjection : remettre 'Plugin 3' dans _PLUGIN_RELANCE_CMD.
    #  2. `Plugin "WingLoader"` est une BASCULE : un envoi unique ARRÊTE une
    #     sonde qui tournait (bug vu sur grandMA3 2.5). La relance
    #     doit donc renvoyer tant que le compteur `tours` n'AVANCE pas — et ne
    #     jamais se fier au fichier d'état, « frais » 5 s même sonde coupée.
    #     Réinjection : revenir à un envoi unique + test `ma3_etat().actif` fait
    #     échouer le scénario « sonde qui tournait » ci-dessous.
    import wing_ui as core2
    sauve = (wm3.ma3_reachable, etat.E.OSC, wm3.time.sleep, wm3._sonde_tours)
    envois = []

    class _OscRec:
        def send_message(self, *a, **k):
            envois.append(a)

    try:
        wm3.ma3_reachable = lambda: "ok"
        etat.E.OSC = _OscRec()
        wm3.time.sleep = lambda *_: None

        # a. sonde muette : le compteur ne bouge jamais → échec actionnable,
        #    après DEUX tentatives (la bascule a été retentée).
        wm3._sonde_tours = lambda: None
        r = wm3.relancer_plugin()
        cmd = envois[0][1] if envois and len(envois[0]) > 1 else ""
        if not envois or envois[0][0] != "/cmd":
            echec("relancer_plugin() n'envoie pas de /cmd OSC", repr(envois))
        elif not re.search(r'Plugin\s+"[A-Za-z]', cmd) or re.search(r"Plugin\s+\d", cmd):
            echec("relancer_plugin() vise un NUMÉRO de slot, pas un nom",
                  f"commande envoyée : {cmd!r} — l'emplacement varie selon l'install")
        elif r.get("ok"):
            echec("relancer_plugin() se dit OK alors que la sonde ne répond pas", repr(r))
        elif "à la main" not in r.get("raison", ""):
            echec("message d'échec de relance pas actionnable", repr(r.get("raison")))
        elif len(envois) != 2:
            echec("relancer_plugin() n'a pas retenté la bascule",
                  f"{len(envois)} envoi(s), attendu 2")
        else:
            ok(f"relancer_plugin() : relance par nom ({cmd!r}), échec actionnable si muet")

        # b. sonde qui TOURNAIT : 1er envoi la coupe (tours figé), 2e la
        #    rallume (tours qui repart). La relance doit renvoyer et finir OK.
        envois.clear()
        etat_sonde = {"tours": 500, "vivante": True}
        appels = {"n": 0}

        def _tours_bascule():
            # à chaque envoi OSC, on inverse l'état ; le compteur n'avance que
            # tant que la sonde est « vivante ».
            if etat_sonde["vivante"]:
                etat_sonde["tours"] += 3
            return etat_sonde["tours"]

        class _OscBascule:
            def send_message(self, *a, **k):
                envois.append(a)
                etat_sonde["vivante"] = not etat_sonde["vivante"]

        etat.E.OSC = _OscBascule()
        wm3._sonde_tours = _tours_bascule
        r = wm3.relancer_plugin()
        if not r.get("ok"):
            echec("relancer_plugin() abandonne une sonde qu'un 2e envoi relance",
                  repr(r))
        elif len(envois) != 2:
            echec("relancer_plugin() : mauvais nombre de bascules",
                  f"{len(envois)} envoi(s), attendu 2")
        elif not etat_sonde["vivante"]:
            echec("relancer_plugin() laisse la sonde ARRÊTÉE après relance")
        else:
            ok("relancer_plugin() : sonde qui tournait → coupée par le 1er "
               "envoi, rallumée par le 2e, verdict sur `tours` qui avance")
    finally:
        (wm3.ma3_reachable, etat.E.OSC, wm3.time.sleep, wm3._sonde_tours) = sauve

    sauve = (wm3.ma3_reachable, wm3._plugin_source_dir, wm3._ma3_base, etat.E.OSC)
    envois = []

    class _OscMuet:
        def send_message(self, *a, **k):
            envois.append(a)

    try:
        base = Path(tempfile.mkdtemp(prefix="wb_plugin_base_"))
        src = Path(tempfile.mkdtemp(prefix="wb_plugin_src_"))
        vide = Path(tempfile.mkdtemp(prefix="wb_plugin_vide_"))
        # `src` porte les 4 fichiers : ainsi, en scénario 2, la SEULE chose qui
        # arrête la copie est le garde-fou « MA3 injoignable » — pas un dossier
        # source vide. Réinjection : retirer ce garde-fou fait copier les
        # fichiers dans `pool`, et le scénario 2 vire au ROUGE.
        for n in ("wingbridge.lua", "wingbridge.xml",
                  "wingloader.lua", "wingloader.xml"):
            (src / n).write_text("-- factice\n", encoding="utf-8")
        wm3._ma3_base = lambda: base
        wm3._plugin_source_dir = lambda: src
        etat.E.OSC = _OscMuet()
        pool = base / "gma3_library" / "datapools" / "plugins"

        # 2. MA3 injoignable → refus AVANT toute copie, rien envoyé
        wm3.ma3_reachable = lambda: "off"
        r = wm3.installer_plugin()
        if r.get("ok"):
            echec("installer_plugin réussit alors que MA3 est injoignable", repr(r))
        elif pool.exists() and any(pool.iterdir()):
            echec("MA3 injoignable mais des fichiers ont été copiés dans le pool",
                  "la copie ne doit pas s'exécuter hors contexte")
        elif envois:
            echec("MA3 injoignable mais des commandes OSC sont parties", repr(envois))
        elif "grandMA3" not in r.get("raison", "") or "à la main" not in r.get("raison", ""):
            echec("message d'échec pas actionnable (MA3 injoignable)",
                  repr(r.get("raison")))
        else:
            ok("MA3 injoignable : refus net, aucun fichier écrit, aucun OSC, "
               "repli manuel proposé")

        # 3. fichiers du plugin absents de l'app → refus, aucun OSC
        wm3._plugin_source_dir = lambda: vide
        wm3.ma3_reachable = lambda: "ok"
        envois.clear()
        r = wm3.installer_plugin()
        if r.get("ok"):
            echec("installer_plugin réussit sans les fichiers du plugin", repr(r))
        elif envois:
            echec("fichiers absents mais des commandes OSC sont quand même parties",
                  repr(envois))
        elif "à la main" not in r.get("raison", ""):
            echec("message d'échec pas actionnable (fichiers absents)",
                  repr(r.get("raison")))
        else:
            ok("fichiers du plugin absents : refus actionnable, aucun OSC envoyé")

        # 4. les messages d'échec ne citent aucun script et ne crient pas
        wm3._plugin_source_dir = lambda: vide
        wm3.ma3_reachable = lambda: "off"
        msgs = [wm3.installer_plugin().get("raison", "")]
        wm3.ma3_reachable = lambda: "ok"
        msgs.append(wm3.installer_plugin().get("raison", ""))
        # « citer un script » = dire à l'utilisateur d'en LANCER un (.py/.sh) —
        # lister les .lua manquants du bundle est légitime, pas visé.
        fautes = [m for m in msgs
                  if ".py" in m or ".sh" in m
                  or any(c in m for c in ("DÉBRANCHE", "REBRANCHE-LA", "REBRANCHE"))]
        if fautes:
            echec("un message d'échec cite un script à lancer ou crie", repr(fautes))
        else:
            ok("messages d'échec : pas de script, pas de capitales d'insistance")
    finally:
        (wm3.ma3_reachable, wm3._plugin_source_dir, wm3._ma3_base, etat.E.OSC) = sauve

    # ── Fin de wizard de capture : aiguillage « où sera utilisé Wing Bridge » ──
    # Après la phase 7, l'assistant demande la plateforme AVANT l'invitation
    # « vérifie ta wing » :
    #   • « ici »  → ferme juste l'aiguillage, le fil standard A→E (#oscEtape /
    #                #pluginEtape) prend le relais tout seul au poll suivant.
    #   • « mac »  → propose l'export du .bin, PAS d'install de plugin ici.
    # 🐛 Avant (19/09/2026, test réel) : la branche « ici » ouvrait son PROPRE
    # panneau d'installation (#fwAiguillageIci, fwAiguillageInstaller()) —
    # dupliqué de l'Étape B, hors barre A→E, et sans attendre l'étape A (OSC).
    # Retiré : un seul chemin d'installation (#pluginEtape / pluginInstaller()).
    # Réinjection : réintroduire un second panneau/appel /api/plugin/install
    # fait retomber ce contrôle.
    html = core.HTML
    js = _js_de(html)
    manques = []
    if 'id="fwCaptureAiguillage"' not in html:
        manques.append("encart #fwCaptureAiguillage absent du balisage")
    if "fwAiguillage('ici')" not in html or "fwAiguillage('mac')" not in html:
        manques.append("les deux branches (ici / mac) ne sont pas toutes deux câblées")
    if 'id="fwAiguillageMac"' not in html or "fwExport()" not in html:
        manques.append("branche « mac » sans bouton d'export du firmware")
    if 'id="fwAiguillageIci"' in html or "fwAiguillageInstaller" in js:
        manques.append("le panneau dupliqué « ici » (#fwAiguillageIci / "
                        "fwAiguillageInstaller()) est revenu — l'Étape B "
                        "(#pluginEtape) doit rester le seul chemin d'install")
    # « ici » : un seul geste, fermer l'aiguillage — pas un second appel serveur.
    fa = re.search(r"function fwAiguillage\(cible\)\s*\{.*?\n\}", js, re.S)
    if not fa:
        manques.append("fwAiguillage(cible) non définie")
    elif "/api/plugin/install" in fa.group(0):
        manques.append("fwAiguillage() appelle encore /api/plugin/install "
                        "(devrait revenir à #pluginEtape)")
    # L'avertissement SaveShow doit survivre au retrait du panneau — déplacé
    # dans la vraie Étape B (#pluginEtape) pour ne pas perdre l'info.
    if "enregistrera ton show" not in html:
        manques.append("avertissement « enregistrera ton show » disparu "
                        "(devrait être dans #pluginEtape)")
    pe = re.search(r'id="pluginEtape".*?id="fwCaptureSuite"', html, re.S)
    if pe and "enregistrera ton show" not in pe.group(0):
        manques.append("l'avertissement « enregistrera ton show » n'est pas "
                        "dans #pluginEtape")
    # L'aiguillage doit précéder #fwCaptureSuite dans majCapture (succès).
    mc = re.search(r"function majCapture\b.*?\n\}", js, re.S)
    if mc and "fwCaptureAiguillage" not in mc.group(0):
        manques.append("majCapture() ne déclenche pas l'aiguillage sur succès")
    if manques:
        echec("aiguillage de fin de wizard incomplet", " ; ".join(manques))
    else:
        ok("fin de wizard : aiguillage ici/Mac — « ici » referme et rend la "
           "main au fil standard A→E (pas de second chemin d'install), "
           "« Mac » exporte le .bin, avertissement SaveShow dans l'Étape B")


def test_plugin_slot(wm3):
    """Emplacement (slot) du plugin, configurable — SETTINGS["plugin_slot"].

    🔑 Le slot était en dur à 3 (`_PLUGIN_OSC`). Devenu un réglage parce
    qu'OSC est à sens unique : l'app ne peut pas lire quels slots de MA3 sont
    déjà occupés avant d'importer, donc pas de détection fiable d'une
    collision — un slot déjà pris ouvre un dialogue Overwrite/Merge/Cancel qui
    bloque l'import en silence. Vérifie :
      1. `_plugin_osc(slot)` interpole le slot dans les 3 commandes qui en ont
         besoin (Import/Set/Plugin), pas dans SaveShow ;
      2. `/api/plugin_slot` est routé vers `Handler._post_plugin_slot` ;
      3. `installer_plugin()` lit `SETTINGS["plugin_slot"]` et l'utilise tel
         quel dans la séquence OSC envoyée (pas figé à 3) ;
      4. un slot HORS BORNES ne fait pas planter l'installation : repli sur
         le défaut (3), `SETTINGS["plugin_slot"]` corrigé en mémoire, aucune
         exception.
    """
    section("54. Emplacement configurable du plugin grandMA3")
    import wing_handler
    import wing_ui as core

    # ── 1. _plugin_osc(slot) : interpolation, pas un « 3 » qui traîne ────────
    seq7 = wm3._plugin_osc(7)
    attendu7 = ('Import Plugin Library "wingloader.xml" At 7',
                'Set Plugin 7.1 Property "Installed" "Yes"',
                'Plugin 7',
                'SaveShow')
    if seq7 != attendu7:
        echec("_plugin_osc(7) ne produit pas la séquence attendue",
              f"obtenu : {seq7!r}")
        return
    if any("3" in c for c in seq7):
        echec("_plugin_osc(7) contient encore un « 3 » — le slot n'a pas "
              "remplacé le défaut en dur", repr(seq7))
        return
    seq3 = wm3._plugin_osc(3)
    if seq3 != ('Import Plugin Library "wingloader.xml" At 3',
                'Set Plugin 3.1 Property "Installed" "Yes"',
                'Plugin 3',
                'SaveShow'):
        echec("_plugin_osc(3) — le défaut — a changé de forme", repr(seq3))
        return
    ok("_plugin_osc(7) → At 7 / Plugin 7.1 / Plugin 7 (SaveShow inchangé) ; "
       "_plugin_osc(3) toujours identique à l'ancien _PLUGIN_OSC")

    # ── 2. Routage /api/plugin_slot ───────────────────────────────────────────
    routes = dict(wing_handler.Handler.ROUTES_POST)
    if routes.get("/api/plugin_slot") != "_post_plugin_slot":
        echec("/api/plugin_slot non routé vers _post_plugin_slot",
              f"table de routage : {routes.get('/api/plugin_slot')!r}")
        return
    if not hasattr(wing_handler.Handler, "_post_plugin_slot"):
        echec("Handler._post_plugin_slot manquant")
        return
    ok("/api/plugin_slot → Handler._post_plugin_slot")

    # ── 3 et 4. installer_plugin() lit le réglage, et absorbe un slot hors bornes ─
    #
    # `time.sleep` neutralisé (même pattern que la section relancer_plugin() de
    # test_plugin_install()) : installer_plugin() attend réellement ~3 s
    # (settle + fenêtre `_sonde_avance()`) pour vérifier une PROGRESSION du
    # compteur — mais aucune assertion ci-dessous ne porte sur `ok`/le
    # résultat de cette vérification, seulement sur les commandes OSC
    # envoyées et sur SETTINGS corrigé. Le neutraliser garde le test de fumée
    # rapide sans rien affaiblir.
    sauve = (wm3.ma3_reachable, wm3._plugin_source_dir, wm3._ma3_base,
             etat.E.OSC, etat.E.SETTINGS.get("plugin_slot"), wm3.time.sleep)
    envois = []

    class _OscRec:
        def send_message(self, *a, **k):
            envois.append(a)

    try:
        base = Path(tempfile.mkdtemp(prefix="wb_slot_base_"))
        src = Path(tempfile.mkdtemp(prefix="wb_slot_src_"))
        for n in ("wingbridge.lua", "wingbridge.xml",
                  "wingloader.lua", "wingloader.xml"):
            (src / n).write_text("-- factice\n", encoding="utf-8")
        wm3._ma3_base = lambda: base
        wm3._plugin_source_dir = lambda: src
        wm3.ma3_reachable = lambda: "ok"
        etat.E.OSC = _OscRec()
        wm3.time.sleep = lambda *_: None

        # 3. Slot valide (7) : la séquence OSC envoyée le reflète vraiment —
        #    pas un _PLUGIN_OSC figé qu'on aurait oublié de brancher.
        etat.E.SETTINGS["plugin_slot"] = 7
        envois.clear()
        wm3.installer_plugin()
        cmds = [a[1] for a in envois if len(a) > 1]
        if not any("At 7" in c for c in cmds) or any("At 3" in c for c in cmds):
            echec("installer_plugin() n'utilise pas SETTINGS[\"plugin_slot\"]",
                  f"commandes envoyées : {cmds!r}")
        else:
            ok("installer_plugin() envoie bien la séquence OSC du slot réglé (7)")

        # 4. Slot hors bornes (0) : repli sur le défaut (3), pas d'exception,
        #    SETTINGS corrigé en mémoire pour que l'UI reflète ce qui a été
        #    réellement tenté (pas la valeur invalide laissée affichée).
        etat.E.SETTINGS["plugin_slot"] = 0
        envois.clear()
        try:
            wm3.installer_plugin()
        except Exception as e:
            echec("installer_plugin() plante sur un slot hors bornes", repr(e))
        else:
            cmds = [a[1] for a in envois if len(a) > 1]
            if not any("At 3" in c for c in cmds):
                echec("slot hors bornes (0) : pas de repli sur le défaut (3)",
                      f"commandes envoyées : {cmds!r}")
            elif etat.E.SETTINGS.get("plugin_slot") != 3:
                echec("slot hors bornes : SETTINGS[\"plugin_slot\"] pas corrigé "
                      "en mémoire", repr(etat.E.SETTINGS.get("plugin_slot")))
            else:
                ok("slot hors bornes (0) : repli sur le défaut (3), réglage "
                   "corrigé en mémoire, aucune exception")
    finally:
        (wm3.ma3_reachable, wm3._plugin_source_dir, wm3._ma3_base,
         etat.E.OSC, etat.E.SETTINGS["plugin_slot"], wm3.time.sleep) = sauve
        shutil.rmtree(base, ignore_errors=True)
        shutil.rmtree(src, ignore_errors=True)
