"""Contrôles de sécurité et de robustesse — test de fumée, Wing Bridge.

Chaque contrôle de ce fichier vient de l'audit de code du 25/09/2026 et
surveille un défaut qui a été VÉRIFIÉ dans le code réel avant correction.
Règle du projet appliquée partout ici : un contrôle jamais vu ROUGE ne prouve
rien — chacun réinjecte le défaut qu'il garde et exige de le voir échouer.

  test_xss_profil_importe   un profil importé exécutait du JavaScript dans
                            l'interface (nom, raccourcis, roues) — donc avec
                            le droit d'appeler toute l'API
  test_profil_mal_type      un profil mal typé tuait la boucle USB, et rien
                            ne la relançait
  test_pas_de_route_debug   une route de débogage qui tuait la boucle USB a
                            été livrée en v1.0.0
  test_une_seule_boucle_usb une reconnexion lente laissait deux boucles USB
                            tourner sur le même device
  test_empreinte_firmware_a_l_envoi
                            l'empreinte du firmware n'était vérifiée qu'à
                            l'import, jamais juste avant l'envoi
  test_jeton_api            une requête sans en-tête Origin (programme local)
                            passait sans condition sur toute l'API
  test_raccourcis_filtres   une frappe de raccourci non filtrée corrompait le
                            XML de MA3 ou s'échappait d'une commande OSC
  test_amorce_elevee_verifiee
                            script élevé et installeur USBPcap substituables ;
                            registre système réécrit sans nécessité
  test_journal_hors_boucle  le journal touchait au disque depuis la boucle USB
  test_ecritures_etat_sous_verrou
                            STATE/SETTINGS écrits hors verrou, SETTINGS
                            sérialisé pendant qu'un autre fil le modifiait
  test_handler_robuste      corps invalide ou route qui lève : connexion
                            coupée sans réponse
  test_profil_load_confine  /api/profile/load non confiné au dossier profils
  test_ecritures_usb_comptees
                            écritures DMX/LED refusées avalées en silence
  test_part_unique          temporaire .part partagé entre sauvegardes
  test_dmx_local            DMX réseau accepté de tout le réseau
  test_validation_entrees   paramètres d'API lus sans borne ni type
  test_handler_mince        Handler et wing_init trop gros ; noms déplacés gardés
"""

import etat
import json
import shutil
import subprocess
import tempfile
import time
from html.parser import HTMLParser
from pathlib import Path

import wing_firmware

from smoke_core import HERE, ok, echec, note, section, _blocs_js


# ── 64. XSS par profil importé ────────────────────────────────────────────────

# Chaque vecteur porte son propre marqueur : on peut ainsi exiger qu'il ait
# bien ÉTÉ AFFICHÉ (sinon le contrôle passerait au vert sur du vide) et dire
# lequel s'exécute.
_VECTEURS = {
    "XSS_NOM": "nom du profil (liste des profils)",
    "XSS_CLE": "code de touche (tableau des touches)",
    "XSS_TOK": "commande de touche (tableau des touches)",
    "XSS_REF": "executor de touche (tableau des touches)",
    "XSS_RAC": "raccourci clavier (attribut value entre apostrophes)",
    "XSS_DBL": "double-appui (attribut value entre apostrophes)",
    "XSS_ENC": "attribut de roue (gabarit tHtml)",
    "XSS_SHC": "écart de raccourci renvoyé par /api/shcuts (tHtml imbriqué)",
}


def _profil_piege():
    """Le contenu JSON d'un profil « reçu d'un collègue », piégé."""
    import wing_mapper as wm
    p = wm.new_profile_from_defaults()
    p["name"] = '<img src=x onerror="XSS_NOM()">'
    p["buttons"]["0x97"] = "Store"
    p["buttons"]["0x98<svg onload=XSS_CLE()>"] = "Go+ Executor 101"
    p["buttons"]["0x99"] = "<svg onload=XSS_TOK()> x"
    p.setdefault("executor_ref", {})["0x99"] = "<img src=x onerror=XSS_REF()>"
    p.setdefault("console_keys", {})["Store"] = "' autofocus onfocus='XSS_RAC()"
    p.setdefault("double_clic", {})["Store"] = "' onmouseover='XSS_DBL()"
    p["enc_groups"][0][0] = "'><img src=x onerror=XSS_ENC()>"
    return p


class _Chasseur(HTMLParser):
    """Relève tout gestionnaire d'événement (on…) qui porte un marqueur :
    c'est-à-dire une balise ou un attribut que le navigateur EXÉCUTERAIT."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.executes = set()

    def handle_starttag(self, tag, attrs):
        for nom, val in attrs:
            if nom.lower().startswith("on") and val:
                for m in _VECTEURS:
                    if m in val:
                        self.executes.add(m)


def _node():
    for cand in ("node", "/opt/homebrew/bin/node", "/usr/local/bin/node",
                 "/opt/homebrew/opt/node@22/bin/node"):
        try:
            subprocess.run([cand, "--version"], capture_output=True, timeout=5)
            return cand
        except Exception:
            continue
    return None


# DOM factice qui ENREGISTRE chaque innerHTML posé. Tout élément existe
# (getElementById ne rend jamais null) pour que tout le rendu soit parcouru.
_PROLOGUE = r"""
const RENDUS = [];
const __ELS = {};
function mkEl(){
  const o = {_html:"", style:{}, dataset:{g:"0", i:"0"}, value:"",
             classList:{add(){},remove(){},contains(){return false;},toggle(){}}};
  return new Proxy(o, {
    get:(t,k)=>{
      if (k === "innerHTML") return t._html;
      if (k === "querySelectorAll") return ()=>[];
      if (k === "querySelector") return ()=>mkEl();
      if (k in t) return t[k];
      if (typeof k === "string") return ()=>mkEl();
      return undefined; },
    set:(t,k,v)=>{
      if (k === "innerHTML") { t._html = String(v); RENDUS.push(String(v)); }
      else t[k] = v;
      return true; } });
}
globalThis.document = {
  getElementById:(id)=> (__ELS[id] = __ELS[id] || mkEl()),
  createElement:()=>mkEl(), querySelectorAll:()=>[], querySelector:()=>mkEl(),
  addEventListener:()=>{}, body:mkEl(), documentElement:mkEl(),
};
globalThis.window = globalThis;
globalThis.addEventListener = ()=>{};
globalThis.navigator = { sendBeacon:()=>true, language:"fr" };
globalThis.localStorage = { getItem:()=>"fr", setItem(){}, removeItem(){} };
globalThis.alert = ()=>{}; globalThis.confirm = ()=>false;
globalThis.prompt = ()=>null;
globalThis.setInterval = ()=>0; globalThis.setTimeout = ()=>0;
globalThis.clearTimeout = ()=>{}; globalThis.clearInterval = ()=>{};
globalThis.requestAnimationFrame = ()=>0;
const __DONNEES = __DONNEES_JSON__;
globalThis.fetch = async (u) => {
  u = String(u);
  let corps = {};
  if (u.indexOf("/locales/") === 0) corps = __DONNEES.locales[u.slice(9, -5)] || {};
  else if (u === "/api/profile") corps = __DONNEES.profil;
  else if (u === "/api/profiles") corps = __DONNEES.liste;
  else if (u === "/api/shcuts") corps = __DONNEES.shcuts;
  return { ok:true, status:200,
           json: async () => JSON.parse(JSON.stringify(corps)),
           text: async () => "" };
};
"""

_EPILOGUE = r"""
;(async () => {
  await chargerCatalogues(); LANG = "fr";
  await loadProfiles();
  await loadProfile();
  await shcutsRafraichir();
  require("fs").writeFileSync(__SORTIE__, JSON.stringify({rendus: RENDUS}));
})().catch(e => require("fs").writeFileSync(__SORTIE__,
                  JSON.stringify({erreur: String(e && e.stack || e)})));
