#!/usr/bin/env python3
"""
smoke_faders.py — Wing Bridge
==============================
Domaine faders/encodeurs du test de fumée : mots-clés MA3 des faders et des
roues, symétrie appui/relâchement des executors, types de fader documentés,
remontée d'observation des roues, application d'un groupe d'encodeurs. Voir
smoke_core.py pour ok/echec/note/section/_page.
"""

import etat
import json
import re
from pathlib import Path

from smoke_core import HERE, ok, echec, note, section, _page, _poster


def _catalogue_i18n():
    """Concat de toutes les valeurs de locales/fr.json — pour les contrôles qui
    lisaient des chaînes du balisage/JS déplacées dans le catalogue i18n."""
    p = HERE / "locales" / "fr.json"
    if not p.is_file():
        return ""
    try:
        return "\n".join(v for v in json.loads(p.read_text(encoding="utf-8")).values()
                         if isinstance(v, str))
    except Exception:
        return ""


# Contrôle sauté si MA3 n'est pas installé sur cette machine.

def _attributs_ma3():
    """Noms d'attributs valides, lus dans le MA3 installé le plus récent."""
    base = Path.home() / "MALightingTechnology"
    if not base.is_dir():
        return None, None
    xmls = sorted(base.glob("gma3_*/shared/resource/attribute_definitions.xml"))
    if not xmls:
        return None, None
    src = xmls[-1]
    texte = src.read_text(encoding="utf-8", errors="replace")
    noms = set(re.findall(r'<Attribute\b[^>]*?\bName="([^"]*)"', texte))
    return (noms or None), src


def test_attributs(wb, wv):
    section("8. Attributs d'encodeur reconnus par MA3")
    valides, src = _attributs_ma3()
    if not valides:
        note("MA3 introuvable sur cette machine — contrôle sauté")
        return

    def _proche(attr):
        p = sorted(n for n in valides if n.lower().startswith(str(attr).lower()))
        return f" — vouliez-vous « {p[0]} » ?" if p else ""

    # a) les groupes par défaut
    mauvais = []
    for gi, groupe in enumerate(getattr(wb, "ENC_GROUPS", [])):
        for i, attr in enumerate(groupe):
            if attr and attr not in valides:
                mauvais.append(f"groupe {gi+1}, roue {i+1} : « {attr} »" + _proche(attr))
    if mauvais:
        echec(f"{len(mauvais)} attribut(s) d'encodeur inexistant(s) dans MA3",
              "\n".join(mauvais) + f"\n(référence : {src})")
    else:
        n = sum(1 for g in wb.ENC_GROUPS for a in g if a)
        ok(f"{n} attributs d'encodeur valides ({len(valides)} connus de MA3)")

    # b) la liste de repli montrée quand MA3 n'est pas sur la machine.
    # Elle est écrite à la main : sans ce contrôle elle pourrait proposer
    # des noms faux — exactement le bug qu'elle est censée éviter.
    # (Vécu : « ColorRGB_A » et « ColorMacro1 », inventés de bonne foi.)
    repli = getattr(wv, "ATTRS_REPLI", None)
    if repli is None:
        note("liste de repli introuvable (wing_ui.ATTRS_REPLI) — contrôle sauté")
        return
    faux = [f"{grp} : « {n} »" + _proche(n)
            for grp, noms in repli for n in noms if n not in valides]
    if faux:
        echec(f"{len(faux)} nom(s) inexistant(s) dans la liste de repli",
              "\n".join(faux))
    else:
        ok(f"liste de repli valide ({sum(len(n) for _, n in repli)} noms)")


# ── Les mots-clés de fader existent vraiment dans MA3 ────────────────────────
#
# Même famille de risque que les attributs d'encodeur : un mot-clé faux part
# en OSC sans erreur et MA3 refuse en silence. La source est le manuel installé
# avec MA3 (pages keyword_fader*.html) — donc à jour avec la version installée.
#
# Le contrôle marche dans les DEUX sens :
#   • un mot-clé qu'on envoie et que MA3 ne connaît pas → échec ;
#   • un mot-clé Fader* que MA3 connaît et qu'on n'offre pas → note.
# Le second est là pour une version future de MA3 : sans lui, on découvrirait
# la nouveauté par hasard, des mois plus tard.

def test_faders(wv):
    section("9. Mots-clés de fader reconnus par MA3")
    try:
        d = wv.ma3_fader_functions()
    except Exception as e:
        echec("ma3_fader_functions() échoue", f"{type(e).__name__}: {e}")
        return
    if d["source"] != "ma3":
        note("manuel MA3 introuvable sur cette machine — contrôle sauté")
        return
    faux = [f"{f['libelle']} → « {f['motcle']} »"
            for f in d["fonctions"] if f["confirme"] is False]
    if faux:
        echec(f"{len(faux)} mot(s)-clé(s) de fader inexistant(s) dans MA3",
              "\n".join(faux) + f"\n(référence : {d['chemin']})")
    else:
        n = sum(1 for f in d["fonctions"] if f["confirme"] is True)
        ok(f"{n} mots-clés de fader confirmés (manuel {d['version'] or '?'})")
    if d["manquants"]:
        note("MA3 connaît des mots-clés Fader* non proposés par Wing Bridge : "
             + ", ".join(d["manquants"]))


