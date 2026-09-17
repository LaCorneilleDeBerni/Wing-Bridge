#!/usr/bin/env python3
"""
smoke_profils.py — Wing Bridge
===============================
Domaine profils du test de fumée : schéma de profil, assistant de
configuration guidée, forme garantie par la migration, profil favori, import
de profil. Voir smoke_core.py pour ok/echec/note/section/_poster.
"""

import etat
import json

import wing_etat_materiel
from pathlib import Path

from smoke_core import ok, echec, note, section, _poster


def test_profil(wm):
    section("6. Schéma de profil")
    try:
        p = wm.new_profile_from_defaults()
    except Exception as e:
        echec("new_profile_from_defaults() échoue", f"{type(e).__name__}: {e}")
        return
    # Schéma réel d'un profil (cf. new_profile_from_defaults dans wing_mapper).
    # Si tu ajoutes une clé au profil, ajoute-la ICI aussi : c'est ce qui évite
    # qu'une nouvelle fonctionnalité parte sans être écrite dans les profils.
    attendus = ("name", "buttons", "executor_ref", "faders", "fader_noms",
                "enc_groups", "enc_default_group", "enc_step",
                "console_keys", "double_clic")
    manquants = [c for c in attendus if c not in p]
    if manquants:
        echec("clés absentes du profil par défaut", ", ".join(manquants))
    else:
        ok(f"profil par défaut complet ({len(p)} clés)")

    # Sérialisable en JSON : c'est ainsi qu'il est stocké sur disque
    try:
        json.dumps(p)
        ok("profil sérialisable en JSON")
    except Exception as e:
        echec("profil non sérialisable en JSON", e)

    # migrate_profile doit être IDEMPOTENTE : la migration tourne à chaque
    # ouverture de profil, elle ne doit jamais dériver d'une fois sur l'autre.
    try:
        un = wm.migrate_profile(json.loads(json.dumps(p)))
        deux = wm.migrate_profile(json.loads(json.dumps(un)))
        if un == deux:
            ok("migrate_profile idempotente")
        else:
            echec("migrate_profile N'EST PAS idempotente "
                  "(le profil dérive à chaque ouverture)")
    except Exception as e:
        echec("migrate_profile échoue", f"{type(e).__name__}: {e}")


def test_assistant(wv, wm):
    section("16. Assistant de configuration guidée")
    try:
        d = wv.assistant_liste()
    except Exception as e:
        echec("assistant_liste() échoue", f"{type(e).__name__}: {e}")
        return
    if not d["etapes"]:
        echec("l'assistant ne propose aucune étape")
        return

    # ⚠️⚠️ CE CONTRÔLE VÉRIFIAIT LA MAUVAISE CHOSE (corrigé depuis).
    #
    # Il se contentait de « le token est-il connu de l'app ? ». « Exec » l'était
    # — il figurait dans la table des raccourcis console — et l'assistant le
    # proposait donc tranquillement. Sauf que « Exec » n'est PAS un mot-clé
    # MA3 : la touche s'appelle Exec, le mot-clé est Executor. Le bouton
    # configuré était mort, et c'est un test manuel qui l'a vu, pas ce contrôle.
    #
    # La bonne question est : ce token peut-il ATTEINDRE MA3 ? Deux voies, il
    # en faut au moins une :
    #   • tous ses mots sont des mots-clés MA3  → part en OSC
    #   • il a un raccourci clavier non vide    → part en frappe
    # Sans aucune des deux, la touche ne fera jamais rien.
    mots_ma3 = set(wv.ma3_motscles()["mots"])
    raccourcis = wm.CONSOLE_KEY_DEFAULTS
    morts = []
    for e in d["etapes"]:
        if e["type"] != "cmd":
            continue
        v = e["valeur"]
        if not v[0].isalpha():                 # chiffres, « . », « + », « - »
            continue
        motcle = all(m in mots_ma3 for m in v.split())
        frappe = bool(raccourcis.get(v))
        if not motcle and not frappe:
            morts.append(v)
    if morts:
        echec(f"{len(morts)} étape(s) proposent une touche MORTE "
              f"(ni mot-clé MA3, ni raccourci clavier)", ", ".join(morts))
    else:
        ok(f"{d['total']} étapes, toutes atteignent MA3")

    # Les types d'assignation doivent être ceux que /api/assign accepte.
    types = {e["type"] for e in d["etapes"]}
    if not types <= {"cmd", "exec", "push"}:
        echec("type d'assignation inconnu dans l'assistant",
              ", ".join(sorted(types - {"cmd", "exec", "push"})))
    else:
        ok(f"types d'assignation valides ({', '.join(sorted(types))})")

    doublons = [v for v, n in
                __import__("collections").Counter(
                    (e["type"], e["valeur"]) for e in d["etapes"]).items() if n > 1]
    if doublons:
        echec("étapes en double dans l'assistant", str(doublons))
    else:
        ok("aucune étape en double")
    if d["ignores"]:
        note("tokens écartés faute d'être gérés : " + ", ".join(d["ignores"]))