"""

# Réinjection ROUGE : les trois défauts exacts relevés par l'audit.
#   • esc() sans ' ni " (la version d'avant) ;
#   • tHtml() qui interpole ses paramètres sans échapper ;
#   • le nom du profil posé brut dans la liste.
# Les déclarations `function` ajoutées EN FIN de script l'emportent sur les
# premières (même portée, la dernière déclaration gagne).
_REINJECTION = r"""
function esc(s) {
  return String(s == null ? "" : s).replace(/&/g, "&amp;")
    .replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function tHtml(cle, params) { return t(cle, params); }
"""


def _rendre(node, js, donnees):
    """Exécute l'interface dans node ; rend (liste des innerHTML, erreur)."""
    # Le résultat passe par un FICHIER, pas par stdout : l'interface écrit
    # elle-même dans la console (console.warn…), ce qui mêlerait les deux.
    dossier = Path(tempfile.mkdtemp())
    chemin, sortie = dossier / "rendu.js", dossier / "rendus.json"
    chemin.write_text(_PROLOGUE.replace("__DONNEES_JSON__", json.dumps(donnees))
                      + js + _EPILOGUE.replace("__SORTIE__",
                                               json.dumps(str(sortie))),
                      encoding="utf-8")
    try:
        r = subprocess.run([node, str(chemin)], capture_output=True,
                           text=True, timeout=60)
        if not sortie.exists():
            return None, (r.stderr or r.stdout or "aucune sortie")[:400]
        res = json.loads(sortie.read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(dossier, ignore_errors=True)
    if "rendus" in res:
        return res["rendus"], None
    return None, res.get("erreur", "?")[:400]


def _executes(rendus):
    ch = _Chasseur()
    for h in rendus:
        ch.feed(h)
        ch.close()
        ch.reset()
    return ch.executes


def test_xss_profil_importe(html):
    """Un profil importé ne doit JAMAIS pouvoir exécuter du JavaScript.

    🔴 FAILLE CRITIQUE (audit du 25/09/2026). `profils.js` posait le nom du
    profil brut dans innerHTML ; `esc()` n'échappait pas les apostrophes alors
    qu'il remplit des attributs `value='…'` ; `tHtml()` interpolait ses
    paramètres sans échapper. Un profil reçu d'un collègue exécutait donc son
    script dès l'affichage — sur l'ORIGINE DE L'APP, ce qui passe le contrôle
    d'Origin et donne accès à toute l'API (désinstaller, quitter, réécrire
    les touches).

    Le contrôle IMPORTE réellement un profil piégé (importer_profil), le
    relit par le même chemin que le serveur, exécute le VRAI JavaScript de
    l'interface dans node, et analyse chaque innerHTML produit avec un parseur
    HTML : aucun attribut `on…` ne doit porter un marqueur du profil.

    Puis RÉINJECTION : les trois défauts d'origine remis en place, il doit
    voir rouge — sinon il ne prouve rien.
    """
    section("64. Un profil importé ne peut pas exécuter de JavaScript")
    node = _node()
    if not node:
        note("node introuvable — contrôle XSS sauté")
        return

    import wing_mapper as wm
    import wing_profils
    import wing_ui as ui

    # 1) Import RÉEL, dans un dossier jetable, par le chemin de production.
    sauve_dir, sauve_log = wm.PROFILE_DIR, ui.log
    try:
        d = Path(tempfile.mkdtemp())
        wm.PROFILE_DIR = d
        ui.log = lambda *a, **k: None
        r = wing_profils.importer_profil("cadeau.json", _profil_piege())
        if not r.get("ok"):
            echec("l'import du profil piégé a échoué — contrôle aveugle",
                  str(r))
            return
        fichier = d / r["file"]
        profil = wm.load_profile(fichier)
        # Depuis la liste blanche des raccourcis (test_raccourcis_filtres), le
        # chargement NEUTRALISE déjà cette frappe piégée. L'échappement de
        # l'affichage doit pourtant tenir SEUL — défense en profondeur : on la
        # remet donc après le chargement, pour tester cette couche-ci isolément.
        profil["console_keys"]["Store"] = _profil_piege()["console_keys"]["Store"]
        # Même lecture que wing_handler._get_profiles.
        nom = json.load(open(fichier, encoding="utf-8")).get("name", fichier.stem)
        liste = [{"file": fichier.name, "name": nom,
                  "favori": False, "protege": False}]
    finally:
        wm.PROFILE_DIR, ui.log = sauve_dir, sauve_log

    donnees = {
        "locales": {lg: json.loads((HERE / "locales" / f"{lg}.json")
                                   .read_text(encoding="utf-8"))
                    for lg in ("fr", "en")},
        "profil": profil,
        "liste": liste,
        # /api/shcuts renvoie des frappes et des noms de touche tirés du
        # profil : un écart piégé doit rester inerte lui aussi.
        "shcuts": {"possible": True, "a_jour": False, "actif": True,
                   "ecartees": [],
                   "ecarts": [{"touche": "<img src=x onerror=XSS_SHC()>",
                               "ma3": "x", "app": "y"}]},
    }
    js = "\n;\n".join(code for _, code in _blocs_js(html))

    # 2) Le code actuel : chaque vecteur affiché, aucun exécuté.
    rendus, err = _rendre(node, js, donnees)
    if rendus is None:
        echec("le rendu de l'interface a planté dans node — contrôle aveugle",
              err)
        return
    tout = "\n".join(rendus)
    absents = [m for m in _VECTEURS if m not in tout]
    if absents:
        echec("vecteur(s) jamais affiché(s) — le contrôle ne les voit pas",
              ", ".join(f"{m} ({_VECTEURS[m]})" for m in absents))
    executes = _executes(rendus)
    if executes:
        echec(f"{len(executes)} donnée(s) du profil deviennent du code exécutable",
              ", ".join(f"{m} ({_VECTEURS[m]})" for m in sorted(executes)))
    elif not absents:
        ok(f"{len(_VECTEURS)} vecteurs d'un profil piégé affichés, aucun exécuté")

    # 3) Réinjection ROUGE : les défauts d'origine doivent être vus.
    js_bug = js.replace('"<b>" + esc(p.name) + "</b>', '"<b>" + p.name + "</b>')
    if js_bug == js:
        echec("réinjection impossible : la ligne du nom de profil a changé",
              "mettre à jour _REINJECTION / le motif dans smoke_securite.py")
        return
    rendus_bug, err = _rendre(node, js_bug + _REINJECTION, donnees)
    if rendus_bug is None:
        echec("réinjection : le rendu a planté — contrôle non prouvé", err)
        return
    vus = _executes(rendus_bug)
    attendus = {"XSS_NOM", "XSS_RAC", "XSS_ENC"}
    if attendus <= vus:
        ok("réinjection des 3 défauts d'origine → détectés "
           f"({', '.join(sorted(vus))}) : le contrôle sait voir rouge")
    else:
        echec("réinjection NON détectée — le contrôle est aveugle",
              f"attendus {sorted(attendus)}, vus {sorted(vus)}")


# ── 65. Profil mal typé : la boucle USB ne meurt plus ─────────────────────────

def _profil_mal_type():
    """Les valeurs MESURÉES comme mortelles avant correction, et quelques
    voisines de la même famille."""
    import wing_mapper as wm
    p = wm.new_profile_from_defaults()
    p["faders"] = ["x"] * 8                        # dict("x") → ValueError
    p["faders"][1] = {"kind": "executor", "exec": "101; Delete Show"}
    p["faders"][2] = {"kind": "inconnu"}
    p["faders"][3] = {"kind": "speed", "num": 1, "unit": "furlong",
                      "min": "bas", "max": float("nan")}
    p["enc_step"] = "1"                            # "1" * delta >= 0 → TypeError
    p["enc_groups"][0][0] = 42
    p["buttons"]["0x97"] = 7
    return p


def _forme_sure(p):
    """Rend la liste des défauts de TYPE qui tueraient usb_loop."""
    import wing_mapper as wm
    fautes = []
    for i, fx in enumerate(p["faders"]):
        if not isinstance(fx, dict) or fx.get("kind", "executor") not in wm.KINDS_FADER:
            fautes.append(f"faders[{i}]={fx!r}")
        elif "exec" in fx and (isinstance(fx["exec"], bool)
                               or not isinstance(fx["exec"], int)):
            fautes.append(f"faders[{i}].exec={fx['exec']!r}")
    if isinstance(p["enc_step"], bool) or not isinstance(p["enc_step"], (int, float)):
        fautes.append(f"enc_step={p['enc_step']!r}")
    for gi, g in enumerate(p["enc_groups"]):
        for i, a in enumerate(g):
            if a is not None and not isinstance(a, str):
                fautes.append(f"enc_groups[{gi}][{i}]={a!r}")
    if any(not isinstance(v, str) for v in p["buttons"].values()):
        fautes.append("buttons : valeur non texte")
    # Les deux expressions EXACTES de usb_loop qui plantaient :
    try:
        [dict(x) for x in p["faders"]]
        step = p["enc_step"] * 1
        _ = step >= 0
    except Exception as e:
        fautes.append(f"usb_loop lèverait {type(e).__name__}: {e}")
    return fautes


def _importer_et_charger(contenu):
    import wing_mapper as wm
    import wing_profils
    import wing_ui as ui
    sauve_dir, sauve_log = wm.PROFILE_DIR, ui.log
    try:
        d = Path(tempfile.mkdtemp())
        wm.PROFILE_DIR = d
        ui.log = lambda *a, **k: None
        r = wing_profils.importer_profil("collegue.json", contenu)
        if not r.get("ok"):
            return None, r
        return wm.load_profile(d / r["file"]), r
    finally:
        wm.PROFILE_DIR, ui.log = sauve_dir, sauve_log
        shutil.rmtree(d, ignore_errors=True)


def _faire_tourner(ui, wc, cible, profil_faders, n_tours=30, timeout=10):
    """Fait tourner `cible` (usb_loop ou _usb_boucle) en mode bridge avec des
    doublures, un fader qui bouge à chaque tour, et PROFILE['faders'] posé
    tel quel (sans validation). Rend (thread encore vivant ?, tours joués,
    erreurs_tour, exception sortie du thread ou None)."""
    import threading as _th
    # Les FONCTIONS remplacées sont sauvées/restaurées ; l'ÉTAT, lui, est un
    # état neuf INJECTÉ (etat.injecter) — rien à sauver, rien à remettre.
    sauv = {"cycle": ui.cycle_dmx, "pstate": ui.wb.parse_state,
            "pevents": ui.wb.parse_events, "absente": ui.wing_init.wing_absente,
            "etat": ui.ma3_etat, "log": ui.log}
    scene = {"n": 0}
    sortie = {"exc": None}

    def faux_cycle(dev):
        scene["n"] += 1
        if scene["n"] > n_tours:
            ui.USB_ARRET.set()
            return None
        return b"\x00" * 96

    class _Osc:
        def send_message(self, *a):
            pass

    def corps():
        try:
            cible()
        except BaseException as e:      # noqa — on veut TOUT voir sortir
            sortie["exc"] = e

    with etat.injecter() as e:
        e.OSC = _Osc()
        e.LED["ma3"] = False
        e.PROFILE["faders"] = profil_faders
        e.STATE.update(mode="bridge", wing=True)
        e.DEV[0] = object()
        try:
            ui.cycle_dmx = faux_cycle
            ui.wb.parse_state = lambda d: {"faders": [scene["n"] * 7 % 1000] * 8,
                                           "encoders": [scene["n"]] * 4}
            ui.wb.parse_events = lambda d: []
            ui.wing_init.wing_absente = lambda: False
            ui.ma3_etat = lambda: {"actif": False}
            ui.log = lambda *a, **k: None
            ui.USB_ARRET.clear(); ui.USB_SORTIE.clear()
            fil = _th.Thread(target=corps, daemon=True)
            fil.start()
            fil.join(timeout=timeout)
            vivant = fil.is_alive()
            erreurs = e.BOUCLE.get("erreurs_tour", 0)
        finally:
            ui.USB_ARRET.set()
            time.sleep(0.05)       # le fil sort AVANT qu'on rende l'état d'origine
            ui.cycle_dmx = sauv["cycle"]
            ui.wb.parse_state = sauv["pstate"]; ui.wb.parse_events = sauv["pevents"]
            ui.wing_init.wing_absente = sauv["absente"]; ui.ma3_etat = sauv["etat"]
            ui.log = sauv["log"]
            ui.USB_ARRET.clear(); ui.USB_SORTIE.clear()
    return vivant, scene["n"], erreurs, sortie["exc"]


def test_profil_mal_type(ui, wc):
    """Un profil mal typé ne peut plus tuer la boucle USB.

    🔴 FAILLE CRITIQUE (audit du 25/09/2026). Mesuré avant correction : un
    profil importé avec `"faders": ["x", …]` ou `"enc_step": "1"` était
    accepté, puis `usb_loop` levait au premier tour en mode bridge — et
    RIEN ne la relançait. Trois étages sont vérifiés, chacun avec sa
    réinjection rouge :
      (a) `wing_mapper.valider_types` ramène chaque champ à un type sûr ;
      (b) le filet par tour de `_usb_boucle` garde la boucle en vie ;
      (c) le superviseur `usb_loop` relance une boucle morte, et ABANDONNE
          (exception visible) au-delà de USB_RELANCE_MAX morts.
    """
    section("65. Un profil mal typé ne tue plus la boucle USB")
    import wing_mapper as wm

    # (0) Une seule liste de types de fader, deux endroits : ils doivent
    #     rester d'accord, sinon un type valide serait « réparé » à tort.
    attendus = set(ui.FADER_KEYWORDS) | {"gm", "selected", "speed", "faderspeed"}
    if wm.KINDS_FADER != attendus:
        echec("wing_mapper.KINDS_FADER diverge des types de fader de l'app",
              f"en trop : {sorted(wm.KINDS_FADER - attendus)} ; "
              f"manquants : {sorted(attendus - wm.KINDS_FADER)}")
    else:
        ok(f"KINDS_FADER = les {len(attendus)} types de fader de l'app")

    # (a) Validation de schéma, par le VRAI chemin d'import + chargement.
    profil, r = _importer_et_charger(_profil_mal_type())
    if profil is None:
        echec("l'import du profil mal typé a été refusé — contrôle aveugle", str(r))
        return
    fautes = _forme_sure(profil)
    if fautes:
        echec(f"{len(fautes)} valeur(s) mortelle(s) passent la validation",
              " ; ".join(fautes[:6]))
    else:
        f1 = profil["faders"][1]
        ok("profil mal typé importé puis chargé : tous les champs ramenés à "
           f"un type sûr (ex. exec « 101; Delete Show » → {f1.get('exec')!r}, "
           f"enc_step \"1\" → {profil['enc_step']!r})")

    sauve = wm.valider_types
    try:
        wm.valider_types = lambda p: []           # réinjection : pas de validation
        profil_bug, _ = _importer_et_charger(_profil_mal_type())
    finally:
        wm.valider_types = sauve
    if profil_bug is not None and _forme_sure(profil_bug):
        ok("réinjection (validation retirée) → valeurs mortelles détectées")
    else:
        echec("réinjection de la validation NON détectée — (a) est aveugle")

    # (b) Filet par tour : la VRAIE boucle, des faders empoisonnés posés
    #     directement dans PROFILE (comme si un chemin oubliait la validation).
    poison = ["x"] * 8
    vivant, n, erreurs, exc = _faire_tourner(ui, wc, wc._usb_boucle, poison)
    if exc is not None:
        echec("la boucle USB meurt encore sur un tour fautif",
              f"{type(exc).__name__}: {exc}")
    elif vivant or n < 20:
        echec("scénario non concluant", f"{n} tour(s), vivant={vivant}")
    elif erreurs < 5:
        echec("le filet n'a pas vu les tours fautifs — contrôle aveugle",
              f"erreurs_tour={erreurs} sur {n} tours")
    else:
        ok(f"{n} tours avec des faders empoisonnés : {erreurs} tour(s) "
           "abandonné(s), la boucle a continué jusqu'à l'arrêt demandé")

    sauve = wc._erreur_tour
    def _sans_filet(e):
        raise e
    try:
        wc._erreur_tour = _sans_filet                # réinjection : plus de filet
        _, _, _, exc = _faire_tourner(ui, wc, wc._usb_boucle, poison)
    finally:
        wc._erreur_tour = sauve
    if exc is not None:
        ok(f"réinjection (filet retiré) → la boucle meurt ({type(exc).__name__}) : "
           "le contrôle sait voir rouge")
    else:
        echec("réinjection du filet NON détectée — (b) est aveugle")

    # (c) Superviseur : une boucle qui meurt deux fois puis sort normalement
    #     doit avoir été relancée deux fois ; une boucle qui meurt sans fin
    #     doit finir par laisser l'exception sortir (THREAD_MORT, visible).
    sauv = {"b": wc._usb_boucle, "d": wc.USB_RELANCE_DELAI_S,
            "m": wc.USB_RELANCE_MAX, "log": ui.log,
            "rel": etat.E.BOUCLE.get("relances", 0)}
    appels = {"n": 0}

    def boucle_fragile(gen=None):
        appels["n"] += 1
        if appels["n"] <= 2:
            raise RuntimeError("mort simulée")

    def boucle_maudite(gen=None):
        appels["n"] += 1
        raise RuntimeError("mort permanente simulée")

    try:
        wc.USB_RELANCE_DELAI_S = 0.0
        wc.USB_RELANCE_MAX = 3
        ui.log = lambda *a, **k: None
        wc._usb_boucle = boucle_fragile
        sortie_ok = True
        try:
            wc.usb_loop()
        except Exception:
            sortie_ok = False
        n_fragile = appels["n"]

        appels["n"] = 0
        wc._usb_boucle = boucle_maudite
        abandon = False
        try:
            wc.usb_loop()
        except RuntimeError:
            abandon = True
        n_maudite = appels["n"]

        # Réinjection : l'ancien point d'entrée = la boucle nue, sans superviseur.
        appels["n"] = 0
        wc._usb_boucle = boucle_fragile
        sans_sup_meurt = False
        try:
            wc._usb_boucle()
        except RuntimeError:
            sans_sup_meurt = True
    finally:
        wc._usb_boucle = sauv["b"]
        wc.USB_RELANCE_DELAI_S = sauv["d"]; wc.USB_RELANCE_MAX = sauv["m"]
        ui.log = sauv["log"]; etat.E.BOUCLE["relances"] = sauv["rel"]

    if sortie_ok and n_fragile == 3:
        ok("superviseur : boucle morte 2 fois → relancée 2 fois, puis sortie "
           "volontaire respectée (pas de relance)")
    else:
        echec("le superviseur ne relance pas la boucle morte",
              f"appels={n_fragile}, sortie normale={sortie_ok} (attendu 3, vrai)")
    if abandon and n_maudite == 4:
        ok("superviseur : au-delà de USB_RELANCE_MAX morts, il abandonne et "
           "laisse l'exception sortir (THREAD_MORT, visible à l'écran)")
    else:
        echec("le superviseur ne sait pas abandonner une mort permanente",
              f"appels={n_maudite}, exception sortie={abandon} (attendu 4, vrai)")
    if sans_sup_meurt:
        ok("réinjection (sans superviseur) → la 1re mort est définitive : "
           "le contrôle sait voir rouge")
    else:
        echec("réinjection du superviseur NON détectée — (c) est aveugle")


# ── 66. Aucune route de débogage dans l'app livrée ────────────────────────────

# ⚠️ Pas « test » : `/api/console/test` est une vraie fonction (tester une
# frappe vers MA3), pas un outil de débogage.
_MOTS_DEBUG = ("debug", "boom", "crash")


def _routes_debug(handler_cls, module_ui) -> list:
    """Tout ce qui ressemble à un outil de débogage exposé par le serveur."""
    trouves = []
    for table in ("ROUTES_GET", "ROUTES_POST"):
        for cible, nom in getattr(handler_cls, table, []):
            chemin = cible if isinstance(cible, str) else ""
            if any(m in (chemin + " " + nom).lower() for m in _MOTS_DEBUG):
                trouves.append(f"{table} {chemin or '(lambda)'} → {nom}")
    for nom in dir(handler_cls):
        if nom.startswith(("_post_", "_get_")) and \
                any(m in nom.lower() for m in _MOTS_DEBUG):
            trouves.append(f"méthode {nom}")
    if hasattr(module_ui, "DEBUG_BOOM"):
        trouves.append("wing_ui.DEBUG_BOOM (crochet qui tue usb_loop)")
    return sorted(set(trouves))


def test_pas_de_route_debug(ui):
    """Aucune route de débogage n'est exposée par le serveur.

    🟠 Audit du 25/09/2026 : `/api/_debug_boom_usb_loop` tuait volontairement
    la boucle USB. Elle a été LIVRÉE en v1.0.0, alors que son commentaire
    disait « à retirer avant tout build final ». Une requête sans en-tête
    Origin étant acceptée, n'importe quel processus local la déclenchait :
    wing gelée d'un `curl`. Un outil de test ne se retire pas « à la fin » :
    on l'oublie. D'où ce contrôle, qui refuse son retour sous tout nom.
    """
    section("66. Aucune route de débogage exposée par le serveur")
    import wing_handler

    trouves = _routes_debug(wing_handler.Handler, ui)
    if trouves:
        echec(f"{len(trouves)} outil(s) de débogage exposé(s) par le serveur",
              " ; ".join(trouves))
    else:
        ok(f"{len(wing_handler.Handler.ROUTES_GET) + len(wing_handler.Handler.ROUTES_POST)}"
           " routes, aucune de débogage")

    # Réinjection : la route d'origine remise dans une copie de la table.
    class _HandlerBug(wing_handler.Handler):
        ROUTES_POST = wing_handler.Handler.ROUTES_POST + [
            ("/api/_debug_boom_usb_loop", "_post_debug_boom_usb_loop")]
    if _routes_debug(_HandlerBug, ui):
        ok("réinjection (route /api/_debug_boom_usb_loop remise) → détectée")
    else:
        echec("réinjection de la route de débogage NON détectée — contrôle aveugle")


# ── 67. Une seule boucle USB, même après une reconnexion lente ────────────────

def _boucles_apres_reconnexion(ui, wc, bloque_s=0.8):
    """Joue le scénario de l'audit avec le VRAI connect_wing() : une boucle
    coincée dans un tour plus long que l'attente de connect_wing (réduite ici
    à 0,3 s via USB_SORTIE_ATTENTE_S pour que le contrôle reste rapide), puis
    une reconnexion. Rend le nombre de fils `usb_loop` NÉS DU SCÉNARIO encore
    vivants une fois l'ancienne boucle réveillée."""
    import threading as _th

    class _FauxDev:
        pass

    avant = {t for t in _th.enumerate() if t.name == "usb_loop"}
    sauv = {"log": ui.log, "cycle": ui.cycle_dmx, "init": ui.full_init,
            "absente": ui.wing_init.wing_absente,
            "attente": wc.USB_SORTIE_ATTENTE_S}
    injection = etat.injecter()          # état neuf, isolé, le temps du scénario
    e = injection.__enter__()
    lent = {"a_faire": True}

    def faux_cycle(dev):
        if lent["a_faire"]:
            lent["a_faire"] = False
            time.sleep(bloque_s)            # le tour qui dépasse l'attente
        time.sleep(0.02)
        return None

    try:
        ui.log = lambda *a, **k: None
        wc.USB_SORTIE_ATTENTE_S = 0.3
        ui.cycle_dmx = faux_cycle
        ui.full_init = lambda **k: _FauxDev()
        ui.wing_init.wing_absente = lambda: False
        e.DEV[0] = _FauxDev()
        e.STATE.update(wing=True, want_connected=True)
        ui.USB_ARRET.clear(); ui.USB_SORTIE.clear()
        _th.Thread(target=ui.usb_loop, daemon=True, name="usb_loop").start()
        time.sleep(0.2)                     # la boucle entre dans son tour long
        ui.connect_wing(force=True, quiet=True)
        time.sleep(bloque_s)                # l'ancienne se réveille
        nes = [t for t in _th.enumerate()
               if t.name == "usb_loop" and t not in avant and t.is_alive()]
        return len(nes)
    finally:
        ui.USB_ARRET.set()
        fin = time.time() + 3
        while time.time() < fin and any(
                t.name == "usb_loop" and t not in avant and t.is_alive()
                for t in _th.enumerate()):
            time.sleep(0.05)
        ui.log = sauv["log"]; ui.cycle_dmx = sauv["cycle"]
        wc.USB_SORTIE_ATTENTE_S = sauv["attente"]
        ui.full_init = sauv["init"]; ui.wing_init.wing_absente = sauv["absente"]
        ui.USB_ARRET.clear(); ui.USB_SORTIE.clear()
        injection.__exit__(None, None, None)   # les boucles sont sorties avant


def test_une_seule_boucle_usb(ui, wc):
    """Après une reconnexion, il ne reste qu'UNE boucle USB — même si
    l'ancienne a mis plus de 2 s à rendre la main.

    🔴 FAILLE CRITIQUE (audit du 25/09/2026). `connect_wing()` attend 2 s la
    sortie de la boucle ; à l'expiration, il relâchait la poignée puis
    effaçait USB_ARRET et lançait une boucle neuve. L'ancienne, réveillée
    APRÈS l'effacement, ne voyait jamais l'arrêt et continuait. Mesuré en
    isolé : 2 fils `usb_loop` vivants. En régie : chaque geste part deux
    fois vers MA3 (un Go+ doublé saute une cue).

    Correctif : une GÉNÉRATION par boucle (`core.USB_GEN`), qu'elle vérifie à
    chaque tour et juste après sa lecture USB. Réinjection : vérification
    neutralisée → les 2 boucles doivent réapparaître.
    """
    section("67. Une seule boucle USB, même après une reconnexion lente")
    n = _boucles_apres_reconnexion(ui, wc)
    if n == 1:
        ok("tour plus long que l'attente de connect_wing + reconnexion : "
           "1 seule boucle usb_loop vivante "
           "(l'ancienne s'est retirée d'elle-même)")
    else:
        echec(f"{n} boucle(s) usb_loop vivante(s) après la reconnexion (attendu 1)",
              "deux boucles = deux lectures du même device et chaque geste "
              "envoyé deux fois à MA3")

    sauve = wc._generation_perimee
    try:
        wc._generation_perimee = lambda gen: False     # réinjection
        n_bug = _boucles_apres_reconnexion(ui, wc)
    finally:
        wc._generation_perimee = sauve
    if n_bug >= 2:
        ok(f"réinjection (génération ignorée) → {n_bug} boucles vivantes : "
           "le contrôle sait voir rouge")
    else:
        echec("réinjection de la double boucle NON détectée — contrôle aveugle",
              f"{n_bug} boucle(s) vivante(s) sans la génération")


# ── 68. Empreinte du firmware revérifiée juste avant l'envoi ──────────────────

def _envoi_firmware_simule(wi, contenu: bytes):
    """Lance le VRAI upload_firmware vers une wing simulée en bootloader,
    avec `contenu` comme firmware sur disque. Rend (résultat, octets de
    firmware écrits après le Hello, envoi_tente)."""
    import threading as _th
    dossier = Path(tempfile.mkdtemp())
    fichier = dossier / "wing_firmware.bin"
    fichier.write_bytes(contenu)
    ecrits = {"apres_hello": 0, "hello_vu": False}

    class _Dev:
        def write(self, ep, data, timeout=None):
            if bytes(data[:len(wi.HELLO_PKT)]) == bytes(wi.HELLO_PKT) \
                    and not ecrits["hello_vu"]:
                ecrits["hello_vu"] = True
            elif ecrits["hello_vu"]:
                ecrits["apres_hello"] += len(data)
            return len(data)

    sauv = {"etat": wi.etat_wing, "read": wi._read,
            "res": wing_firmware.resoudre_firmware, "journal": wi.JOURNAL}
    sortie = {"r": None}

    def corps():
        try:
            sortie["r"] = wi.upload_firmware(_Dev(), verbose=False)
        except Exception as e:           # au-delà du refus, peu importe
            sortie["r"] = f"{type(e).__name__}"

    try:
        wi.etat_wing = lambda d: "bootloader"
        wi._read = lambda dev, t=None: bytes(wi.HELLO_REP_BOOTLOADER) + b"\x00" * 60
        wing_firmware.resoudre_firmware = lambda: str(fichier)
        wi.JOURNAL = lambda *a, **k: None
        fil = _th.Thread(target=corps, daemon=True)
        fil.start()
        fil.join(timeout=15)
    finally:
        wi.etat_wing = sauv["etat"]; wi._read = sauv["read"]
        wing_firmware.resoudre_firmware = sauv["res"]; wi.JOURNAL = sauv["journal"]
        shutil.rmtree(dossier, ignore_errors=True)
    return sortie["r"], ecrits["apres_hello"], wi.DERNIER_ECHEC.get("envoi_tente")


def test_empreinte_firmware_a_l_envoi(wi):
    """Un firmware dont l'empreinte ne correspond pas n'est JAMAIS envoyé.

    🟠 Audit du 25/09/2026 : le SHA-256 n'était vérifié qu'à l'IMPORT. Un
    cache abîmé sur le disque, ou un `wing_firmware.bin` remplacé, partait
    tel quel vers le bootloader. On simule une wing en bootloader et un
    firmware altéré d'UN octet (même taille : le cache d'empreinte indexé par
    taille/date ne l'aurait pas vu). Réinjection : contrôle d'empreinte
    neutralisé → des octets doivent partir.
    """
    section("68. Empreinte du firmware revérifiée juste avant l'envoi")
    altere = bytes([0x5A]) * wing_firmware.FW_LONGUEUR
    r, octets, tente = _envoi_firmware_simule(wi, altere)
    if r is False and octets == 0 and not tente:
        ok("firmware altéré (même taille) : refusé, 0 octet envoyé à la wing, "
           "anti-martèlement non déclenché")
    else:
        echec("un firmware à l'empreinte fausse part vers la wing",
              f"résultat={r!r}, octets de firmware écrits={octets}, "
              f"envoi_tente={tente}")

    # Réinjection : sha256 qui répond toujours « bonne empreinte ».
    class _ShaComplaisant:
        def __init__(self, *a):
            pass
        def hexdigest(self):
            return wing_firmware.FW_SHA256
    class _HashlibBug:
        sha256 = _ShaComplaisant
    sauve = wi.hashlib
    try:
        wi.hashlib = _HashlibBug
        _, octets_bug, _ = _envoi_firmware_simule(wi, altere)
    finally:
        wi.hashlib = sauve
    if octets_bug > 0:
        ok(f"réinjection (empreinte non vérifiée) → {octets_bug} octets altérés "
           "envoyés : le contrôle sait voir rouge")
    else:
        echec("réinjection NON détectée — le contrôle est aveugle",
              "sans vérification, le firmware aurait dû partir")


# ── 69. Jeton d'API exigé sur les écritures et la file de frappes ─────────────

def _http(port, methode, chemin, jeton=None, origine=None, corps=None):
    """Une VRAIE requête HTTP vers le serveur de test → (code, texte)."""
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    entetes = {"Host": f"127.0.0.1:{port}"}
    if jeton is not None:
        entetes["X-Wing-Jeton"] = jeton
    if origine is not None:
        entetes["Origin"] = origine
    brut = json.dumps(corps).encode() if corps is not None else None
    if brut is not None:
        entetes["Content-Type"] = "application/json"
        entetes["Content-Length"] = str(len(brut))
    try:
        c.request(methode, chemin, body=brut, headers=entetes)
        r = c.getresponse()
        return r.status, r.read().decode("utf-8", "replace")
    finally:
        c.close()


def _scenario_jeton(ui):
    """Rend {nom_du_cas: code HTTP obtenu} contre un vrai serveur local."""
    import threading as _th
    from http.server import ThreadingHTTPServer
    import wing_handler

    sauv = {"port": ui.UI_PORT, "log": ui.log,
            "ws": {k: etat.E.WS.get(k) for k in ("helper_seen", "helper_trusted",
                                            "helper_build")}}
    serveur = ThreadingHTTPServer(("127.0.0.1", 0), wing_handler.Handler)
    port = serveur.server_address[1]
    fil = _th.Thread(target=serveur.serve_forever, daemon=True)
    j = ui.API_JETON
    res = {}
    try:
        ui.UI_PORT = port                      # _origine_sure compare le Host
        ui.log = lambda *a, **k: None
        fil.start()
        lang = {"lang": "xx"}                  # langue inconnue : aucun effet
        res["post_sans_jeton"] = _http(port, "POST", "/api/lang", corps=lang)[0]
        res["post_jeton_faux"] = _http(port, "POST", "/api/lang", jeton="x" * 43,
                                       corps=lang)[0]
        res["post_avec_jeton"] = _http(port, "POST", "/api/lang", jeton=j,
                                       corps=lang)[0]
        res["post_jeton_url"] = _http(port, "POST",
                                      f"/api/lang?jeton={j}", corps=lang)[0]
        res["frappes_sans_jeton"] = _http(port, "GET",
                                          "/api/keystrokes?trusted=1&build=0")[0]
        res["frappes_avec_jeton"] = _http(port, "GET",
                                          "/api/keystrokes?trusted=1&build=0",
                                          jeton=j)[0]
        # Défense en profondeur : le jeton ne dispense PAS du contrôle d'Origin.
        res["post_jeton_origine_etrangere"] = _http(
            port, "POST", "/api/lang", jeton=j, origine="http://evil.example",
            corps=lang)[0]
        code, page = _http(port, "GET", "/")
        res["page_porte_jeton"] = 200 if (code == 200 and
            f'<meta name="wing-jeton" content="{j}">' in page) else code
        res["lecture_sans_jeton"] = _http(port, "GET", "/api/instance")[0]
    finally:
        serveur.shutdown()
        serveur.server_close()
        ui.UI_PORT = sauv["port"]; ui.log = sauv["log"]
        etat.E.WS.update(sauv["ws"])
    return res


_ATTENDU_JETON = {
    "post_sans_jeton": 403, "post_jeton_faux": 403, "post_avec_jeton": 200,
    "post_jeton_url": 200, "frappes_sans_jeton": 403, "frappes_avec_jeton": 200,
    "post_jeton_origine_etrangere": 403, "page_porte_jeton": 200,
    "lecture_sans_jeton": 200,
}


def test_jeton_api(ui):
    """Tout POST et `GET /api/keystrokes` exigent le jeton de ce lancement.

    🟠 Audit du 25/09/2026 : une requête SANS en-tête Origin (tout programme
    local hors navigateur, de n'importe quel compte) passait sans condition —
    `curl -X POST …/api/uninstall` suffisait, et la file de frappes de
    l'assistant clavier (qui a l'autorisation Accessibilité) était ouverte.

    Joué contre un VRAI serveur HTTP local (port libre), avec de vraies
    requêtes. Vérifie aussi : le fichier du jeton en 0600, le JS qui le joint,
    les deux assistants clavier qui le présentent. Réinjection : vérification
    du jeton neutralisée → un POST sans jeton doit passer.

    ⚠️ Ce contrôle NE PROUVE PAS une protection contre un programme local qui
    lit d'abord la page (elle contient le jeton) — limite assumée, voir
    wing_jeton.py.
    """
    section("69. Jeton d'API exigé sur les écritures et la file de frappes")
    import os as _os
    import stat
    import wing_handler
    import wing_jeton

    # (a) Le serveur réel.
    res = _scenario_jeton(ui)
    faux = {k: (res.get(k), v) for k, v in _ATTENDU_JETON.items()
            if res.get(k) != v}
    if faux:
        echec(f"{len(faux)} cas du jeton d'API ne se comportent pas comme prévu",
              " ; ".join(f"{k} → {obt} (attendu {att})"
                         for k, (obt, att) in faux.items()))
    else:
        ok("vrai serveur : POST et file de frappes refusés sans jeton ou avec "
           "un faux (403), acceptés avec (en-tête ou ?jeton=), Origin étrangère "
           "toujours refusée, page porteuse du jeton, lectures libres")

    # (b) Le fichier pour l'assistant : 0600, relu à l'identique.
    d = Path(tempfile.mkdtemp())
    try:
        f = wing_jeton.ecrire_jeton("jeton-de-test", d / "sous" / "api_jeton")
        mode = stat.S_IMODE(_os.stat(f).st_mode)
        relu = wing_jeton.lire_jeton(f)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    if _os.name == "nt":
        note("Windows : permissions 0600 non vérifiables ici (ACL du dossier)")
    elif mode != 0o600 or relu != "jeton-de-test":
        echec("fichier du jeton mal protégé ou illisible",
              f"mode {oct(mode)} (attendu 0o600), relu {relu!r}")
    else:
        ok("fichier du jeton écrit en 0600 et relu à l'identique")

    # (c) Les clients : le JS et les deux assistants joignent le jeton.
    core_js = (HERE / "ui" / "core.js").read_text(encoding="utf-8")
    init_js = (HERE / "ui" / "init.js").read_text(encoding="utf-8")
    manques = []
    if '"X-Wing-Jeton": jetonApi()' not in core_js:
        manques.append("ui/core.js : api() ne joint plus le jeton")
    if "sendBeacon(\"/api/fermeture-onglet?jeton=\"" not in init_js:
        manques.append("ui/init.js : le beacon de fermeture n'a plus le jeton")
    for nom in ("wing_keyboard_macos.py", "wing_keyboard_windows.py"):
        src = (HERE / nom).read_text(encoding="utf-8")
        if "urllib.request.urlopen(" in src:
            manques.append(f"{nom} : un appel urlopen SANS jeton")
        if "wing_jeton.ouvrir(" not in src:
            manques.append(f"{nom} : n'utilise pas wing_jeton.ouvrir")
    if manques:
        echec("un client du serveur n'envoie pas le jeton", " ; ".join(manques))
    else:
        ok("clients : api() et le beacon (JS), assistants macOS et Windows "
           "joignent tous le jeton")

    # (d) Réinjection : plus de vérification du jeton.
    sauve = wing_handler.Handler._jeton_valide
    try:
        wing_handler.Handler._jeton_valide = lambda self: True
        res_bug = _scenario_jeton(ui)
    finally:
        wing_handler.Handler._jeton_valide = sauve
    if res_bug.get("post_sans_jeton") == 200 and \
            res_bug.get("frappes_sans_jeton") == 200:
        ok("réinjection (jeton non vérifié) → POST et file de frappes ouverts "
           "sans jeton : le contrôle sait voir rouge")
    else:
        echec("réinjection NON détectée — le contrôle est aveugle",
              f"{res_bug}")


# ── 70. Raccourcis clavier : liste blanche avant MA3 ──────────────────────────

_FRAPPES_PIEGEES = {
    "guillemet": 'Ctrl+X" ; Delete Show ; "',     # sortie de chaîne OSC
    "chevron":   "Ctrl+<",                         # XML de MA3 corrompu
    "balise":    "<b>",
    "vide_mod":  "Ctrl++Z",
}


def _tables_assistant():
    """Les tables de touches des DEUX assistants clavier, lues dans leur
    source (ni Quartz ni ctypes à importer ici)."""
    import ast
    def cles(fichier, nom):
        arbre = ast.parse((HERE / fichier).read_text(encoding="utf-8"))
        for n in ast.walk(arbre):
            if isinstance(n, ast.Assign) and any(
                    getattr(c, "id", None) == nom for c in n.targets):
                return {k.value for k in n.value.keys}
        return None
    return {"mac_mods": cles("wing_keyboard_macos.py", "MOD_FLAGS"),
            "mac_touches": cles("wing_keyboard_macos.py", "NAMED_KEYS"),
            "win_mods": cles("wing_keyboard_windows.py", "MOD_VK"),
            "win_touches": cles("wing_keyboard_windows.py", "NAMED_VK")}


def _envoi_ma3_piege(ui, frappe):
    """shcuts_envoyer(force) RÉEL, dans un bac à sable, avec `frappe` posée
    SANS validation sur « Store ». Rend (messages OSC, XML bien formé ?,
    journal) — ou None si aucune table MA3 n'existe sur cette machine."""
    import xml.etree.ElementTree as ET
    import wing_reglages as wr
    reel = Path.home() / ("MALightingTechnology/gma3_library/userprofiles"
                          "/keyboardshortcuts")
    sources = sorted(reel.glob("*.xml")) if reel.is_dir() else []
    if not sources:
        return None
    bac = Path(tempfile.mkdtemp(prefix="wingshcuts-"))
    bac_settings = Path(tempfile.mkdtemp(prefix="wingsettings-"))
    envoyes, journal = [], []

    class _Osc:
        def send_message(self, addr, valeur):
            envoyes.append(str(valeur))

    sauve = (ui.MA3_SHCUTS_DIR, ui.ma3_etat, wr.SETTINGS_FILE, ui.log)
    injection = etat.injecter()          # état neuf : profil, OSC, réglages
    injection.__enter__()
    try:
        for f in sources:
            shutil.copy2(f, bac / f.name)
        ui.MA3_SHCUTS_DIR, etat.E.OSC = bac, _Osc()
        wr.SETTINGS_FILE = bac_settings / "settings.json"
        ui.ma3_etat = lambda: {"actif": False}
        ui.log = lambda cle, **k: journal.append((cle, k))
        etat.E.PROFILE["console_keys"]["Store"] = frappe
        ui.shcuts_envoyer(force=True)
        time.sleep(0.6)            # les commandes partent sur des Timer
        cible = bac / f"{ui.MA3_SHCUTS_NOM}.xml"
        try:
            ET.fromstring(cible.read_bytes())
            bien_forme = True
        except Exception:
            bien_forme = False
        return envoyes, bien_forme, journal
    finally:
        injection.__exit__(None, None, None)
        ui.MA3_SHCUTS_DIR, ui.ma3_etat, wr.SETTINGS_FILE, ui.log = sauve
        shutil.rmtree(bac, ignore_errors=True)
        shutil.rmtree(bac_settings, ignore_errors=True)


def test_raccourcis_filtres(ui):
    """Une frappe de raccourci ne peut rien glisser dans MA3.

    🟠 Audit du 25/09/2026 : les frappes de `console_keys` partaient dans le
    XML de MA3 (seuls `&` et `"` échappés — `<` le corrompait) et dans une
    commande OSC `Set KeyboardShortcut … "<frappe>"` (où `"` sortait de la
    chaîne), sans aucun filtre, depuis un profil importé ou un champ de saisie.
    Vérifié à trois portes — chargement du profil, route /api/console/key,
    écriture vers MA3 — chacune avec sa réinjection.
    """
    section("70. Raccourcis clavier : liste blanche avant MA3")
    import wing_mapper as wm
    import wing_profils
    from smoke_core import _poster

    # (0) La liste blanche recopie les tables des assistants : identiques ?
    t = _tables_assistant()
    ecarts = []
    for nom, attendu in (("mac_mods", wm.MODIFICATEURS_RACCOURCI),
                         ("win_mods", wm.MODIFICATEURS_RACCOURCI),
                         ("mac_touches", wm.TOUCHES_NOMMEES),
                         ("win_touches", wm.TOUCHES_NOMMEES)):
        if t[nom] != attendu:
            ecarts.append(f"{nom} : en trop {sorted((attendu or set()) - (t[nom] or set()))},"
                          f" manquants {sorted((t[nom] or set()) - (attendu or set()))}")
    if ecarts:
        echec("la liste blanche des raccourcis diverge des assistants clavier",
              " ; ".join(ecarts))
    else:
        ok(f"liste blanche = tables des deux assistants ({len(wm.TOUCHES_NOMMEES)} "
           f"touches nommées, {len(wm.MODIFICATEURS_RACCOURCI)} modificateurs)")
    faux_defauts = [k for k, v in wm.CONSOLE_KEY_DEFAULTS.items()
                    if not wm.raccourci_valide(v)]
    if faux_defauts:
        echec("des raccourcis PAR DÉFAUT de l'app sont refusés par la liste blanche",
              ", ".join(faux_defauts))

    # (a) Porte 1 : import + chargement d'un profil piégé.
    p = wm.new_profile_from_defaults()
    p["console_keys"].update({f"Tok{i}": v for i, v in
                              enumerate(_FRAPPES_PIEGEES.values())})
    p["console_keys"]["Store"] = _FRAPPES_PIEGEES["guillemet"]
    charge, r = _importer_et_charger(p)
    if charge is None:
        echec("import du profil piégé refusé — contrôle aveugle", str(r))
    else:
        restes = [v for v in charge["console_keys"].values()
                  if not wm.raccourci_valide(v)]
        if restes:
            echec(f"{len(restes)} frappe(s) piégée(s) passent le chargement",
                  " ; ".join(map(repr, restes)))
        else:
            ok("profil importé : 5 frappes piégées neutralisées au chargement "
               f"(Store → {charge['console_keys']['Store']!r}, son défaut)")

    # (b) Porte 2 : la route de saisie.
    sauve_log = ui.log
    injection = etat.injecter()          # état neuf : le vrai profil n'est pas touché
    injection.__enter__()
    try:
        ui.log = lambda *a, **k: None
        refus = [_poster(ui, "/api/console/key", {"token": "Store", "key": v})
                 for v in _FRAPPES_PIEGEES.values()]
        pris = [v for v in _FRAPPES_PIEGEES.values()
                if etat.E.PROFILE["console_keys"].get("Store") == v]
        bon = _poster(ui, "/api/console/key", {"token": "Store", "key": "Ctrl+Alt+S"})
        bon_pris = etat.E.PROFILE["console_keys"].get("Store") == "Ctrl+Alt+S"
    finally:
        injection.__exit__(None, None, None)
        ui.log = sauve_log
    if any(r.get("ok") for r in refus) or pris:
        echec("la route /api/console/key accepte une frappe piégée",
              f"réponses {refus}, enregistrées {pris}")
    elif not (bon.get("ok") and bon_pris):
        echec("la route /api/console/key refuse une frappe légitime (Ctrl+Alt+S)",
              str(bon))
    else:
        ok("route /api/console/key : 4 frappes piégées refusées, Ctrl+Alt+S acceptée")

    # (c) Porte 3 : l'écriture vers MA3, frappe posée SANS validation (chemin
    #     d'entrée oublié). Rien ne doit partir en OSC, le XML reste valide.
    charge_utile = "Delete Show"
    res = _envoi_ma3_piege(ui, _FRAPPES_PIEGEES["guillemet"])
    if res is None:
        note("aucune table de raccourcis MA3 sur cette machine — porte 3 sautée")
        return
    envoyes, bien_forme, journal = res
    fuites = [m for m in envoyes if charge_utile in m]
    refusee = any(c == "journal.shcut.frappe_refusee" for c, _ in journal)
    if fuites or not bien_forme or not refusee:
        echec("une frappe piégée atteint MA3",
              f"OSC {fuites}, XML bien formé={bien_forme}, refus journalisé={refusee}")
    else:
        ok("écriture MA3 : frappe piégée refusée et journalisée, aucune "
           "commande OSC ne la porte, XML toujours bien formé")

    sauve = wm.raccourci_valide
    try:
        wm.raccourci_valide = lambda spec: True        # réinjection
        envoyes_bug, _, _ = _envoi_ma3_piege(ui, _FRAPPES_PIEGEES["guillemet"])
    finally:
        wm.raccourci_valide = sauve
    fuites_bug = [m for m in envoyes_bug if charge_utile in m]
    if fuites_bug:
        ok(f"réinjection (liste blanche retirée) → la commande OSC porte la "
           f"charge : {fuites_bug[0]!r} — le contrôle sait voir rouge")
    else:
        echec("réinjection NON détectée — la porte 3 est aveugle", str(envoyes_bug))


# ── 71. Scripts élevés (Windows) : amorce vérifiée, registre intouché ─────────

def _code_ps(texte: str) -> str:
    """Le CODE d'un .ps1, commentaires (# … et <# … #>) retirés."""
    import re
    texte = re.sub(r"<#.*?#>", "", texte, flags=re.S)
    return "\n".join(l.split("#", 1)[0] if not l.lstrip().startswith("#") else ""
                     for l in texte.splitlines())


def _defauts_lancement(params: str, script_src: str, attendus: dict) -> list:
    """Défauts de la ligne de commande powershell.exe construite par
    `_commande_eleve`. `attendus` : {nom de copie: sha256}."""
    import base64
    import shlex
    d = []
    morceaux = shlex.split(params, posix=False)
    if "-File" in morceaux:
        d.append("lancement par -File : le script élevé est le fichier ORIGINAL, modifiable")
    if "-EncodedCommand" not in morceaux:
        d.append("pas d'amorce -EncodedCommand")
        return d
    code = base64.b64decode(morceaux[morceaux.index("-EncodedCommand") + 1]) \
        .decode("utf-16-le")
    appel = [l for l in code.splitlines() if l.strip().startswith("& ")]
    if appel != ["    & (Join-Path $d 'script.ps1') @p"]:
        d.append(f"l'amorce n'exécute pas (seulement) la copie : {appel}")
    if script_src in "\n".join(l for l in code.splitlines()
                               if "$copies.Add" not in l):
        d.append("le chemin du script original apparaît hors de la copie")
    if "[System.IO.Directory]::CreateDirectory($d, $sec)" not in code \
            or "SetAccessRuleProtection($true, $false)" not in code:
        d.append("dossier de copie pas créé avec son ACL en une opération")
    sids = set(__import__("re").findall(r"S-1-5-[\d-]+", code))
    if sids != {"S-1-5-32-544", "S-1-5-18"}:
        d.append(f"ACL du dossier de copie : {sorted(sids)} (attendu Admins + SYSTEM)")
    if code.index("Get-FileHash") > code.index("& (Join-Path $d"):
        d.append("empreinte vérifiée APRÈS l'exécution")
    for nom, sha in attendus.items():
        if f"'{nom}', '{sha}'" not in code:
            d.append(f"empreinte de {nom} absente ou différente de la valeur figée")
    return d


def test_amorce_elevee_verifiee():
    """Les scripts lancés ÉLEVÉS sous Windows ne peuvent pas être substitués.

    🟠 Audit du 25/09/2026 (I3/I4 + deux points mineurs du .ps1).
      • I3 : l'installeur USBPcap était vérifié en NON élevé puis exécuté
        élevé depuis l'original modifiable, par un script lui-même modifiable.
        Désormais une amorce en -EncodedCommand copie script et installeur
        dans %ProgramData% (Admins + SYSTEM), vérifie leur empreinte, et
        n'exécute que la copie.
      • I4 : PendingFileRenameOperations n'est plus réécrit (gain nul,
        risque réel de décaler les paires).
      • `$args` (variable automatique) n'est plus écrasé ; `icacls` accorde
        la lecture au PROPRIÉTAIRE du dossier de travail, pas au compte élevé.

    ⚠️ PAS DE WINDOWS ICI : ce contrôle lit le CODE et décode la commande
    réellement construite. Rien n'a été exécuté sous PowerShell.
    """
    section("71. Scripts élevés (Windows) : amorce vérifiée, registre intouché")
    import hashlib
    import wing_firmware_capture as fc

    # (a) Empreintes figées = fichiers livrés.
    faux = []
    for chemin, sha in ((fc.SCRIPT_CAPTURE, fc.SCRIPT_CAPTURE_SHA256),
                        (fc.SCRIPT_RETIRER, fc.SCRIPT_RETIRER_SHA256)):
        reel = hashlib.sha256(Path(chemin).read_bytes()).hexdigest()
        if reel != sha:
            faux.append(f"{Path(chemin).name} : figée {sha[:12]}…, réelle {reel[:12]}…")
    if faux:
        echec("empreinte figée d'un script élevé périmée — mettre à jour "
              "SCRIPT_*_SHA256 dans wing_firmware_capture.py", " ; ".join(faux))
    else:
        ok("empreintes figées des deux scripts élevés = fichiers livrés")

    # (b) La commande réellement construite, pour les deux usages.
    cas = {
        "capture": (fc.SCRIPT_CAPTURE, fc._commande_eleve(
            fc.SCRIPT_CAPTURE, fc.SCRIPT_CAPTURE_SHA256,
            {"DejaPresent": "0", "StatusFile": r"C:\t\s.json"}, r"C:\t\s.json",
            fichiers={"InstallerPath": (fc.INSTALLER, fc.USBPCAP_SHA256)}),
            {"script.ps1": fc.SCRIPT_CAPTURE_SHA256,
             "InstallerPath.exe": fc.USBPCAP_SHA256}),
        "retrait": (fc.SCRIPT_RETIRER, fc._commande_eleve(
            fc.SCRIPT_RETIRER, fc.SCRIPT_RETIRER_SHA256,
            {"StatusFile": r"C:\t\s.json"}, r"C:\t\s.json"),
            {"script.ps1": fc.SCRIPT_RETIRER_SHA256}),
    }
    pb = {n: _defauts_lancement(p, src, att) for n, (src, p, att) in cas.items()}
    pb = {n: v for n, v in pb.items() if v}
    if pb:
        echec("l'amorce élevée ne protège pas l'exécution", str(pb))
    else:
        ok("capture et retrait : amorce -EncodedCommand, copie en %ProgramData% "
           "(Admins + SYSTEM, ACL posée à la création), empreintes vérifiées "
           "AVANT d'exécuter la copie — jamais l'original")
    ps = fc._powershell_systeme().replace("/", "\\")
    if not ps.lower().endswith("\\system32\\windowspowershell\\v1.0\\powershell.exe"):
        echec("powershell.exe n'est pas lancé par son chemin système absolu", ps)

    # (c) Les scripts eux-mêmes (code seul, commentaires retirés).
    defauts = []
    for chemin in (fc.SCRIPT_CAPTURE, fc.SCRIPT_RETIRER):
        code = _code_ps(Path(chemin).read_text(encoding="utf-8-sig"))
        nom = Path(chemin).name
        if "PendingFileRenameOperations" in code:
            defauts.append(f"{nom} touche encore PendingFileRenameOperations")
        if __import__("re").search(r"\$args\s*=", code):
            defauts.append(f"{nom} écrase la variable automatique $args")
    code_cap = _code_ps(Path(fc.SCRIPT_CAPTURE).read_text(encoding="utf-8-sig"))
    if "GetOwner(" not in code_cap or '"*${lecteur}:(OI)(CI)RX"' not in code_cap:
        defauts.append("icacls n'accorde pas la lecture au propriétaire du dossier de travail")
    if defauts:
        echec("script élevé non conforme à l'audit", " ; ".join(defauts))
    else:
        ok("scripts : registre PendingFileRenameOperations intouché, $args non "
           "écrasé, lecture accordée au propriétaire du dossier de travail")

    # (d) Réinjection : l'ancien lancement `-File <original>`.
    import subprocess as _sp
    ancien = _sp.list2cmdline(["-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                               "Bypass", "-File", fc.SCRIPT_CAPTURE, "-DejaPresent", "0"])
    if _defauts_lancement(ancien, fc.SCRIPT_CAPTURE, {}):
        ok("réinjection (ancien lancement -File de l'original) → détecté")
    else:
        echec("réinjection de l'ancien lancement NON détectée — contrôle aveugle")
    ancien_code = ("$pfro = Get-ItemProperty -Name PendingFileRenameOperations\n"
                   "$args = @('-d')")
    if "PendingFileRenameOperations" in _code_ps(ancien_code) and \
            __import__("re").search(r"\$args\s*=", _code_ps(ancien_code)):
        ok("réinjection (bloc registre + $args d'origine) → détectée")
    else:
        echec("réinjection du .ps1 d'origine NON détectée — contrôle aveugle")


# ── 72. Le journal ne touche plus au disque depuis la boucle USB ──────────────

def _chrono_journal(ui, wr, n=40, lenteur=0.25):
    """Journalise `n` lignes pendant que le disque « met `lenteur` s » par
    écriture. Rend (durée côté appelant en s, lignes finalement écrites)."""
    d = Path(tempfile.mkdtemp())
    fichier = d / "wing_server.log"
    sauv = {"f": wr.LOG_FILE, "ecr": wr._ecrire_lot}
    vrai = wr._ecrire_lot

    def lot_lent(lot):
        time.sleep(lenteur)                  # disque qui traîne
        vrai(lot)
    try:
        wr.vider_journal(2.0)                # rien d'étranger en file
        wr.LOG_FILE = fichier
        wr._ecrire_lot = lot_lent
        t0 = time.perf_counter()
        for i in range(n):
            wr.log(f"ENC1 Pan +{i}")         # ce que usb_loop écrit par cran
        duree = time.perf_counter() - t0
        wr.vider_journal(10.0)
        lignes = fichier.read_text(encoding="utf-8").splitlines() \
            if fichier.exists() else []
    finally:
        wr.LOG_FILE = sauv["f"]
        wr._ecrire_lot = sauv["ecr"]
        shutil.rmtree(d, ignore_errors=True)
    return duree, lignes


def test_journal_hors_boucle(ui):
    """Journaliser ne coûte plus un accès disque à l'appelant.

    🟠 Audit du 25/09/2026 (I7) : `_log_to_file` ouvrait/écrivait/fermait le
    fichier à chaque ligne, sous verrou, y compris depuis `usb_loop` (une
    ligne par cran de roue). Un disque lent ralentissait la wing. Désormais
    l'appelant dépose dans une file ; un seul fil écrit, par lots.

    Mesure : disque simulé à 0,25 s par écriture, 40 lignes journalisées.
    Réinjection : écriture synchrone d'origine → l'appelant paie le disque.
    """
    section("72. Le journal ne touche plus au disque depuis la boucle USB")
    import wing_reglages as wr

    duree, lignes = _chrono_journal(ui, wr)
    attendues = [f"ENC1 Pan +{i}" for i in range(40)]
    if duree > 0.05:
        echec(f"journaliser 40 lignes a coûté {duree*1000:.0f} ms à l'appelant",
              "le disque est encore touché depuis le fil qui journalise")
    elif [l.split("  ", 1)[-1] for l in lignes] != attendues:   # sans l'horodatage
        echec("des lignes manquent ou sont dans le désordre sur le disque",
              f"{len(lignes)} écrites sur 40 : {lignes[:3]}…")
    else:
        ok(f"40 lignes, disque lent (0,25 s/écriture) : {duree*1000:.1f} ms côté "
           "appelant, toutes écrites dans l'ordre après vider_journal()")

    # Les sorties brutales (os._exit / os.execv) doivent vider la file avant.
    import ast
    manques = []
    for fichier in ("wing_ui.py", "wing_connexion.py"):
        arbre = ast.parse((HERE / fichier).read_text(encoding="utf-8"))
        for fn in ast.walk(arbre):
            if not isinstance(fn, ast.FunctionDef):
                continue
            appels = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
            noms = [ast.unparse(c.func) for c in appels]
            sorties = [c for c in appels if ast.unparse(c.func) in ("os._exit", "os.execv")]
            for s in sorties:
                vidages = [c for c in appels if ast.unparse(c.func).endswith("vider_journal")
                           and c.lineno < s.lineno]
                if not vidages:
                    manques.append(f"{fichier}:{s.lineno} ({fn.name})")
    if manques:
        echec("une sortie brute du process ne vide pas le journal avant",
              ", ".join(manques))
    else:
        ok("chaque os._exit / os.execv du moteur est précédé de vider_journal()")

    # Réinjection : l'écriture synchrone d'origine.
    sauve = wr._log_to_file
    def synchrone(entree):
        wr._ecrire_lot([(entree, wr.LOG_FILE)])
    try:
        wr._log_to_file = synchrone
        ui._log_to_file = synchrone
        duree_bug, _ = _chrono_journal(ui, wr, n=4)
    finally:
        wr._log_to_file = sauve
        ui._log_to_file = sauve
    if duree_bug >= 0.9:
        ok(f"réinjection (écriture synchrone) → 4 lignes coûtent "
           f"{duree_bug:.2f} s à l'appelant : le contrôle sait voir rouge")
    else:
        echec("réinjection NON détectée — le contrôle est aveugle",
              f"{duree_bug:.3f} s pour 4 lignes synchrones")


# ── 73. STATE et SETTINGS : toute écriture sous core.LOCK ─────────────────────

_ACCESSEURS = ("etat_poser", "reglage_poser", "mark_dirty")
_METHODES_ECRITURE = ("update", "pop", "clear", "setdefault", "popitem")


def _est_etat(expr) -> bool:
    import ast
    nom = ast.unparse(expr)
    return nom in ("STATE", "SETTINGS", "core.STATE", "core.SETTINGS",
                   "etat.E.STATE", "etat.E.SETTINGS",
                   "ui.STATE", "ui.SETTINGS")


def _audit_verrou(source: str, fichier: str):
    """(écritures hors verrou, accesseurs appelés SOUS verrou) d'un fichier."""
    import ast
    arbre = ast.parse(source)
    hors, sous = [], []

    def cibles(n):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                yield from (t.elts if isinstance(t, ast.Tuple) else [t])
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign)):
            yield n.target
        elif isinstance(n, ast.Delete):
            yield from n.targets

    def visite(n, verrou, fonction):
        if isinstance(n, ast.With) and any(
                ast.unparse(i.context_expr) in ("LOCK", "core.LOCK", "etat.E.LOCK")
                for i in n.items):
            verrou = True
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fonction = n.name
            verrou = False          # un corps de fonction ne tient pas le verrou
        exempt = fonction in _ACCESSEURS
        for c in cibles(n):
            if isinstance(c, ast.Subscript) and _est_etat(c.value) \
                    and not verrou and not exempt:
                hors.append(f"{fichier}:{n.lineno} {ast.unparse(c)}")
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute) and f.attr in _METHODES_ECRITURE \
                    and _est_etat(f.value) and not verrou and not exempt:
                hors.append(f"{fichier}:{n.lineno} {ast.unparse(f)}()")
            nom = ast.unparse(f).split(".")[-1]
            if nom in _ACCESSEURS and verrou:
                sous.append(f"{fichier}:{n.lineno} {nom}() sous core.LOCK "
                            "(verrou NON réentrant : interblocage)")
        for c in ast.iter_child_nodes(n):
            visite(c, verrou, fonction)

    visite(arbre, False, None)
    return hors, sous


def _accesseur_indirect_sous_verrou(prof_max=3) -> list:
    """Fonctions appelées SOUS core.LOCK qui, elles-mêmes (jusqu'à
    `prof_max` niveaux), appellent un accesseur — interblocage indirect."""
    import ast
    defs = {}
    arbres = {}
    for f in sorted(HERE.glob("wing_*.py")):
        arbres[f.name] = ast.parse(f.read_text(encoding="utf-8"))
        for n in ast.walk(arbres[f.name]):
            if isinstance(n, ast.FunctionDef):
                defs.setdefault(n.name, []).append(n)

    def mene(fn, prof, vus):
        for c in ast.walk(fn):
            if isinstance(c, ast.Call):
                nom = ast.unparse(c.func).split(".")[-1]
                if nom in _ACCESSEURS:
                    return nom
                if prof < prof_max and nom in defs and nom not in vus:
                    vus.add(nom)
                    for d in defs[nom]:
                        r = mene(d, prof + 1, vus)
                        if r:
                            return f"{nom} → {r}"
        return None

    trouves = []
    for fichier, arbre in arbres.items():
        for w in ast.walk(arbre):
            if isinstance(w, ast.With) and any(
                    ast.unparse(i.context_expr) in ("LOCK", "core.LOCK", "etat.E.LOCK")
                    for i in w.items):
                for c in ast.walk(w):
                    if isinstance(c, ast.Call):
                        nom = ast.unparse(c.func).split(".")[-1]
                        for d in defs.get(nom, []):
                            r = mene(d, 1, {nom})
                            if r:
                                trouves.append(f"{fichier}:{c.lineno} {nom} → {r} "
                                               "(interblocage indirect)")
    return trouves


def test_ecritures_etat_sous_verrou():
    """Toute écriture de STATE / SETTINGS passe par core.LOCK.

    🟠 Audit du 25/09/2026 (I8). Des champs de STATE (wing, mode, resume_mode,
    want_connected…) et TOUS ceux de SETTINGS étaient écrits hors verrou,
    alors que la doc promettait un invariant — la correction du TOCTOU de
    `_post_mode` ne garantissait donc rien — et `save_settings` sérialisait
    SETTINGS pendant que d'autres fils le modifiaient.
    Tranché : ACCESSEURS (`etat_poser`, `reglage_poser`, `mark_dirty`), qui
    prennent le verrou. Ce contrôle balaie l'AST de chaque wing_*.py :
      • toute écriture (affectation, tuple compris, del, update/pop/clear/
        setdefault) de STATE/SETTINGS hors `with core.LOCK` → échec ;
      • tout accesseur appelé SOUS le verrou → échec (LOCK n'est pas
        réentrant : ce serait un interblocage de tout le moteur).
    Complète test_lock_sans_appel_lent, qui ne regarde que l'INTÉRIEUR des
    blocs verrouillés. Réinjection : les écritures d'origine de
    `connect_wing` / `_release_device`, et un accesseur sous verrou.
    """
    section("73. STATE et SETTINGS : toute écriture sous core.LOCK")
    hors, sous = [], []
    for f in sorted(HERE.glob("wing_*.py")):
        h, s = _audit_verrou(f.read_text(encoding="utf-8"), f.name)
        hors += h
        sous += s
    sous += _accesseur_indirect_sous_verrou()
    if hors:
        echec(f"{len(hors)} écriture(s) de STATE/SETTINGS hors core.LOCK",
              " ; ".join(hors[:12]) + (" …" if len(hors) > 12 else ""))
    if sous:
        echec(f"{len(sous)} accesseur(s) appelé(s) sous core.LOCK", " ; ".join(sous))
    if not hors and not sous:
        ok("toutes les écritures de STATE/SETTINGS des modules wing_*.py sont "
           "sous core.LOCK ou passent par un accesseur, aucun accesseur sous verrou")

    bug = ("def _release_device():\n"
           "    core.DEV[0] = None\n"
           "    core.STATE['wing'] = False\n"
           "def f():\n"
           "    with core.LOCK:\n"
           "        core.etat_poser(mode='idle')\n")
    h, s = _audit_verrou(bug, "réinjection")
    if h and s:
        ok("réinjection (écriture d'origine hors verrou + accesseur sous verrou) "
           "→ les deux détectés")
    else:
        echec("réinjection NON détectée — contrôle aveugle", f"{h} / {s}")


# ── 74. Serveur HTTP : corps invalide → 400, route qui lève → 500 ─────────────

def _http_brut(port, requete: bytes, delai=3.0):
    """Envoie des octets bruts ; rend (code HTTP ou None si coupé sans
    réponse, corps). Timeout court : une requête qui BLOQUE compte comme
    « pas de réponse »."""
    import socket
    s = socket.create_connection(("127.0.0.1", port), timeout=delai)
    try:
        s.sendall(requete)
        try:
            s.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        morceaux = []
        try:
            while True:
                m = s.recv(65536)
                if not m:
                    break
                morceaux.append(m)
        except (socket.timeout, ConnectionResetError):
            pass
    finally:
        s.close()
    brut = b"".join(morceaux).decode("utf-8", "replace")
    if not brut.startswith("HTTP/"):
        return None, brut
    return int(brut.split()[1]), brut.split("\r\n\r\n", 1)[-1]


def _scenario_robuste(ui):
    import threading as _th
    from http.server import ThreadingHTTPServer
    import wing_handler
    serveur = ThreadingHTTPServer(("127.0.0.1", 0), wing_handler.Handler)
    # La réinjection fait EXPRÈS lever le Handler : socketserver imprimerait
    # la trace sur stderr, et du bruit attendu masquerait une vraie trace.
    serveur.handle_error = lambda *a: None
    port = serveur.server_address[1]
    _th.Thread(target=serveur.serve_forever, daemon=True).start()
    sauv = {"port": ui.UI_PORT, "log": ui.log}
    j = ui.API_JETON

    def req(chemin, corps: bytes, longueur=None):
        lg = str(len(corps)) if longueur is None else longueur
        return (f"POST {chemin} HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\n"
                f"X-Wing-Jeton: {j}\r\nContent-Type: application/json\r\n"
                f"Content-Length: {lg}\r\n\r\n").encode() + corps
    res = {}
    try:
        ui.UI_PORT = port
        ui.log = lambda *a, **k: None
        res["json_casse"] = _http_brut(port, req("/api/lang", b"{pas du json"))
        res["longueur_texte"] = _http_brut(port, req("/api/lang", b"{}", "abc"))
        res["longueur_negative"] = _http_brut(port, req("/api/lang", b"{}", "-5"))
        res["tableau"] = _http_brut(port, req("/api/lang", b"[1, 2]"))
        # Une route qui lève une VRAIE exception interne : depuis la
        # validation centrale (§79), un paramètre invalide donne un 400 ; on
        # casse donc volontairement une route le temps d'une requête.
        vraie = wing_handler.Handler._post_learn_clear
        wing_handler.Handler._post_learn_clear = lambda self, body: 1 / 0
        try:
            res["route_leve"] = _http_brut(port, req("/api/learn/clear", b"{}"))
        finally:
            wing_handler.Handler._post_learn_clear = vraie
        res["normal"] = _http_brut(port, req("/api/lang", b'{"lang": "xx"}'))
    finally:
        serveur.shutdown()
        serveur.server_close()
        ui.UI_PORT, ui.log = sauv["port"], sauv["log"]
    return res


def test_handler_robuste(ui):
    """Une requête mal formée ou une route qui lève reçoit une réponse JSON.

    🟡 Audit du 25/09/2026 : `int(Content-Length)` et `json.loads` sans
    filet ; toute exception coupait la connexion SANS réponse, et une longueur
    négative devenait `rfile.read(-1)` — fil de requête bloqué. Joué contre un
    VRAI serveur, en octets bruts. Réinjection : l'ancien `_read_body` et
    l'appel de route sans filet.
    """
    section("74. Serveur HTTP : corps invalide → 400, route qui lève → 500")
    import wing_handler
    attendu = {"json_casse": 400, "longueur_texte": 400, "longueur_negative": 400,
               "tableau": 400, "route_leve": 500, "normal": 200}
    res = _scenario_robuste(ui)
    faux = {k: res[k][0] for k, v in attendu.items() if res[k][0] != v}
    json_ok = all(res[k][1].lstrip().startswith("{") for k in attendu)
    if faux or not json_ok:
        echec("le serveur ne répond pas proprement aux requêtes invalides",
              f"codes {faux or '—'} ; corps JSON partout : {json_ok}")
    else:
        ok("JSON cassé, Content-Length illisible ou négatif, corps non-objet → "
           "400 JSON ; route qui lève (ZeroDivisionError) → 500 JSON")

    H = wing_handler.Handler
    sauv = (H._read_body, H._executer)
    def ancien_read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length:
            return json.loads(self.rfile.read(length))
        return {}
    def ancien_executer(self, route, *args):
        route(*args)
    try:
        H._read_body, H._executer = ancien_read_body, ancien_executer
        bug = _scenario_robuste(ui)
    finally:
        H._read_body, H._executer = sauv
    sans_reponse = [k for k in ("json_casse", "longueur_texte", "route_leve")
                    if bug[k][0] is None]
    if len(sans_reponse) == 3:
        ok("réinjection (ancien _read_body, route sans filet) → connexions "
           "coupées sans réponse : le contrôle sait voir rouge")
    else:
        echec("réinjection NON détectée — contrôle aveugle", str(bug))


# ── 75. /api/profile/load confiné au dossier des profils ──────────────────────

def test_profil_load_confine(ui):
    """`/api/profile/load` ne charge QUE dans le dossier des profils.

    🟡 Audit du 25/09/2026 : pas de confinement (contrairement à `delete`).
    `PROFILE_DIR / "/chemin/absolu.json"` vaut le chemin absolu, `../` remonte :
    n'importe quel JSON du disque se chargeait comme profil actif.
    Réinjection : l'ancienne construction du chemin.
    """
    section("75. /api/profile/load confiné au dossier des profils")
    import wing_handler
    import wing_mapper as wm
    from smoke_core import _poster

    d = Path(tempfile.mkdtemp())
    dossier = d / "profiles"
    dossier.mkdir()
    dehors = d / "dehors.json"
    wm_prof = wm.new_profile_from_defaults()
    dehors.write_text(json.dumps(dict(wm_prof, name="HORS DOSSIER")),
                      encoding="utf-8")
    (dossier / "legit.json").write_text(json.dumps(dict(wm_prof, name="LEGIT")),
                                        encoding="utf-8")
    sauv = (wm.PROFILE_DIR, json.loads(json.dumps(etat.E.PROFILE)), ui.log,
            etat.E.STATE.get("dirty"))

    def charger(nom):
        r = _poster(ui, "/api/profile/load", {"file": nom})
        return r, etat.E.PROFILE.get("name")

    try:
        wm.PROFILE_DIR = dossier
        ui.log = lambda *a, **k: None
        essais = {n: charger(n) for n in ("../dehors.json", str(dehors),
                                          "sous/../../dehors.json")}
        legit = charger("legit.json")

        # Réinjection : l'ancienne construction, sans confinement.
        import wing_profils
        sauve_cp = wing_profils.chemin_profil
        wing_profils.chemin_profil = lambda f: wm.PROFILE_DIR / f
        try:
            bug = charger("../dehors.json")
        finally:
            wing_profils.chemin_profil = sauve_cp
    finally:
        wm.PROFILE_DIR = sauv[0]
        etat.E.PROFILE.clear(); etat.E.PROFILE.update(sauv[1])
        ui.log = sauv[2]; etat.E.STATE["dirty"] = sauv[3]
        shutil.rmtree(d, ignore_errors=True)

    fuites = [n for n, (_, nom) in essais.items() if nom == "HORS DOSSIER"]
    if fuites:
        echec("un profil HORS du dossier des profils se charge", ", ".join(fuites))
    elif legit[1] != "LEGIT":
        echec("un profil légitime ne se charge plus", str(legit[0]))
    else:
        ok("../, chemin absolu, sous/../../ refusés ; profil du dossier chargé")
    if bug[1] == "HORS DOSSIER":
        ok("réinjection (chemin non confiné) → le fichier extérieur se charge : "
           "le contrôle sait voir rouge")
    else:
        echec("réinjection NON détectée — contrôle aveugle", str(bug[0]))


# ── 76. Écritures DMX/LED refusées : comptées et affichées ────────────────────

def test_ecritures_usb_comptees(ui):
    """Une écriture DMX/LED refusée par la wing ne passe plus inaperçue.

    🟡 Audit du 25/09/2026 : `except Exception: pass` dans `cycle_dmx`. On
    fait tourner le VRAI `cycle_dmx` avec une wing simulée qui accepte le
    POLL mais refuse les paquets LED/DMX : le compteur doit monter, l'API et
    l'interface l'exposer. Réinjection : le `pass` d'origine.
    """
    section("76. Écritures DMX/LED refusées : comptées et affichées")
    import ast
    import wing_connexion as wc

    class _Dev:
        def write(self, ep, data, timeout=None):
            if bytes(data[:len(ui.wb.POLL)]) == bytes(ui.wb.POLL):
                return len(data)
            raise OSError("écriture refusée (simulée)")

    sauv = {"read": ui.wb.read_pkt, "drain": ui.wb.drain,
            "ko": etat.E.BOUCLE.get("ecritures_ko", 0), "err": etat.E.BOUCLE.get("ecriture_err", "")}
    try:
        ui.wb.read_pkt = lambda dev, timeout_ms=300: b"\x00" * 96
        ui.wb.drain = lambda dev, n, timeout_ms=None: None
        etat.E.BOUCLE["ecritures_ko"] = 0
        for _ in range(3):
            wc.cycle_dmx(_Dev())
        n = etat.E.BOUCLE["ecritures_ko"]
        err = etat.E.BOUCLE.get("ecriture_err", "")
        # Exposé par le VRAI /api/status (pas une recherche de texte).
        import wing_statut
        b = wing_statut.statut()["boucle"]
        expose_api = b.get("ecritures_ko") == n and b.get("ecriture_err") == err
    finally:
        ui.wb.read_pkt, ui.wb.drain = sauv["read"], sauv["drain"]
        etat.E.BOUCLE["ecritures_ko"], etat.E.BOUCLE["ecriture_err"] = sauv["ko"], sauv["err"]

    bridge = (HERE / "ui" / "bridge.js").read_text(encoding="utf-8")
    expose = expose_api and "s.boucle.ecritures_ko" in bridge
    if n >= 3 and "refusée" in err and expose:
        ok(f"3 cycles, paquets LED/DMX refusés → {n} écritures comptées, "
           "dernière erreur retenue, exposées par /api/status et la pastille Bridge")
    else:
        echec("les écritures DMX/LED refusées restent invisibles",
              f"compteur {n}, erreur {err!r}, exposé : {expose}")

    def avale(source: str) -> bool:
        """cycle_dmx contient-il un `except Exception: pass` ?"""
        for n in ast.walk(ast.parse(source)):
            if isinstance(n, ast.ExceptHandler) and \
                    len(n.body) == 1 and isinstance(n.body[0], ast.Pass):
                return True
        return False
    fn = next(n for n in ast.walk(ast.parse((HERE / "wing_connexion.py")
              .read_text(encoding="utf-8")))
              if isinstance(n, ast.FunctionDef) and n.name == "cycle_dmx")
    origine = ("def cycle_dmx(dev):\n    for pkt in paquets:\n        try:\n"
               "            dev.write(1, pkt)\n        except Exception:\n"
               "            pass\n")
    if avale(ast.unparse(fn)):
        echec("cycle_dmx avale encore une exception en silence")
    elif avale(origine):
        ok("aucun `except: pass` dans cycle_dmx ; réinjection (le `pass` "
           "d'origine) → détectée")
    else:
        echec("réinjection NON détectée — contrôle aveugle")


# ── 77. Sauvegardes simultanées d'un même profil ──────────────────────────────

def _sauvegardes_concurrentes(sauver, dossier: Path, n=150):
    import threading as _th
    import wing_mapper as wm
    erreurs = []
    cible = dossier / "concurrent.json"

    def fil(k):
        for i in range(n):
            try:
                sauver(dict(wm.new_profile_from_defaults(), name=f"t{k}-{i}"), cible)
            except Exception as e:
                erreurs.append(f"{type(e).__name__}: {e}")
    fils = [_th.Thread(target=fil, args=(k,)) for k in range(3)]
    for f in fils:
        f.start()
    for f in fils:
        f.join()
    try:
        json.loads(cible.read_text(encoding="utf-8"))
        valide = True
    except Exception:
        valide = False
    restes = list(dossier.glob("*.part"))
    return erreurs, valide, restes


def test_part_unique():
    """Deux sauvegardes simultanées du même profil ne se marchent plus dessus.

    🟡 Audit du 25/09/2026 : le temporaire s'appelait toujours `profil.part`.
    3 fils × 150 sauvegardes du MÊME profil : aucune erreur, JSON final
    valide, aucun `.part` orphelin. Réinjection : le nom fixe d'origine.
    """
    section("77. Sauvegardes simultanées d'un même profil")
    import os as _os
    import wing_mapper as wm
    d = Path(tempfile.mkdtemp())
    sauve_dir = wm.PROFILE_DIR
    try:
        wm.PROFILE_DIR = d
        erreurs, valide, restes = _sauvegardes_concurrentes(wm.save_profile, d)

        def ancien(profile, path):           # nom de temporaire FIXE
            tmp = path.with_suffix(".part")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(profile, f, indent=2, ensure_ascii=False)
            _os.replace(tmp, path)
        d2 = Path(tempfile.mkdtemp())
        erreurs_bug, valide_bug, _ = _sauvegardes_concurrentes(ancien, d2)
        shutil.rmtree(d2, ignore_errors=True)
    finally:
        wm.PROFILE_DIR = sauve_dir
        shutil.rmtree(d, ignore_errors=True)
    if erreurs or not valide or restes:
        echec("sauvegardes concurrentes en conflit",
              f"{len(erreurs)} erreur(s) {erreurs[:2]}, JSON valide {valide}, "
              f"orphelins {[r.name for r in restes]}")
    else:
        ok("3 fils × 150 sauvegardes du même profil : 0 erreur, JSON final "
           "valide, aucun temporaire orphelin")
    if erreurs_bug or not valide_bug:
        ok(f"réinjection (nom fixe `.part`) → {len(erreurs_bug)} erreur(s), "
           f"JSON valide {valide_bug} : le contrôle sait voir rouge")
    else:
        note("réinjection du nom fixe : aucune collision cette fois-ci "
             "(course non déterministe) — le contrôle n'a pas vu rouge à ce passage")


# ── 78. DMX réseau « local uniquement » ───────────────────────────────────────

_SCRIPT_DMX = r"""
import json, socket, sys, threading, time
sys.path.insert(0, sys.argv[1])
import etat, wing_ui as ui, wing_connexion as wc
ui.log = lambda *a, **k: None
etat.E.SETTINGS["dmx_local"] = sys.argv[2] == "1"
etat.E.DMX["uni"][:] = [1, 2]
def port_libre():
    t = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); t.bind(("", 0))
    p = t.getsockname()[1]; t.close(); return p
wc.ARTNET_PORT, wc.SACN_PORT = port_libre(), port_libre()
threading.Thread(target=wc.dmx_listener, daemon=True).start()
time.sleep(0.5)
def artnet(valeur):
    return (b"Art-Net\x00" + (0x5000).to_bytes(2, "little") + b"\x00\x0e\x00\x00"
            + (0).to_bytes(2, "little") + (512).to_bytes(2, "big") + bytes([valeur]) * 512)
res = {}
for nom, ip, val in (("bouclage", "127.0.0.1", 11), ("reseau", sys.argv[3], 22)):
    if not ip:
        res[nom] = None
        continue
    etat.E.DMX["buf"][0][:] = bytes(512)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((ip, 0))
    s.sendto(artnet(val), ("127.0.0.1" if nom == "bouclage" else ip, wc.ARTNET_PORT))
    s.close()
    time.sleep(0.8)
    res[nom] = etat.E.DMX["buf"][0][0]
res["refuses"] = etat.E.DMX["refuses"]
print("@@" + json.dumps(res))
"""


def _ips_reseau():
    """Adresses NON bouclage de cette machine, la route par défaut d'abord
    (aucun paquet n'est émis pour les trouver)."""
    import re
    import socket
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))          # TEST-NET : rien n'est envoyé
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        ips += socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        pass
    try:                                     # macOS/Linux : toutes les interfaces
        sortie = subprocess.run(["ifconfig"], capture_output=True, text=True,
                                timeout=5).stdout
        ips += re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", sortie)
    except (OSError, subprocess.SubprocessError):
        pass
    vus = []
    for ip in ips:
        if not ip.startswith("127.") and ip not in vus:
            vus.append(ip)
    return vus


