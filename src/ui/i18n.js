/* ui/i18n.js — moteur d'internationalisation (client)
   ─────────────────────────────────────────────────────────────
   ⚠️ PORTÉE GLOBALE : <script> CLASSIQUE, jamais un module ES — les
      gestionnaires inline du balisage (onclick="appliquerLangue('fr')"…)
      exigent que `t`, `appliquerLangue`… soient des globales.
   ⚠️ ORDRE DE CHARGEMENT : juste APRÈS core.js, AVANT tous les autres —
      bridge.js/touches.js/… appellent `t(...)` dès leur premier rendu.
      init.js (en dernier) attend `I18N_PRET` avant d'amorcer l'interface.

   Comment ça marche, conventions, limites : voir docs/I18N.md

   PRINCIPE : le balisage porte le français EN CLAIR (c'est la langue par
   défaut, et le repli si le catalogue ne charge pas) DOUBLÉ d'un attribut
   `data-i18n="clé"`. Les chaînes nées dans le JS passent par `t("clé")`.
   Le catalogue (locales/fr.json, locales/en.json) est la seule source de
   vérité des traductions ; il est servi par une route dédiée du moteur
   (voir wing_handler._get_locale). */

/* ── Langue courante ──────────────────────────────────────────────────
   Choix : préférence mémorisée > langue du navigateur > anglais. */
let LANG = (function () {
  try {
    const stocke = localStorage.getItem("wingLang");
    if (stocke === "fr" || stocke === "en") return stocke;
  } catch (e) { /* localStorage indisponible : on retombe sur le navigateur */ }
  const nav = String(navigator.language || "").toLowerCase();
  return nav.indexOf("fr") === 0 ? "fr" : "en";
})();

/* ── Catalogues ───────────────────────────────────────────────────────
   Remplis par chargerCatalogues() au démarrage. Tant qu'ils sont vides,
   `t()` renvoie le repli et appliquerLangue() ne touche pas au DOM :
   le français du balisage reste affiché, donc AUCUN scintillement de
   clés brutes même si la route est injoignable. */
const CATALOGUE = { fr: {}, en: {} };

/* Les langues qu'un contributeur a ajoutées se déclarent ici ET dans
   REGLES_PLURIEL. `fr`/`en` d'abord, les autres à la suite. */
const LANGUES_SUPPORTEES = ["fr", "en"];

async function chargerCatalogues() {
  await Promise.all(LANGUES_SUPPORTEES.map(async (lg) => {
    try {
      const r = await fetch("/locales/" + lg + ".json", { cache: "no-store" });
      if (r.ok) CATALOGUE[lg] = await r.json();
      else console.warn("i18n : /locales/" + lg + ".json → HTTP " + r.status);
    } catch (e) {
      console.warn("i18n : catalogue " + lg + " non chargé (" + e
                   + ") — repli sur le texte du balisage");
    }
  }));
}

/* Promise résolue quand les catalogues sont là (ou l'échec encaissé).
   init.js l'attend avant le premier rendu. */
window.I18N_PRET = chargerCatalogues();

/* ── Interpolation : "{nom}" → params.nom ─────────────────────────────
   Un trou sans valeur est laissé tel quel (visible = bug repérable,
   plutôt que "undefined" ou une phrase tronquée). */
function _interpoler(chaine, params) {
  if (!params) return chaine;
  return String(chaine).replace(/\{(\w+)\}/g, function (brut, cle) {
    return (params[cle] != null) ? params[cle] : brut;
  });
}

/* ── t() : une clé → sa traduction ───────────────────────────────────
   Repli en cascade : langue courante → français → la clé elle-même
   (jamais afficher une clé brute en conditions normales : le français
   est toujours présent dans fr.json). */
function t(cle, params) {
  let s = CATALOGUE[LANG] && CATALOGUE[LANG][cle];
  if (s == null) s = CATALOGUE.fr && CATALOGUE.fr[cle];
  if (s == null) s = cle;
  return _interpoler(s, params);
}