def test_forme_profil(wm, wb, wv):
    section("18. Forme du profil garantie par la migration")
    n_faders = len(wb.FADER_EXEC)
    # 🐛 Groupes 5-8 au double-clic : « n_roues »
    # confondait deux nombres qui coïncidaient par hasard (4 groupes = 4
    # roues) — le nombre de GROUPES (len(ENC_GROUPS), maintenant 8) et le
    # nombre de roues PAR groupe (len(ENC_GROUPS[0]), toujours 4). Séparés
    # explicitement pour ne plus jamais reconfondre les deux.
    n_groupes = len(wb.ENC_GROUPS)
    n_roues = len(wb.ENC_GROUPS[0]) if wb.ENC_GROUPS else 4

    abimes = {
        "faders tronqués":      lambda p: p.update(faders=p["faders"][:3]),
        "enc_groups tronqués":  lambda p: p.update(enc_groups=[p["enc_groups"][0][:2]]),
        "groupe de départ hors plage": lambda p: p.update(enc_default_group=9),
        "clés du mauvais type": lambda p: p.update(faders={}, enc_groups=None),
    }
    for titre, casser in abimes.items():
        p = wm.new_profile_from_defaults()
        casser(p)
        try:
            q = wm.migrate_profile(json.loads(json.dumps(p)))
        except Exception as e:
            echec(f"migrate_profile plante sur « {titre} »",
                  f"{type(e).__name__}: {e}")
            continue
        soucis = []
        if len(q.get("faders", [])) < n_faders:
            soucis.append(f"{len(q.get('faders', []))} faders au lieu de {n_faders}")
        groupes = q.get("enc_groups", [])
        if len(groupes) < n_groupes:
            soucis.append(f"{len(groupes)} groupes au lieu de {n_groupes}")
        elif any(len(g) < n_roues for g in groupes):
            soucis.append(f"groupe trop court : {[len(g) for g in groupes]}")
        gi = q.get("enc_default_group")
        if not isinstance(gi, int) or not (0 <= gi < len(groupes)):
            soucis.append(f"groupe de départ hors plage ({gi})")
        if soucis:
            echec(f"« {titre} » n'est pas réparé", " ; ".join(soucis))
        else:
            ok(f"« {titre} » → {n_faders} faders, {n_groupes} groupes × {n_roues} roues")

    # Preuve par l'usage : le dernier fader doit être adressable sans lever.
    # C'est LE geste exact qui plantait dans la boucle USB.
    p = wm.new_profile_from_defaults()
    p["faders"] = p["faders"][:1]
    q = wm.migrate_profile(json.loads(json.dumps(p)))
    sauve_osc, sauve_profil = etat.E.OSC, json.loads(json.dumps(etat.E.PROFILE))

    class _Muet:
        def send_message(self, *a):
            pass

    try:
        etat.E.OSC = _Muet()
        etat.E.PROFILE.clear()
        etat.E.PROFILE.update(q)
        for i in range(n_faders):
            wv.send_fader(i, dict(q["faders"][i]), 500)
        ok(f"les {n_faders} faders d'un profil réparé sont adressables")
    except Exception as e:
        echec("send_fader lève encore sur un profil réparé",
              f"{type(e).__name__}: {e}")
    finally:
        etat.E.OSC = sauve_osc
        etat.E.PROFILE.clear()
        etat.E.PROFILE.update(sauve_profil)
        etat.E.FADER_LAST.clear()
        etat.E.FADER_T.clear()
        etat.E.FADER_ATTENTE.clear()


