#!/usr/bin/env python3
"""
smoke_i18n.py — Wing Bridge
============================
Domaine internationalisation du test de fumée. Le bilingue FR/EN repose sur un
catalogue plat (locales/fr.json, locales/en.json) et un moteur maison
(ui/i18n.js). Façons SILENCIEUSES de le casser :

  • une clé `data-i18n` ou `t("…")` sans entrée au catalogue → `t()` retombe sur
    la clé brute, et l'utilisateur voit « ui.bridge.journal.titre » à l'écran ;
  • `fr.json` et `en.json` qui divergent → une langue affiche des clés brutes là
    où l'autre est correcte, selon la machine du testeur ;
  • le texte français du balisage (filet anti-clignotement : il reste EN CLAIR à
    côté du `data-i18n`) qui DÉRIVE de `fr.json` → au chargement l'utilisateur
    voit une chose, après la première bascule il en voit une autre.

Et une faute de méthode qui ne casse rien tout de suite mais rend la traduction
impossible plus tard : **assembler des morceaux de phrase** (`t("a") + x +
t("b")`). L'ordre des mots change d'une langue à l'autre ; un traducteur qui ne
voit jamais la phrase entière ne peut pas la réparer. Voir docs/I18N.md

Contenu du contrôle `test_i18n` :
  (a) toute clé data-i18n* du HTML existe dans fr.json ET en.json
  (b) toute clé t()/tHtml() du JS (hors i18n.js) existe dans les deux
  (c) fr.json et en.json ont exactement le même jeu de clés
  (d) aucun élément-feuille du HTML avec > 2 mots de texte visible sans
      data-i18n (allowlist justifiée sinon) — BLOQUANT
  (e) aucun `t(...)` collé à un `+` (pas d'assemblage de phrases)
  (f) pour toute clé data-i18n*, le texte inline du HTML == fr.json[clé]
      (comparaison à espaces normalisés). fr.json fait référence ; le balisage
      n'en est qu'un instantané, qu'on garde synchronisé.

Réinjection ROUGE vérifiée sur (a), (e) et (f).

Voir smoke_core.py pour ok/echec/note/section/HERE/_blocs_js.
"""

import html as _htmlmod
import json
import re

from smoke_core import HERE, ok, echec, note, section, _blocs_js


# Éléments-feuille dont on lit le texte pour l'heuristique (d).
_FEUILLES = ("h1", "h2", "h3", "h4", "summary", "button", "label", "option")

# (d) — allowlist : textes-feuille > 2 mots qu'on assume NE PAS traduire.
# Chaque entrée DOIT être justifiée (le texte exact → la raison). Vide : tout
# le texte visible du balisage a été extrait.
_ALLOWLIST_D = {
    # "texte exact": "raison",
}


def _norm(s):
    """Espaces normalisés : runs d'espaces/retours → un espace, trim.
    C'est la forme sous laquelle on compare balisage et catalogue — le HTML
    est indenté, le JSON non, et cette différence-là n'est pas une dérive."""
    return " ".join((s or "").split())


def _cles_catalogue():
    """(fr, en, erreur) — dicts chargés, ou (None, None, message)."""
    fr_p = HERE / "locales" / "fr.json"
    en_p = HERE / "locales" / "en.json"
    if not fr_p.is_file() or not en_p.is_file():
        return None, None, f"catalogue absent (attendus : {fr_p}, {en_p})"
    try:
        fr = json.loads(fr_p.read_text(encoding="utf-8"))
        en = json.loads(en_p.read_text(encoding="utf-8"))
    except Exception as e:
        return None, None, f"catalogue JSON invalide : {e}"
    if not isinstance(fr, dict) or not isinstance(en, dict):
        return None, None, "un catalogue n'est pas un objet JSON plat"
    return fr, en, None


def _inline_par_cle(html):
    """{clé: texte inline du HTML} pour chaque data-i18n*.

    - data-i18n="k"            → le contenu de l'élément (feuille : pas d'enfant)
    - data-i18n-html="k"       → l'innerHTML de l'élément
    - data-i18n-<attr>="k"     → la valeur de l'attribut <attr> du même élément
    """
    out = {}
    # ── data-i18n / data-i18n-html : contenu de l'élément ────────────────────
    # Une itération PAR occurrence : un élément peut porter data-i18n ET
    # data-i18n-title (l'input assignVal), il faut les deux.
    for m in re.finditer(r'data-i18n(-html)?="([^"]+)"', html):
        is_html, cle = m.group(1), m.group(2)
        lt = html.rfind("<", 0, m.start())
        mt = re.match(r'<([a-z0-9]+)', html[lt:])
        if not mt:
            continue
        tag = mt.group(1)
        gt = html.find(">", m.end())
        fin = html.find(f"</{tag}>", gt)
        if gt < 0 or fin < 0:
            continue
        contenu = html[gt + 1:fin]
        # data-i18n (textContent) : le navigateur décode les entités → on
        # compare DÉCODÉ. data-i18n-html (innerHTML) : re-parsé → on garde BRUT.
        out.setdefault(cle, contenu if is_html
                       else _htmlmod.unescape(re.sub(r"<[^>]+>", "", contenu)))
    # ── data-i18n-title / -placeholder / -aria-label : valeur d'un attribut ──
    for m in re.finditer(r'data-i18n-(title|placeholder|aria-label)="([^"]+)"',
                         html):
        attr, cle = m.group(1), m.group(2)
        lt = html.rfind("<", 0, m.start())
        gt = html.find(">", m.end())
        if lt < 0 or gt < 0:
            continue
        # `(?<![-\w])` : ne PAS confondre `title=` avec `data-i18n-title=`.
        mv = re.search(r'(?<![-\w])' + attr + r'="([^"]*)"', html[lt:gt + 1])
        if mv:
            out.setdefault(cle, _htmlmod.unescape(mv.group(1)))
    return out