# ── L'appui et le relâchement d'un executor suivent la MÊME règle ────────────
#
# 🐛 Ce contrôle existe à cause d'un bug trouvé à la relecture, invisible
# pendant des semaines et présent dans le mode PAR DÉFAUT (console éteinte) :
# le relâchement passait par token_selon_ma3, l'appui envoyait le texte brut
# du profil. Les deux moitiés d'un même geste ne suivaient pas la même règle.
#
# Conséquence concrète : profil réglé sur « Flash », MA3 sur « Go+ » →
# l'appui envoyait « Flash On », le relâchement n'envoyait rien, et
# l'executor restait BLOQUÉ ALLUMÉ. Rien dans le journal ne le disait.
#
# On rejoue donc un appui-relâchement complet, sonde MA3 simulée, et on
# vérifie l'appariement. Aucun matériel, aucun réseau : tout est en mémoire.

def test_executor_symetrie(wv):
    section("12. Appui/relâchement d'executor — même règle des deux côtés")
    envoyes = []

    class _OSCespion:
        def send_message(self, addr, valeur):
            envoyes.append(valeur)

    # Sonde simulée : deux executors dont la fonction MA3 CONTREDIT le profil.
    # C'est le seul cas qui distingue « on suit MA3 » de « on suit le profil ».
    faux_etat = {
        "actif": True, "page": {"no": 1, "nom": "Page 1"}, "executors": [
            # MA3 dit Flash (maintenu) ; le profil dit Go+ (coup unique)
            {"no": 105, "nom": "Spots", "fader": 50.0,
             "fonction": "Master", "touche": "Flash", "tourne": False},
            # MA3 dit Go+ (coup unique) ; le profil dit Flash (maintenu)
            {"no": 106, "nom": "Contres", "fader": 0.0,
             "fonction": "Master", "touche": "Go+", "tourne": False},
        ]}

    sauve_osc, sauve_etat = etat.E.OSC, wv.ma3_etat
    sauve_console = wv.console_helper_alive
    sauve_profil = json.loads(json.dumps(etat.E.PROFILE))
    try:
        etat.E.OSC = _OSCespion()
        wv.ma3_etat = lambda: faux_etat
        # Assistant clavier ABSENT → repli OSC pur (le seul repli qui subsiste)
        wv.console_helper_alive = lambda: False
        etat.E.STATE["cmd_buf"] = ""
        etat.E.PROFILE["buttons"]["0x7c"] = "Go+ Executor 105"
        etat.E.PROFILE["executor_ref"]["0x7c"] = "Executor 105"
        etat.E.PROFILE["buttons"]["0x7d"] = "Flash On Executor 106"
        etat.E.PROFILE["executor_ref"]["0x7d"] = "Executor 106"

        def geste(btn):
            envoyes.clear()
            wv._btn_last_event.clear()        # neutralise l'anti-rebond
            wv.DERNIER_APPUI.clear()          # et la détection de double appui
            wv.handle_button_bridge(btn)
            wv._btn_last_event.clear()
            wv.handle_button_release(btn)
            return list(envoyes)

        cas = [
            (0x7c, ["Flash On Executor 105", "Flash Off Executor 105"],
             "MA3 réglé sur Flash, profil sur Go+ : la paire On/Off doit être "
             "complète, sinon l'executor reste allumé"),
            (0x7d, ["Go+ Executor 106"],
             "MA3 réglé sur Go+, profil sur Flash : un seul envoi à l'appui, "
             "rien au relâchement"),
        ]
        for btn, attendu, pourquoi in cas:
            obtenu = geste(btn)
            if obtenu == attendu:
                ok(f"0x{btn:02x} : {' + '.join(obtenu) or '(rien)'}")
            else:
                echec(f"0x{btn:02x} : appui/relâchement incohérents",
                      f"attendu : {attendu}\nobtenu  : {obtenu}\n{pourquoi}")
    except Exception as e:
        echec("le contrôle appui/relâchement a levé une exception",
              f"{type(e).__name__}: {e}")
    finally:
        etat.E.OSC, wv.ma3_etat = sauve_osc, sauve_etat
        wv.console_helper_alive = sauve_console
        etat.E.PROFILE.clear()
        etat.E.PROFILE.update(sauve_profil)
        wv._btn_last_event.clear()
        wv.DERNIER_APPUI.clear()


# ── Tout type de fader proposé par l'interface est documenté ─────────────────
#
# La liste déroulante du HTML et le tableau de référence affiché juste en
# dessous sont écrits à deux endroits différents. Ils avaient divergé : le
# type « selected » (Master de la séquence sélectionnée) était proposé au
# choix sans figurer nulle part dans le tableau — l'utilisateur pouvait le
# choisir sans trouver la moindre explication de ce qu'il fait.