def _ip_joignable():
    """(ip, résultat option DÉCOCHÉE) pour la 1ʳᵉ adresse dont un paquet
    envoyé à soi-même REVIENT vraiment. ⚠️ La route par défaut ne suffit pas :
    avec un VPN (interface utun point-à-point, 10.5.0.2 mesuré le 25/09/2026),
    le paquet n'arrive jamais, filtre ou pas — le contrôle échouait sur un code
    juste. Rend ("", résultat) si aucune ne revient, ou ("", {"erreur"…}) si le
    script plante."""
    dernier = {}
    for ip in _ips_reseau()[:5]:
        dernier = _dmx_reel(False, ip)
        if "erreur" in dernier:
            return "", dernier
        if dernier.get("reseau") == 22:
            return ip, dernier
    return "", dernier


def _dmx_reel(local: bool, ip: str):
    import sys as _sys
    r = subprocess.run([_sys.executable, "-c", _SCRIPT_DMX, str(HERE),
                        "1" if local else "0", ip],
                       capture_output=True, text=True, timeout=30)
    ligne = [l for l in r.stdout.splitlines() if l.startswith("@@")]
    return json.loads(ligne[0][2:]) if ligne else {"erreur": r.stderr[-300:]}


def test_dmx_local():
    """« Local uniquement » : le DMX réseau d'un autre poste est refusé.

    🟡 Audit du 25/09/2026 : sACN/Art-Net écoutés sur toutes les interfaces,
    donc n'importe quel poste du réseau pilotait les XLR. Nouvelle option,
    désactivée par défaut. Joué avec de VRAIS paquets Art-Net UDP, dans un
    process séparé (le fil d'écoute ne s'arrête pas) : un depuis 127.0.0.1,
    un depuis l'adresse réseau de cette machine. Réinjection : option
    décochée → le paquet réseau passe.
    """
    section("78. DMX réseau « local uniquement »")
    import wing_connexion as wc
    import wing_ui as ui
    if etat.E.SETTINGS.get("dmx_local") is not False:
        echec("« local uniquement » n'est pas désactivé par défaut",
              repr(etat.E.SETTINGS.get("dmx_local")))
    table = {("127.0.0.1", True): True, ("::1", True): True,
             ("192.168.1.20", True): False, ("10.0.0.5", True): False,
             ("pas-une-ip", True): False, ("192.168.1.20", False): True}
    faux = [k for k, v in table.items() if wc._source_dmx_acceptee(*k) != v]
    if faux:
        echec("filtre de source DMX faux", str(faux))
    ip, ouvert = _ip_joignable()
    local = ouvert if "erreur" in ouvert else _dmx_reel(True, ip)
    if "erreur" in local:
        # ⚠️ Seule une vraie impossibilité d'ÉCOUTER est une remarque. Toute
        # autre erreur du script (nom déplacé, import…) est un ÉCHEC : sinon le
        # contrôle devient aveugle en restant vert — c'est arrivé pendant la
        # migration D1 (script en chaîne, non réécrit par l'outil).
        if "Address already in use" in local["erreur"] or "Errno 48" in local["erreur"]:
            note(f"écoute DMX impossible ici (port occupé) : {local['erreur'][-120:]}")
        else:
            echec("le script d'écoute DMX a planté — contrôle aveugle",
                  local["erreur"][-300:])
        return
    if not ip:
        note("aucune adresse réseau de cette machine ne se renvoie un paquet "
             f"(candidates : {_ips_reseau()}) — seul le bouclage a été vérifié")
    if local.get("bouclage") == 11 and (not ip or (local.get("reseau") == 0
                                                  and local.get("refuses", 0) >= 1)):
        ok(f"local uniquement : paquet de 127.0.0.1 accepté, paquet de {ip or '—'} "
           f"refusé ({local.get('refuses')} écarté)")
    else:
        echec("« local uniquement » ne filtre pas comme annoncé", str(local))
    if ip:
        if ouvert.get("reseau") == 22:
            ok(f"réinjection (option décochée) → le paquet de {ip} passe : le "
               "contrôle sait voir rouge")
        else:
            echec("réinjection NON détectée — contrôle aveugle", str(ouvert))


