/* ui/aides.js — la LISTE des sujets d'aide de l'interface, à un seul endroit
   ─────────────────────────────────────────────────────────────────────────
   ⚠️ CES TEXTES SONT LUS PAR L'UTILISATEUR. Ils décrivent donc ce que l'app
   FAIT AUJOURD'HUI, jamais son histoire : pas de numéro de build, pas de date,
   pas de « avant ça marchait autrement ». Un utilisateur qui installe l'app
   n'a pas connu les versions précédentes — lui en parler l'égare.
   Le récit va dans docs/, la règle va ici.

   Avant, l'aide vivait dans 11 blocs <details> semés dans le balisage, dont 7
   dans le seul onglet Bridge : l'écran était noyé d'explications qu'on ne lit
   qu'une fois.

   🔑 UNE SEULE SOURCE, désormais les catalogues i18n. Les TEXTES (titre + corps
   HTML) ne sont PLUS ici : ils vivent dans locales/fr.json et locales/en.json,
   sous les clés `aide.<sujet>.titre` / `aide.<sujet>.html`, résolues par
   `t()`/`tHtml()` dans `aide()` et `construireAide()` (ui/core.js). Ce fichier
   ne porte que la LISTE des sujets connus et leur classement par onglet —
   recopier les textes ici les aurait fait diverger du catalogue, exactement
   la classe de bug que ce projet paie le plus cher.

   ⚠️ PORTÉE GLOBALE : fichier <script> classique, jamais un module ES.
   ⚠️ Chargé APRÈS core.js et AVANT init.js (mais AVANT i18n.js n'est pas requis :
      ce fichier ne résout aucune clé lui-même, il ne fait que les nommer). */

// ── Classement par onglet, pour la page Aide ─────────────────────────────────
// ⚠️ Toute rubrique ajoutée doit apparaître ici, sinon elle sera joignable par
//    son « ? » (si un bouton l'appelle) mais INTROUVABLE dans la page Aide. Le
//    contrôle test_aides_completes du test de fumée refuse un classement
//    incomplet.
// Le 1er élément de chaque paire est la clé i18n du nom d'onglet (`ui.nav.*`) —
// PAS un libellé en dur : la page Aide doit afficher le même nom que l'onglet
// réel dans la langue courante.
const AIDES_PAR_ONGLET = [
  ["ui.nav.bridge", ["demarrage", "suivreMa3", "faderPickup", "ledMa3",
                      "verbeCible", "usbArrache", "plugin"]],
  ["ui.nav.touches", ["raccourcis", "accessibilite", "conflitRaccourci"]],
  ["ui.nav.encodeurs", ["suivreEncMa3"]],
];

// Liste plate, pour que aide(cle) puisse refuser une rubrique inconnue SANS
// deviner (le catalogue, lui, renverrait la clé brute plutôt que rien).
const AIDES_SUJETS = new Set(AIDES_PAR_ONGLET.flatMap(([, cles]) => cles));
