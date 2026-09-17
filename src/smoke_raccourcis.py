#!/usr/bin/env python3
"""
smoke_raccourcis.py — Wing Bridge
==================================
Domaine raccourcis clavier du test de fumée : raccourcis console par défaut,
unicité, forme garantie par la migration (partagée avec smoke_profils.py côté
appelant), envoi vers MA3, confirmation par la sonde, appui long universel.
Voir smoke_core.py pour ok/echec/note/section.
"""

import etat
import json
import re
import tempfile
import time
from pathlib import Path

from smoke_core import HERE, ok, echec, note, section


def test_raccourcis(wm, wk):
    section("7. Raccourcis console par défaut")
    try:
        wk.LAYOUT = wk.build_layout_map()
    except Exception as e:
        note(f"disposition clavier illisible ({e}) — contrôle sauté")
        return
    if not wk.LAYOUT:
        note("disposition clavier vide — contrôle sauté")
        return
    mauvais = []
    for token, spec in wm.CONSOLE_KEY_DEFAULTS.items():
        if not spec:
            continue
        if wk.resolve_spec(spec) is None and len(spec) != 1:
            mauvais.append(f"{token} → « {spec} »")
    if mauvais:
        echec(f"{len(mauvais)} raccourci(s) par défaut non résolvable(s)",
              "\n".join(mauvais))
    else:
        ok(f"{len(wm.CONSOLE_KEY_DEFAULTS)} raccourcis par défaut résolvables")


# ── Unicité des raccourcis console ────────────────────────────────────────────
#
# Le doublon se détecte sans rien connaître de MA3 : deux tokens distincts ne
# peuvent pas légitimement produire la même frappe, puisque MA3 ne saurait pas
# lequel des deux on veut.
#
# En BONUS, quand MA3 est installé : on compare à sa table de raccourcis réelle
# et on SIGNALE les écarts sans les traiter comme des fautes. L'utilisateur a le
# droit de remapper ses raccourcis dans MA3 (cas vu pour Assign), et
# l'app a le droit de s'en écarter volontairement. Mais un écart qu'on ne voit
# pas est un écart qui coûte une soirée.

def _raccourcis_ma3():
    """Table de raccourcis MA3 ACTIVE, si elle est sur cette machine.
    Retourne ({KeyCode: frappe}, nom du fichier) ou (None, None)."""
    rep = (Path.home() / "MALightingTechnology" / "gma3_library"
           / "userprofiles" / "keyboardshortcuts")
    if not rep.is_dir():
        return None, None
    actifs = []
    for f in sorted(rep.glob("*.xml")):
        t = f.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'KeyboardShortcutsActive="([^"]*)"', t)
        if m and m.group(1).lower() == "yes":
            actifs.append((f, t))
    if not actifs:
        return None, None
    f, t = actifs[-1]
    table = {a: b for a, b in
             re.findall(r'KeyCode="([^"]+)"\s+Shortcut="([^"]*)"', t)}
    return (table or None), f.name


def test_raccourcis_uniques(wm):
    section("17. Unicité des raccourcis console")
    table = wm.CONSOLE_KEY_DEFAULTS
    par_frappe = {}
    for token, spec in table.items():
        if spec:
            par_frappe.setdefault(spec.lower(), []).append(token)
    doublons = {s: t for s, t in par_frappe.items() if len(t) > 1}
    if doublons:
        echec(f"{len(doublons)} frappe(s) partagée(s) par plusieurs touches",
              "\n".join(f"« {s} » → {', '.join(t)}  (MA3 ne peut pas deviner "
                        f"laquelle on veut)" for s, t in doublons.items()))
    else:
        ok(f"{len(par_frappe)} frappes distinctes, aucune partagée")

    # Comparaison à la table réelle de MA3 — informative, jamais bloquante.
    ma3, fichier = _raccourcis_ma3()
    if not ma3:
        note("aucune table de raccourcis MA3 active sur cette machine "
             "— comparaison sautée")
        return
    def _norm(s):
        return (s or "").replace("+", "").replace(" ", "").lower()

    ecarts, connus, compares = [], [], 0
    for token, spec in table.items():
        ref = ma3.get(wm.keycode_de(token))
        if ref is None or not spec:
            continue
        compares += 1
        if _norm(ref) != _norm(spec):
            ligne = f"{token} : app « {spec} » / MA3 « {ref} »"
            # L'écart n'est « assumé » que tant que la touche vaut la valeur
            # documentée — sinon c'est un choix de l'utilisateur, à signaler.
            (connus if wm.ecart_assume(token, spec) else ecarts).append(ligne)
    if ecarts:
        note(f"{len(ecarts)}/{compares} écart(s) NON documenté(s) avec "
             f"{fichier} : " + " · ".join(ecarts) +
             "  — vérifier sur la console AVANT de « corriger » : la table ne "
             "liste qu'une liaison, MA3 en accepte d'autres")
    else:
        ok(f"{compares} raccourcis conformes à {fichier} "
           f"({len(connus)} écart(s) assumé(s))")