# ── 79. Entrées de l'API validées à un seul endroit ───────────────────────────

def _poster_code(ui, chemin, corps):
    """Comme smoke_core._poster, mais rend AUSSI le code HTTP."""
    import io
    h = ui.Handler.__new__(ui.Handler)
    h.path = chemin
    rendu = {}
    def _json(d, code=200):
        rendu.clear(); rendu.update(d); rendu["_code"] = code
    h._json = _json
    brut = json.dumps(corps).encode()
    h.rfile = io.BytesIO(brut)
    h.headers = {"Content-Length": str(len(brut)), "Origin": "http://127.0.0.1:8765",
                 "Host": "127.0.0.1:8765", "X-Wing-Jeton": ui.API_JETON}
    h.command = "POST"
    h.send_response = lambda *a, **k: None
    h.send_header = lambda *a, **k: None
    h.end_headers = lambda *a, **k: None
    h.wfile = io.BytesIO()
    h.do_POST()
    return rendu.get("_code"), rendu


def _scenario_validation(ui):
    """Rend {cas: (code, effet observé)}."""
    import wing_mapper as wm
    sauv = (ui.log, ui.save_settings)
    res = {}
    injection = etat.injecter()          # état neuf, isolé
    injection.__enter__()
    try:
        ui.log = lambda *a, **k: None
        ui.save_settings = lambda: True
        n_noms = len(etat.E.PROFILE.get("fader_noms", []))
        c, _ = _poster_code(ui, "/api/fader/nom", {"index": 10000, "nom": "x"})
        res["nom_index_geant"] = (c, len(etat.E.PROFILE.get("fader_noms", [])) - n_noms)
        dernier = etat.E.PROFILE["fader_noms"][-1]
        c, _ = _poster_code(ui, "/api/fader/nom", {"index": -1, "nom": "PIEGE"})
        res["nom_index_negatif"] = (c, etat.E.PROFILE["fader_noms"][-1] != dernier)
        etat.E.SETTINGS["suivre_ma3"] = True
        c, _ = _poster_code(ui, "/api/suivre_ma3", {"actif": "false"})
        res["booleen_chaine"] = (c, etat.E.SETTINGS["suivre_ma3"])
        avant = dict(etat.E.PROFILE["faders"][0])
        c, _ = _poster_code(ui, "/api/fader", {"index": 0, "kind": "executor",
                                               "exec": "101; Delete Show"})
        res["exec_texte"] = (c, etat.E.PROFILE["faders"][0] != avant)
        c, _ = _poster_code(ui, "/api/encoders", {"step": 1e9})
        res["pas_geant"] = (c, etat.E.PROFILE["enc_step"])
        c, _ = _poster_code(ui, "/api/fader", {"index": 2, "kind": "crossfade",
                                               "exec": 105, "suivre": False})
        f2 = dict(etat.E.PROFILE["faders"][2])
        res["fader_valide"] = (c, f2)
        # Ce que l'interface pose doit être accepté tel quel au rechargement.
        p = json.loads(json.dumps(etat.E.PROFILE))
        res["coherent_avec_C2"] = (200, wm.valider_types(p))
        c, _ = _poster_code(ui, "/api/assign", {"key": "0x97", "type": "exec",
                                                "value": "105", "func": "Flash"})
        res["assign_exec"] = (c, etat.E.PROFILE["buttons"].get("0x97"))
    finally:
        injection.__exit__(None, None, None)
        ui.log, ui.save_settings = sauv
    return res