def test_i18n(html):
    section("51. Internationalisation (i18n) : clés, parité, discipline")

    fr, en, err = _cles_catalogue()
    if err:
        echec("catalogue i18n inutilisable", err)
        return

    # ── (c) même jeu de clés des deux côtés ──────────────────────────────────
    seul_fr = sorted(set(fr) - set(en))
    seul_en = sorted(set(en) - set(fr))
    if seul_fr or seul_en:
        echec("(c) fr.json et en.json n'ont pas le même jeu de clés",
              (f"seulement dans fr : {seul_fr[:12]} ; " if seul_fr else "")
              + (f"seulement dans en : {seul_en[:12]}" if seul_en else "")
              + " — une langue afficherait des clés brutes")
    else:
        ok(f"(c) fr.json / en.json : {len(fr)} clés, jeux identiques")

    connues = set(fr) & set(en)

    # ── note non bloquante : clés encore identiques fr/en après Phase 3 ──────
    # diag.* exclu : namespace toujours anglais, quelques étiquettes neutres
    # (« Date :», « macOS », « OSC »…) y sont légitimement identiques aux deux
    # catalogues sans que ce soit un oubli de traduction.
    identiques = sorted(k for k in connues
                         if not k.startswith("diag.") and fr[k] == en[k])
    if identiques:
        note(f"Phase 3 : {len(identiques)} clé(s) encore identiques "
             f"fr.json/en.json (hors diag.*) : " + ", ".join(identiques[:40])
             + (" …" if len(identiques) > 40 else ""))
    else:
        note("Phase 3 : plus aucune clé (hors diag.*) identique entre "
             "fr.json et en.json")

    # ── (a) clés data-i18n* du HTML ⊆ catalogue ──────────────────────────────
    cles_html = set(re.findall(r'data-i18n(?:-[a-z-]+)?="([^"]+)"', html))
    manq_html = sorted(k for k in cles_html if k not in connues)
    if manq_html:
        echec(f"(a) {len(manq_html)} clé(s) data-i18n du HTML absente(s) des "
              f"catalogues", ", ".join(manq_html[:15])
              + " — `t()` afficherait la clé brute")
    else:
        ok(f"(a) {len(cles_html)} clé(s) data-i18n du HTML : toutes au catalogue")

    # ── (b) clés t()/tHtml()/plural() du JS (hors moteur i18n.js) ⊆ catalogue ─
    #
    # ⚠️ (b) ne force PAS encore que TOUT littéral user-facing du JS soit passé
    # en t() — c'est un GATE explicite de la Phase 2 (voir docs/I18N.md,
    # « Phase 2 — reste à extraire côté JS »). (b) vérifie seulement que les
    # appels DÉJÀ écrits pointent vers une clé qui existe des deux côtés.
    js_tabs = "\n".join(code for nom, code in _blocs_js(html)
                        if "i18n.js" not in nom)
    # ⚠️ Le `["\']…["\']` doit être suivi de `,` ou `)` (fin d'argument) : sans
    # ça, `t("aide." + cle + ".titre")` (clé CONSTRUITE, ex. ui/aides.js) ferait
    # capturer le fragment `aide.` comme si c'était une clé complète — absent
    # du catalogue, (b) échouerait sur un FAUX positif. Une clé construite par
    # concaténation n'est de toute façon pas vérifiable ici : c'est le rôle
    # d'un contrôle dédié (ex. test_aides_completes) de la garantir autrement.
    cles_js = set(re.findall(r'\bt(?:Html)?\(\s*["\']([\w.]+)["\']\s*[,)]',
                             js_tabs))
    manq_js = sorted(k for k in cles_js if k not in connues)
    # plural("cle", …) : il faut cle.one ET cle.other des deux côtés (fr/en
    # n'ont que ces deux formes ; une langue à pluriels multiples en ajoute).
    prefs_plural = set(re.findall(r'\bplural\(\s*["\']([\w.]+)["\']\s*[,)]',
                                  js_tabs))
    manq_plural = sorted(
        f"{p}.{forme}" for p in prefs_plural for forme in ("one", "other")
        if f"{p}.{forme}" not in connues)
    manque = manq_js + manq_plural
    if manque:
        echec(f"(b) {len(manque)} clé(s) t()/tHtml()/plural() du JS absente(s) "
              f"des catalogues", ", ".join(manque[:15])
              + " — le libellé sortirait en clé brute")
    else:
        ok(f"(b) {len(cles_js)} t()/tHtml() + {len(prefs_plural)} plural() du "
           f"JS : toutes les clés au catalogue")

    # ── (e) pas d'assemblage de phrase autour d'un t(...) / plural(...) ─────
    #
    # La règle : une phrase affichée = UNE clé, avec des {trous}. Interdit donc
    # `"Fader " + t(...)` et `t(...) + " rattrapé"` — un LITTÉRAL de prose collé
    # à un appel de traduction.
    # AUTORISÉ : coller un appel à du BALISAGE PUR (`"</td><td>" + t(...)`) ou à
    # une variable / un appel (`msg + hors`, `t(...) + oscPourquoi(s)` — deux
    # blocs déjà traduits, ou un fragment différé Phase 2 ; ces cas-là se voient
    # en revue, ils ne sont pas la faute qu'on chasse ici).
    appel = r'\b(?:t(?:Html)?|plural)\((?:[^()]|\([^()]*\))*\)'
    _STR = r'''"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*\''''    # un littéral chaîne
    markup_only = re.compile(r'''^(["'])(?:\s|<[^<>]*>|&[a-z]+;|&#\d+;|\\n)*\1$''')

    def _prose_lit(operand):
        """`operand` est-il un littéral chaîne DE PROSE (pas du markup pur) ?"""
        operand = operand.strip()
        return operand[:1] in "\"'" and not markup_only.match(operand)

    colles = []
    for m in re.finditer(appel, js_tabs):
        ls = js_tabs.rfind("\n", 0, m.start()) + 1
        le = js_tabs.find("\n", m.end())
        le = le if le != -1 else len(js_tabs)
        avant, apres = js_tabs[ls:m.start()], js_tabs[m.end():le]
        colle = False
        mb = re.search(r'(' + _STR + r')\s*\+\s*$', avant)
        if mb and _prose_lit(mb.group(1)):
            colle = True
        ma = re.match(r'\s*\+(?!=)\s*(' + _STR + r')', apres)
        if ma and _prose_lit(ma.group(1)):
            colle = True
        if colle:
            colles.append(js_tabs[ls:le].strip()[:120])
    if colles:
        echec(f"(e) {len(colles)} assemblage(s) de phrase autour d'un t(…)",
              " ⏎ ".join(colles[:6]) + " — une phrase affichée = UNE clé, avec "
              "des {trous} ; le markup pur peut être collé. Voir docs/I18N.md")
    else:
        ok("(e) aucun t(…) collé à de la prose : pas d'assemblage de phrases")

    # ── (d) tout texte-feuille visible est marqué ────────────────────────────
    oublies = []
    for m in re.finditer(
            r'<(' + "|".join(_FEUILLES) + r')\b([^>]*)>([^<]+)</\1>', html):
        attrs, txt = m.group(2), m.group(3).strip()
        mots = [w for w in re.split(r'\s+', txt) if re.search(r'[^\W\d_]', w)]
        if len(mots) > 2 and "data-i18n" not in attrs \
                and txt not in _ALLOWLIST_D:
            oublies.append(txt[:70])
    if oublies:
        echec(f"(d) {len(oublies)} élément(s)-feuille > 2 mots sans data-i18n",
              " | ".join(oublies[:8]) + " — texte visible non traduisible. "
              "Ajoute data-i18n (+ la clé aux 2 JSON), ou une entrée justifiée "
              "dans _ALLOWLIST_D")
    else:
        ok("(d) tout texte-feuille visible (> 2 mots) porte un data-i18n")

    # ── (f) balisage inline == fr.json (référence) ───────────────────────────
    inline = _inline_par_cle(html)
    divergents, sans_valeur = [], []
    for cle in sorted(cles_html):
        if cle not in fr:
            continue                       # déjà signalé par (a)
        if cle not in inline:
            sans_valeur.append(cle)
            continue
        if _norm(inline[cle]) != _norm(fr[cle]):
            divergents.append(
                f"{cle}\n      HTML : {_norm(inline[cle])[:90]}"
                f"\n      json : {_norm(fr[cle])[:90]}")
    if sans_valeur:
        echec(f"(f) {len(sans_valeur)} clé(s) data-i18n dont le texte inline est "
              f"introuvable", ", ".join(sans_valeur[:10])
              + " — un data-i18n-html sur un élément à balises ? un attribut "
              "mal formé ?")
    elif divergents:
        echec(f"(f) {len(divergents)} texte(s) du balisage divergent(s) de "
              f"fr.json", "\n    ".join(divergents[:5])
              + "\n    — fr.json fait foi : réaligne le balisage (ou corrige "
              "fr.json si c'est LUI qui a dérivé)")
    else:
        ok(f"(f) {len(cles_html)} texte(s) inline == fr.json (référence)")

    _test_i18n_serveur(fr, en, connues)
    _test_i18n_pas_de_francais_en_dur()