# ── L'app écrit son fichier de raccourcis ET applique dans MA3 ───────────────
#
#   • ne PAS réécrire quand MA3 est déjà d'accord (sinon le fichier est
#     réécrit à chaque clic — et la première version le faisait, à cause
#     d'une comparaison sensible à la casse : « S » ≠ « s ») ;
#   • ne PAS accumuler de copies dans le dossier de MA3 ;
#   • ne PAS toucher aux 33 touches que l'app ne gère pas (pavé numérique,
#     touches X, écrans onPC) — les écraser effacerait des réglages qu'elle
#     n'a jamais vus.
#
# Le contrôle travaille sur une COPIE du dossier : il ne touche jamais à la
# vraie configuration de grandMA3.

def _norm_spec(s):
    return "+".join(p.strip().lower() for p in str(s or "").split("+") if p.strip())


def test_shcuts(wv, wm):
    section("19. Envoi des raccourcis vers MA3")
    import shutil
    reel = Path.home() / ("MALightingTechnology/gma3_library/userprofiles"
                          "/keyboardshortcuts")
    sources = sorted(reel.glob("*.xml")) if reel.is_dir() else []
    if not sources:
        note("aucune table de raccourcis MA3 sur cette machine — contrôle sauté")
        return

    bac = Path(tempfile.mkdtemp(prefix="wingshcuts-"))
    # Bac SÉPARÉ pour le settings.json de test : `bac` sert de MA3_SHCUTS_DIR
    # et le contrôle (c) plus bas vérifie que RIEN ne s'y accumule au-delà des
    # fichiers copiés depuis `sources` — y déposer aussi settings.json le
    # ferait échouer pour une raison qui n'a rien à voir avec ce qu'il vérifie.
    bac_settings = Path(tempfile.mkdtemp(prefix="wingsettings-"))
    envoyes = []

    class _OSCespion:
        def send_message(self, addr, valeur):
            envoyes.append(valeur)

    import wing_reglages as wr
    sauve = (wv.MA3_SHCUTS_DIR, etat.E.OSC, json.loads(json.dumps(etat.E.PROFILE)),
             wv.ma3_etat, wr.SETTINGS_FILE, etat.E.SETTINGS.get("shcuts_horodate"))
    try:
        for f in sources:
            shutil.copy2(f, bac / f.name)
        wv.MA3_SHCUTS_DIR, etat.E.OSC = bac, _OSCespion()
        # ⚠️ REDIRIGÉ DÈS ICI, avant le premier appel à shcuts_envoyer() :
        # _marquer_shcuts_envoyes() (appelée à CHAQUE succès, y compris (a) et
        # (b) plus bas) écrit sinon dans le VRAI settings.json de cette
        # machine — vécu une fois pendant ce développement (valeur de test
        # retrouvée dans le settings.json réel, lu par un serveur en marche).
        wr.SETTINGS_FILE = bac_settings / "settings.json"
        # ⚠️ SONDE NEUTRALISÉE. Elle lit le VRAI MA3 ; ces contrôles-ci portent
        # sur la logique de fichier, dans un bac à sable. Sans ce leurre, la
        # console réelle contredisait la copie et le test échouait pour une
        # raison qui n'a rien à voir avec ce qu'il vérifie (« un 2e envoi
        # réécrit alors que MA3 est déjà d'accord »).
        # La vérification PAR la sonde est contrôlée juste après, avec une
        # sonde simulée dont on maîtrise le contenu.
        wv.ma3_etat = lambda: {"actif": False}

        cible = bac / f"{wv.MA3_SHCUTS_NOM}.xml"
        if not cible.exists():
            note(f"{cible.name} absent — l'app partira du gabarit d'origine")
        avant = cible.read_bytes() if cible.exists() else None
        # ⚠️ On passe par le parseur RÉEL : lui seul rend TOUTES les valeurs
        # d'un KeyCode (OOPS en a deux) et ignore les entrées d'executor.
        # Une regex maison ici testerait autre chose que ce qui tourne.
        toutes = lambda t: {k: " / ".join(v)
                            for k, v in wv._shcuts_par_touche(t).items()}
        orig = toutes(avant.decode("utf-8")) if avant else {}

        # Frappe LIBRE pour l'essai : en prendre une au hasard tombe sur une
        # collision (« F7 » appartient à X7) et le test se mordrait la queue.
        occupees = {p.strip().lower()
                    for v in orig.values() for p in v.split(" / ")}
        libres = [f"Ctrl+Alt+Shift+F{i}" for i in range(1, 13)
                  if f"ctrl+alt+shift+f{i}" not in occupees]
        if len(libres) < 2:
            note("pas assez de frappes libres — essais d'écriture sautés")
            return
        libre, libre2 = libres[0], libres[1]
        libre3 = libres[2] if len(libres) > 2 else None

        # a) déjà d'accord → aucune écriture, aucun envoi
        wv.shcuts_envoyer()                       # met à niveau une 1re fois
        envoyes.clear()
        apres1 = cible.read_bytes()
        r = wv.shcuts_envoyer()
        if not r.get("inchange"):
            echec("un 2e envoi réécrit alors que MA3 est déjà d'accord",
                  f"modifiés : {r.get('modifies')}")
        elif envoyes:
            echec("un 2e envoi parle à MA3 pour rien", str(envoyes))
        elif cible.read_bytes() != apres1:
            echec("un 2e envoi modifie le fichier alors que rien n'a changé")
        else:
            ok("rien n'est réécrit ni envoyé quand MA3 est déjà d'accord")

        # b) une vraie modification passe, et elle SEULE
        depart = toutes(cible.read_text(encoding="utf-8"))
        etat.E.PROFILE.setdefault("console_keys", {})["Store"] = libre
        envoyes.clear()
        r = wv.shcuts_envoyer()
        final = toutes(cible.read_text(encoding="utf-8"))
        bouges = [k for k in depart if depart.get(k) != final.get(k)]
        geres = {wm.keycode_de(t) for t, s in wm.CONSOLE_KEY_DEFAULTS.items() if s}
        hors = [k for k in bouges if k not in geres]
        if hors:
            echec(f"{len(hors)} touche(s) NON gérée(s) par l'app ont été "
                  f"modifiées", ", ".join(hors))
        elif "STORE" not in bouges:
            echec("la modification demandée n'a pas été écrite",
                  f"bougées : {bouges}")
        elif len(envoyes) != 1:
            echec("l'import n'a pas été demandé exactement une fois", str(envoyes))
        else:
            ok(f"seules les touches gérées bougent ({len(bouges)} : "
               f"{', '.join(bouges)})")

        # b-bis) UN ÉCART ASSUMÉ QUE L'UTILISATEUR MODIFIE DOIT PARTIR.
        #
        # 🐛 Signalé. « Assign » figurait dans ECARTS_ASSUMES ; remplacé par
        # Ctrl+Alt+B puis « Envoyer les raccourcis »… et rien n'est parti,
        # pendant que le
        # bouton affichait « MA3 est déjà d'accord ». Le réglage était avalé
        # en silence ET le message était faux.
        # L'exclusion suit désormais la VALEUR : dès qu'elle change, c'est le
        # choix de l'utilisateur qui gagne.
        for token, (valeur, _) in wm.ECARTS_ASSUMES.items():
            kc = wm.keycode_de(token)
            if kc not in toutes(cible.read_text(encoding="utf-8")):
                continue
            etat.E.PROFILE["console_keys"][token] = "Ctrl+Alt+F9"
            e = wv.shcuts_etat()
            vus = [x["touche"] for x in e["ecarts"]]
            if kc not in vus:
                echec(f"« {token} » modifié par l'utilisateur n'est PAS "
                      f"détecté comme écart",
                      f"il reste traité comme assumé alors qu'il ne vaut plus "
                      f"« {valeur} » — réglage avalé en silence")
            else:
                envoyes.clear()
                wv.shcuts_envoyer()
                final2 = toutes(cible.read_text(encoding="utf-8"))
                if _norm_spec(final2.get(kc)) != _norm_spec("Ctrl+Alt+F9"):
                    echec(f"« {token} » modifié n'a pas été écrit dans MA3",
                          f"fichier : {final2.get(kc)}")
                else:
                    ok(f"« {token} » modifié par l'utilisateur est bien envoyé")
            etat.E.PROFILE["console_keys"][token] = valeur
            wv.shcuts_envoyer()

        # b-ter) COLLISION : une frappe déjà prise par une AUTRE touche de MA3
        # ne doit PAS être écrite.
        #
        # 🐛 Vécu : « Assign » mis sur Ctrl+Alt+F en croyant la combinaison
        # libre — SELFIX l'avait déjà. MA3 a affiché
        # SelectFixtures à la place d'Assign, sans un mot. Deux touches sur la
        # même frappe : la console ne peut pas deviner laquelle on veut.
        table_ma3 = toutes(cible.read_text(encoding="utf-8"))
        pris = {v: k for k, v in table_ma3.items() if v}
        if pris:
            frappe, proprio = next(iter(pris.items()))
            victime = next((t for t in wm.CONSOLE_KEY_DEFAULTS
                            if wm.keycode_de(t) in table_ma3
                            and wm.keycode_de(t) != proprio), None)
            if victime:
                garde = cible.read_bytes()
                etat.E.PROFILE["console_keys"][victime] = frappe
                e = wv.shcuts_etat()
                envoyes.clear()
                r = wv.shcuts_envoyer()
                if not e.get("collisions"):
                    echec(f"collision non détectée : « {victime} » sur "
                          f"« {frappe} », déjà pris par {proprio}")
                elif r.get("ok") or envoyes:
                    echec("une frappe en collision a quand même été envoyée",
                          f"{victime} → {frappe} (déjà à {proprio})")
                elif cible.read_bytes() != garde:
                    echec("le fichier a été modifié malgré la collision")
                else:
                    ok(f"une frappe déjà prise ({frappe} → {proprio}) est "
                       f"refusée, fichier intact")
                del etat.E.PROFILE["console_keys"][victime]

        # b-quater) ORTHOGRAPHE DE MA3. Une frappe juste mais mal capitalisée
        # doit être corrigée, pas déclarée conforme.
        #
        # 🐛 Vécu : « Update » mis sur « n » ; l'app a écrit
        # `Shortcut="n"` alors que MA3 note ses lettres en MAJUSCULE, et la
        # touche est restée sans effet dans la console — tout en tapant bien
        # « n » quand les raccourcis étaient désactivés. Pire : la comparaison
        # insensible à la casse déclarait ensuite le fichier conforme, donc la
        # faute s'installait à demeure.
        vocab = wv._shcuts_vocabulaire(cible.read_text(encoding="utf-8"))
        cas = [("n", "N"), ("ctrl+alt+b", "Ctrl+Alt+B"), ("pageup", "PageUp")]
        faux = [f"« {s} » → « {wv._shcut_style_ma3(s, vocab)} » "
                f"(attendu « {att} »)"
                for s, att in cas if wv._shcut_style_ma3(s, vocab) != att]
        if faux:
            echec("l'orthographe de MA3 n'est pas respectée", "\n".join(faux))
        else:
            ok("les frappes sont écrites dans l'orthographe de MA3 "
               "(n → N, pageup → PageUp)")

        # b-quinquies) LA COMMANDE ENVOYÉE À MA3.
        #
        # ❌ `Import KeyboardShortcut Library "…"` a été RÉFUTÉE sur console :
        # envoyée cinq fois, jamais appliquée — la touche ne
        # répondait qu'après un Import fait à la main dans le menu de MA3.
        # ✅ `Set KeyboardShortcut <n> Property "Shortcut" "<v>"` s'applique
        # immédiatement, avec <n> = position dans le fichier (confirmé par
        # `List KeyboardShortcut` : 120 ASSIGN, 122 UPDATE, 123 STORE).
        envoyes.clear()
        etat.E.PROFILE["console_keys"]["Update"] = libre2
        wv.shcuts_envoyer()
        time.sleep(0.6)                       # les envois sont espacés
        if any("Import" in c for c in envoyes):
            echec("l'app envoie encore la commande Import, réfutée sur console",
                  str(envoyes))
        elif not any(c.startswith("Set KeyboardShortcut ") for c in envoyes):
            echec("aucune commande « Set KeyboardShortcut » envoyée",
                  str(envoyes))
        else:
            # Le numéro doit correspondre à la position réelle dans le fichier.
            cmd = next(c for c in envoyes if c.startswith("Set KeyboardShortcut"))
            no = int(cmd.split()[2])
            entrees = wv._shcuts_entrees(cible.read_text(encoding="utf-8"),
                                         executors=True)
            reel = entrees[no - 1][1] if 0 < no <= len(entrees) else "?"
            if reel != "UPDATE":
                echec(f"le n° envoyé ne désigne pas la bonne touche",
                      f"« {cmd} » → position {no} = {reel}, attendu UPDATE")
            else:
                ok(f"commande immédiate correcte : n°{no} = UPDATE")

        # c) rien ne s'accumule dans le dossier
        noms = sorted(p.name for p in bac.iterdir())
        parasites = [n for n in noms if n.endswith((".part", ".tmp"))
                     or n not in {f.name for f in sources}]
        if parasites:
            echec("des fichiers s'accumulent dans le dossier de MA3",
                  ", ".join(parasites))
        else:
            ok(f"aucune copie créée ({len(noms)} fichier(s), comme au départ)")

        # d) le compte des touches ne change pas
        if len(final) != len(depart):
            echec("le nombre de raccourcis a changé",
                  f"{len(depart)} → {len(final)}")
        else:
            ok(f"les {len(final)} raccourcis de MA3 sont tous conservés")

        # e) HORODATAGE DU DERNIER ENVOI RÉUSSI (SETTINGS["shcuts_horodate"]).
        #
        # Persisté par _marquer_shcuts_envoyes() (wing_raccourcis.py), appelée
        # aux DEUX points de succès de shcuts_envoyer() — « déjà d'accord »
        # ET « vraiment envoyé » — voir docs/KEYBOARD_MAPPING.md. SETTINGS_FILE
        # est déjà redirigé vers le bac de test depuis le tout début de cette
        # fonction (voir plus haut) : (a), (b) et (b-quinquies) ont donc déjà
        # écrit un horodate dedans, sans jamais toucher au vrai settings.json.
        import wing_raccourcis as wraccourcis
        if libre3 is None:
            note("pas de 3e frappe libre — contrôle de l'horodatage sauté")
        else:
            etat.E.SETTINGS["shcuts_horodate"] = None
            avant_h = etat.E.SETTINGS.get("shcuts_horodate")
            r_inchange = wv.shcuts_envoyer()  # déjà à jour depuis (a)/(b-quinquies)
            apres_h1 = etat.E.SETTINGS.get("shcuts_horodate")
            if not r_inchange.get("inchange") or not apres_h1:
                echec("l'horodatage n'est pas posé sur un envoi « déjà à jour »",
                      f"avant={avant_h} après={apres_h1} r={r_inchange}")
            elif not wr.SETTINGS_FILE.is_file():
                echec("shcuts_envoyer() n'a pas persisté l'horodatage sur disque",
                      str(wr.SETTINGS_FILE))
            else:
                # Frappe INÉDITE (libre3, jamais utilisée plus haut) : réutiliser
                # libre2 ici entrerait en collision avec « Update », déjà réglé
                # dessus par (b-quinquies) — shcuts_envoyer() refuserait
                # d'écrire, et ce contrôle mesurerait une fausse panne.
                time.sleep(0.01)
                etat.E.PROFILE["console_keys"]["Store"] = libre3
                r_reel = wv.shcuts_envoyer()
                apres_h2 = etat.E.SETTINGS.get("shcuts_horodate")
                if r_reel.get("inchange") or not apres_h2 or apres_h2 <= apres_h1:
                    echec("l'horodatage n'avance pas sur un envoi RÉEL",
                          f"après (a jour)={apres_h1} après (envoi)={apres_h2} "
                          f"r={r_reel}")
                else:
                    # RÉINJECTION ROUGE : sans _marquer_shcuts_envoyes(), ce
                    # contrôle doit échouer — sinon il ne prouve rien.
                    sauve_marquer = wraccourcis._marquer_shcuts_envoyes
                    wraccourcis._marquer_shcuts_envoyes = lambda: None
                    try:
                        time.sleep(0.01)
                        etat.E.PROFILE["console_keys"]["Store"] = libre
                        wv.shcuts_envoyer()
                        apres_h3 = etat.E.SETTINGS.get("shcuts_horodate")
                        if apres_h3 != apres_h2:
                            echec("réinjection ratée : l'horodate avance encore "
                                  "sans _marquer_shcuts_envoyes() — ce contrôle "
                                  "ne prouverait rien", f"{apres_h2} → {apres_h3}")
                        else:
                            ok("horodatage du dernier envoi persisté (SETTINGS + "
                               "disque), avance à chaque succès ; réinjection "
                               "(marquage neutralisé) le fige bien")
                    finally:
                        wraccourcis._marquer_shcuts_envoyes = sauve_marquer
    except Exception as e:
        echec("le contrôle des raccourcis a levé une exception",
              f"{type(e).__name__}: {e}")
    finally:
        wv.MA3_SHCUTS_DIR, etat.E.OSC = sauve[0], sauve[1]
        etat.E.PROFILE.clear()
        etat.E.PROFILE.update(sauve[2])
        wv.ma3_etat = sauve[3]
        wr.SETTINGS_FILE = sauve[4]
        etat.E.SETTINGS["shcuts_horodate"] = sauve[5]
        shutil.rmtree(bac, ignore_errors=True)