/* tHtml() : le GABARIT peut contenir des balises (il vient du catalogue, donc
   de nous) et sera posé via innerHTML. Séparé de t() pour que l'intention
   soit lisible sur le site d'appel (et vérifiable par le test de fumée).

   🔒 LES PARAMÈTRES SONT ÉCHAPPÉS PAR DÉFAUT. Ils portent des données :
   nom de touche, frappe, attribut de roue — souvent venues d'un profil
   importé. Les interpoler brutes dans innerHTML, c'était laisser un profil
   exécuter du JavaScript dans l'interface. Un paramètre qui est LUI-MÊME du
   HTML déjà construit par tHtml() passe par brut() (ui/core.js) — et
   seulement celui-là. Contrôle test_xss_profil_importe (smoke_securite.py). */
function tHtml(cle, params) {
  if (!params) return t(cle);
  const surs = {};
  Object.keys(params).forEach(function (k) {
    const v = params[k];
    surs[k] = (v && typeof v === "object" && "__htmlSur" in v)
      ? v.__htmlSur : (v == null ? v : esc(v));
  });
  return t(cle, surs);
}

/* ── Pluriel ─────────────────────────────────────────────────────────
   fr : n ≤ 1 → "one", sinon "other".
   en : n === 1 → "one", sinon "other".
   Les langues à pluriels multiples (pl, ru, cs, ar…) ajoutent ici une
   fonction n → "zero"|"one"|"two"|"few"|"many"|"other", et les formes
   correspondantes dans le catalogue. La table est volontairement
   explicite plutôt que de dépendre d'Intl.PluralRules : "télécharge et
   lance", pas de surprise selon la version du moteur JS. */
const REGLES_PLURIEL = {
  fr: function (n) { return Math.abs(n) <= 1 ? "one" : "other"; },
  en: function (n) { return n === 1 ? "one" : "other"; },
};

/* plural(cle, n, params) : comme t(), mais choisit la FORME selon `n`.
   La clé du catalogue est un préfixe ; les formes sont des sous-clés :
     "ui.x.frappes.one"   = "{n} frappe déjà prise"
     "ui.x.frappes.other" = "{n} frappes déjà prises"
   `plural("ui.x.frappes", n, { items: … })` → forme + interpolation ({n} inclus).
   Les catalogues fr/en n'ont que .one / .other ; une langue à pluriels
   multiples ajoute .few / .many… (règle correspondante dans REGLES_PLURIEL). */
function plural(cle, n, params) {
  const regle = REGLES_PLURIEL[LANG] || REGLES_PLURIEL.fr;
  const cat = regle(Number(n));
  const p = Object.assign({ n: n }, params || {});
  let s = CATALOGUE[LANG] && (CATALOGUE[LANG][cle + "." + cat]
                              || CATALOGUE[LANG][cle + ".other"]);
  if (s == null) s = CATALOGUE.fr && (CATALOGUE.fr[cle + "." + cat]
                                      || CATALOGUE.fr[cle + ".other"]);
  if (s == null) s = cle;
  return _interpoler(s, p);
}

/* ── appliquerLangue() : bascule + traduction à chaud ────────────────
   1. pose LANG + mémorise + <html lang>
   2. si le catalogue de la langue est chargé, remplace le texte des
      [data-i18n], le HTML des [data-i18n-html], et les attributs
      title / placeholder / aria-label des [data-i18n-<attr>]
   3. re-render des zones dynamiques (poll(), construireAide()…)
   4. met en évidence le drapeau actif

   ⚠️ [data-i18n-dynamic] : les éléments dont le texte est piloté par l'état
   (bridgeBtn « Démarrer / Arrêter », wingBtn « Connecter / Reconnecter »,
   learnBtn, l'étiquette de la ligne de commande…). On NE touche PAS leur
   textContent ici — c'est `poll()` qui en est le seul maître, appelé juste
   après. Sans ça : double écriture (statique puis dynamique) à chaque bascule.
   Ils gardent `data-i18n` uniquement pour le repli hors-JS et le test de fumée. */