def test_validation_entrees(ui):
    """Les paramètres de l'API sont validés à un seul endroit (wing_validation).

    🟠 Audit du 25/09/2026 (D3). Les routes lisaient leurs paramètres à la
    main ; défauts réels rejoués ici :
      • `/api/fader/nom` index 10 000 → 10 000 étiquettes vides ajoutées ;
        index −1 → un fader renommé depuis la fin ;
      • `bool("false")` vaut True : décocher une case pouvait la COCHER ;
      • un `exec` texte partait dans la commande MA3 ;
      • un pas de roue démesuré acceptée sans borne.
    Et deux garanties : un fader posé par l'interface est accepté tel quel par
    la validation des profils (C2), une affectation d'executor produit la
    bonne commande. Réinjection : l'ancienne lecture permissive.
    """
    section("79. Entrées de l'API validées à un seul endroit")
    import wing_validation as wv
    res = _scenario_validation(ui)
    attendu = {
        "nom_index_geant": (400, 0), "nom_index_negatif": (400, False),
        "booleen_chaine": (400, True), "exec_texte": (400, False),
        "fader_valide": (200, {"kind": "crossfade", "exec": 105, "suivre": False}),
        "coherent_avec_C2": (200, []),
        "assign_exec": (200, "Flash On Executor 105"),
    }
    faux = {k: res[k] for k, v in attendu.items() if res[k] != v}
    if res["pas_geant"][0] != 400 or res["pas_geant"][1] > 1000:
        faux["pas_geant"] = res["pas_geant"]
    if faux:
        echec(f"{len(faux)} cas de validation d'entrée faux", str(faux))
    else:
        ok("index 10 000 / −1, \"false\", exec texte, pas 1e9 → 400 sans effet ; "
           "fader et affectation valides posés correctement, et acceptés tels "
           "quels par la validation des profils")

    # Chaque message de refus doit se RENDRE (ni clé brute, ni « {x} »
    # restant) — un message mal paramétré a déjà transformé tous les 400 en
    # 500 pendant l'écriture de ce module.
    essais = [lambda: wv.entier({"a": "x"}, "a", 0, 1),
              lambda: wv.entier({"a": 5}, "a", 0, 1),
              lambda: wv.entier({}, "a", 0, 1),
              lambda: wv.hexa({"a": "zz"}, "a", 0, 1),
              lambda: wv.reel({"a": "x"}, "a", 0, 1),
              lambda: wv.booleen({"a": "false"}, "a"),
              lambda: wv.texte({"a": 3}, "a", 5),
              lambda: wv.texte({"a": "xxxxxxx"}, "a", 5),
              lambda: wv.choix({"a": "z"}, "a", ("x", "y")),
              lambda: wv.groupes_encodeurs({"a": [[1]]}, "a"),
              lambda: wv.entier([], "a", 0, 1)]
    mauvais = []
    for i, f in enumerate(essais):
        try:
            f()
            mauvais.append(f"essai {i} : aucun refus")
        except wv.EntreeInvalide as e:
            if "{" in str(e) or "err.entree" in str(e):
                mauvais.append(f"essai {i} : {e}")
        except Exception as e:
            mauvais.append(f"essai {i} : {type(e).__name__}: {e}")
    if mauvais:
        echec("message de refus mal rendu ou refus manquant", " ; ".join(mauvais))
    else:
        ok(f"{len(essais)} refus de wing_validation : chacun lève EntreeInvalide "
           "avec un message entièrement rendu")

    sauv = (wv.entier, wv.booleen)
    def entier_permissif(body, cle, mini, maxi, defaut=None):
        return int(body.get(cle, defaut))
    def booleen_permissif(body, cle, defaut=None):
        return bool(body.get(cle, defaut))
    try:
        wv.entier, wv.booleen = entier_permissif, booleen_permissif
        bug = _scenario_validation(ui)
    finally:
        wv.entier, wv.booleen = sauv
    if bug["nom_index_geant"][1] > 1000 and bug["booleen_chaine"][1] is True \
            and bug["booleen_chaine"][0] == 200:
        ok(f"réinjection (lecture permissive d'origine) → "
           f"{bug['nom_index_geant'][1]} étiquettes ajoutées, \"false\" lu vrai : "
           "le contrôle sait voir rouge")
    else:
        echec("réinjection NON détectée — contrôle aveugle", str(bug))