# ── La sonde MA3 confirme (ou dément) ce qu'on a envoyé ───────────────────────
#
# 🎯 Besoin : « faisons confirmation honnête, je veux de la
# sûreté ». Jusque-là l'app relisait SON PROPRE fichier pour annoncer le
# succès — MA3 fermé, elle disait la même chose. La sonde tourne DANS la
# console : elle seule prouve quelque chose.
#
# Ce contrôle simule une sonde et vérifie les deux verdicts, car c'est le
# DÉMENTI qui a de la valeur : un outil de vérification qui ne sait que dire
# « tout va bien » ne vérifie rien.

def test_shcuts_sonde(wv, wm):
    section("20. Confirmation par la sonde MA3")
    import shutil
    # 🐛 Côté interface : `shcutsEnvoyer()` ne doit PAS conclure à l'échec au
    # premier `non_applique` vu pendant l'attente (MA3 applique les touches
    # espacées de 0,15 s, la sonde relit ensuite) — sinon un « ⛔ MA3 n'a pas
    # appliqué » périmé reste affiché pour un envoi qui a pris.
    js = (Path(__file__).parent / "ui" / "touches.js").read_text(encoding="utf-8")
    debut = js.find("async function shcutsEnvoyer(")
    fin = js.find("\n}\n", debut)
    corps = js[debut:fin] if debut >= 0 and fin > debut else ""
    if not corps:
        echec("shcutsEnvoyer() introuvable dans ui/touches.js")
    elif re.search(r"non_applique[^\n]*\)\.length\)\s*\{[^}]*return", corps):
        echec("shcutsEnvoyer() abandonne dès le 1er « non_applique » vu",
              "un retard normal de MA3 est pris pour un échec définitif")
    else:
        ok("shcutsEnvoyer() attend la fin du délai avant d'affirmer que MA3 "
           "n'a pas appliqué")
    reel = Path.home() / ("MALightingTechnology/gma3_library/userprofiles"
                          "/keyboardshortcuts")
    sources = sorted(reel.glob("*.xml")) if reel.is_dir() else []
    if not sources:
        note("aucune table de raccourcis MA3 — contrôle sauté")
        return
    bac = Path(tempfile.mkdtemp(prefix="wingsonde-"))
    sauve = (wv.MA3_SHCUTS_DIR, wv.ma3_etat, json.loads(json.dumps(etat.E.PROFILE)))
    try:
        for f in sources:
            shutil.copy2(f, bac / f.name)
        wv.MA3_SHCUTS_DIR = bac
        cible = bac / f"{wv.MA3_SHCUTS_NOM}.xml"
        if not cible.exists():
            note(f"{cible.name} absent — contrôle sauté")
            return
        entrees = wv._shcuts_entrees(cible.read_text(encoding="utf-8"),
                                     executors=True)

        def sonde(frappes):
            """Sonde simulée : une entrée par position, comme la vraie."""
            return lambda: {"actif": True, "page": None, "executors": [],
                            "raccourcis": [{"no": i + 1, "frappe": f}
                                           for i, f in enumerate(frappes)],
                            "raccourcis_via": "simulée"}

        # a) MA3 tient exactement ce que dit le fichier → tout est confirmé
        wv.ma3_etat = sonde([sc or "" for _, _, sc in entrees])
        d = wv.shcuts_etat()
        if not d.get("sonde"):
            echec("la sonde n'est pas exploitée", str(d.get("sonde_via")))
        elif d.get("non_applique"):
            echec("un désaccord est signalé alors que MA3 est identique",
                  str(d["non_applique"]))
        elif not d.get("confirmes"):
            echec("aucune touche confirmée alors que tout correspond")
        else:
            ok(f"{d['confirmes']} touches confirmées dans MA3")

        # b) LE CAS QUI COMPTE : MA3 n'a PAS appliqué. Le fichier est correct,
        # la console tient l'ancienne valeur — exactement la panne de la
        # commande « Import », qui écrivait sans que MA3 relise.
        i_up = next((i for i, (_, kc, _) in enumerate(entrees)
                     if kc == "UPDATE"), None)
        if i_up is None:
            note("UPDATE absent du fichier — démenti non testé")
        else:
            frappes = [sc or "" for _, _, sc in entrees]
            frappes[i_up] = "Ctrl+Alt+Shift+F12"      # MA3 tient autre chose
            wv.ma3_etat = sonde(frappes)
            d = wv.shcuts_etat()
            vus = [x["touche"] for x in d.get("non_applique", [])]
            if "UPDATE" not in vus:
                echec("un raccourci NON appliqué par MA3 n'est pas détecté",
                      f"la console tient « Ctrl+Alt+Shift+F12 », le fichier "
                      f"autre chose — non_applique = {d.get('non_applique')}")
            elif d.get("a_jour"):
                echec("« à jour » annoncé alors que MA3 n'a pas appliqué")
            else:
                ok("un raccourci non appliqué par MA3 est démenti")

            # b-bis) 🐛 LE MÊME CAS, CÔTÉ ENVOI. Constaté en test réel sur
            # l'app buildée : le fichier est déjà bon, la console tient
            # autre chose (touches déréglées dans MA3) —
            # `a_jour` est faux, mais l'envoi ne calculait « quoi envoyer »
            # que d'après le FICHIER : 0 commande partie, `ok` renvoyé, et
            # l'étape D du wizard annonçait « Raccourcis envoyés ». Détecter
            # ne suffit pas : l'envoi doit AGIR sur ce que la sonde démentit.
            import time
            import wing_reglages as wr
            envoyes = []

            class _OSCespion:
                def send_message(self, addr, valeur):
                    envoyes.append(valeur)

            bac_settings = Path(tempfile.mkdtemp(prefix="wingsettings-"))
            sauve_env = (etat.E.OSC, wr.SETTINGS_FILE,
                         etat.E.SETTINGS.get("shcuts_horodate"))
            try:
                etat.E.OSC = _OSCespion()
                wr.SETTINGS_FILE = bac_settings / "settings.json"
                r = wv.shcuts_envoyer()
                time.sleep(0.4)      # les commandes partent en Timer espacés
                attendu = f'Set KeyboardShortcut {i_up + 1} Property "Shortcut"'
                if r.get("inchange") or not r.get("ok"):
                    echec("l'envoi ne réagit pas à un raccourci non appliqué "
                          "par MA3", str({k: r.get(k) for k in
                                          ("ok", "inchange", "erreur")}))
                elif not any(c.startswith(attendu) for c in envoyes):
                    echec("« envoyé » renvoyé mais AUCUNE commande Set pour la "
                          "touche que MA3 n'a pas appliquée",
                          f"attendu « {attendu} … », parti : {envoyes}")
                else:
                    ok("l'envoi ré-émet la touche que la sonde démentit "
                       "(fichier déjà bon, MA3 en retard)")
            finally:
                etat.E.OSC, wr.SETTINGS_FILE = sauve_env[0], sauve_env[1]
                etat.E.SETTINGS["shcuts_horodate"] = sauve_env[2]
                shutil.rmtree(bac_settings, ignore_errors=True)

        # c) GARDE-FOU : listes de longueurs différentes → aucune jointure.
        # Comparer par position deux listes décalées comparerait des touches
        # sans rapport : pire que pas de vérification.
        wv.ma3_etat = sonde([sc or "" for _, _, sc in entrees][:-3])
        d = wv.shcuts_etat()
        if d.get("sonde"):
            echec("la jointure se fait malgré des listes de tailles "
                  "différentes", f"{len(entrees)} vs {len(entrees) - 3}")
        else:
            ok("des listes désynchronisées coupent la vérification "
               "au lieu de comparer n'importe quoi")
    except Exception as e:
        echec("le contrôle de la sonde a levé une exception",
              f"{type(e).__name__}: {e}")
    finally:
        wv.MA3_SHCUTS_DIR, wv.ma3_etat = sauve[0], sauve[1]
        etat.E.PROFILE.clear()
        etat.E.PROFILE.update(sauve[2])
        shutil.rmtree(bac, ignore_errors=True)