# ── i18n CÔTÉ SERVEUR (Phase 2) ─────────────────────────────────────────────
#
# Le journal, les messages d'erreur actionnables, les étapes de l'assistant
# firmware et le diagnostic sont passés en clés Python résolues par
# `wing_i18n` (L / L_en / plural). Trois façons SILENCIEUSES de casser ça :
#   (g) une clé `journal.` / `err.` / `firmware.` / `diag.` citée dans le code
#       mais absente d'un catalogue → la ligne sort en clé brute ;
#   (h) une phrase ASSEMBLÉE autour d'un appel de résolution
#       (`L("x") + " suite"`) → intraduisible, comme côté client (règle (e)) ;
#   (i) `wing_diagnostic.py` qui appellerait `L(` au lieu de `L_en(` → le
#       rapport suivrait la langue de l'app alors qu'il DOIT rester anglais.
#
# Réinjection ROUGE vérifiée sur (g), (h) et (i).

# Fonctions qui prennent une clé i18n en 1er argument chaîne.
_APPELS_CLE = (r"_LE?", r"L", r"L_en", r"log", r"log_plural", r"_msg",
               r"_etape", r"_pluriel")
# Namespaces réservés au serveur (le client gère `ui.*` et `aide.*`).
_NS_SRV = ("journal.", "err.", "firmware.", "diag.")
_PLURAL_SITES = re.compile(
    r"""(?:log_plural|core\.log_plural|wing_i18n\.plural|_pluriel)\(\s*["']([\w.]+)["']""")