# ── 80. Handler mince, noms déménagés gardés ──────────────────────────────────

def _handler_epais(source: str) -> list:
    """Ce qui, dans un Handler, relève d'un autre module (lecture à la main
    des paramètres, construction de commandes MA3, dialogue système)."""
    import ast
    import re
    defauts = []
    code = "\n".join(l.split("#", 1)[0] for l in source.splitlines())
    for motif, quoi in ((r"\b(int|float|bool)\(\s*body\b", "paramètre lu à la main"),
                        (r"\bbody\.get\([^)]*\)\.strip\(", "paramètre lu à la main"),
                        (r"osascript|ShellExecute|OpenFileDialog", "dialogue système"),
                        (r"f\"[^\"]*\bExecutor \{", "commande MA3 construite")):
        for m in re.finditer(motif, code):
            ligne = code[:m.start()].count("\n") + 1
            defauts.append(f"ligne {ligne} : {quoi} ({m.group(0)[:30]})")
    import textwrap
    for n in ast.walk(ast.parse(textwrap.dedent(source))):
        if isinstance(n, ast.FunctionDef) and n.name.startswith(("_post_", "_get_")) \
                and n.end_lineno - n.lineno > 120:
            defauts.append(f"{n.name} fait {n.end_lineno - n.lineno} lignes")
    return defauts