def test_appui_long_universel(ui):
    """Toute touche console relaie sa VRAIE durée d'appui, sans réglage.

    🔑 Exigence : « je veux que tout soit implémenté par défaut pour ne pas
    avoir à cocher de case appui long ». Le principe était
    déjà écrit dans le projet : le maintien est NATIF côté MA3 (Clear maintenu
    = ClearAll). On relaie la durée, MA3 décide.

    Ce contrôle vérifie les trois propriétés qui comptent :
      1. un appui enfonce la touche (`hold_down`), il ne la tape pas ;
      2. le relâchement la relâche (`hold_up`), avec le MÊME spec ;
      3. ça vaut pour n'importe quelle touche, sans réglage préalable.

    ⚠️ Et surtout : l'appariement se fait par **bouton physique**. Si le profil
    change entre l'appui et le relâchement, on doit relâcher ce qu'on a
    réellement enfoncé — sinon une touche reste bloquée dans MA3, ce qui est
    bien pire qu'une frappe manquée. C'est la leçon du bug « appui et
    relâchement ont divergé ».
    """
    section("31. Appui long : toutes les touches, sans réglage")
    file, vrai = [], ui.KEYQ if hasattr(ui, "KEYQ") else None
    sauve_profil = json.loads(json.dumps(etat.E.PROFILE))
    envois = []
    memo = {k: getattr(ui, k) for k in ("enqueue_key", "enqueue_key_down",
                                        "enqueue_key_up")}
    try:
        ui.enqueue_key      = lambda spec: envois.append(("tap", spec)) or True
        ui.enqueue_key_down = lambda spec: envois.append(("down", spec)) or True
        ui.enqueue_key_up   = lambda spec: envois.append(("up", spec)) or True
        etat.E.MAINTIENS.clear()

        btn = 0x21
        etat.E.PROFILE["buttons"][f"0x{btn:02x}"] = "Clear"
        etat.E.PROFILE["console_keys"]["Clear"] = "c"
        ui.console_helper_alive = lambda: True

        ui.handle_button_bridge(btn)
        ui.handle_button_release(btn)

        ennuis = []
        if ("tap", "c") in envois:
            ennuis.append("la touche a été TAPÉE au lieu d'être enfoncée "
                          "(la durée d'appui n'est plus relayée)")
        if ("down", "c") not in envois:
            ennuis.append("aucun enfoncement à l'appui")
        if ("up", "c") not in envois:
            ennuis.append("aucun relâchement — la touche resterait bloquée dans MA3")
        if envois and envois[0][0] != "down":
            ennuis.append(f"le 1er envoi est « {envois[0][0]} », attendu « down »")
        if etat.E.MAINTIENS:
            ennuis.append(f"maintien non purgé après relâchement : {etat.E.MAINTIENS}")

        # Le profil change ENTRE l'appui et le relâchement : on doit quand même
        # relâcher ce qui a été enfoncé.
        envois.clear()
        time.sleep(0.08)          # au-delà de l'anti-rebond (60 ms)
        ui.handle_button_bridge(btn)
        etat.E.PROFILE["console_keys"]["Clear"] = "z"      # l'utilisateur remappe
        ui.handle_button_release(btn)
        if ("up", "c") not in envois:
            ennuis.append("après remappage, on relâche la mauvaise touche "
                          f"(envois : {envois}) — « c » devait être relâché")

        if ennuis:
            echec("l'appui long universel ne se comporte pas comme prévu",
                  " ; ".join(ennuis))
        else:
            ok("appui = enfoncé, relâchement = relâché, apparié par bouton "
               "physique même après remappage")
    except Exception as e:
        echec("le contrôle d'appui long a levé une exception",
              f"{type(e).__name__}: {e}")
    finally:
        for k, v in memo.items():
            setattr(ui, k, v)
        etat.E.PROFILE.clear(); etat.E.PROFILE.update(sauve_profil)
        etat.E.MAINTIENS.clear()