function appliquerLangue(lang) {
  if (LANGUES_SUPPORTEES.indexOf(lang) === -1) lang = "fr";
  LANG = lang;
  try { localStorage.setItem("wingLang", lang); } catch (e) { /* sans mémoire, tant pis */ }
  document.documentElement.setAttribute("lang", lang);

  /* Le serveur a AUSSI une langue courante (wing_i18n.LANGUE) : elle décide
     de la langue du journal affiché, des messages d'erreur actionnables et
     des étapes de l'assistant firmware. On la synchronise ici — envoi
     best-effort : si la route manque (vieux moteur) ou échoue, le prochain
     /api/status rendra simplement le journal dans l'ancienne langue, sans
     casser la bascule du DOM. Le fichier wing_server.log, lui, reste anglais
     quoi qu'il arrive. */
  try {
    if (typeof api === "function") api("/api/lang", { lang: lang }).catch(function () {});
  } catch (e) { /* le serveur suivra au pire au prochain redémarrage */ }

  const cat = CATALOGUE[lang];
  if (cat && Object.keys(cat).length) {
    document.querySelectorAll("[data-i18n]:not([data-i18n-dynamic])").forEach(function (el) {
      const v = cat[el.getAttribute("data-i18n")];
      if (v != null) el.textContent = v;
    });
    document.querySelectorAll("[data-i18n-html]").forEach(function (el) {
      const v = cat[el.getAttribute("data-i18n-html")];
      if (v != null) el.innerHTML = v;
    });
    ["title", "placeholder", "aria-label"].forEach(function (attr) {
      const da = "data-i18n-" + attr;
      document.querySelectorAll("[" + da + "]").forEach(function (el) {
        const v = cat[el.getAttribute(da)];
        if (v != null) el.setAttribute(attr, v);
      });
    });
  }

  /* Zones peintes par le JS : on les rejoue pour qu'elles se re-traduisent.
     Chacune dans son try — une zone absente ou en erreur ne doit pas
     empêcher la bascule des autres. */
  try { if (typeof poll === "function") poll(); } catch (e) { /* re-render best-effort */ }
  try { if (typeof pollDMX === "function") pollDMX(); } catch (e) { /* idem */ }
  try { if (typeof construireAide === "function") construireAide(); } catch (e) { /* idem */ }
  // Les tableaux touches / faders / roues et la liste des profils sont
  // reconstruits en JS (libellés d'options, titres…) : on les rejoue pour
  // qu'ils sortent dans la nouvelle langue. Une bascule est un geste
  // délibéré — pas un poll — donc le coût d'un rechargement est acceptable.
  try { if (typeof loadProfile === "function") loadProfile(); } catch (e) { /* idem */ }
  try { if (typeof loadProfiles === "function") loadProfiles(); } catch (e) { /* idem */ }
  try { if (typeof loadFaderFuncs === "function") loadFaderFuncs(); } catch (e) { /* idem */ }
  try { if (typeof renderAttrs === "function") renderAttrs(); } catch (e) { /* idem */ }
  // Procédure manuelle du plugin grandMA3 : pas de data-i18n-html (le slot y
  // est interpolé), donc pas retraduite par le passage générique ci-dessus —
  // on la rejoue avec le slot actuellement affiché (0 poll écoulé depuis le
  // chargement ⇒ champ vide ⇒ repli sur le défaut, 3).
  try {
    if (typeof majPluginProcedureManuelle === "function") {
      const el = document.getElementById("pluginSlotInput");
      majPluginProcedureManuelle((el && el.value) ? el.value : 3);
    }
  } catch (e) { /* idem */ }

  const bf = document.getElementById("langFr");
  const be = document.getElementById("langEn");
  if (bf) bf.classList.toggle("actif", lang === "fr");
  if (be) be.classList.toggle("actif", lang === "en");
}
