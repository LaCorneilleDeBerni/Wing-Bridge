"""i18n côté serveur — miroir Python du moteur client (`ui/i18n.js`).

Le bilingue FR/EN repose sur UN catalogue plat partagé :
`locales/fr.json` + `locales/en.json`, les MÊMES fichiers que le client, lus
par `wing_ui._lire_locale` (même liste blanche, même cache). Ce module n'ouvre
aucun fichier lui-même : il demande le contenu à `wing_ui` et le parse une fois.

Trois façons de résoudre une clé, selon la SURFACE (voir docs/I18N.md,
« Côté serveur ») :

| Surface                                   | Fonction   | Langue          |
|-------------------------------------------|------------|-----------------|
| Journal affiché dans l'interface          | `L(...)`   | `LANGUE`        |
| Message d'erreur actionnable (JSON `raison`)| `L(...)` | `LANGUE`        |
| Étapes de l'assistant firmware            | `L(...)`   | `LANGUE`        |
| Fichier `wing_server.log` sur disque      | `L_en(...)`| toujours anglais|
| Rapport de diagnostic                     | `L_en(...)`| toujours anglais|

`LANGUE` est une variable de module, défaut `"fr"`, posée par
`POST /api/lang` (voir `wing_handler._post_lang`). Le client l'appelle depuis
`appliquerLangue()` (`ui/i18n.js`) en plus de sa traduction du DOM.

⚠️ `import wing_ui as core` est fait À L'INTÉRIEUR de `_cat()`, jamais en tête :
`wing_ui` importe `wing_reglages` qui, lui, appelle `wing_i18n` — un import en
tête bouclerait. Le pattern est celui de tout le projet.
"""

import re

# Langue courante des surfaces « langue de l'app ». Posée par POST /api/lang.
LANGUE = "fr"

# Repli ultime : le français est la langue de référence, toute clé y existe.
_REPLI = "fr"

# Catalogues parsés, remplis paresseusement par _cat().
_CAT = {}

# "{nom}" → params["nom"] ; un trou sans valeur est laissé littéralement
# (visible = bug repérable, comme côté client).
_TROU = re.compile(r"\{(\w+)\}")

# n → catégorie CLDR, par langue. Table explicite (pas de dépendance à une lib
# de pluriel) : comportement identique quelle que soit la version de Python.
# fr : n ≤ 1 → "one" (le français met « 0 » au singulier) ; en : n == 1 → "one".
# Les langues à pluriels multiples ajoutent leur règle ici + les formes
# .few/.many… au catalogue.
_REGLES_PLURIEL = {
    "fr": lambda n: "one" if abs(n) <= 1 else "other",
    "en": lambda n: "one" if n == 1 else "other",
}


def poser_langue(lang: str) -> bool:
    """Pose `LANGUE` si `lang` est connue. Renvoie True si prise en compte.
    Seul point d'écriture — `wing_handler._post_lang` passe par ici."""
    global LANGUE
    if lang in _REGLES_PLURIEL:
        LANGUE = lang
        return True
    return False


def _cat(lang: str) -> dict:
    """Le catalogue `lang`, parsé et mis en cache. `{}` si indisponible."""
    if lang not in _CAT:
        d = {}
        try:
            import json
            import wing_ui as core
            d = json.loads(core._lire_locale(lang) or "{}")
        except Exception:
            d = {}
        _CAT[lang] = d if isinstance(d, dict) else {}
    return _CAT[lang]


def vider_cache():
    """Oublie les catalogues parsés — pour les tests, ou après un rechargement
    du catalogue disque."""
    _CAT.clear()


def _interpoler(chaine, params):
    if not params:
        return chaine
    def _sub(m):
        v = params.get(m.group(1))
        return str(v) if v is not None else m.group(0)
    return _TROU.sub(_sub, str(chaine))


def _resoudre(cle, langue, params):
    """langue → repli fr → la clé brute (dernier recours)."""
    s = _cat(langue).get(cle)
    if s is None and langue != _REPLI:
        s = _cat(_REPLI).get(cle)
    if s is None:
        s = cle
    return _interpoler(s, params)


def _pluriel(cle, n, langue, params):
    """Comme `_resoudre`, mais choisit la FORME (`cle.one`/`cle.other`/…)
    selon `n`. `{n}` est injecté dans les params."""
    try:
        n_num = float(n)
    except (TypeError, ValueError):
        n_num = 0.0
    forme = _REGLES_PLURIEL.get(langue, _REGLES_PLURIEL[_REPLI])(n_num)
    p = dict(params or {})
    p.setdefault("n", n)
    for lg in (langue, _REPLI):
        d = _cat(lg)
        s = d.get(f"{cle}.{forme}") or d.get(f"{cle}.other")
        if s is not None:
            return _interpoler(s, p)
    return _interpoler(cle, p)


# ── API publique ────────────────────────────────────────────────────────────

def L(cle, **params):
    """Résout `cle` dans `LANGUE` (repli fr, puis clé brute). Surfaces
    « langue de l'app » : journal affiché, `raison` des réponses JSON,
    étapes de l'assistant firmware."""
    return _resoudre(cle, LANGUE, params)


def L_en(cle, **params):
    """Force l'anglais (repli fr). Surfaces TOUJOURS anglaises : le fichier
    `wing_server.log` sur disque, le rapport de diagnostic."""
    return _resoudre(cle, "en", params)


def plural(cle, n, **params):
    """Miroir serveur de `plural()` client : forme selon `n`, dans `LANGUE`."""
    return _pluriel(cle, n, LANGUE, params)


def rendre(cle, params, n, langue):
    """Rend une entrée de journal STRUCTURÉE (`cle` + `params`, `n` non-None si
    c'est un pluriel) dans `langue`. Utilisé par `wing_reglages` :
    `langue=LANGUE` pour l'interface, `langue="en"` pour le disque."""
    if n is not None:
        return _pluriel(cle, n, langue, params or {})
    return _resoudre(cle, langue, params or {})