def _fichiers_serveur():
    """Les .py du moteur (pas les smoke_*, pas wing_ui.html)."""
    for p in sorted(HERE.glob("wing_*.py")):
        yield p


def _cles_serveur_citees(txt):
    """Toutes les clés `journal./err./firmware./diag.` littérales du fichier.

    On ratisse TOUT littéral de ce namespace (et pas seulement le 1er argument
    d'un appel connu) : une clé de ce préfixe n'a pas d'autre raison d'exister
    dans le code que d'être résolue. `_phase(n, "firmware.x", "firmware.y")`,
    `_suivi_dit(cle, "journal.x")`, un ternaire `"a" if c else "b"`… tout est
    couvert. Les exemples en commentaire/docstring sont exclus (`journal.xxx`,
    `journal.<namespace>` — pas une vraie clé pointée)."""
    out = set()
    for m in re.finditer(r'"([a-z_]+(?:\.[a-z0-9_]+)+)"', txt):
        cle = m.group(1)
        if cle.startswith(_NS_SRV) and not cle.endswith((".xxx", ".x", ".y")):
            out.add(cle)
    return out


def _test_i18n_serveur(fr, en, connues):
    # ── (g) toute clé serveur citée existe des deux côtés ────────────────────
    plural_prefs, manque = set(), []
    par_fichier = {}
    for p in _fichiers_serveur():
        txt = p.read_text(encoding="utf-8")
        par_fichier[p.name] = txt
        plural_prefs |= set(_PLURAL_SITES.findall(txt))

    for nom, txt in par_fichier.items():
        for cle in sorted(_cles_serveur_citees(txt)):
            if cle in plural_prefs:
                for forme in ("one", "other"):
                    if f"{cle}.{forme}" not in connues:
                        manque.append(f"{nom}: {cle}.{forme}")
            elif cle not in connues and f"{cle}.one" not in connues:
                manque.append(f"{nom}: {cle}")
    if manque:
        echec(f"(g) {len(manque)} clé(s) i18n serveur absente(s) des catalogues",
              " ; ".join(manque[:15]) + " — la ligne sortirait en clé brute")
    else:
        n = sum(len(_cles_serveur_citees(t)) for t in par_fichier.values())
        ok(f"(g) {n} clé(s) journal./err./firmware./diag. citées : toutes au "
           f"catalogue (fr + en)")

    # ── (h) pas d'assemblage de phrase autour d'un L()/L_en()/plural() ───────
    appel = r'\b(?:_LE?|L|L_en|wing_i18n\.(?:L|L_en|plural)|plural)\((?:[^()]|\([^()]*\))*\)'
    _STR = r'''"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*\''''
    markup_only = re.compile(r'''^(["'])(?:\s|<[^<>]*>|&[a-z]+;|&#\d+;|\\n)*\1$''')

    def _prose_lit(op):
        op = op.strip()
        return op[:1] in "\"'" and not markup_only.match(op)

    colles = []
    for nom, txt in par_fichier.items():
        for m in re.finditer(appel, txt):
            ls = txt.rfind("\n", 0, m.start()) + 1
            le = txt.find("\n", m.end())
            le = le if le != -1 else len(txt)
            avant, apres = txt[ls:m.start()], txt[m.end():le]
            mb = re.search(r'(' + _STR + r')\s*\+\s*$', avant)
            ma = re.match(r'\s*\+(?!=)\s*(' + _STR + r')', apres)
            if (mb and _prose_lit(mb.group(1))) or (ma and _prose_lit(ma.group(1))):
                colles.append(f"{nom}: {txt[ls:le].strip()[:110]}")
    if colles:
        echec(f"(h) {len(colles)} assemblage(s) de phrase autour d'un L(…) serveur",
              " ⏎ ".join(colles[:6]) + " — une phrase = UNE clé à {trous}")
    else:
        ok("(h) aucun L(…)/plural(…) serveur collé à de la prose")

    # ── (i) wing_diagnostic.py : L_en UNIQUEMENT, jamais L( nu ───────────────
    diag = (HERE / "wing_diagnostic.py").read_text(encoding="utf-8")
    # `_LE(` (helper local) et `L_en(` sont OK. On cherche un `L(` ou `_L(` ou
    # `wing_i18n.L(` qui ne soit PAS `L_en(` ni `_LE(` — hors commentaires.
    fautes = []
    for i, ligne in enumerate(diag.splitlines(), 1):
        code = ligne.split("#", 1)[0]
        for m in re.finditer(r'(?<![\w.])(_L|L|wing_i18n\.L)\(', code):
            # écarte L_en( / _LE( : le \( suit immédiatement le nom capturé,
            # donc "L_en(" donne un match "L(" seulement si on ne regarde pas
            # le caractère suivant le nom — on le vérifie ici.
            suffixe = code[m.start():m.start() + 5]
            if suffixe.startswith(("L_en(", "_LE(")):
                continue
            fautes.append(f"L{i}: …{code.strip()[:80]}")
    if fautes:
        echec(f"(i) wing_diagnostic.py appelle L( au lieu de L_en(",
              " ; ".join(fautes[:6]) + " — le rapport DOIT rester anglais "
              "quelle que soit la langue de l'app (utilise _LE / L_en)")
    else:
        ok("(i) wing_diagnostic.py : L_en / _LE uniquement (rapport anglais)")