def test_types_fader_documentes(wv, html):
    section("13. Types de fader proposés vs documentés")
    # La liste est construite en JS (loadProfile) et son gabarit HTML est passé
    # dans le catalogue i18n (ui.faders.item) : on cherche dans le balisage, le
    # JS ET les valeurs de fr.json.
    bloc = re.search(r"<select class='fkind'>(.*?)</select>",
                     _page(html) + "\n" + _catalogue_i18n(), re.S)
    if not bloc:
        echec("liste déroulante des types de fader introuvable",
              "le gabarit du fader a-t-il changé, ou ce contrôle ne regarde-t-il "
              "plus au bon endroit ? Dans les deux cas il ne garde plus rien")
        return
    proposes = set(re.findall(r"value='([\w]+)'", bloc.group(1)))
    documentes = set(getattr(wv, "FADER_FUNC_KINDS", ()))
    orphelins = sorted(proposes - documentes)
    fantomes = sorted(documentes - proposes)
    if orphelins:
        echec(f"{len(orphelins)} type(s) proposé(s) dans l'interface mais "
              f"absent(s) du tableau de référence", ", ".join(orphelins))
    else:
        ok(f"{len(proposes)} types proposés, tous documentés")
    if fantomes:
        note("documentés mais non proposés dans la liste : " + ", ".join(fantomes))

    # ── libellé/description de chaque type au catalogue i18n (fr + en) ───────
    #
    # `wing_ma3.ma3_fader_functions()` résout `fader_func.<kind>.nom`/`.desc`
    # par CONCATÉNATION (f-string) : invisible pour le contrôle (g) de
    # test_i18n, qui ne voit que des clés LITTÉRALES écrites en dur. Sans ce
    # contrôle dédié, une clé oubliée renverrait la clé brute (ou le repli fr)
    # à l'écran, en silence.
    try:
        fr = json.loads((HERE / "locales" / "fr.json").read_text(encoding="utf-8"))
        en = json.loads((HERE / "locales" / "en.json").read_text(encoding="utf-8"))
    except Exception as e:
        note(f"catalogue i18n illisible — textes de fader_func.* non vérifiés ({e})")
        fr = en = None
    if fr is not None:
        manque = []
        for kind in sorted(documentes):
            for champ in ("nom", "desc"):
                cle = f"fader_func.{kind}.{champ}"
                if cle not in fr:
                    manque.append(f"{cle} (absente de fr.json)")
                if cle not in en:
                    manque.append(f"{cle} (absente de en.json)")
        if "fader_func.valeur" not in fr:
            manque.append("fader_func.valeur (absente de fr.json)")
        if "fader_func.valeur" not in en:
            manque.append("fader_func.valeur (absente de en.json)")
        if manque:
            echec(f"{len(manque)} clé(s) fader_func.* absente(s) du catalogue",
                  ", ".join(manque[:15]))
        else:
            ok(f"les {len(documentes)} types ont leur libellé ET leur "
               f"description au catalogue (fr + en)")

    # Les deux tables de verbes maintenus doivent rester d'accord : elles
    # décrivaient la même notion sous des noms opposés (cf. wing_ui.py).
    ui = getattr(wv, "MAINTENUES_UI", None)
    ma3 = getattr(wv, "MA3_VERBES_MAINTENUS", None)
    if ui is None or ma3 is None:
        note("tables des verbes maintenus introuvables — contrôle sauté")
    elif not {v.lower() for v in ui} <= ma3:
        echec("MAINTENUES_UI contient un verbe absent de MA3_VERBES_MAINTENUS",
              f"{sorted(ui)} vs {sorted(ma3)}")
    else:
        ok(f"verbes maintenus cohérents ({', '.join(sorted(ui))})")


# ── Les roues suivent l'Encoder Bar de MA3 ────────────────────────────────────
#
# 🎯 Besoin : « connaître là où on est, et que les roues prennent le pas sur
# ce qu'il y a à l'écran ». PILOTAGE RÉEL sous `SETTINGS["encodeurs_ma3"]`
# (défaut False).
#
# Une 1re version déduisait les roues d'une table GLOBALE feature →
# attributs ; réfutée (chaque projecteur a SES attributs, RVB ≠ CMJ). La sonde v6 lit les vrais canaux du projecteur sélectionné
# (`SelectionFirst()` uniquement — sélection mélangée = limitation connue).
# `ma3_encodeurs()` continue de ne faire QUE REMONTER ce que la sonde voit ;
# la décision de pilotage est dans `enc_attr_selon_ma3()` (wing_faders.py),
# testée séparément plus bas (cas e).