def test_handler_mince():
    """Le Handler lit, valide et délègue ; les noms déplacés sont gardés.

    🟠 Audit du 25/09/2026 (D3) : `wing_handler.py` (2 080 lignes) construisait
    lui-même les commandes MA3, lisait ses paramètres à la main, ouvrait des
    boîtes de dialogue, portait la désinstallation ; `wing_init.py` (2 156
    lignes, « CONNEXION seulement ») portait aussi la gestion des fichiers
    firmware et l'état anti-martèlement. Découpé en wing_validation,
    wing_desinstall, wing_dialogues, wing_statut, wing_firmware,
    wing_etat_materiel (+ config_fader, affectation, chemin_profil).
    Ce contrôle empêche le retour, et vérifie la GARDE des noms déplacés : un
    test qui patcherait encore `wing_init.ETAT_FICHIER` doit LEVER, pas
    écrire en silence dans le vrai fichier d'état. Réinjection : un Handler
    qui relit ses paramètres à la main et construit une commande MA3.
    """
    section("80. Handler mince, noms déménagés gardés")
    import wing_handler
    import wing_init
    defauts = _handler_epais((HERE / "wing_handler.py").read_text(encoding="utf-8"))
    if defauts:
        echec(f"{len(defauts)} responsabilité(s) revenue(s) dans le Handler",
              " ; ".join(defauts[:8]))
    else:
        ok("wing_handler.py : aucun paramètre lu à la main, aucune commande MA3 "
           "construite, aucun dialogue système, aucune route de plus de 120 lignes")

    non_gardes = []
    for module, noms in ((wing_init, ("ETAT_FICHIER", "blocage_connu",
                                      "resoudre_firmware", "FW_SHA256")),
                         (wing_handler, ("_desinstall_plan", "_chemin_profil",
                                         "_choisir_fichier"))):
        for nom in noms:
            try:
                setattr(module, nom, None)
                non_gardes.append(f"{module.__name__}.{nom}")
            except AttributeError:
                pass
    if non_gardes:
        echec("un nom déplacé se patche encore EN SILENCE sur son ancien module",
              ", ".join(non_gardes))
    else:
        ok("7 noms déplacés : les patcher sur leur ancien module lève "
           "AttributeError avec la nouvelle adresse")

    epais = ('    def _post_fader(self, body):\n'
             '        i = int(body.get("index", -1))\n'
             '        cmd = f"FaderMaster Executor {exe} At {pct}"\n')
    if len(_handler_epais(epais)) >= 2:
        ok("réinjection (lecture à la main + commande MA3 dans le Handler) → "
           "détectée")
    else:
        echec("réinjection NON détectée — contrôle aveugle")


