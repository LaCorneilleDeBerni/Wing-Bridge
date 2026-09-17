#!/usr/bin/env python3
"""
smoke_interface.py — Wing Bridge
=================================
Domaine interface (HTML/JS générique) du test de fumée : syntaxe JS, équilibre
des balises, cohérence des identifiants, gestionnaires inline, onglets,
exécution du script, aide, réglages qui partent à la saisie. Voir
smoke_core.py pour ok/echec/note/section/_blocs_js/_js_manquants/_js_de.
"""

import json
import os
import re
import subprocess
import tempfile

from smoke_core import ok, echec, note, section, _blocs_js, _js_manquants, _js_de, HERE


def test_js(html):
    section("2. Syntaxe du JavaScript de l'interface")
    # ⚠️ Un <script src> déclaré mais absent du disque = interface INERTE, et la
    # page se charge sans la moindre erreur visible. On refuse avant tout le
    # reste : c'est la panne que le découpage du JS rend possible.
    absents = _js_manquants(html)
    if absents:
        echec(f"{len(absents)} fichier(s) <script src> introuvable(s)",
              ", ".join(absents) + " — la page se chargerait et AUCUN bouton "
              "ne répondrait. Vérifie aussi le --add-data des scripts de build")
        return

    # ⚠️ Le fichier existe sur le disque, mais le serveur ne le sert QUE si son
    # nom est dans la liste blanche `wing_ui.JS_FICHIERS` (voir `_lire_js`) : un
    # <script src> ajouté au HTML sans être ajouté là part en 404 → `t` (ou
    # autre) undefined → interface inerte, sans une erreur au build. Vécu en
    # posant i18n.js. On vérifie donc les deux listes ensemble.
    try:
        import wing_ui as _core
        srcs = re.findall(r'<script[^>]*\bsrc="/ui/([\w-]+)\.js"', html)
        hors_liste = [s for s in srcs if s not in _core.JS_FICHIERS]
        if hors_liste:
            echec("des <script src=\"/ui/…\" > ne sont pas dans "
                  "wing_ui.JS_FICHIERS", ", ".join(hors_liste)
                  + " — le serveur les refuserait en 404 (liste blanche de "
                  "`_lire_js`) et l'interface serait inerte")
            return
        manque_html = [s for s in _core.JS_FICHIERS
                       if s not in srcs]
        if manque_html:
            echec("des fichiers de wing_ui.JS_FICHIERS ne sont chargés par "
                  "aucun <script> du HTML", ", ".join(manque_html)
                  + " — code embarqué mais jamais exécuté")
            return
        if srcs != list(_core.JS_FICHIERS):
            echec("l'ordre des <script src> du HTML ≠ wing_ui.JS_FICHIERS",
                  f"HTML {srcs} vs {list(_core.JS_FICHIERS)} — l'ordre de "
                  "chargement est imposé (core→i18n→…→init)")
            return
        ok(f"{len(srcs)} <script src=/ui/> : liste et ordre = wing_ui.JS_FICHIERS")
    except Exception as e:
        note(f"vérif liste blanche JS_FICHIERS sautée ({e})")
    blocs = _blocs_js(html)
    if not blocs:
        echec("aucun JavaScript trouvé (ni inline, ni <script src>)")
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
        note("node introuvable — contrôle syntaxique JS SAUTÉ "
             "(installe node pour l'activer : brew install node)")
        return

    for nom, js in blocs:
        # Extension .js = mode script, exactement comme un <script> de page :
        # un `await` hors fonction async y est une erreur, comme dans un
        # navigateur. (.mjs serait plus permissif et masquerait de vrais bugs.)
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as f:
            f.write(js)
            chemin = f.name
        try:
            r = subprocess.run([node, "--check", chemin],
                               capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                lignes = js.count("\n") + 1
                ok(f"{nom} : syntaxe valide ({lignes} lignes)")
            else:
                # node donne le numéro de ligne DANS le fichier testé
                echec(f"{nom} : erreur de syntaxe JS", r.stderr or r.stdout)
        finally:
            os.unlink(chemin)


def test_balises(html):
    section("3. Équilibre des balises HTML")
    # On retire CSS et JS : ils contiennent des mots comme "details.help" ou
    # des chaînes "<div …>" qui fausseraient le comptage.
    sans_js = re.sub(r"<script>.*?</script>", "", html, flags=re.S)
    sans_js = re.sub(r"<style>.*?</style>", "", sans_js, flags=re.S)
    for tag in ("div", "details", "summary", "section", "header", "table"):
        ouv = len(re.findall(rf"<{tag}[\s>]", sans_js))
        fer = sans_js.count(f"</{tag}>")
        if ouv == fer:
            ok(f"<{tag}> : {ouv} ouverts / {fer} fermés")
        else:
            echec(f"<{tag}> déséquilibré : {ouv} ouverts / {fer} fermés")


def test_ids(html):
    """Tout `getElementById("x")` vise-t-il un `id="x"` qui existe ?

    🐛 CE CONTRÔLE EST DEVENU AVEUGLE PENDANT LE DÉCOUPAGE DU JS.
    Il cherchait les `getElementById` dans le HTML, ce qui marchait tant que le
    script y était inline. Le JS sorti dans `wing_ui.js`, il n'a plus rien
    trouvé — et il a affiché « ✓ 0 id(s) visés existent tous », donc **VERT sur
    du vide**. Le pire cas possible : un garde-fou qui rassure sans rien garder.

    🔑 C'est la démonstration en direct du risque du découpage : déplacer du
    code ne casse pas seulement le code, ça casse les CONTRÔLES qui le lisent —
    et un contrôle cassé ne se plaint pas, il approuve. D'où `_blocs_js()`, et
    d'où le refus explicite d'un décompte nul ci-dessous.
    """
    section("4. Cohérence des identifiants")
    ids_html = set(re.findall(r'\bid="([\w-]+)"', html))
    # ids créés dynamiquement en JS (innerHTML) : légitimes bien qu'absents
    ids_html |= set(re.findall(r"id='([\w-]+)'", html))
    js = _js_de(html)
    vises = set(re.findall(r'getElementById\("([\w-]+)"\)', js))
    vises |= set(re.findall(r"getElementById\('([\w-]+)'\)", js))
    if not vises:
        echec("aucun getElementById trouvé — ce contrôle ne vérifie donc RIEN",
              "le JS a-t-il été déplacé sans que _blocs_js() suive ? "
              "Un contrôle qui ne trouve rien à vérifier doit crier, pas "
              "afficher un ✓")
        return
    manquants = sorted(vises - ids_html)
    if manquants:
        echec(f"{len(manquants)} id(s) visés par getElementById mais absents "
              f"du HTML", ", ".join(manquants))
    else:
        ok(f"{len(vises)} id(s) visés existent tous dans le HTML")


def test_onclick(html):
    """Toute fonction appelée depuis un attribut `on…=` du HTML existe-t-elle ?

    🐛 CE CONTRÔLE NE REGARDAIT QUE `onclick` ET `onchange`.
    Il a donc laissé passer `oninput="ledLevelTest()"` : le curseur « Niveau
    d'éclairage » de l'onglet Paramètres appelait une fonction qui n'existe pas.
    Le bouger ne faisait RIEN — pas même mettre à jour le nombre affiché à côté.

    ⚠️ Il ne suffit pas non plus de compter sur le contrôle test_js_execute : lui exécute
    et audite le SCRIPT, alors que ces gestionnaires-là vivent dans le BALISAGE.
    Ce sont deux surfaces différentes, chacune a besoin de son garde-fou.

    On balaie donc TOUS les `on…=`, sans liste blanche à tenir à jour : oninput,
    onsubmit, onkeyup, onfocus… Une liste d'attributs à maintenir à la main est
    exactement ce qui a créé le trou.
    """
    section("5. Gestionnaires inline du HTML (onclick, oninput, onchange…)")
    js = _js_de(html)
    # ⚠️ On ne se contente PAS du 1er nom de l'attribut. Un gestionnaire peut
    # contenir plusieurs appels, et le vrai est parfois le second :
    #     onkeydown="if(event.key==='Enter')consoleTest()"
    # La 1re version capturait « if » (faux positif) et manquait consoleTest
    # (vrai angle mort). On extrait donc TOUS les appels de la valeur.
    MOTS = {"if", "for", "while", "switch", "catch", "return", "typeof", "new",
            "function", "await", "else", "do", "delete", "void", "throw"}
    appels = set()
    for _, valeur in re.findall(r'\bon[a-z]+\s*=\s*(["\'])(.*?)\1', html, re.S):
        for nom in re.findall(r'(?:^|[^.\w$])([A-Za-z_$][\w$]*)\(', valeur):
            if nom not in MOTS:
                appels.add(nom)
    definies = set(re.findall(r"function\s+(\w+)\s*\(", js))
    definies |= set(re.findall(r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(", js))
    definies |= set(re.findall(r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?function", js))
    manquantes = sorted(appels - definies)
    if manquantes:
        echec(f"{len(manquantes)} fonction(s) appelée(s) depuis un attribut "
              f"on…= du HTML mais NON DÉFINIE(S)",
              ", ".join(manquantes) + " — le contrôle qui les utilise est mort : "
              "l'utilisateur clique, rien ne se passe, et rien ne l'explique")
    else:
        ok(f"{len(appels)} fonction(s) inline toutes définies")


def test_onglets(html):
    """La barre d'onglets sépare le SHOW du RÉGLAGE, et rien ne pend dans le vide.

    🧹 Revue d'interface (« il y a des menus trop compliqués »). DMX, LEDs et
    Détection ont fusionné en **⚙️ Paramètres** :
    ce qu'on règle une fois, contre ce qu'on touche pendant un show.

    ⚠️ Ce qui décrit la DISPOSITION de la wing — touches, faders, roues — garde
    son propre onglet. Chaque exemplaire de wing est différent (ordre des faders,
    touches remplacées) : c'est du réglage par machine, pas de la configuration
    d'usine. Voir le principe en tête de GUIDE_PROJET.md.
    """
    section("27. Onglets : show d'un côté, réglages de l'autre")
    import re as _re
    onglets = _re.findall(r'data-tab="(\w+)"', html)
    # « aide » : l'aide était éparpillée en 11 blocs
    # dépliants dans le balisage, dont 7 dans le seul onglet Bridge.
    attendus = ["bridge", "touches", "faders", "encodeurs", "profils",
                "parametres", "aide"]
    if onglets != attendus:
        echec("la barre d'onglets a changé",
              f"attendu {attendus}, trouvé {onglets} — si c'est voulu, mettre "
              f"ce contrôle à jour ET vérifier qu'aucune personnalisation de "
              f"disposition n'a disparu (GUIDE_PROJET.md)")
        return
    ok(f"{len(onglets)} onglets : " + " · ".join(onglets))

    # Chaque bouton doit avoir sa section, et réciproquement
    sections = _re.findall(r'<section id="tab-(\w+)"', html)
    orphelins = set(onglets) ^ set(sections)
    if orphelins:
        echec("onglets et sections ne correspondent pas",
              f"sans vis-à-vis : {sorted(orphelins)}")
    else:
        ok("chaque onglet a sa section, et réciproquement")

    # Les réglages de DISPOSITION restent hors de Paramètres
    i = html.find('<section id="tab-parametres"')
    j = html.find("</section>", i)
    param = html[i:j]
    interdits = [("api/assign", "assignation des touches"),
                 ("api/fader\b", "type/position des faders"),
                 ("api/encoders", "groupes des roues")]
    dedans = [nom for motif, nom in interdits if _re.search(motif, param)]
    if dedans:
        echec("des réglages de DISPOSITION ont été déplacés dans Paramètres",
              ", ".join(dedans) + " — ils décrivent CETTE wing et doivent rester "
              "dans leur propre onglet (voir GUIDE_PROJET.md)")
    else:
        ok("Paramètres ne contient aucun réglage de disposition")


def test_js_execute(html):
    """Le script s'EXÉCUTE-t-il sans planter ? (pas seulement : compile-t-il ?)

    🔴 UN BUG QUI A COÛTÉ TRÈS CHER.

    `setInterval(pollOscIn, 1000)` est resté après la suppression de
    `pollOscIn`. Syntaxe parfaite, donc le contrôle test_js (syntaxe JS)
    passait au vert. Mais à l'exécution : ReferenceError au niveau SUPÉRIEUR du
    script → **tout ce qui suit ne tourne jamais**, dont `loadProfile()`.

    Symptômes vécus : plus aucun raccourci clavier, profil non chargé à
    l'écran… et même les messages d'erreur ajoutés pour diagnostiquer ne
    s'affichaient pas, puisqu'ils sont définis plus bas dans le fichier.

    Trouvé dans la console de Safari, après trois tentatives ratées : un
    rechercher-remplacer avait nettoyé les appels `pollOscIn();` mais pas
    celui-ci, qui ne finit pas par `();`.

    🔑 **Vérifier la syntaxe ne suffit pas.** On exécute le script dans node
    avec un DOM factice : toute référence à une fonction supprimée casse ici,
    au lieu de casser chez l'utilisateur.

    ── RENFORCÉ : l'exécution seule laissait passer trop ────────────────────

    Exécuter le script ne joue que son NIVEAU SUPÉRIEUR. Une fonction qui n'est
    appelée que sur un clic n'est jamais entrée : un appel mort à l'intérieur
    passait donc au vert ici et cassait chez l'utilisateur, exactement comme
    avant. Trois trous, tous réels dans ce fichier :

      • un appel mort dans une fonction jamais appelée au chargement ;
      • un appel mort dans une BRANCHE (le `else` d'un cas rare) ;
      • un `onclick='machin(this)'` écrit DANS UNE CHAÎNE d'innerHTML —
        que le navigateur évalue au clic, et qu'aucune exécution ne visite.

    On ajoute donc un contrôle STATIQUE : tout nom appelé comme une fonction
    dans le script doit exister quelque part — déclaré dans le script, ou connu
    de l'environnement. Il est délibérément préféré à « appeler chaque fonction
    une par une » : il couvre les branches et les chaînes, et il est
    DÉTERMINISTE. Un contrôle instable finit contourné, donc inutile — c'est la
    raison écrite plus bas pour laquelle on ne juge que les ReferenceError.
    """
    section("28. Le JavaScript s'exécute, et n'appelle rien qui n'existe pas")
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

    absents = _js_manquants(html)
    if absents:
        echec(f"{len(absents)} fichier(s) <script src> introuvable(s)",
              ", ".join(absents))
        return
    blocs = _blocs_js(html)
    if not blocs:
        echec("aucun JavaScript trouvé (ni inline, ni <script src>)")
        return
    ids = sorted(set(re.findall(r'id="([^"]+)"', html)))

    # DOM factice : un id absent rend `null`, comme dans un navigateur.
    import wing_mapper as _wm
    prologue = """
const IDS = new Set(%s);
function mkEl(){ return new Proxy({}, { get:(o,k)=>{
  if(k==='style') return {};
  if(k==='classList') return {add(){},remove(){},contains(){return false;},toggle(){}};
  if(k==='querySelectorAll') return ()=>[];
  if(k==='dataset') return {};
  if(k==='files') return [];
  if(typeof k==='string' && !(k in o)) return ()=>mkEl();
  return o[k]; }, set:(o,k,v)=>{o[k]=v;return true;} }); }
globalThis.document = {
  getElementById:(id)=> IDS.has(id) ? mkEl() : null,
  createElement:()=>mkEl(), querySelectorAll:()=>[], querySelector:()=>mkEl(),
  addEventListener:()=>{}, body:mkEl(), documentElement:mkEl(),
};
globalThis.window = globalThis;
// Un navigateur porte toujours ces membres — sans eux, les écouteurs
// beforeunload/pagehide de ui/init.js jetteraient un TypeError au chargement
// (non fatal ici, mais ça sautait l'audit d'appels de tout le bundle).
globalThis.addEventListener = ()=>{};
globalThis.navigator = { sendBeacon:()=>true };
globalThis.localStorage = { getItem:()=>null, setItem(){}, removeItem(){} };
const PROFIL = %s;
globalThis.fetch = async (u) => ({
  json: async () => (String(u).includes("/api/profile") && !String(u).includes("profiles")
                     ? PROFIL : {}),
  text: async () => "" });
globalThis.alert = ()=>{}; globalThis.confirm = ()=>false;
globalThis.prompt = ()=>null;   // annulation : le chemin le plus sûr
globalThis.setInterval = ()=>0; globalThis.setTimeout = ()=>0;
globalThis.clearTimeout = ()=>{}; globalThis.clearInterval = ()=>{};
globalThis.requestAnimationFrame = ()=>0;
""" % (json.dumps(ids), json.dumps(_wm.new_profile_from_defaults()))

    # ── Épilogue : l'audit statique des appels ───────────────────────────────
    #
    # Il tourne APRÈS le script, dans la même portée de module — c'est ce qui
    # permet à `eval(nom)` de voir les `function machin()` du script, qui ne
    # sont PAS sur globalThis quand node charge un fichier en CommonJS.
    #
    # Trois filtres, et il faut les trois pour n'avoir aucun faux positif :
    #   1. le nom est appelé quelque part           (`nom(`)
    #   2. il n'est déclaré NULLE PART dans le script (fonction, const/let/var,
    #      propriété-fonction) — sinon toute fonction locale à une autre serait
    #      signalée : `tryReload` dans hardReset() est invisible au niveau
    #      module, et parfaitement légitime
    #   3. il n'existe pas non plus dans l'environnement (builtins, DOM factice)
    #
    # ⚠️ On scanne le source BRUT, chaînes comprises. C'est voulu : c'est ce qui
    # attrape `onclick='pickAttr(this)'` posé dans un innerHTML.
    # ⚠️ ON NE SCANNE PAS LE SOURCE BRUT — 1re version, faux positifs massifs.
    #
    # Les commentaires de ce projet sont en français et pleins de « mot ( » :
    # le balayage y a vu 60 « fonctions inexistantes » (pastille, tour, heures,
    # Bureau…). Un contrôle qui crie toujours ne sert à rien — c'est écrit noir
    # sur blanc pour `_vpn_actif` dans wing_ui.py, et je viens de le refaire.
    #
    # On retire donc commentaires ET littéraux regex (qui contiennent des `/`
    # et des parenthèses), mais on GARDE les chaînes : c'est là que vivent les
    # `onclick='machin(this)'` posés en innerHTML, et ce sont eux qu'on veut.
    # Et on exige `nom(` SANS espace : la prose écrit « MA3 (plugin lancé ?) »,
    # jamais un appel de fonction.
    epilogue = """
;(function __auditAppels(){
  // `garderChaines` : true → on garde le texte des chaînes (pour y pêcher les
  // gestionnaires inline) ; false → on les blanchit (pour scanner le CODE seul).
  // Vérifié : ce script ne contient AUCUN littéral template — les 34 backticks
  // du fichier sont tous dans des commentaires, donc déjà mangés ici.
  function decommenter(s, garderChaines) {
    let out = "", i = 0, etat = "code", prev = "";
    while (i < s.length) {
      const c = s[i], d = s[i+1];
      if (etat === "code") {
        if (c === "/" && d === "/") { etat = "ligne"; i += 2; continue; }
        if (c === "/" && d === "*") { etat = "bloc";  i += 2; continue; }
        if (c === "'" || c === '"' || c === "`") { etat = c; out += c; i++; continue; }
        if (c === "/" && "(,=:[!&|?{};+-*%~^<>".includes(prev)) {
          etat = "regex"; out += " "; i++; continue;
        }
        out += c;
        if (!/\\s/.test(c)) prev = c;
        i++; continue;
      }
      if (etat === "ligne") { if (c === "\\n") { etat = "code"; out += "\\n"; } i++; continue; }
      if (etat === "bloc")  { if (c === "*" && d === "/") { etat = "code"; i += 2; } else i++; continue; }
      if (etat === "regex") {
        if (c === "\\\\") { i += 2; continue; }
        if (c === "[") { while (i < s.length && s[i] !== "]") { if (s[i] === "\\\\") i++; i++; } i++; continue; }
        if (c === "/") { etat = "code"; prev = "/"; }
        i++; continue;
      }
      if (c === "\\\\") { if (garderChaines) out += s.substr(i, 2); i += 2; continue; }
      if (garderChaines || c === etat) out += c;
      if (c === etat) { etat = "code"; prev = c; }
      i++;
    }
    return out;
  }
  const BRUT = __SOURCE_JS__;
  // ⚠️ ON NE CHERCHE PAS D'APPELS DANS LES CHAÎNES ORDINAIRES — 2e faux
  // positif, corrigé. Le français écrit « 12 bouton(s) »,
  // « tour(s) », « écart(s) », et le CSS écrit « var(--red) » : le balayage y
  // voyait 13 fonctions inexistantes nommées bouton, tour, cart, var…
  //
  // 🔑 Ce qu'on veut vraiment dans les chaînes, ce n'est pas « du texte avec
  // une parenthèse », c'est un GESTIONNAIRE INLINE — onclick="machin(…)" posé
  // en innerHTML, que le navigateur évaluera au clic. On l'extrait donc
  // explicitement, au lieu de ratisser toute la prose.
  const SRC = decommenter(BRUT, false);        // code seul, chaînes blanchies
  const AVEC = decommenter(BRUT, true);        // chaînes gardées
  let h, hRe = /\\bon[a-z]+\\s*=\\s*(['"])([\\s\\S]*?)\\1/g, HANDLERS = [];
  while ((h = hRe.exec(AVEC))) HANDLERS.push(h[2]);
  const MOTS = new Set(["if","for","while","switch","catch","function","return",
    "typeof","new","await","case","do","else","delete","void","in","of",
    "instanceof","throw","yield","super","import","export","try","finally"]);
  const appels = new Set();
  let m, re = /(^|[^.\\w$])([A-Za-z_$][\\w$]*)\\(/g;
  for (const texte of [SRC].concat(HANDLERS)) {
    re.lastIndex = 0;
    while ((m = re.exec(texte))) appels.add(m[2]);
  }
  const declares = new Set();
  for (const r of [/function\\s+([A-Za-z_$][\\w$]*)/g,
                   /(?:const|let|var)\\s+([A-Za-z_$][\\w$]*)/g,
                   /([A-Za-z_$][\\w$]*)\\s*[:=]\\s*(?:async\\s*)?(?:function|\\()/g]) {
    let x; while ((x = r.exec(SRC))) declares.add(x[1]);
  }
  const morts = [];
  for (const nom of appels) {
    if (MOTS.has(nom) || declares.has(nom)) continue;
    let existe = false;
    try { existe = typeof eval(nom) !== "undefined"; } catch (e) { existe = false; }
    if (!existe) morts.push(nom);
  }
  if (morts.length) console.error("APPELS_MORTS:" + morts.join(","));
})();
"""

    # ⚠️ ON CONCATÈNE LES FICHIERS — corrigé au découpage du JS.
    #
    # La 1re version auditait chaque fichier SÉPARÉMENT. Dès que le JS a été
    # découpé en sept, `bridge.js` s'est mis à « appeler des fonctions qui
    # n'existent pas » : elles sont dans `touches.js`. Faux positif massif,
    # et un contrôle qui crie à tort finit contourné.
    #
    # 🔑 Ce sont des <script> CLASSIQUES : ils partagent une seule portée
    # globale et s'exécutent dans l'ordre du document. Les concaténer, c'est
    # exactement le modèle du navigateur — plus fidèle, et sans faux positif.
    # `_blocs_js` les rend déjà dans l'ordre de déclaration du HTML.
    for nom, js in [("l'ensemble des fichiers JS",
                     "\n".join(code for _, code in blocs))]:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as f:
            # ⚠️ `.replace`, PAS `%` : l'épilogue contient des `%` littéraux
            # (classe de caractères du décommenteur) que le formatage Python
            # prendrait pour des marqueurs.
            f.write(prologue + "\n" + js + "\n"
                    + epilogue.replace("__SOURCE_JS__", json.dumps(js)))
            chemin = f.name
        try:
            r = subprocess.run([node, chemin], capture_output=True, text=True,
                               timeout=25)
        finally:
            os.unlink(chemin)
        err = (r.stderr or "").strip()
        # On ne juge QUE les erreurs de référence/type au chargement : le reste
        # (appels réseau simulés, etc.) n'a pas de sens hors navigateur.
        # ⚠️ UNIQUEMENT les ReferenceError. C'est la classe de bug visée : une
        # fonction supprimée encore appelée. Les TypeError viennent le plus
        # souvent des limites du DOM factice — les inclure rendrait ce contrôle
        # instable, donc contourné, donc inutile.
        fatales = [l for l in err.split("\n") if "ReferenceError" in l]
        if fatales:
            echec(f"{nom} : le script PLANTE à l'exécution",
                  fatales[0][:200] + " — une fonction supprimée est encore "
                  "appelée ; tout ce qui suit cette ligne ne tourne jamais")
            return
        # L'audit statique : un appel vers un nom qui n'existe nulle part. Il ne
        # plante PAS au chargement (la ligne fautive n'est jamais atteinte), il
        # plantera au clic de l'utilisateur — d'où l'intérêt de le voir ici.
        morts = [l.split("APPELS_MORTS:", 1)[1].strip()
                 for l in err.split("\n") if l.startswith("APPELS_MORTS:")]
        if morts:
            # On rend le nom du fichier fautif : « l'ensemble des fichiers »
            # n'aide personne à ouvrir le bon.
            import re as _re
            situe = []
            for m in morts[0].split(","):
                m = m.strip()
                ou = [n for n, code in blocs
                      if _re.search(r"[^.\w$]" + _re.escape(m) + r"\(", code)]
                situe.append(f"{m} ({', '.join(ou) or 'introuvable'})")
            morts = [" · ".join(situe)]
            echec(f"appel(s) vers une fonction qui N'EXISTE PAS",
                  f"{morts[0]} — appelé(s) dans le script (ou dans un onclick "
                  f"posé en innerHTML) sans être défini(s) nulle part. Ça ne "
                  f"casse pas au chargement : ça cassera au clic.")
            return
    ok(f"{len(blocs)} fichier(s)/bloc(s) JS exécuté(s), aucun appel vers une "
       f"fonction inexistante")


def test_aides_completes(html):
    """Chaque rubrique d'aide est-elle joignable, et son texte existe-t-il ?

    🔑 Les textes d'aide ont une SOURCE UNIQUE : les catalogues i18n
    (`aide.<sujet>.titre` / `aide.<sujet>.html` dans fr.json/en.json),
    résolus par `t()`/`tHtml()` dans `aide()` et `construireAide()`
    (ui/core.js). `ui/aides.js` ne porte plus que la LISTE des sujets
    (`AIDES_PAR_ONGLET`, classée par onglet dès sa définition — un sujet ne
    peut donc plus exister sans être classé, structurellement).

    Deux dangers, tous deux silencieux, et qu'aucun autre contrôle n'attrape :
    (a)/(b) de `test_i18n` ne voient que les clés i18n LITTÉRALES, or ici la
    clé est construite par concaténation (`"aide." + cle + ".titre"`) — donc
    invisible pour eux.

      • un « ? » qui appelle une rubrique absente de `AIDES_PAR_ONGLET` → la
        fenêtre ne s'ouvre pas, et rien ne dit pourquoi ;
      • une rubrique listée dans `AIDES_PAR_ONGLET` mais dont
        `aide.<sujet>.titre`/`.html` manque dans fr.json OU en.json → `t()`
        renverrait la clé brute (ou le repli fr, selon le catalogue en
        cause) — un utilisateur verrait « aide.xxx.html » affiché tel quel.

    Les deux se voient à l'œil nu le jour où on cherche, jamais avant.
    """
    section("40. Aide : rubriques joignables et textes au catalogue")
    js = _js_de(html)
    import re as _re

    m = _re.search(r"AIDES_PAR_ONGLET = \[(.*?)\n\];", js, _re.S)
    if not m:
        echec("AIDES_PAR_ONGLET introuvable dans ui/aides.js",
              "le fichier a-t-il été renommé/restructuré ? ce contrôle ne "
              "vérifie plus rien")
        return
    # Les clés d'onglet (`ui.nav.xxx`) contiennent un point : \w+ ne les
    # capture pas, donc ce même motif ne ramasse QUE les slugs de sujet.
    definies = set(_re.findall(r'"(\w+)"', m.group(1)))
    if not definies:
        echec("aucun sujet trouvé dans AIDES_PAR_ONGLET",
              "le fichier a-t-il été renommé ? ce contrôle ne vérifie plus rien")
        return

    appelees = set(_re.findall(r"aide\('(\w+)'\)", html))
    manquantes = sorted(appelees - definies)
    if manquantes:
        echec(f"{len(manquantes)} « ? » appellent une rubrique inexistante",
              ", ".join(manquantes) + " — la fenêtre resterait fermée sans un mot")
        return
    ok(f"{len(appelees)} « ? » pointent tous vers une rubrique existante et classée")

    fr_p, en_p = HERE / "locales" / "fr.json", HERE / "locales" / "en.json"
    try:
        fr = json.loads(fr_p.read_text(encoding="utf-8"))
        en = json.loads(en_p.read_text(encoding="utf-8"))
    except Exception as e:
        echec("catalogue i18n illisible pour vérifier les textes d'aide", str(e))
        return
    manque_catalogue = []
    for sujet in sorted(definies):
        for champ in ("titre", "html"):
            cle = f"aide.{sujet}.{champ}"
            if cle not in fr:
                manque_catalogue.append(f"{cle} (absente de fr.json)")
            if cle not in en:
                manque_catalogue.append(f"{cle} (absente de en.json)")
    if manque_catalogue:
        echec(f"{len(manque_catalogue)} clé(s) d'aide absente(s) du catalogue",
              ", ".join(manque_catalogue[:15]) + " — t()/tHtml() afficherait "
              "la clé brute (ou le repli fr) à l'écran")
    else:
        ok(f"les {len(definies)} rubriques ont leur titre ET leur corps au "
           f"catalogue (fr + en)")


def test_reglages_sappliquent(html):
    """Un réglage se transmet-il dès la saisie, sans bouton propre à l'onglet ?

    🐛 Signalé : « j'ai mis Pan en roue 1, en testant j'ai toujours Dimmer »
    ET « du moment où on fait une modif, je dois pouvoir
    l'enregistrer dans le profil, ce n'est pas le cas ».

    UNE SEULE CAUSE POUR LES DEUX. Les cases de l'onglet Encodeurs n'étaient
    câblées que sur `focus`/`input` : rien ne partait tant qu'on n'avait pas
    cliqué un « Enregistrer » PROPRE À CET ONGLET — homonyme de celui de
    l'en-tête, qui enregistre le profil. On éditait, on cliquait celui de
    l'en-tête, et le profil sauvegardé n'avait jamais reçu la modification.

    🔑 DEUX RÈGLES, toutes deux nées de là :
      1. **Un réglage part à la saisie** (`change`), comme les faders l'ont
         toujours fait. Deux onglets qui se ressemblent ne doivent pas se
         comporter différemment.
      2. **Un seul bouton « Enregistrer »** dans toute l'interface, celui de
         l'en-tête, et il veut dire « graver dans le profil ». Un homonyme
         local fait perdre du travail sans un mot.

    ⚠️ Ce contrôle lit le SOURCE : il voit qu'un `change` est câblé, pas que le
    navigateur le déclenche. C'est une barrière contre la régression, pas une
    preuve de bon fonctionnement — celle-là se fait à la main, sur la wing.
    """
    section("41. Les réglages partent à la saisie, sans bouton par onglet")
    js = _js_de(html)

    # 1. un seul « Enregistrer » cliquable, et c'est celui du profil
    boutons = re.findall(r'<button[^>]*onclick="(\w+)\(\)"[^>]*>([^<]*Enregistrer[^<]*)</button>', html)
    boutons += re.findall(r'<button[^>]*>([^<]*Enregistrer[^<]*)</button>', html)
    locaux = [b for b in boutons if isinstance(b, tuple)
              and b[0] not in ("saveActiveProfile", "saveProfile")]
    if locaux:
        echec(f"{len(locaux)} bouton(s) « Enregistrer » propre(s) à un onglet",
              ", ".join(f"{f}()" for f, _ in locaux) + " — homonyme de celui de "
              "l'en-tête : l'utilisateur clique le mauvais et perd sa saisie")
        return
    # ⚠️ « Enregistrer sous… » a été REFUSÉ ici, et c'était le
    #    bon appel : même avec un suffixe, le mot revient deux fois dans
    #    l'interface avec deux sens. Le bouton s'appelle « ＋ Créer un
    #    profil… ». Ne pas assouplir ce contrôle pour faire passer un libellé.
    ok("un seul « Enregistrer » : celui de l'en-tête, qui grave le profil")

    # 2. les champs de l'onglet Encodeurs partent à la saisie
    manquants = [c for c in ('addEventListener("change", appliquerEncodeurs)',
                             '_encDef.onchange', '_encPas.onchange')
                 if c not in js]
    if manquants:
        echec("des réglages d'encodeur ne partent PAS à la saisie",
              ", ".join(manquants) + " — la modification resterait dans le "
              "navigateur, et le profil enregistré ne la contiendrait pas")
    else:
        ok("cases de roue, groupe de départ et pas : tous câblés sur « change »")