def test_encodeurs_ma3(wv, html):
    section("21. Roues : observation ET suivi de l'Encoder Bar")
    sauve = wv.ma3_etat
    try:
        # a) la sonde répond → l'observation est exposée fidèlement.
        # 🎯 Observation seule (étape 0) : chaque canal porte aussi
        # `subattribut` (h.SUBATTRIBUTE) et `index` (h.INDEX), à côté de
        # `nom` (h.name) — voir wingbridge.lua::lire_encodeurs pour le
        # pourquoi (l'exemple officiel de GetUIChannels lit SUBATTRIBUTE,
        # pas .name). `pilote` reflète le réglage réel (False ici, par
        # défaut — cas e ci-dessous vérifie le cas True).
        wv.ma3_etat = lambda: {"actif": True, "encodeurs": {
            "feature": "PanTilt", "attribut": "Tilt", "fixture": "Spot RVB",
            "selection": 3,
            "canaux": [{"nom": "Pan", "subattribut": "Pan", "index": 0},
                       {"nom": "Tilt", "subattribut": "Tilt", "index": 1},
                       {"nom": "ColorRGB_R",
                        "subattribut": "ColorRGB_R", "index": 7}]}}
        e = wv.ma3_encodeurs()
        # `feature_reel` (observation Feature/ordre) est
        # lu dans le VRAI attribute_definitions.xml installé — on interroge
        # la même fonction plutôt que de figer une valeur qui casserait sur
        # une machine sans MA3 installé (comme `test_attributs`, sauté dans
        # ce cas — voir plus haut dans ce fichier).
        fpa = wv.wing_ma3._feature_par_attribut()
        attendu = [{"nom": "Pan", "subattribut": "Pan", "index": 0,
                    "feature_reel": fpa.get("Pan")},
                   {"nom": "Tilt", "subattribut": "Tilt", "index": 1,
                    "feature_reel": fpa.get("Tilt")},
                   {"nom": "ColorRGB_R", "subattribut": "ColorRGB_R", "index": 7,
                    "feature_reel": fpa.get("ColorRGB_R")}]
        if not e["actif"]:
            echec("l'observation ne s'active pas alors que la sonde répond")
        elif e.get("pilote") != bool(etat.E.SETTINGS.get("encodeurs_ma3", False)):
            echec("« pilote » ne reflète pas SETTINGS['encodeurs_ma3']",
                  f"obtenu {e.get('pilote')}")
        elif e["canaux"] != attendu:
            echec("les attributs du projecteur ne sont pas remontés fidèlement",
                  f"obtenu {e['canaux']}")
        else:
            noms = [c["nom"] for c in e["canaux"]]
            ok(f"observation remontée : {e['fixture']} → {noms}")

        # b) rien de sélectionné → note explicite, aucune invention.
        wv.ma3_etat = lambda: {"actif": True, "encodeurs": {
            "feature": None, "attribut": None, "fixture": None,
            "selection": 0, "canaux": [], "note": "aucune fixture selectionnee"}}
        e = wv.ma3_encodeurs()
        if e["canaux"]:
            echec("des attributs remontent sans sélection", str(e["canaux"]))
        else:
            ok("sans sélection : aucun attribut inventé")

        # c) sonde absente → aucune donnée.
        wv.ma3_etat = lambda: {"actif": False}
        e = wv.ma3_encodeurs()
        if e["actif"]:
            echec("l'observation s'active sans sonde")
        else:
            ok("sans sonde, aucune donnée d'encodeur")

        # d) 🐛 LE CONTRÔLE QUI MANQUAIT. « majEncMa3 » lisait
        # « e.roues », renommé « e.canaux » côté serveur : .map() sur undefined
        # levait, poll() sautait dans son catch, et le HEADER ENTIER
        # disparaissait (plus de numéro de build, pastilles rouges). Le JS
        # passait le contrôle de SYNTAXE — c'est un décalage de CHAMPS entre
        # les deux fichiers qu'il faut attraper. On vérifie que chaque « e.X »
        # lu par majEncMa3 est bien exposé par ma3_encodeurs().
        m = re.search(r"function majEncMa3.*?\n\}", _page(html), re.S) if html else None
        if not m:
            note("majEncMa3 introuvable dans le HTML — contrôle sauté")
        else:
            lus = set(re.findall(r"\be\.(\w+)", m.group(0)))
            wv.ma3_etat = lambda: {"actif": True, "encodeurs": {
                "feature": "x", "attribut": "y", "fixture": "z",
                "selection": 1, "canaux": [{"nom": "Pan"}], "note": None}}
            exposes = set(wv.ma3_encodeurs().keys())
            absents = sorted(lus - exposes)
            if absents:
                echec(f"majEncMa3 lit {len(absents)} champ(s) que le serveur "
                      f"n'expose plus — poll() planterait et le header "
                      f"disparaîtrait", ", ".join("e." + c for c in absents))
            else:
                ok(f"les {len(lus)} champs d'encodeur lus par le JS existent "
                   f"côté serveur")

        # e) 🎯 La DÉCISION de pilotage, enc_attr_selon_ma3() (wing_faders.py).
        # Doit lire `subattribut`, JAMAIS `nom` — vérifié en direct sur une
        # vraie sélection : `nom` valait « Spot 1 » (le FIXTURE) pour les 32
        # canaux, sans exception. Un retour à `nom` enverrait le nom du
        # fixture à MA3 comme s'il s'agissait d'un attribut — silencieux,
        # comme le bug Focus/Focus1.
        sauve_settings = etat.E.SETTINGS
        sauve_ma3_encodeurs = wv.ma3_encodeurs
        try:
            etat.E.SETTINGS = dict(sauve_settings)
            configure = ["Pan", "Tilt", "Zoom", "Focus1"]

            # e1) suivi désactivé (défaut) → groupe configuré intact.
            etat.E.SETTINGS["encodeurs_ma3"] = False
            if wv.enc_attr_selon_ma3(configure) != configure:
                echec("suivi désactivé : le groupe configuré est modifié")
            else:
                ok("suivi désactivé : le groupe configuré part tel quel")

            # e2) suivi activé mais sonde muette → repli sur le configuré,
            # même règle que kind_selon_ma3/token_selon_ma3 pour les faders.
            etat.E.SETTINGS["encodeurs_ma3"] = True
            wv.ma3_etat = lambda: {"actif": False}
            if wv.enc_attr_selon_ma3(configure) != configure:
                echec("sonde absente : le suivi ne retombe pas sur le configuré")
            else:
                ok("sonde absente : repli sur le groupe configuré")

            # e3) suivi activé, sonde active, sélection MA3 vide → rien.
            wv.ma3_etat = lambda: {"actif": True}
            wv.ma3_encodeurs = lambda: {"actif": True, "pilote": True,
                                         "selection": 0, "canaux": []}
            if wv.enc_attr_selon_ma3(configure) != [None, None, None, None]:
                echec("sélection MA3 vide : une valeur part quand même")
            else:
                ok("sélection MA3 vide : rien n'est envoyé, comme sur une console")

            # e4) suivi activé, vraie sélection → les VRAIS attributs
            # (subattribut) partent, jamais le nom du fixture.
            wv.ma3_encodeurs = lambda: {"actif": True, "pilote": True,
                "selection": 1, "canaux": [
                    {"nom": "Spot 1", "subattribut": "Pan", "index": 14},
                    {"nom": "Spot 1", "subattribut": "Tilt", "index": 15},
                    {"nom": "Spot 1", "subattribut": "ColorRGB_R", "index": 16}]}
            resultat = wv.enc_attr_selon_ma3(configure)
            if resultat != ["Pan", "Tilt", "ColorRGB_R", None]:
                echec("le suivi n'envoie pas les vrais attributs (subattribut)",
                      f"obtenu {resultat}")
            else:
                ok(f"suivi actif, sélection réelle : {resultat}")
        finally:
            etat.E.SETTINGS = sauve_settings
            wv.ma3_encodeurs = sauve_ma3_encodeurs
    except Exception as e:
        echec("le contrôle des roues a levé une exception",
              f"{type(e).__name__}: {e}")
    finally:
        wv.ma3_etat = sauve