# ── (j) plus aucune prose française hors catalogue, dans TOUT le projet ────
#
# 🐛 Angle mort trouvé par l'auteur, pas par ce test de fumée : (a)-(i)
# ne lisent que le HTML statique et les appels t()/tHtml()/L()/… DÉJÀ écrits.
# Un littéral français resté en dur — dans ui/aides.js (11 rubriques d'aide),
# wing_ma3.py (FADER_FUNC_INFO), ui/parametres.js (_fwMsg), ui/bridge.js
# (oscPourquoi), ui/touches.js (bandeau raccourcis) — était donc INVISIBLE
# pour (a)-(i) : rien à comparer à un catalogue puisque rien n'était une clé.
# Cinq poches, trouvées à l'œil, pas par la machine. Premier passage de (j) une
# fois écrit : 176 littéraux dans ~20 fichiers — bien au-delà des cinq poches
# connues. Chacun trié en 3 cases (UI-facing → clé i18n ; diagnostic qui finit
# uniquement dans wing_server.log/le rapport, toujours anglais → texte anglais
# direct sans clé bilingue inutile ; jamais vu par personne → _ALLOWLIST_J avec
# justification vérifiée, pas supposée).
#
# Réinjection ROUGE vérifiée sur (j) : une clé remplacée par son texte français
# en dur (ui/parametres.js::fwImportCapture) → (j) l'attrape aussitôt.
#
# (j) inverse la logique : au lieu de vérifier que les clés CONNUES existent,
# il cherche tout littéral de chaîne ACCENTUÉ (français quasi assuré) qui
# n'est PAS déjà à l'intérieur d'un appel de résolution i18n. C'est un GARDE-
# FOU, pas une preuve de traduction correcte — mais un texte français oublié
# ne peut plus y échapper en silence.

# Fonctions dont le(s) argument(s) sont EXEMPTÉS du scan (leur contenu est déjà
# résolu par le moteur i18n, ou en est un alias établi ailleurs dans le projet
# — voir _APPELS_CLE plus haut : _LE/_msg/_etape/_pluriel délèguent tous à
# L()/L_en()/plural(), même garantie que les 7 noms cités par la consigne.
_APPELS_EXEMPTES_J = (
    "tHtml", "t", "L_en", "L", "plural", "log_plural", "log",
    "_LE", "_msg", "_etape", "_pluriel",
    "wing_i18n.L_en", "wing_i18n.L", "wing_i18n.plural",
)