def test_cmd_buf_verrouille():
    """`cmd_buf` : lecture ET écriture protégées par LE MÊME verrou, partout.

    🐛 Bugs liés (#9, #10) : `wing_boutons.handle_button_bridge` lisait
    `cmd_buf` une seule fois, sous `core.LOCK`, tout en haut de la fonction —
    puis écrivait dessus bien plus loin, HORS verrou, sur cette valeur
    potentiellement périmée. Pendant ce temps, `wing_handler._post_mode`
    (remise à zéro de `cmd_buf` au changement de mode) écrivait `STATE` en
    plusieurs instructions successives SANS JAMAIS prendre le verrou. Une
    frappe en cours pendant un changement de mode pouvait donc faire
    réapparaître une commande périmée juste après une remise à zéro voulue.

    ⚠️ AUDIT DE SOURCE, pas un contrôle comportemental : la fenêtre de course
    tient en quelques instructions, trop étroite pour qu'un test à quelques
    threads l'expose de façon fiable via le seul GIL — même limite déjà
    documentée pour le verrou de `connect_wing()`
    (smoke_hardware.py::test_connect_wing_verrou_et_boucle). On vérifie donc
    que chaque écriture est immédiatement précédée d'un `with core.LOCK:`.
    """
    section("58. cmd_buf : lecture et écriture sous le même verrou")
    ennuis = []
    FENETRE = 15    # lignes précédentes scrutées — voir les cas comptés en revue

    # ── wing_boutons.py : chaque écriture de cmd_buf, verrou juste au-dessus ──
    src = (HERE / "wing_boutons.py").read_text(encoding="utf-8") \
        .replace("etat.E.", "core.").splitlines()  # etat.E.X ramené à core.X : mêmes motifs d'audit (D1, 25/09/2026)
    cible = 'core.STATE["cmd_buf"] = '
    trouvees_boutons = 0
    for i, ligne in enumerate(src):
        if cible in ligne and not ligne.strip().startswith("#"):
            trouvees_boutons += 1
            fenetre = src[max(0, i - FENETRE):i]
            if not any("with core.LOCK:" in l for l in fenetre):
                ennuis.append(f"wing_boutons.py:{i + 1} — écriture de cmd_buf "
                              f"sans `with core.LOCK:` dans les {FENETRE} "
                              f"lignes précédentes : {ligne.strip()!r}")
    if trouvees_boutons == 0:
        ennuis.append("aucune écriture de cmd_buf trouvée dans "
                      "wing_boutons.py — le contrôle ne teste plus rien")

    # ── wing_handler.py : _post_mode écrit STATE sous verrou ────────────────
    txt = (HERE / "wing_handler.py").read_text(encoding="utf-8") \
        .replace("etat.E.", "core.")  # etat.E.X ramené à core.X : mêmes motifs d'audit (D1, 25/09/2026)
    i0 = txt.find("def _post_mode(")
    if i0 == -1:
        ennuis.append("wing_handler._post_mode introuvable")
    else:
        i1 = txt.find("\n    def ", i0 + 1)
        bloc = txt[i0:i1 if i1 != -1 else len(txt)].splitlines()
        champs = ('core.STATE["mode"] = ', 'core.STATE["resume_mode"] = ',
                 'core.STATE["last_event"] = ', 'core.STATE["cmd_buf"] = ')
        trouvees_mode = 0
        for champ in champs:
            for i, ligne in enumerate(bloc):
                if champ in ligne:
                    trouvees_mode += 1
                    fenetre = bloc[max(0, i - FENETRE):i]
                    if not any("with core.LOCK:" in l for l in fenetre):
                        ennuis.append(f"_post_mode : écriture {champ.strip()!r} "
                                      f"sans `with core.LOCK:` proche : "
                                      f"{ligne.strip()!r}")
        if trouvees_mode == 0:
            ennuis.append("aucune écriture STATE trouvée dans _post_mode — "
                          "le contrôle ne teste plus rien")

    if ennuis:
        echec("cmd_buf/STATE encore écrit(e) hors verrou quelque part",
              " ; ".join(ennuis))
    else:
        ok(f"{trouvees_boutons} écriture(s) de cmd_buf (wing_boutons.py) et "
           f"les écritures STATE de _post_mode toutes protégées par core.LOCK")