def test_groupe_encodeur_applique(ui):
    """Éditer un groupe de roues s'applique-t-il tout de suite ?

    🐛 Signalé : « l'onglet Encodeurs ne s'applique pas au réel ». Reproduit —
    clic sur la roue 3, édition du groupe 3,
    « Enregistrer » → les roues SAUTAIENT sur le groupe par défaut. Le réglage
    était enregistré mais les roues jouaient autre chose.

    L'app retenait les VALEURS des 4 roues, jamais QUEL GROUPE est actif :
    `reset_enc_attr()` n'avait donc que le groupe par défaut comme option.

    ⚠️ Bug PRÉEXISTANT, resté invisible parce qu'il ne
    casse rien de bruyant : il change de groupe EN SILENCE.

    ⚠️ Ce contrôle vérifie AUSSI le sens inverse — un chargement de profil doit,
    lui, repartir du groupe par défaut. Corriger le premier cas en cassant le
    second serait invisible autrement.

    🎯 Le contrôle couvre aussi les groupes 5-8, atteints par un DOUBLE-clic
    sur la roue (`ENC_GROUPES_SIMPLE` = 4). Il couvre un angle mort : jusqu'ici,
    seule la PRÉSENCE de la table
    `double_clic` était vérifiée (`smoke_profils.py`), jamais la FENÊTRE de
    temporisation elle-même. Ici, on simule un vrai enchaînement de deux
    appuis physiques — dans la fenêtre (double), puis hors fenêtre (redevient
    simple) — en reculant les horodatages plutôt qu'en dormant réellement.
    """
    section("38. Éditer un groupe de roues s'applique tout de suite")
    import io, json as _j
    sauv = (etat.E.PROFILE.get("enc_groups"), etat.E.PROFILE.get("enc_default_group"),
            etat.E.PROFILE.get("buttons"), etat.E.STATE.get("enc_attr"),
            etat.E.STATE.get("enc_group"), ui.log, ui.console_helper_alive,
            dict(ui.DERNIER_APPUI), dict(ui._btn_last_event))
    try:
        ui.log = lambda *a, **k: None
        etat.E.PROFILE["enc_groups"] = [["A1", "A2", "A3", "A4"], ["B1", "B2", "B3", "B4"],
                                    ["C1", "C2", "C3", "C4"], ["D1", "D2", "D3", "D4"]]
        etat.E.PROFILE["enc_default_group"] = 1          # défaut = groupe 2
        ui.appliquer_groupe_enc(2)                   # l'utilisateur clique la roue 3
        if etat.E.STATE["enc_attr"] != ["C1", "C2", "C3", "C4"]:
            echec("un clic de roue n'active pas son groupe",
                  str(etat.E.STATE["enc_attr"])); return

        neufs = [list(g) for g in etat.E.PROFILE["enc_groups"]]
        neufs[2] = ["Zoom", "Iris", "Frost1", "Prism1"]
        h = ui.Handler.__new__(ui.Handler); h.path = "/api/encoders"
        corps = _j.dumps({"groups": neufs, "default": 1,
                          "step": etat.E.PROFILE["enc_step"]}).encode()
        h.rfile = io.BytesIO(corps)
        # X-Wing-Jeton : comme la vraie interface (voir test_jeton_api).
        h.headers = {"Content-Length": str(len(corps)),
                     "Origin": "http://127.0.0.1:8765", "Host": "127.0.0.1:8765",
                     "X-Wing-Jeton": ui.API_JETON}
        h._json = lambda d, code=200: None
        h.do_POST()

        if etat.E.STATE["enc_attr"] != neufs[2]:
            echec("éditer le groupe ACTIF ne s'applique pas aux roues",
                  f"roues = {etat.E.STATE['enc_attr']}, attendu {neufs[2]} — "
                  f"l'utilisateur enregistre et les roues jouent autre chose")
            return
        ok("le groupe édité est appliqué aux roues sans changer de groupe")

        # Sens inverse : un chargement de profil repart du groupe PAR DÉFAUT.
        ui.reset_enc_attr()
        if etat.E.STATE["enc_attr"] != ["B1", "B2", "B3", "B4"]:
            echec("un chargement de profil ne repart pas du groupe par défaut",
                  str(etat.E.STATE["enc_attr"]))
            return
        ok("un chargement de profil repart bien du groupe par défaut")

        # ── Double-clic sur une roue → groupes 5-8 ─────────────────────────
        etat.E.PROFILE["enc_groups"] = [
            ["A1", "A2", "A3", "A4"], ["B1", "B2", "B3", "B4"],
            ["C1", "C2", "C3", "C4"], ["D1", "D2", "D3", "D4"],
            ["E1", "E2", "E3", "E4"], ["F1", "F2", "F3", "F4"],
            ["G1", "G2", "G3", "G4"], ["H1", "H2", "H3", "H4"],
        ]
        btn = 0x77                     # code arbitraire, pas un vrai bouton
        key = f"0x{btn:02x}"
        # RÉASSIGNATION, pas mutation en place : `sauv` garde une référence
        # nue vers l'ancien dict `buttons` — le muter directement l'aurait
        # corrompu, rendant la restauration en `finally` illusoire.
        etat.E.PROFILE["buttons"] = dict(etat.E.PROFILE["buttons"])
        etat.E.PROFILE["buttons"][key] = "__ENC1_PUSH__"
        ui.console_helper_alive = lambda: False     # mode bridge, le cas normal
        ui.DERNIER_APPUI.pop(btn, None)
        ui._btn_last_event.pop((btn, "press"), None)
        fenetre = ui.wing_boutons.DOUBLE_APPUI_S

        # a) un clic SEUL → groupe 1 (index 0), comportement inchangé.
        ui.handle_button_bridge(btn)
        if etat.E.STATE["enc_attr"] != ["A1", "A2", "A3", "A4"]:
            echec("un clic simple sur la roue n'active pas le groupe 1",
                  str(etat.E.STATE["enc_attr"]))
        else:
            ok("clic simple sur la roue → groupe 1 (comportement inchangé)")

        # b) un DEUXIÈME clic, DANS la fenêtre de double-clic (recul simulé,
        # pas une vraie pause) → groupe 5, pas un second groupe 1.
        recul = fenetre / 2
        ui.DERNIER_APPUI[btn] -= recul
        ui._btn_last_event[(btn, "press")] -= recul
        ui.handle_button_bridge(btn)
        if etat.E.STATE["enc_attr"] != ["E1", "E2", "E3", "E4"]:
            echec("un double-clic dans la fenêtre n'active pas le groupe 5",
                  f"obtenu {etat.E.STATE['enc_attr']} (fenêtre = {fenetre*1000:.0f} ms, "
                  f"recul simulé = {recul*1000:.0f} ms)")
        else:
            ok(f"double-clic dans la fenêtre ({recul*1000:.0f} ms < "
               f"{fenetre*1000:.0f} ms) → groupe 5")

        # c) un TROISIÈME clic, HORS fenêtre (recul simulé > DOUBLE_APPUI_S)
        # → redevient un clic SIMPLE (groupe 1), pas un 3ᵉ palier ni un
        # groupe 5 qui reste collé. « pas de triple déclenchement » (le code)
        # remet DERNIER_APPUI à 0.0 après un double — seul l'anti-rebond
        # (_btn_last_event) doit donc encore être reculé ici.
        ui._btn_last_event[(btn, "press")] -= (fenetre + 0.1)
        ui.handle_button_bridge(btn)
        if etat.E.STATE["enc_attr"] != ["A1", "A2", "A3", "A4"]:
            echec("un clic hors fenêtre de double-clic ne redevient pas un "
                  "clic simple", f"obtenu {etat.E.STATE['enc_attr']}")
        else:
            ok("clic hors fenêtre de double-clic → redevient un clic simple "
               "(groupe 1), pas de troisième palier")
    finally:
        (etat.E.PROFILE["enc_groups"], etat.E.PROFILE["enc_default_group"],
         etat.E.PROFILE["buttons"], etat.E.STATE["enc_attr"], etat.E.STATE["enc_group"],
         ui.log, ui.console_helper_alive) = sauv[:7]
        ui.DERNIER_APPUI.clear(); ui.DERNIER_APPUI.update(sauv[7])
        ui._btn_last_event.clear(); ui._btn_last_event.update(sauv[8])