# Allowlist : chaque entrée DOIT être justifiée. `(fichier, littéral EXACT
# avec ses guillemets)` → raison. Un littéral qui ne matche plus MOT POUR MOT
# (renommage, reformulation) retombe en échec — l'allowlist ne protège pas
# une zone, seulement la ligne précise revue une fois.
_ALLOWLIST_J = {
    # (fichier, "littéral exact") : "justification",
    ("wing_handler.py", '"origine non autorisée"'):
        "erreur de protocole HTTP (garde CORS/Origin) — précédent déjà "
        "documenté dans docs/I18N.md § « Ce qui reste volontairement en "
        "français » (\"{'error': 'not found'}\") : seul un client trafiqué "
        "peut la déclencher, jamais un navigateur normal sur l'app.",
    ("wing_handler.py",
     '"le port {p} est celui sur lequel MA3 écoute déjà "'):
        "route /api/osc/listen (observation OSC) : aucun ui/*.js n'appelle "
        "cette route — vérifié par grep, aucune occurrence dans ui/. "
        "Erreur JSON jamais rendue dans l'interface.",
    ("wing_handler.py", '"connexion déjà en cours"'):
        "le champ JSON \"raison\" n'est jamais lu côté client "
        "(bridge.js::wingAction ignore la réponse d'/api/wing/connect) — "
        "le vrai retour utilisateur pour ce cas est journal.wing.clic_ignore, "
        "déjà traduit et affiché dans le journal.",
    ("wing_handler.py",
     '"La désinstallation réelle n\'est possible que "'):
        "garde-fou développeur : ne se déclenche QUE si l'app tourne "
        "depuis les sources (pas sys.frozen) — impossible sur l'app "
        "distribuée que l'utilisateur final installe (voir GUIDE_PROJET.md).",
    ("wing_handler.py",
     '"depuis l\'application installée, pas depuis les "'):
        "suite du même message que ci-dessus (garde-fou sources vs app "
        "installée) — même justification.",
    ("wing_handler.py",
     '"sources. Utilise dry_run pour prévisualiser."'):
        "suite du même message que ci-dessus (garde-fou sources vs app "
        "installée) — même justification.",

    # wing_ma3.py — le champ base["erreur"] de ma3_etat() : vérifié par grep,
    # aucun appelant (wing_faders.py, wing_ma3.py, wing_raccourcis.py) ne lit
    # jamais .get("erreur") sur son résultat (seulement actif/page/executors/
    # masters), et aucune route de wing_handler.py ne renvoie ce dict brut au
    # client. Champ mort côté i18n : jamais montré à personne.
    ("wing_ma3.py", '"aucune sonde (plugin MA3 non installé ou arrêté)"'):
        "base[\"erreur\"] de ma3_etat() : jamais lu par un appelant, jamais "
        "renvoyé au client (voir note plus haut dans ce fichier).",
    ("wing_ma3.py", '"MA3 n\'est pas lancé — aucune sonde possible"'):
        "idem — base[\"erreur\"] de ma3_etat(), champ jamais lu.",
    ("wing_ma3.py", '"Sonde MA3 arrêtée : relance le plugin dans "'):
        "idem — base[\"erreur\"] de ma3_etat(), champ jamais lu.",
    ("wing_ma3.py", '"fichier d\'état illisible : {e}"'):
        "idem — base[\"erreur\"] de ma3_etat(), champ jamais lu.",

    # wing_raccourcis.py — _shcuts_ma3_reel() renvoie (None, note) quand la
    # jointure sonde↔fichier échoue ; `note` finit dans base["sonde_via"]
    # (shcuts_etat()). Vérifié par grep : sonde_via n'est lu que par le
    # smoke test (smoke_raccourcis.py), jamais par ui/*.js.
    ("wing_raccourcis.py",
     '"(plugin MA3 à relancer : Plugin 3 deux fois)"'):
        "base[\"sonde_via\"] : jamais lu côté client (grep ui/*.js), "
        "seulement par le smoke test.",
    ("wing_raccourcis.py",
     '"désaccord de structure : {len(liste)} raccourcis dans "'):
        "idem — base[\"sonde_via\"], jamais lu côté client.",
    ("wing_raccourcis.py",
     '"impossible, aucune vérification faite"'):
        "idem — base[\"sonde_via\"], jamais lu côté client.",

    ("wing_profils.py", '"profil-importé"'):
        "fallback du STEM de fichier (Path(nom_brut or …).stem, puis "
        "slugify) quand aucun nom n'est fourni à l'import — visible au plus "
        "dans le Finder/l'explorateur de fichiers, pas dans l'app ; même "
        "convention que les autres noms de fichiers de profils non "
        "traduits (défauts-sécurité.json, défauts.json).",

    # ── wing_demenagement.py ──────────────────────────────────────────────
    ("wing_demenagement.py", '"{source}.{nom} a déménagé : utiliser {cible} "'):
        "message d'AttributeError destiné au DÉVELOPPEUR : ne se lève que si "
        "un test ou un module lit/patche un nom déplacé par le découpage D3. "
        "Jamais montré à l'utilisateur de l'app.",

    # ── wing_init.py ──────────────────────────────────────────────────────
    ("wing_firmware.py", '"livré"'):   # déplacé de wing_init.py (D3, 25/09/2026)
        "jeton interne (source = \"cache\" if … else \"livré\"), comparé par "
        "=== côté client (ui/parametres.js::majFirmware) qui choisit lui-même "
        "ui.param.fw.src_livre/src_importe — jamais affiché tel quel.",
    ("wing_init.py", '"délai dépassé"'):
        "valeur de _ERR_USB/_ERR_ERRNO (et clé du dict _ERR_USB_CLES qui la "
        "mappe) : CODE INTERNE STABLE renvoyé par _err_usb(), comparé par "
        "égalité dans _partie_du_bus() — une traduction romprait la "
        "comparaison en anglais. Le TEXTE affiché passe par "
        "_err_usb_texte()/_ERR_USB_CLES, déjà résolu via wing_i18n.L().",
    ("wing_init.py", '"occupé"'):
        "idem — valeur/clé de _ERR_USB/_ERR_ERRNO/_ERR_USB_CLES, code interne "
        "stable, jamais affiché directement (voir _err_usb_texte()).",
    ("wing_init.py", '"erreur libusb générique (LIBUSB_ERROR_OTHER)"'):
        "idem — valeur/clé de _ERR_USB/_ERR_USB_CLES, code interne stable.",
    ("wing_init.py", '"configurée"'):
        "DERNIER_OPEN[\"config\"] : vérifié par grep (wing_handler.py, "
        "wing_ui.py) — seul DERNIER_OPEN[\"claim\"] est lu ailleurs, jamais "
        "[\"config\"]. Diagnostic interne à _open(), jamais exposé.",
    ("wing_init.py", '"déjà configurée — non retouchée"'):
        "idem — DERNIER_OPEN[\"config\"], jamais lu hors de _open().",
    ("wing_init.py", '"  [INIT] Phase 1 terminée, wing en reboot..."'):
        "print() gardé par `if verbose`, et full_init() est TOUJOURS appelé "
        "avec verbose=False depuis l'app (wing_connexion.py:128) — ne "
        "s'exécute que lancé en script directement (`python wing_init.py`, "
        "voir `if __name__ == \"__main__\"` en bas du fichier), jamais par "
        "un utilisateur de l'app.",
    ("wing_init.py", '"[INIT] Wing trouvée — état : {etat_usb} "'):
        "idem — print() sous `if verbose`, verbose=False dans l'app.",
    ("wing_init.py",
     '"  [INIT] Wing re-énumérée : {dev2.bus}/{dev2.address} — {etat_usb}"'):
        "idem — print() sous `if verbose`, verbose=False dans l'app.",
    ("wing_init.py", '"  [INIT] Wing prête pour le polling !"'):
        "idem — print() sous `if verbose`, verbose=False dans l'app.",
    ("wing_init.py", '"\\n✓ Wing initialisée et prête !"'):
        "print() dans `if __name__ == \"__main__\"` — CLI de développement "
        "(`python wing_init.py`), jamais atteint par l'app.",
    ("wing_init.py", '"\\n✗ Échec init"'):
        "idem — print() dans `if __name__ == \"__main__\"`, CLI seulement.",

    ("wing_ui.py", '"défauts-sécurité.json"'):
        "nom de FICHIER (SEED_PROFILE, comparé sur disque), pas un texte "
        "affiché — même convention que les autres noms de fichiers de "
        "profils non traduits (__reference__.json, défauts.json).",
    ("wing_ui.py",
     '"— l\'interface sera inerte. Cherché dans {JS_DIR}"'):
        "print() de diagnostic BUILD (ui/ incomplet) à l'import du module — "
        "jamais dans l'interface elle-même, seulement dans la console/le "
        "terminal, et seulement si le build est cassé (condition qui ne "
        "devrait jamais se produire pour un build normal).",
    ("wing_ui.py",
     '"— l\'interface restera en français. Cherché dans {LOCALES_DIR}"'):
        "idem — print() de diagnostic BUILD (locales/ incomplet), jamais "
        "dans l'interface, seulement en console si le build est cassé.",

    # wing_firmware_extract.py::_main() — CLI développeur autonome
    # (`python wing_firmware_extract.py capture.pcapng`), jamais invoquée par
    # l'app ni exposée via une route HTTP (voir GUIDE_PROJET.md : outil « pur
    # Python » séparé). argparse/print() de terminal, pas de l'UI.
    ("wing_firmware_extract.py",
     '"fichier de sortie (par défaut : wing_firmware.bin)"'):
        "argparse --help de la CLI développeur _main(), jamais exécutée "
        "par l'app.",
    ("wing_firmware_extract.py", '"  → écrit dans {args.output}"'):
        "print() de la CLI développeur _main(), jamais exécutée par l'app.",
    ("wing_firmware_extract.py",
     '"  Fichier NON écrit (le firmware extrait ne correspond pas à "'):
        "idem — print() de la CLI développeur _main().",

    ("ui/parametres.js", '"livré"'):
        "jeton interne comparé par === (fw.source, valeur JSON de "
        "/api/status côté serveur — voir wing_init.py) pour choisir entre "
        "t(\"ui.param.fw.src_livre\") et t(\"ui.param.fw.src_importe\") — "
        "jamais affiché tel quel. Même paire que l'entrée wing_init.py "
        "\"livré\" ci-dessus.",

    ("ui/i18n.js", '" non chargé ("'):
        "console.warn() du moteur i18n lui-même — visible seulement dans "
        "la console développeur du navigateur (DevTools), jamais dans "
        "l'interface : c'est justement le repli sur le texte du balisage "
        "(déjà en clair) qui garantit qu'aucun utilisateur ne voit rien "
        "de cassé.",
}

