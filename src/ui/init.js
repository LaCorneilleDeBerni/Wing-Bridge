/* ui/init.js — amorçage — DOIT être chargé EN DERNIER (il appelle les autres)
   ─────────────────────────────────────────────────────────────
   Sorti de wing_ui.js lors du découpage du JS par onglet.
   ⚠️ PORTÉE GLOBALE : ces fichiers sont des <script> CLASSIQUES,
      jamais des modules ES — une quarantaine de gestionnaires
      inline du balisage (onclick=…) en dépendent.
   ⚠️ ORDRE DE CHARGEMENT IMPOSÉ : core en premier, init en
      dernier. Voir l'ordre des <script defer> dans wing_ui.html. */

// ── Init ──────────────────────────────────────────────────────────────
//
// ⚠️ On ATTEND que les catalogues i18n soient chargés (window.I18N_PRET, posé
// par ui/i18n.js) AVANT le premier rendu : sinon les libellés dynamiques
// (bridgeBtn, wingBtn…) sortiraient en clé brute le temps du fetch, puis
// sauteraient à leur texte au tour de poll() suivant. I18N_PRET encaisse déjà
// l'échec réseau — si le catalogue ne charge pas, le français du balisage
// reste, et on amorce quand même.
I18N_PRET.then(demarrerInterface);

// ⚠️ RÉFÉRENCE AU NIVEAU SUPÉRIEUR, pas un appel : un minuteur dont la cible a
// été supprimée (`setInterval(pollOscIn, 1000)` resté après la disparition de
// `pollOscIn` — panne du build 144) lève un ReferenceError ici, que le contrôle
// test_js_execute attrape en exécutant le script. Les `setInterval` réels, eux,
// vivent DANS demarrerInterface (donc après I18N_PRET) : `poll()` ne doit
// JAMAIS tourner avant que le catalogue soit chargé, sinon `t()` rend la clé
// brute (« ui.bridge.bouton.demarrer », plus longue que le libellé) comme texte
// de bouton → les gros boutons enflent puis rétrécissent au chargement.
void [poll, pollDMX];

// ── Fermer la fenêtre = éteindre Wing Bridge ─────────────────────────────────
//
// 🎯 Décision de l'auteur : plus jamais de process serveur en fond. Fermer
// l'onglet coupe le moteur — comme « ⏻ Quitter » (même chemin d'arrêt côté
// serveur, la wing repart en bootloader). L'encart permanent de l'onglet Bridge
// (ui.bridge.vie.encart) l'explique.
//
// ⚠️ Deux écouteurs, deux rôles :
//   • beforeunload : déclenche le dialogue GÉNÉRIQUE du navigateur (« quitter le
//     site ? »). Son texte n'est PAS personnalisable — limite navigateur, on ne
//     cherche pas à la contourner.
//   • pagehide : la page s'en va pour de bon → on prévient le serveur par
//     sendBeacon (part à la fermeture sous Chrome/Edge/Firefox/Safari). Le
//     serveur arme un arrêt différé ; si c'était un rechargement (F5), le poll
//     qui revient l'annule dans la fenêtre de grâce.
//
// Un simple arrêt du poll (veille de l'ordi, coupure réseau) ne passe PAS par
// là : SEUL le beacon explicite éteint l'app. La veille ne tue rien.
window.addEventListener("beforeunload", (e) => {
  if (arretVolontaire) return;          // quitApp / hardReset : on gère nous-mêmes
  e.preventDefault();
  e.returnValue = "";                   // requis par Chrome / anciens navigateurs
});
window.addEventListener("pagehide", () => {
  if (arretVolontaire) return;
  // `?jeton=` : sendBeacon ne sait pas poser d'en-tête (voir api(), ui/core.js).
  try { navigator.sendBeacon("/api/fermeture-onglet?jeton="
                             + encodeURIComponent(jetonApi())); } catch (e) {}
});

function demarrerInterface() {
  appliquerLangue(LANG);   // pose la langue + traduit le DOM statique
  initHelp();
  construireAide();   // la page Aide, bâtie depuis ui/aides.js
  // ⚠️ UN ÉCHEC DE CHARGEMENT NE DOIT PAS LAISSER L'ÉCRAN VIDE.
  //
  // `loadProfile()` remplit les tables des touches, des faders, des roues et
  // des raccourcis. Si son `await api(...)` échoue (hoquet réseau au démarrage,
  // serveur pas encore prêt), la promesse était rejetée EN SILENCE : les tables
  // restaient vides et l'utilisateur croyait ses réglages disparus.
  //
  // Signalé deux fois — « les options de personnalisation ne sont plus là »,
  // puis « il n'y a pas de raccourcis clavier » — sans reproduction possible,
  // parce que le code est correct : c'est le cas d'ÉCHEC qui n'était pas traité.
  // On réessaie, et on le DIT.
  (async function demarrer() {
    for (let essai = 1; essai <= 3; essai++) {
      try {
        await loadProfile();
        await loadProfiles();
        return;
      } catch (e) {
        if (essai === 3) {
          const j = document.getElementById("logbox");
          if (j) j.innerHTML = tHtml("ui.init.profil_echec", { erreur: e.message })
            + j.innerHTML;
          console.error("profile load failed", e);   // console développeur uniquement
          return;
        }
        await new Promise(r => setTimeout(r, 400 * essai));
      }
    }
  })();
  loadAttrs();
  loadKeywords();
  loadFaderFuncs();
  shcutsRafraichir();
  poll();

  // ── Les deux minuteurs de l'interface ──────────────────────────────────────
  // Démarrés ICI, après I18N_PRET : leur premier tour voit un catalogue chargé.
  // Regroupés, on voit d'un coup d'œil TOUT ce qui tourne en boucle dans la page.
  setInterval(poll, 400);     // état de la chaîne (wing, OSC, sonde, journal)
  setInterval(pollDMX, 300);  // aperçu DMX — ne fait rien hors onglet Paramètres
}