def test_profil_favori(ui):
    """Le profil favori se charge au démarrage — et ne bloque JAMAIS l'app.

    ⭐ Besoin : « possibilité de mettre un favori pour que l'app charge le mis
    en favori en priorité ».

    Le besoin est réel : **deux wings n'ont pas la même disposition** (ordre des
    faders, touches présentes ou remplacées, rôle de chaque roue). Redémarrer et
    retomber sur les défauts d'usine obligeait à recharger son profil à la main.

    ⚠️ Le point qui compte ici n'est pas « ça charge » mais **« ça ne casse
    jamais le démarrage »** : un favori supprimé, renommé ou corrompu doit être
    signalé et ignoré. Un réglage de confort qui empêche l'app de démarrer
    serait pire que pas de réglage du tout.
    """
    section("33. Profil favori — chargé au démarrage, jamais bloquant")
    import tempfile
    wm = ui.wm                      # le wing_mapper vu par wing_ui
    sauve_dir, sauve_fav = wm.PROFILE_DIR, etat.E.SETTINGS.get("profil_favori")
    sauve_profil = json.loads(json.dumps(etat.E.PROFILE))
    sauve_log, journal = ui.log, []
    ennuis = []
    try:
        d = Path(tempfile.mkdtemp())
        wm.PROFILE_DIR = d
        ui.log = lambda *a, **k: journal.append(str(ui._rendre_appel(*a, **k)))

        prof = wm.new_profile_from_defaults()
        prof["name"] = "Ma wing"
        prof["fader_noms"] = ["ZZTOP"] + list(prof.get("fader_noms", [])[1:])
        (d / "ma-wing.json").write_text(json.dumps(prof), encoding="utf-8")

        # 1. favori valide → chargé
        etat.E.SETTINGS["profil_favori"] = "ma-wing.json"
        etat.E.PROFILE.clear(); etat.E.PROFILE.update(wm.new_profile_from_defaults())
        ui.charger_favori()
        if etat.E.PROFILE.get("fader_noms", [""])[0] != "ZZTOP":
            ennuis.append("un favori valide n'est pas chargé")

        # 2. favori INTROUVABLE → signalé, oublié, pas d'exception
        journal.clear()
        etat.E.SETTINGS["profil_favori"] = "disparu.json"
        ui.charger_favori()
        if not any("introuvable" in l for l in journal):
            ennuis.append("un favori introuvable ne dit rien à l'utilisateur")
        if etat.E.SETTINGS.get("profil_favori"):
            ennuis.append("un favori introuvable reste enregistré (il rejouerait)")

        # 3. favori ILLISIBLE → signalé, app debout
        journal.clear()
        (d / "casse.json").write_text("{ ceci n'est pas du JSON", encoding="utf-8")
        etat.E.SETTINGS["profil_favori"] = "casse.json"
        ui.charger_favori()
        if not any("illisible" in l for l in journal):
            ennuis.append("un favori corrompu ne dit rien")

        # 4. aucun favori → la CONFIG SÛRE prend le relais.
        #
        # Voulu : « le profil défaut doit être chargé par défaut s'il n'y a
        # pas de profil favori sélectionné. » Sans favori, l'app démarrait sur
        # les défauts d'usine EN MÉMOIRE — corrects, mais ce n'est pas la
        # référence que l'utilisateur a figée.
        journal.clear()
        etat.E.SETTINGS["profil_favori"] = ""
        ref = ui.REFERENCE_FILE
        try:
            ui.REFERENCE_FILE = d / "__reference__.json"
            r = wm.new_profile_from_defaults()
            r["fader_noms"] = ["REFERENCE"] + list(r.get("fader_noms", [])[1:])
            ui.REFERENCE_FILE.write_text(json.dumps(r), encoding="utf-8")
            etat.E.PROFILE.clear(); etat.E.PROFILE.update(wm.new_profile_from_defaults())
            ui.charger_favori()
            if etat.E.PROFILE.get("fader_noms", [""])[0] != "REFERENCE":
                ennuis.append("sans favori, la config sûre n'est pas chargée")
            if not any("config sûre" in l for l in journal):
                ennuis.append("le chargement de la config sûre n'est pas annoncé")
        finally:
            ui.REFERENCE_FILE = ref
    except Exception as e:
        ennuis.append(f"exception : {type(e).__name__}: {e}")
    finally:
        ui.log = sauve_log
        wm.PROFILE_DIR = sauve_dir
        etat.E.SETTINGS["profil_favori"] = sauve_fav
        etat.E.PROFILE.clear(); etat.E.PROFILE.update(sauve_profil)

    if ennuis:
        echec("le profil favori se comporte mal", " ; ".join(ennuis))
    else:
        ok("favori chargé ; introuvable/corrompu/absent : signalé sans bloquer")