# ── Auto-rattrapage au repos : un fader déjà en place ne clignote pas ─────────
#
# 🐛 Bug signalé : aller-retour de page
# 1 → 2 → 1, les boutons clignotaient encore AU RETOUR alors que rien n'avait
# bougé. Cause : `pickup_page_changee` ré-arme TOUS les faders à chaque
# changement de page, et un fader au repos ne se re-rattrape que s'il BOUGE.
# Correctif : `pickup_verifier_repos(faders_phys)` rattrape sans mouvement un
# fader armé dont la position physique RÉELLE coïncide déjà avec la valeur MA3.
#
# Ce contrôle rejoue le cas EN MÉMOIRE (aucun matériel, aucun réseau) et vérifie
# les trois propriétés sans lesquelles le correctif ne vaut rien — retirer le
# bloc d'auto-rattrapage de wing_faders fait passer (a) au ROUGE :
#   (a) coïncide déjà        → rattrapé SANS mouvement ;
#   (b) position différente  → reste armé (sinon le contrôle serait creux) ;
#   (c) sans position physique (faders_phys=None) → ancien comportement.

def test_pickup_auto_repos(ui):
    section("45. Auto-rattrapage au repos — déjà en place, sans mouvement")
    import wing_faders as wf

    sauv = {"pickup": etat.E.SETTINGS.get("fader_pickup", True),
            "faders": etat.E.PROFILE.get("faders"),
            "etat": ui.ma3_etat, "log": ui.log,
            "pickup_dict": dict(etat.E.PICKUP),
            "page": dict(wf.PICKUP_PAGE),
            "inst_t": wf._FADERS_INSTANTANE["t"]}
    try:
        etat.E.SETTINGS["fader_pickup"] = True
        ui.log = lambda *a, **k: None
        etat.E.PROFILE["faders"] = [{"kind": "executor", "exec": 101, "suivre": True}]
        wf._FADERS_INSTANTANE["t"] = 0.0        # forcer le rafraîchissement du cache
        wf.PICKUP_PAGE["no"] = 1                 # pas de changement de page en cours
        ui.ma3_etat = lambda: {"actif": True, "page": {"no": 1},
                               "executors": [{"no": 101, "fader": 50}]}
        raw_match = round(50 / 100 * 1023)       # 512 → 50 % : coïncide avec MA3
        raw_diff  = round(90 / 100 * 1023)       # 921 → 90 % : ne coïncide pas

        def arme():
            etat.E.PICKUP.clear()
            etat.E.PICKUP[0] = {"pris": False, "signe": 0, "bouge": 0.0, "envoye": None}

        # (a) déjà en place → doit être rattrapé SANS mouvement
        arme()
        ui.pickup_verifier_repos([raw_match])
        if not etat.E.PICKUP[0]["pris"]:
            echec("un fader déjà en place reste armé (clignoterait sans raison)",
                  "position physique = valeur MA3 (50 %), mais pickup_verifier_repos "
                  "ne l'a PAS rattrapé sans mouvement — régression du correctif "
                  "d'auto-rattrapage au repos (aller-retour de page 1→2→1)")
            return
        # (b) position différente → NE doit PAS se rattraper (contrôle non creux)
        arme()
        ui.pickup_verifier_repos([raw_diff])
        if etat.E.PICKUP[0]["pris"]:
            echec("un fader NON en place a été rattrapé à tort sans mouvement",
                  "position physique 90 % ≠ MA3 50 % : un vrai rattrapage doit "
                  "encore exiger le mouvement (traversée de la valeur)")
            return
        # (c) sans position physique fournie → ancien comportement (rien)
        arme()
        ui.pickup_verifier_repos()
        if etat.E.PICKUP[0]["pris"]:
            echec("auto-rattrapage déclenché sans position physique fournie",
                  "faders_phys=None doit garder l'ancien comportement, pour ne pas "
                  "surprendre un appelant qui ne passe pas les positions")
            return
        ok("un fader déjà en place est rattrapé sans mouvement ; sinon il reste "
           "armé ; `None` ne change rien")
    finally:
        etat.E.SETTINGS["fader_pickup"] = sauv["pickup"]
        etat.E.PROFILE["faders"] = sauv["faders"]
        ui.ma3_etat = sauv["etat"]
        ui.log = sauv["log"]
        etat.E.PICKUP.clear(); etat.E.PICKUP.update(sauv["pickup_dict"])
        wf.PICKUP_PAGE.clear(); wf.PICKUP_PAGE.update(sauv["page"])
        wf._FADERS_INSTANTANE["t"] = sauv["inst_t"]