# ── 81. État partagé : un objet injectable (etat.py) ──────────────────────────

_NOMS_ETAT = ("LOCK", "STATE", "PROFILE", "SETTINGS", "OSC", "DEV", "AUTO",
              "BOUCLE", "DMX", "LED", "LED_RAFRAICHI", "ENVOI", "WS", "VEGAS",
              "PICKUP", "FADER_LAST", "FADER_T", "FADER_ATTENTE", "MAINTIENS",
              "VERBE", "CONSOLE_CIBLES", "_SUIVI_VU", "_MA3_CHECK", "THREAD_MORT",
              "USB_GEN", "BOUTONS_ENFONCES", "UI_VIE", "RECOVERY")


def _injection_isolee(injecter) -> list:
    """Défauts d'isolation d'un `injecter` (le vrai, ou une réinjection)."""
    import wing_statut
    import wing_ui as ui
    d = []
    origine = etat.E
    mode0, nom0 = origine.STATE["mode"], origine.PROFILE.get("name")
    with injecter() as e:
        if etat.E is not e:
            d.append("etat.E n'est pas l'état injecté")
        e.STATE["mode"] = "bridge"
        e.PROFILE["name"] = "INJECTÉ"
        ui.etat_poser(dirty=True)                 # vraie fonction du moteur
        if not e.STATE["dirty"]:
            d.append("le moteur (etat_poser) n'écrit pas dans l'état injecté")
        if wing_statut.statut()["mode"] != "bridge":
            d.append("le moteur (/api/status) ne lit pas l'état injecté")
    if etat.E is not origine:
        d.append("l'état d'origine n'est pas revenu après le bloc")
    if origine.STATE["mode"] != mode0 or origine.PROFILE.get("name") != nom0:
        d.append("l'état d'origine a été modifié par le bloc injecté")
    return d


def _entorses_etat(sources: dict) -> list:
    """Accès interdits dans du code source : `from etat import E` (figerait
    l'instance), ancien nom via un module (`core.STATE`…), variable locale
    `etat` qui masquerait le module dans une fonction qui s'en sert."""
    import ast
    d = []
    anciens = set(_NOMS_ETAT)
    for nom, src in sources.items():
        arbre = ast.parse(src)
        for n in ast.walk(arbre):
            if isinstance(n, ast.ImportFrom) and n.module == "etat":
                d.append(f"{nom}:{n.lineno} from etat import … (instance figée)")
            if isinstance(n, ast.Attribute) and n.attr in anciens \
                    and isinstance(n.value, ast.Name) \
                    and n.value.id in ("core", "ui", "wv", "core2", "_core", "wing_ui"):
                d.append(f"{nom}:{n.lineno} {n.value.id}.{n.attr} (ancien nom)")
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                locaux = {x.id for x in ast.walk(n)
                          if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store)}
                locaux |= {a.arg for a in n.args.args}
                if "etat" in locaux and "import etat" in src:
                    d.append(f"{nom}:{n.lineno} variable locale « etat » dans "
                             f"{n.name} (masque le module etat)")
    return d


def test_etat_injecte():
    """L'état partagé est un objet (etat.E), et un test l'INJECTE.

    🟠 Audit du 25/09/2026 (D1). L'état mutable vivait en variables de module
    de `wing_ui.py` (~165 `import wing_ui as core`), et son emplacement était
    dicté par ce que le test de fumée « monkeypatchait ». Il vit désormais dans
    `etat.Etat` ; le code lit `etat.E.<champ>` ; un test injecte un état neuf
    avec `etat.injecter()`. Les anciens noms de `wing_ui` LÈVENT.
    Réinjections : un `injecter` qui ne restaure pas ; `from etat import E` ;
    une variable locale `etat` (le piège rencontré en migrant : `etat =
    shcuts_etat()` masquait le module et `/api/status` aurait levé
    UnboundLocalError au premier appel).
    """
    section("81. État partagé : un objet injectable (etat.py)")
    import contextlib
    import wing_ui as ui

    d = _injection_isolee(etat.injecter)
    if d:
        echec("l'injection d'état n'isole pas", " ; ".join(d))
    else:
        ok("injection : le moteur (etat_poser, /api/status) voit l'état injecté, "
           "l'état d'origine revient intact à la sortie")

    sources = {f.name: f.read_text(encoding="utf-8")
               for f in sorted(HERE.glob("*.py"))
               if f.name not in ("smoke_securite.py",)}
    d = _entorses_etat(sources)
    if d:
        echec(f"{len(d)} accès à l'état contournent etat.E", " ; ".join(d[:8]))
    else:
        ok(f"{len(sources)} fichiers : aucun `from etat import E`, aucun ancien "
           "nom d'état via un module, aucune variable locale « etat » masquante")

    non_gardes = []
    for n in _NOMS_ETAT:
        try:
            getattr(ui, n)
            non_gardes.append(n)
        except AttributeError:
            pass
    if non_gardes:
        echec("un ancien nom d'état se lit encore sur wing_ui", ", ".join(non_gardes))
    else:
        ok(f"les {len(_NOMS_ETAT)} anciens noms d'état de wing_ui lèvent "
           "AttributeError (nouvelle adresse dans le message)")

    # Réinjections.
    @contextlib.contextmanager
    def injecter_sans_restaurer():
        etat.E = etat.Etat()
        yield etat.E
    origine = etat.E
    try:
        rouge1 = _injection_isolee(injecter_sans_restaurer)
    finally:
        etat.E = origine
    rouge2 = _entorses_etat({"piege.py": "import etat\nfrom etat import E\n"
                                         "def f():\n    etat = {}\n    return etat.E\n"
                                         "def g(core):\n    return core.STATE\n"})
    if rouge1 and len(rouge2) >= 3:
        ok("réinjections (injection sans restauration ; `from etat import E`, "
           "variable locale « etat », ancien nom) → toutes détectées")
    else:
        echec("réinjection NON détectée — contrôle aveugle", f"{rouge1} / {rouge2}")