def test_double_clic_casse(ui):
    """Double-appui → commande MA3 : la casse est corrigée, comme _post_assign.

    🐛 `_post_double_clic` n'appliquait pas `core.corriger_casse()`,
    contrairement à `_post_assign` : un mot-clé MA3 mal capitalisé
    (« saveshow » au lieu de « SaveShow ») était stocké TEL QUEL et échoue en
    SILENCE à l'exécution. La commande de double-appui part justement en OSC
    direct (jamais par une frappe clavier relayée — voir
    docs/KEYBOARD_MAPPING.md, section « Double-appui → commande MA3 ») : elle
    est exactement aussi exposée à ce piège qu'une assignation normale.
    """
    section("59. Double-appui → commande MA3 : casse corrigée")
    import wing_handler

    class _FauxHandler:
        def _json(self, obj, code=200):
            pass

    sauve_profil = json.loads(json.dumps(etat.E.PROFILE))
    try:
        etat.E.PROFILE.setdefault("double_clic", {})
        wing_handler.Handler._post_double_clic(
            _FauxHandler(), {"token": "Menu", "commande": "saveshow"})
        obtenu = etat.E.PROFILE.get("double_clic", {}).get("Menu")
        if obtenu != "SaveShow":
            echec("la casse n'est pas corrigée avant enregistrement",
                  f"stocké : {obtenu!r} (attendu « SaveShow »)")
        else:
            ok("« saveshow » corrigé en « SaveShow » avant stockage, "
               "comme pour _post_assign")

        # Une commande déjà bien capitalisée ne doit RIEN changer d'autre.
        wing_handler.Handler._post_double_clic(
            _FauxHandler(), {"token": "Menu", "commande": "Highlight"})
        if etat.E.PROFILE["double_clic"].get("Menu") != "Highlight":
            echec("une commande déjà correcte a été altérée",
                  repr(etat.E.PROFILE["double_clic"].get("Menu")))
    except Exception as e:
        echec("le contrôle double-appui/casse a levé une exception",
              f"{type(e).__name__}: {e}")
    finally:
        etat.E.PROFILE.clear()
        etat.E.PROFILE.update(sauve_profil)