def test_encodeurs_et_migration_casse_corrigees(ui):
    """Casse corrigée aux DEUX endroits qui la manquaient (audit Lot C,
    14/09/2026) — même piège que `_post_assign` (casse des COMMANDES), mais
    trouvé manquant ici :

      • `_post_encoders` (assignation manuelle d'un attribut de roue,
        `/api/encoders`) stockait le nom d'attribut BRUT : « dimmer » au lieu
        de « Dimmer » échoue en SILENCE sur `Attribute dimmer at + 1` — MA3
        refuse sur sa propre ligne de commande, la roue paraît morte ;
      • `migrate_profile()` — le SEUL point de passage commun au chargement
        d'un profil LOCAL et à l'import d'un profil reçu d'un COLLÈGUE (flux
        explicitement prévu, GUIDE_PROJET.md « distribuable ») — ne corrigeait
        RIEN : un profil importé tel quel, jamais réédité à la main dans
        l'UI, gardait ses fautes de casse pour toujours.

    ⚠️ Répertoire DISJOINT du reste : un nom d'ATTRIBUT ("Dimmer", "Pan"…)
    n'est PAS un mot-clé de COMMANDE — `corriger_casse_attribut()` cherche
    dans `ma3_attributes()`, jamais dans `ma3_motscles()` (wing_ma3.py).
    """
    section("61. Casse corrigée : assignation d'une roue + migration de profil")
    import json as _j
    import tempfile
    ennuis = []

    # (a) /api/encoders — assignation manuelle d'un attribut de roue.
    sauv_groups = _j.loads(_j.dumps(etat.E.PROFILE.get("enc_groups")))
    try:
        r = _poster(ui, "/api/encoders",
                    {"groups": [["dimmer", None, None, None]], "step": 1.0})
        if not r.get("ok"):
            ennuis.append(f"/api/encoders refuse une assignation valide : {r}")
        elif etat.E.PROFILE["enc_groups"][0][0] != "Dimmer":
            ennuis.append(
                "« dimmer » n'est pas corrigé en « Dimmer » par _post_encoders "
                f"(obtenu : {etat.E.PROFILE['enc_groups'][0][0]!r})")
    finally:
        etat.E.PROFILE["enc_groups"] = sauv_groups

    # (b) migrate_profile() — import d'un profil reçu d'un collègue.
    wm_ = ui.wm
    sauve_dir, sauve_log = wm_.PROFILE_DIR, ui.log
    try:
        d = Path(tempfile.mkdtemp())
        wm_.PROFILE_DIR = d
        ui.log = lambda *a, **k: None
        prof = wm_.new_profile_from_defaults()
        prof["name"] = "Wing mal capitalisée"
        prof["buttons"]["0x99"] = "go+ executor 105"
        prof["double_clic"]["Menu"] = "flash"
        prof["enc_groups"][0][0] = "dimmer"
        r = _poster(ui, "/api/profile/import",
                    {"nom": "mal-capitalisee.json", "contenu": prof})
        if not r.get("ok"):
            ennuis.append(f"import refusé à tort : {r}")
        else:
            sauvegarde = _j.loads((d / r["file"]).read_text(encoding="utf-8"))
            if sauvegarde["buttons"].get("0x99") != "Go+ Executor 105":
                ennuis.append(
                    "migrate_profile() ne corrige pas la casse d'un bouton "
                    f"importé (obtenu : {sauvegarde['buttons'].get('0x99')!r})")
            if sauvegarde["double_clic"].get("Menu") != "Flash":
                ennuis.append(
                    "migrate_profile() ne corrige pas la casse d'un "
                    f"double-appui importé (obtenu : {sauvegarde['double_clic'].get('Menu')!r})")
            if sauvegarde["enc_groups"][0][0] != "Dimmer":
                ennuis.append(
                    "migrate_profile() ne corrige pas la casse d'un attribut "
                    f"de roue importé (obtenu : {sauvegarde['enc_groups'][0][0]!r})")
    except Exception as e:
        ennuis.append(f"exception : {type(e).__name__}: {e}")
    finally:
        wm_.PROFILE_DIR, ui.log = sauve_dir, sauve_log

    if ennuis:
        echec("la casse n'est pas corrigée à tous les points d'entrée d'un profil",
              " ; ".join(ennuis))
    else:
        ok("« dimmer »/« go+ executor 105 »/« flash » corrigés en « Dimmer »/"
           "« Go+ Executor 105 »/« Flash », à l'assignation ET à l'import")