def test_import_profil(ui):
    """Importer un profil venu d'ailleurs — et refuser ce qui n'en est pas un.

    🔑 Signalé : « on ne peut pas ouvrir un profil dans un dossier ».
    `/api/profile/load` ne lit QUE dans le dossier des profils :
    un fichier reçu d'un collègue devait être déplacé à la main dans ~/Library
    (dossier caché) avant d'être utilisable.

    ⚠️ Le nom de fichier vient du NAVIGATEUR, donc de l'extérieur. Les trois
    refus testés ici comptent autant que l'import lui-même :
      • un JSON qui n'est pas un profil → rejeté AVANT d'atteindre la boucle USB
        (sinon le plantage arrive plus tard, loin de la cause — règle test_forme_profil) ;
      • un chemin dans le nom → jamais écrit hors du dossier des profils ;
      • un nom déjà pris → jamais d'écrasement silencieux.
    """
    section("34. Import de profil — accepte, mais surtout refuse")
    import tempfile
    wm_ = ui.wm
    sauve_dir, sauve_log = wm_.PROFILE_DIR, ui.log
    ennuis = []
    try:
        d = Path(tempfile.mkdtemp())
        wm_.PROFILE_DIR = d
        ui.log = lambda t, *a, **k: None

        prof = wm_.new_profile_from_defaults()
        prof["name"] = "Wing de Paul"

        # 1. import normal
        r = _poster(ui, "/api/profile/import", {"nom": "wing-de-paul.json",
                                                "contenu": prof})
        if not r.get("ok"):
            ennuis.append(f"un profil valide est refusé : {r.get('raison')}")
        elif not (d / r["file"]).exists():
            ennuis.append("l'import dit OK mais aucun fichier n'est écrit")

        # 2. même nom → pas d'écrasement
        r2 = _poster(ui, "/api/profile/import", {"nom": "wing-de-paul.json",
                                                 "contenu": prof})
        if r2.get("ok") and r2.get("file") == r.get("file"):
            ennuis.append("un second import du même nom ÉCRASE le premier")

        # 3. JSON qui n'est pas un profil
        r3 = _poster(ui, "/api/profile/import",
                     {"nom": "notes.json", "contenu": {"blabla": 1}})
        if r3.get("ok"):
            ennuis.append("un JSON quelconque est accepté comme profil")

        # 4. tentative de sortie du dossier
        r4 = _poster(ui, "/api/profile/import",
                     {"nom": "../../evasion.json", "contenu": prof})
        if r4.get("ok"):
            cible = d / r4["file"]
            if not cible.resolve().is_relative_to(d.resolve()):
                ennuis.append(f"écriture HORS du dossier des profils : {cible}")
        fichiers = [f.name for f in d.glob("*.json")]
        if any("evasion" in f and "/" in f for f in fichiers):
            ennuis.append("un chemin a survécu dans le nom de fichier")
    except Exception as e:
        ennuis.append(f"exception : {type(e).__name__}: {e}")
    finally:
        wm_.PROFILE_DIR, ui.log = sauve_dir, sauve_log

    if ennuis:
        echec("l'import de profil se comporte mal", " ; ".join(ennuis))
    else:
        ok("import OK ; refuse un non-profil, n'écrase rien, ne sort pas du dossier")