_ACCENTS = "àâäéèêëïîôöùûüçÀÂÄÉÈÊËÏÎÔÖÙÛÜÇ"
_STR_LIT_J = re.compile(
    r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|`(?:[^`\\]|\\.)*`', re.S)


def _blanchir_appels_exemptes_j(txt):
    """Remplace chaque appel `nom_exempte(...)` — parenthèses équilibrées,
    profondeur QUELCONQUE (comptage, pas une regex à 1 niveau comme (e)/(h) :
    `tHtml("...", { x: y.map(c => tHtml(...)).join(...) })` imbrique large)
    — par des espaces de même longueur, `\\n` préservés pour garder les
    numéros de ligne justes une fois passé au scan."""
    noms = sorted(_APPELS_EXEMPTES_J, key=len, reverse=True)
    motif = re.compile(r'\b(?:' + '|'.join(re.escape(n) for n in noms) + r')\s*\(')
    out, i = [], 0
    for m in motif.finditer(txt):
        if m.start() < i:
            continue                      # déjà dans un bloc blanchi précédent
        out.append(txt[i:m.start()])
        prof, j = 1, m.end()
        while j < len(txt) and prof > 0:
            if txt[j] == "(":
                prof += 1
            elif txt[j] == ")":
                prof -= 1
            j += 1
        out.append(re.sub(r"[^\n]", " ", txt[m.start():j]))
        i = j
    out.append(txt[i:])
    return "".join(out)


def _strip_commentaires_py(txt):
    """Docstrings triple-quotées puis commentaires `#…` → blancs (mêmes
    lignes). Une docstring EST de la documentation, explicitement hors
    périmètre (consigne : « hors commentaires »)."""
    def _blanc(m):
        return re.sub(r"[^\n]", " ", m.group(0))
    txt = re.sub(r'"""(?:[^"\\]|\\.|"(?!""))*"""', _blanc, txt, flags=re.S)
    txt = re.sub(r"'''(?:[^'\\]|\\.|'(?!''))*'''", _blanc, txt, flags=re.S)
    # Heuristique simple, même niveau de rigueur que (h) plus haut (qui coupe
    # aussi sur le 1er « # » de la ligne) : un « # » dans une chaîne est un
    # risque connu et accepté.
    return re.sub(r"#.*", "", txt)


def _strip_commentaires_js(txt):
    txt = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)),
                 txt, flags=re.S)
    return re.sub(r"//.*", "", txt)


def _fichiers_a_scanner_j():
    """(chemin, est_js) — tous les .py/.js du projet, hors wing_keyboard_*.py
    (binaire séparé, hors périmètre i18n) et hors smoke_*.py (le test de
    fumée lui-même, pas de l'UI). sandbox/ et archives/ ne sont PAS des .py de
    prod (GUIDE_PROJET.md : « bancs de test manuel », « scripts dont la question est
    tranchée ») — jamais vus par un utilisateur, donc hors périmètre aussi."""
    for p in sorted(HERE.glob("*.py")):
        if p.name.startswith(("wing_keyboard", "smoke_")):
            continue
        yield p, False
    for p in sorted(HERE.glob("ui/*.js")):
        yield p, True


def _test_i18n_pas_de_francais_en_dur():
    section("52. Aucun texte français en dur hors catalogue i18n")
    trouves = []
    for chemin, est_js in _fichiers_a_scanner_j():
        try:
            txt = chemin.read_text(encoding="utf-8")
        except Exception as e:
            echec(f"(j) {chemin.name} illisible", str(e))
            continue
        propre = (_strip_commentaires_js(txt) if est_js
                  else _strip_commentaires_py(txt))
        propre = _blanchir_appels_exemptes_j(propre)
        # ⚠️ as_posix() : les clés de _ALLOWLIST_J sont écrites avec un « / »
        # (« ui/parametres.js »). str(Path…) rend « ui\parametres.js » sous
        # Windows → la correspondance échouait et (j) sortait 2 faux positifs
        # (ui/i18n.js, ui/parametres.js) sur cette seule plateforme.
        rel = chemin.relative_to(HERE).as_posix()
        for m in _STR_LIT_J.finditer(propre):
            lit = m.group(0)
            if not any(c in _ACCENTS for c in lit):
                continue
            if (rel, lit) in _ALLOWLIST_J:
                continue
            ligne = propre.count("\n", 0, m.start()) + 1
            trouves.append(f"{rel}:{ligne}: {lit[:90]}")
    if trouves:
        echec(f"(j) {len(trouves)} littéral(aux) accentué(s) hors catalogue "
              f"i18n", "\n    ".join(trouves[:20])
              + ("\n    …" if len(trouves) > 20 else "")
              + "\n    — texte français en dur, invisible pour (a)-(i). "
              "Extrais-le vers une clé (fr.json + en.json), ou justifie une "
              "entrée dans _ALLOWLIST_J si c'est un cas légitime "
              "(voir docs/I18N.md § « Ce qui reste volontairement en "
              "français »)")
    else:
        ok(f"(j) {sum(1 for _ in _fichiers_a_scanner_j())} fichier(s) "
           f".py/.js scannés : aucun littéral accentué hors catalogue")