def test_ecritures_atomiques(ui):
    """4 fichiers d'état écrivaient DIRECTEMENT sur le fichier final —
    contrairement au reste du projet (sauvegarde auto, raccourcis XML, cache
    firmware) qui utilise déjà temp-file + `os.replace()` (audit Lot C,
    14/09/2026) : `wing_mapper.save_profile()`, `wing_profils.save_reference()`
    (le filet de secours), `wing_reglages.save_settings()`, et
    `wing_init._ecrire_etat_fichier()` (l'anti-martèlement du renvoi de
    firmware — partagée avec `wing_firmware_capture.py`). Une coupure en plein
    milieu d'une écriture DIRECTE laisse un JSON tronqué à la place du fichier
    précédent, bon.

    Vérifie, pour chacun : en faisant échouer `os.replace()` (coupure simulée
    JUSTE avant la bascule), le fichier CIBLE reste STRICTEMENT intact et le
    contenu neuf se trouve entièrement dans un `.part` À CÔTÉ — la preuve que
    l'écriture passe par un fichier temporaire avant de toucher au fichier
    final.
    """
    section("62. Écritures d'état : temp-file + os.replace (4 fichiers)")
    import os as _os
    import tempfile
    ennuis = []
    sauv_replace = _os.replace

    def _replace_qui_leve(*a, **k):
        raise OSError("coupure simulée (test smoke)")

    def _verifie(nom, cible: Path, ecrire):
        avant = b'{"ancien": true}'
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_bytes(avant)
        tmp = cible.with_suffix(".part")
        tmp.unlink(missing_ok=True)
        _os.replace = _replace_qui_leve
        try:
            ecrire()
        except Exception:
            pass    # une coupure simulée peut remonter OU être avalée : les
                    # deux sont recevables, seul le fichier compte
        finally:
            _os.replace = sauv_replace
        if cible.read_bytes() != avant:
            ennuis.append(f"{nom} : le fichier CIBLE a été modifié AVANT la "
                          "bascule os.replace — l'écriture n'est pas atomique")
        # Le temporaire peut porter un nom PROPRE à l'appel (pid + fil, audit du
        # 25/09/2026 — deux sauvegardes simultanées ne se marchent plus
        # dessus) : on cherche tout `.part` né de cette cible.
        temps = [p for p in cible.parent.glob("*.part")
                 if p.name.startswith((cible.stem + ".", cible.name + "."))]
        if not temps:
            ennuis.append(f"{nom} : aucun fichier temporaire ({tmp.name} ou "
                          f"{cible.name}.<pid>.<fil>.part) — l'écriture ne "
                          "passe pas par un temp-file")
        for t in temps:
            t.unlink(missing_ok=True)

    d = Path(tempfile.mkdtemp())
    wm_ = ui.wm
    sauv_dir = wm_.PROFILE_DIR
    sauv_ref = ui.REFERENCE_FILE
    sauv_settings = ui.wing_reglages.SETTINGS_FILE
    sauv_etat = wing_etat_materiel.ETAT_FICHIER
    sauv_log = ui.log
    try:
        wm_.PROFILE_DIR = d
        ui.log = lambda *a, **k: None

        _verifie("wing_mapper.save_profile()", d / "test-profil.json",
                 lambda: wm_.save_profile(wm_.new_profile_from_defaults(),
                                          d / "test-profil.json"))

        ui.REFERENCE_FILE = d / "__reference__.json"
        _verifie("wing_profils.save_reference()", ui.REFERENCE_FILE,
                 lambda: ui.save_reference(wm_.new_profile_from_defaults()))

        ui.wing_reglages.SETTINGS_FILE = d / "settings.json"
        _verifie("wing_reglages.save_settings()", ui.wing_reglages.SETTINGS_FILE,
                 lambda: ui.save_settings())

        wing_etat_materiel.ETAT_FICHIER = d / "wing_hw_state.json"
        _verifie("wing_init._ecrire_etat_fichier()", wing_etat_materiel.ETAT_FICHIER,
                 lambda: wing_etat_materiel._ecrire_etat_fichier({"fw_envoye_t": 1.0}))
    except Exception as e:
        ennuis.append(f"exception : {type(e).__name__}: {e}")
    finally:
        wm_.PROFILE_DIR = sauv_dir
        ui.REFERENCE_FILE = sauv_ref
        ui.wing_reglages.SETTINGS_FILE = sauv_settings
        wing_etat_materiel.ETAT_FICHIER = sauv_etat
        ui.log = sauv_log
        _os.replace = sauv_replace

    if ennuis:
        echec("une écriture d'état n'est pas atomique", " ; ".join(ennuis))
    else:
        ok("save_profile()/save_reference()/save_settings()/"
           "_ecrire_etat_fichier() passent bien par temp-file + os.replace")
