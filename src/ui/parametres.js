/* ui/parametres.js — onglet Paramètres : DMX, LEDs, scan USB
   ─────────────────────────────────────────────────────────────
   Sorti de wing_ui.js lors du découpage du JS par onglet.
   ⚠️ PORTÉE GLOBALE : ces fichiers sont des <script> CLASSIQUES,
      jamais des modules ES — une quarantaine de gestionnaires
      inline du balisage (onclick=…) en dépendent.
   ⚠️ ORDRE DE CHARGEMENT IMPOSÉ : core en premier, init en
      dernier. Voir l'ordre des <script defer> dans wing_ui.html. */

async function saveLedMa3() {
  await api("/api/led", {ma3: document.getElementById("ledMa3").checked});
}

// ── Configurer le firmware ────────────────────────────────────────────
// Le firmware appartient à MA Lighting : la distrib OSS ne le livre pas. On
// importe une capture (.pcapng, extraite côté serveur) ou un .bin, mis en cache.
// Les sélecteurs de fichier sont NATIFS et ouverts côté serveur (voir
// wing_handler._choisir_fichier) — d'où l'absence d'<input type=file> ici.
function _fwMsg(txt, cls) {
  const el = document.getElementById("fwMsg");
  if (!el) return;
  el.textContent = txt || "";
  el.style.color = cls === "err" ? "var(--red)"
                 : cls === "ok" ? "var(--green)" : "";
}
async function fwImportCapture() {
  _fwMsg(t("firmware.msg.selection_capture"));
  let r;
  try { r = await api("/api/firmware/import_capture", {}); }
  catch (e) { _fwMsg(t("firmware.msg.echec_requete"), "err"); return; }
  if (r && r.annule) { _fwMsg(""); return; }
  if (r && r.ok) _fwMsg(t("firmware.msg.capture_ok"), "ok");
  else _fwMsg("✗ " + ((r && r.raison) || t("firmware.msg.echec")), "err");
}
async function fwImportBin() {
  _fwMsg(t("firmware.msg.selection_bin"));
  let r;
  try { r = await api("/api/firmware/import_bin", {}); }
  catch (e) { _fwMsg(t("firmware.msg.echec_requete"), "err"); return; }
  if (r && r.annule) { _fwMsg(""); return; }
  if (r && r.ok) _fwMsg(t("firmware.msg.bin_ok"), "ok");
  else _fwMsg("✗ " + ((r && r.raison) || t("firmware.msg.echec")), "err");
}
async function fwExport() {
  _fwMsg(t("firmware.msg.selection_destination"));
  let r;
  try { r = await api("/api/firmware/export", {}); }
  catch (e) { _fwMsg(t("firmware.msg.echec_requete"), "err"); return; }
  if (r && r.annule) { _fwMsg(""); return; }
  if (r && r.ok) _fwMsg(t("firmware.msg.export_ok"), "ok");
  else _fwMsg("✗ " + ((r && r.raison) || t("firmware.msg.echec")), "err");
}
// Appelée par poll() (bridge.js) à chaque tick : reflète l'état du firmware
// dans la carte Paramètres et n'affiche « Exporter » qu'une fois en cache.
function majFirmware(fw) {
  const etat = document.getElementById("firmwareEtat");
  const btnExport = document.getElementById("fwExportBtn");
  const banner = document.getElementById("firmwareBanner");
  const configure = !!(fw && fw.configure);
  if (banner) banner.style.display = configure ? "none" : "";
  if (btnExport) btnExport.style.display = configure ? "" : "none";
  if (etat) {
    if (!fw) { etat.textContent = ""; etat.style.color = ""; return; }
    if (configure) {
      const src = fw.source === "livré" ? t("ui.param.fw.src_livre") : t("ui.param.fw.src_importe");
      etat.textContent = t("ui.param.fw.en_place", { src: src,
        empreinte: fw.sha256_ok ? t("ui.param.fw.empreinte_ok") : t("ui.param.fw.empreinte_ko") });
      etat.style.color = fw.sha256_ok ? "var(--green)" : "var(--accent)";
    } else {
      etat.textContent = t("ui.param.fw.aucun");
      etat.style.color = "var(--accent)";
    }
  }
}
// ── Capture intégrée du firmware (Windows x64 uniquement, PAS ARM) ──────
// Le gros du travail (élévation, installation/désinstallation éphémère de
// USBPcap, capture, extraction) est côté serveur (wing_firmware_capture.py) —
// ce JS ne fait que : afficher l'encart de confirmation, lancer la capture,
// et refléter sa progression (pollée via /api/status → s.capture, toutes les
// 400 ms comme le reste du panneau santé, voir ui/init.js).
async function fwCaptureAmorcer() {
  const confirm_ = document.getElementById("fwCaptureConfirm");
  if (confirm_) confirm_.style.display = "";
}
function fwCaptureAnnuler() {
  const confirm_ = document.getElementById("fwCaptureConfirm");
  if (confirm_) confirm_.style.display = "none";
}
async function fwCaptureContinuer() {
  const confirm_ = document.getElementById("fwCaptureConfirm");
  if (confirm_) confirm_.style.display = "none";
  const resultat = document.getElementById("fwCaptureResultat");
  if (resultat) { resultat.style.display = "none"; resultat.textContent = ""; }
  const suite = document.getElementById("fwCaptureSuite");
  if (suite) suite.style.display = "none";
  // Repartir propre : masquer un aiguillage d'un run précédent, réarmer Annuler.
  const aig = document.getElementById("fwCaptureAiguillage");
  if (aig) aig.style.display = "none";
  _fwAnnulDemande = false;
  const annMsg = document.getElementById("fwCaptureAnnulerMsg");
  if (annMsg) annMsg.textContent = "";
  let r;
  try { r = await api("/api/firmware/capture", {}); }
  catch (e) { _fwCaptureResultat(t("ui.param.echec_requete"), "err"); return; }
  if (!r || !r.ok) _fwCaptureResultat("✗ " + ((r && r.raison) || t("firmware.msg.echec_lancement")), "err");
  // Si r.ok : rien à afficher tout de suite, majCapture() prend le relais
  // dès le prochain poll (CAPTURE_STATE.actif devient vrai côté serveur).
}
async function fwRetirerComposant() {
  const btn = document.getElementById("fwRemoveCaptureBtn");
  if (btn) btn.disabled = true;
  let r;
  try { r = await api("/api/firmware/remove_capture_component", {}); }
  catch (e) { _fwCaptureResultat(t("ui.param.echec_requete"), "err"); if (btn) btn.disabled = false; return; }
  if (r && r.ok) _fwCaptureResultat(t("ui.param.fw.composant_retire"), "ok");
  else _fwCaptureResultat("✗ " + ((r && r.raison) || t("firmware.msg.echec")), "err");
  if (btn) btn.disabled = false;
}
function _fwCaptureResultat(txt, cls) {
  const el = document.getElementById("fwCaptureResultat");
  if (!el) return;
  el.style.display = "";
  el.textContent = txt;
  el.style.color = cls === "err" ? "var(--red)" : cls === "ok" ? "var(--green)"
                  : cls === "warn" ? "var(--accent)" : "";
  // "warn" (redémarrage requis, résidu…) mérite plus de poids visuel qu'un
  // simple message de statut : c'est une action concrète à faire, pas un
  // détail : sans ça, le résultat passait inaperçu.
  el.style.fontWeight = cls === "warn" ? "600" : "";
}
// Appelée par poll() (bridge.js) à chaque tick, comme majFirmware. `cap` est
// s.capture : null hors Windows x64 (module absent du build, ou hôte ARM —
// USBPcap/grandMA2 onPC n'existent qu'en x64) — dans ce cas la carte de
// capture intégrée entière reste masquée, le repli manuel (.pcapng / .bin) suffit.
let _fwCaptureActifPrec = false;
let _fwAnnulDemande = false;     // « Annuler la démarche » cliqué, thread pas fini
// Construit la barre d'étapes 1/7 … 7/7 : segments verts jusqu'à la phase
// courante, gris ensuite. Vidée puis reconstruite à chaque poll (bon marché,
// 7 <div>) — c'est le repère visuel qui rend l'ordre des gestes impossible à
// rater pendant toute l'opération. `total` vient du serveur (phase_total).
function _fwCaptureStepbar(phase, total) {
  const bar = document.getElementById("fwCaptureStepbar");
  if (!bar) return;
  bar.textContent = "";
  for (let i = 1; i <= total; i++) {
    const seg = document.createElement("div");
    seg.style.cssText = "flex:1;height:6px;border-radius:3px;background:"
      + (i <= phase ? "var(--green)" : "var(--border)");
    bar.appendChild(seg);
  }
}
// Pastilles A–E de la phase de mise en route (post-firmware) — voir le
// commentaire du balisage (#mercWizStepbar) pour pourquoi des LETTRES et pas
// des chiffres. `states` : {A:'done'|'current'|'pending'|'warn', B:…, …}.
// 'warn' : cas révélé le 18/09/2026 — une étape déjà marquée « done » sur la
// foi d'un signal PARTIEL (reachable === "ok") s'avère fausse une fois la
// preuve complète disponible (_oscConfigOk, seulement possible sonde active).
// Une pastille verte qui ment coûte plus cher qu'une pastille orange — voir
// #finalBloqueOsc. Recalculée à chaque poll, jamais mémorisée.
function _mercWizStepbar(states) {
  const ids = { A: "mercPillA", B: "mercPillB", C: "mercPillC", D: "mercPillD", E: "mercPillE" };
  const couleur = { done: "var(--green)", current: "var(--accent)", warn: "var(--red)", pending: "var(--border)" };
  const couleurTxt = { done: "var(--green)", current: "var(--accent)", warn: "var(--red)", pending: "var(--muted)" };
  for (const k in ids) {
    const el = document.getElementById(ids[k]);
    if (!el) continue;
    const st = states[k] || "pending";
    el.style.opacity = st === "pending" ? "0.45" : "1";
    el.style.borderColor = couleur[st];
    el.style.color = couleurTxt[st];
  }
}

function majCapture(cap) {
  const bloc = document.getElementById("fwCaptureBloc");
  if (bloc) bloc.style.display = cap ? "" : "none";
  if (!cap) return;

  const btn = document.getElementById("fwCaptureBtn");
  const progress = document.getElementById("fwCaptureProgress");
  const etape = document.getElementById("fwCaptureEtape");
  const titre = document.getElementById("fwCaptureTitre");
  const removeBtn = document.getElementById("fwRemoveCaptureBtn");

  const total = cap.phase_total || 5;
  const phase = cap.phase || 0;

  if (btn) btn.disabled = !!cap.actif;
  if (progress) progress.style.display = cap.actif ? "" : "none";
  if (etape) etape.textContent = cap.etape || "…";
  if (titre) titre.textContent = phase
    ? t("ui.param.fw.progress.titre", { phase: phase, total: total }) + (cap.phase_titre || "") : "";
  _fwCaptureStepbar(phase, total);
  if (removeBtn) removeBtn.style.display = cap.bouton_secours ? "" : "none";

  // Bouton « Annuler la démarche » : actif tout du long de la capture. Après
  // le clic on garde son libellé « annulation… » jusqu'à la fin du thread
  // (cap.actif repasse à false) — l'arrêt propre peut retirer USBPcap (~20 s).
  const annBtn = document.getElementById("fwCaptureAnnulerBtn");
  if (annBtn && !_fwAnnulDemande) {
    annBtn.disabled = !cap.actif;
    annBtn.textContent = t("ui.param.fw.progress.annuler_demarche");
  }

  // Transition actif → terminé : afficher le résultat UNE fois (pas à
  // chaque poll, sinon le message clignote / se réinitialise sans arrêt).
  if (_fwCaptureActifPrec && !cap.actif) {
    if (cap.ok === true) {
      // cap.etape porte déjà « Firmware récupéré ✓ — … o, empreinte
      // confirmée. Fichier : … » à ce stade — on le garde tel quel.
      const base = (cap.etape || t("firmware.msg.configure")) + (cap.note || "");
      _fwCaptureResultat(base, cap.note ? "warn" : "ok");
      // Aiguillage « où sera utilisé Wing Bridge ? » — il PRÉCÈDE l'invitation
      // « vérifie ta wing » (#fwCaptureSuite). Branche « ici » → ferme juste
      // l'aiguillage, le fil standard A→E prend le relais (fwAiguillage()) ;
      // branche « Mac » → exporter le .bin (fwAiguillageFini() révèle la suite).
      const aig = document.getElementById("fwCaptureAiguillage");
      if (aig) {
        aig.style.display = "";
        const mac = document.getElementById("fwAiguillageMac");
        if (mac) mac.style.display = "none";
      } else {
        // Repli : pas d'aiguillage dans le balisage → invitation directe.
        const suite = document.getElementById("fwCaptureSuite");
        if (suite) suite.style.display = "";
      }
    } else if (cap.annule) {
      // Annulation demandée par l'utilisateur : message NEUTRE, pas la
      // bannière rouge, et PAS d'aiguillage. Un résidu USBPcap est repris tel
      // quel (« warn » → le bouton de secours apparaît par ailleurs).
      _fwCaptureResultat(cap.raison || t("firmware.annulee"),
                         (cap.raison && cap.raison.indexOf("⚠️") >= 0) ? "warn" : "");
    } else if (cap.ok === false) {
      if (cap.besoin_redemarrage) {
        _fwCaptureResultat("🔁 " + (cap.raison || t("firmware.echec.besoin_redemarrage")), "warn");
      } else {
        _fwCaptureResultat("✗ " + (cap.raison || t("firmware.msg.echec_capture")), "err");
      }
    }
    _fwAnnulDemande = false;   // le thread est fini : on réarme le bouton
  }
  _fwCaptureActifPrec = !!cap.actif;
}

// Bouton « ⏹ Annuler la démarche » — dispo pendant toute la capture. Le serveur
// ne tue rien de force : il pose un drapeau, la boucle de capture s'arrête à la
// prochaine vérification et — si USBPcap est installé — le retire avant de
// rendre la main. On garde le bouton en « annulation… » jusqu'à ce que
// majCapture() voie cap.actif repasser à false.
async function fwCaptureAnnulerDemarche() {
  const btn = document.getElementById("fwCaptureAnnulerBtn");
  const msg = document.getElementById("fwCaptureAnnulerMsg");
  _fwAnnulDemande = true;
  if (btn) { btn.disabled = true; btn.textContent = t("ui.param.fw.annul_en_cours"); }
  if (msg) { msg.textContent = t("ui.param.fw.annul_arret"); msg.style.color = ""; }
  let r;
  try { r = await api("/api/firmware/capture/cancel", {}); }
  catch (e) {
    if (msg) { msg.textContent = t("ui.param.fw.annul_echec_requete"); msg.style.color = "var(--red)"; }
    return;
  }
  if (r && (r.ok || r.annulation)) {
    if (msg) msg.textContent = t("ui.param.fw.annul_demandee");
  } else {
    if (msg) { msg.textContent = "✗ " + ((r && r.raison) || "annulation impossible"); msg.style.color = "var(--red)"; }
  }
}

// ── Aiguillage de fin de wizard : « où utiliseras-tu Wing Bridge ? » ──────
// Affiché par majCapture() à la bascule succès (cap.ok===true), AVANT
// l'invitation « vérifie ta wing » (#fwCaptureSuite). Deux branches :
//   « ici » (ce PC Windows) → ferme juste l'aiguillage. Le fil standard A→E
//                             (#oscEtape / #pluginEtape, majParametresGma3())
//                             prend le relais tout seul au poll suivant —
//                             voir le 🐛 du 19/09/2026 au balisage
//                             (#fwCaptureAiguillage, wing_ui.html) : ça
//                             évite un second chemin d'installation dupliqué
//                             qui ne respectait pas l'attente de l'étape A.
//   « mac » (sur un Mac)    → exporter le .bin, l'installer depuis le Mac.
// Le choix « mac » traité, fwAiguillageFini() révèle #fwCaptureSuite.
function fwAiguillage(cible) {
  if (cible === "ici") {
    const aig = document.getElementById("fwCaptureAiguillage");
    if (aig) aig.style.display = "none";
    return;
  }
  const mac = document.getElementById("fwAiguillageMac");
  if (mac) mac.style.display = "";
}

// Choix « Mac » traité (export lancé, ou rien à faire ici) → passer à la suite.
function fwAiguillageFini() {
  const aig = document.getElementById("fwCaptureAiguillage");
  if (aig) aig.style.display = "none";
  const suite = document.getElementById("fwCaptureSuite");
  if (suite) suite.style.display = "";
}

// Sauter vers un onglet par son data-tab (invitation de fin de capture).
function allerOnglet(nom) {
  const b = document.querySelector('nav button[data-tab="' + nom + '"]');
  if (b) b.click();
}

// Motif « scrollIntoView + surlignage temporaire », partagé par TOUTES les
// fonctions de navigation-désignation du wizard (Firmware, Raccourcis,
// Configuration guidée…) — une seule version pour ne pas diverger (le projet
// s'est déjà fait avoir par deux copies du même geste qui dérivent).
// `delaiMs` : laisser le temps à l'onglet de devenir visible (changement de
// section) avant de mesurer sa position — sans lui, scrollIntoView() peut
// mesurer un élément encore display:none.
function _designer(el, delaiMs) {
  if (!el) return;
  const go = () => {
    el.scrollIntoView({behavior: "smooth", block: "center"});
    el.style.transition = "box-shadow .3s";
    el.style.boxShadow = "0 0 0 2px var(--accent)";
    setTimeout(() => { el.style.boxShadow = ""; }, 1600);
  };
  if (delaiMs) setTimeout(go, delaiMs); else go();
}

// Depuis le bandeau du Bridge : ouvrir Paramètres et pointer la carte firmware.
function allerConfigurerFirmware() {
  const b = document.querySelector('nav button[data-tab="parametres"]');
  if (b) b.click();
  _designer(document.getElementById("firmwareCard"));
}

// Étape D du wizard : bouton « ⌨ Envoyer les raccourcis vers MA3 », un
// SECOND vrai bouton d'envoi (retour auteur, 18/09/2026 : un lien de
// navigation vers le bouton de l'onglet Touches restait confus, redondant
// avec les boutons d'onglet de l'étape C). Mince emballage autour de
// shcutsEnvoyer() (ui/touches.js) — MÊME appel serveur, aucune logique
// dupliquée.
//
// 🐛 Vécu en test réel Windows (19/09/2026) : avant, cet appel se faisait
// SANS arguments — shcutsEnvoyer() écrivait alors dans #btnShcuts/#shcutsEtat
// (onglet Touches, en dur), invisibles depuis Paramètres. Le clic envoyait
// bien la commande à MA3, mais rien ne le disait à côté du bouton du
// wizard : « envoi… », succès, collision ou échec partaient tous dans un
// élément caché. shcutsEnvoyer()/shcutsRafraichir() sont désormais
// paramétrées (ui/touches.js) — on leur passe ICI les ids du wizard.
//
// 🐛 2e round (même jour) : un premier correctif protégeait #shcutsEtapeEtat
// du poll (400 ms) tant que #btnShcutsWizard restait `disabled` — mais CE
// wrapper le réactive juste après l'attente, donc la garde retombait
// AUSSITÔT et le poll suivant effaçait le message (« échec, aucun fichier… »
// vu puis disparu instantanément, constaté en test réel). `disabled` sert à
// bloquer le double-clic, pas à protéger le message : les deux ne doivent
// pas partager le même signal. `_shcutsWizardEnvoiJusqua` protège le message
// pendant une fenêtre fixe, indépendante de l'état du bouton — voir son
// usage dans majMiseEnRouteSuite() ci-dessous.
let _shcutsWizardEnvoiJusqua = 0;
async function shcutsEnvoyerWizard() {
  const btn = document.getElementById("btnShcutsWizard");
  if (btn) btn.disabled = true;
  // Couvre l'appel initial + les ~5 s d'attente de confirmation par la sonde
  // (shcutsEnvoyer(), ui/touches.js) avec une marge.
  _shcutsWizardEnvoiJusqua = Date.now() + 7000;
  await shcutsEnvoyer("btnShcutsWizard", "shcutsEtapeEtat");
  if (btn) btn.disabled = false;
}

// Bouton « ← Retour aux Paramètres » de la carte Raccourcis (onglet Touches) :
// utile depuis la configuration guidée (étape 1/3, qui atterrit ici via
// assistantDemarrer()) — sans lui, aucun chemin de retour (signalé par
// l'auteur, 18/09/2026). Cible #fwCaptureSuite (le conteneur), PAS
// #etapeDRaccourcis : depuis que C/D/E sont des étapes SÉPARÉES (18/09/2026),
// D peut très bien être déjà masquée (passée) au moment du retour — désigner
// un élément display:none ne ferait rien.
function retourParametresRaccourcis() {
  const b = document.querySelector('nav button[data-tab="parametres"]');
  if (b) b.click();
  _designer(document.getElementById("fwCaptureSuite"));
}

// ── Configuration guidée (Étape C du wizard) ──────────────────────────────
// Décision auteur (18/09/2026) : plutôt qu'une popup qui DUPLIQUERAIT la
// grille de faders et les groupes d'encodeurs (deux formulaires pour la même
// donnée = risque de divergence — le projet s'est déjà fait avoir), une
// bannière flottante guide l'utilisateur À TRAVERS les VRAIS onglets. Zéro
// copie : Touches réutilise tel quel l'assistant existant (assistantDemarrer,
// plus haut dans ce fichier — annonce une touche, tu appuies dessus) ; Faders
// et Encodeurs n'ont pas d'assistant pas-à-pas, donc la bannière se contente
// de désigner la VRAIE grille / les VRAIS groupes et de laisser l'utilisateur
// éditer sur place.
let _guideEtat = 0;   // 0 = inactive, 1/2/3 = étape en cours

const _GUIDE_ETAPES = [null,
  { tab: "touches",   titre: "ui.param.guide.etape1.titre", txt: "ui.param.guide.etape1.txt",
    bouton: "ui.param.guide.etape1.bouton" },
  { tab: "faders",    titre: "ui.param.guide.etape2.titre", txt: "ui.param.guide.etape2.txt",
    bouton: "ui.param.guide.etape2.bouton" },
  { tab: "encodeurs", titre: "ui.param.guide.etape3.titre", txt: "ui.param.guide.etape3.txt",
    bouton: "ui.param.guide.etape3.bouton" },
];

function configGuideeDemarrer() {
  _guideEtat = 1;
  _guideAfficherEtape();
}

function _guideAfficherEtape() {
  const conf = _GUIDE_ETAPES[_guideEtat];
  if (!conf) { configGuideeTerminer(); return; }
  const b = document.querySelector('nav button[data-tab="' + conf.tab + '"]');
  if (b) b.click();
  const banniere = document.getElementById("guideBanniere");
  if (banniere) banniere.style.display = "";
  const titreEl = document.getElementById("guideBanniereTitre");
  if (titreEl) titreEl.textContent = t(conf.titre);
  const txtEl = document.getElementById("guideBanniereTxt");
  if (txtEl) txtEl.textContent = t(conf.txt);
  const boutonEl = document.getElementById("guideBanniereSuivant");
  if (boutonEl) { boutonEl.textContent = t(conf.bouton); boutonEl.disabled = false; }

  // Désigner la zone à personnaliser dans le vrai onglet — délai pour laisser
  // le changement d'onglet se rendre avant de mesurer sa position.
  let cible = null;
  if (_guideEtat === 1) cible = document.getElementById("btnAssistant");
  else if (_guideEtat === 2) cible = document.getElementById("faderGrid");
  else if (_guideEtat === 3) {
    // Les 4 PREMIERS groupes seulement (clic simple, roues 1-4) : les 4
    // suivants (double-clic, groupes 5-8) sont un second jeu avancé, pas la
    // première configuration.
    cible = document.querySelector("#encGroups .encgroup") || document.getElementById("encGroups");
  }
  _designer(cible, 150);
}

// Bouton « Suivant » de la bannière. Étape 1 (Touches) → 2 (Faders) : envoie
// d'abord les raccourcis vers MA3 (shcutsEnvoyer(), ui/touches.js) — c'est la
// fin naturelle de la personnalisation des touches (demande auteur : « à la
// fin envoyer vers MA3 »). N'envoie PAS à l'aveugle aux étapes 2→3 et 3→fin :
// rien à envoyer côté faders/encodeurs, ils s'appliquent déjà au onchange.
// 🔁 Envoyait les raccourcis ICI (fin de l'étape Touches) — RETIRÉ (18/09/2026,
// retour auteur) : « ça a encore sauté jusqu'à E quand je fais la
// programmation de l'étape C ». Cause : si OSC + plugin actif étaient déjà
// bons, envoyer les raccourcis dès la fin de la configuration guidée rendait
// D immédiatement « déjà faite » — elle ne s'affichait jamais, avec elle le
// rappel ShCuts. L'envoi reste désormais UNIQUEMENT dans l'étape D
// (#btnShcutsWizard) : c'est la seule façon de garantir que D est
// réellement vue avant que E ne devienne possible.
function configGuideeSuivant() {
  _guideEtat++;
  _guideAfficherEtape();
}

function configGuideeQuitter() {
  _guideEtat = 0;
  const banniere = document.getElementById("guideBanniere");
  if (banniere) banniere.style.display = "none";
}

// Fin des 3 étapes : referme la bannière et reprend le fil normal du wizard.
// Marque aussi l'étape C comme passée (etapeCSuivante() plus haut) : être
// allé au bout de la configuration guidée EST la vérification de la wing que
// C demande — sans ce drapeau, revenir sur Paramètres réafficherait C après
// l'avoir déjà faite via la bannière.
function configGuideeTerminer() {
  configGuideeQuitter();
  etapeCSuivante();
  retourParametresRaccourcis();
}

// Étape E du wizard : bouton « 💾 Sauvegarder la configuration », juste avant
// « Démarrer le bridge » (demande auteur, 18/09/2026) — mince emballage
// autour de saveActiveProfile() (ui/profils.js, MÊME code que le bouton
// « 💾 Enregistrer » de l'en-tête, aucune logique dupliquée), avec un retour
// affiché sur place plutôt que de faire remonter l'utilisateur voir le point
// « modifié » de l'en-tête.
async function sauvegarderConfigWizard() {
  const msg = document.getElementById("sauvegardeWizardMsg");
  if (msg) { msg.textContent = t("ui.param.guide.sauvegarde_en_cours"); msg.style.color = ""; }
  try {
    await saveActiveProfile();
  } catch (e) {
    if (msg) { msg.textContent = t("ui.param.echec_requete"); msg.style.color = "var(--red)"; }
    return;
  }
  if (msg) { msg.textContent = t("ui.param.guide.sauvegarde_ok"); msg.style.color = "var(--green)"; }
}

// Étape E du wizard : bouton « ▶ Démarrer le bridge ». Décision assumée
// (session du 18/09/2026) : contrairement à l'ancien comportement (juste
// rediriger vers l'onglet Bridge, laisser l'utilisateur cliquer lui-même),
// ce bouton démarre RÉELLEMENT le bridge — le même geste que #bridgeBtn
// (toggleBridge(), ui/bridge.js) — puis bascule sur l'onglet Bridge, puis
// referme les <details> « pourquoi » du wizard (elles ne portent pas d'id,
// donc pas de mémorisation localStorage — sans ce nettoyage explicite, elles
// resteraient dépliées en mémoire DOM jusqu'au prochain rechargement complet).
// Ne toggle PAS à l'aveugle : si le bridge tournait déjà, on ne veut pas
// l'arrêter par erreur.
async function allerDemarrerBridge() {
  if (currentMode !== "bridge") await toggleBridge();
  const b = document.querySelector('nav button[data-tab="bridge"]');
  if (b) b.click();
  document.querySelectorAll(
    "#oscEtape details.help, #pluginEtape details.help, #fwCaptureSuite details.help"
  ).forEach(d => { d.open = false; });
}

// ── Étape assistant : OSC est-il VRAIMENT activé dans grandMA3 ? ──────────
// installer_plugin() (wing_ma3.py) accepte ma3_reachable() in ("ok","muet") —
// donc tente l'import même si MA3 n'écoute pas — mais un import qui n'arrive
// jamais ne peut pas faire avancer la sonde : sans OSC actif, l'installation
// échoue TOUJOURS au bout de ~1,4 s avec « sonde muette ». L'étape OSC doit
// donc précéder l'étape plugin dans le parcours (vérifié en réel avec
// l'auteur — voir docs/GRANDMA3_SYNC.md).
//
// Trois issues, jamais une hypothèse déguisée en fait :
//   true  → la sonde tourne ET confirme une ligne OSCData sur le port
//           attendu avec Receive ET Receive Command = Yes (osc_config_ma3(),
//           /api/status → osc.ma3 : PREUVE, ça tourne DANS MA3).
//   false → la sonde tourne mais ne voit RIEN de tel : OSC mal réglé.
//   null  → la sonde n'est pas encore active (poule-et-œuf : elle vient de
//           l'étape suivante) — on ne sait pas, on ne prétend pas savoir.
function _oscConfigOk(ma3) {
  if (!ma3 || !ma3.actif) return null;
  if (!ma3.entree) return false;
  return (ma3.configs || []).some(c =>
    Number(c.port) === Number(ma3.port_attendu) && c.recoit && c.rec_cmd);
}

// Repli honnête tant que la sonde n'est pas active : ma3_reachable() dit déjà
// si MA3 écoute sur le port OSC attendu (osc.reachable === "ok"), ce qui est
// un signe fort (mais PARTIEL : ça ne prouve pas Receive Command) que l'OSC
// est bien configuré. On le dit comme tel, jamais comme une preuve complète.
function majOscEtape(s, montrer) {
  const bloc = document.getElementById("oscEtape");
  if (!bloc) return;
  bloc.style.display = montrer ? "" : "none";
  if (!montrer) return;
  const etat = document.getElementById("oscEtapeEtat");
  if (!etat) return;
  const ok = _oscConfigOk(s.osc && s.osc.ma3);
  if (ok === true) {
    etat.textContent = t("ui.param.fw.osc_etape_ok");
    etat.style.color = "var(--green)";
  } else if (ok === false) {
    etat.textContent = t("ui.param.fw.osc_etape_ko");
    etat.style.color = "var(--red)";
  } else {
    const r = s.osc ? s.osc.reachable : null;
    if (r === "ok") {
      etat.textContent = t("ui.param.fw.osc_etape_partiel_ok");
      etat.style.color = "var(--accent)";
    } else if (r === "muet") {
      // Texte retiré (retour auteur, 18/09/2026) : redondant avec le
      // diagnostic déjà visible ailleurs, et source de confusion pendant les
      // tests. Rien à afficher tant qu'on n'a que ce signal partiel.
      etat.textContent = "";
    } else {
      etat.textContent = t("ui.param.fw.osc_etape_lance_ma3");
      etat.style.color = "";
    }
  }
}

// ── Suite de la mise en route : #fwCaptureSuite (vérifie ta wing → envoie
// les raccourcis → démarre le bridge). Poll-driven comme le reste de cette
// carte : revenir sur l'assistant après avoir déjà tout fait doit montrer
// directement les bonnes coches, jamais repartir de zéro. ──────────────────
// Étape C : rien ne permet de DÉTECTER que l'utilisateur a vérifié sa wing
// (contrairement à A→B, gaté sur oscReady/oscOkFull) — bouton manuel, posé
// une fois pour la session (retour auteur, 18/09/2026 : « C/D/E séparées,
// comme A et B, avec un bouton passer à l'étape suivante si besoin »).
let _etapeCPasseeManuel = false;
function etapeCSuivante() { _etapeCPasseeManuel = true; }

// 🔁 Un bouton « ✅ ShCuts activé dans MA3 » a existé ici brièvement (même
// session, 18/09/2026) pour gater le passage D→E — RETIRÉ aussitôt, retour
// auteur : « ça n'a aucun sens, ça n'active pas le bouton dans MA3, et ça
// laisse croire que c'est fait alors que non ». Un bouton qui affirme sans
// vérifier est pire qu'une absence de bouton (GUIDE_PROJET.md). ShCuts reste donc
// une information affichée dans D (jamais prétendue confirmée) — voir le
// commentaire du balisage, #etapeDRaccourcis.
//
// 🐛 D→E est ensuite RESTÉ gaté sur shcuts_horodate (+ oscOk/active/Accessibilité)
// — signal réel, mais PERSISTÉ SUR DISQUE (wing_reglages.py charge
// SETTINGS["shcuts_horodate"] depuis le fichier de config) : une fois envoyé
// UNE fois, il reste vrai pour toujours, même après relancer l'app ou
// reprendre C depuis zéro. Conséquence vécue 3 fois de suite (18/09/2026,
// avec l'auteur) : dès que C (re)passait vrai — via la configuration guidée
// ou le bouton manuel — D se retrouvait déjà « remplie » par un envoi d'un
// test précédent et sautait direct à E, sans jamais être vue. Même les 4
// conditions réelles réunies ne prouvent pas que CETTE traversée du wizard a
// vu D. Repli sur le MÊME motif que C : un bouton manuel, neutre, qui ne
// prétend rien vérifier (juste « je passe à la suite »).
let _etapeDPasseeManuel = false;
function etapeDSuivante() { _etapeDPasseeManuel = true; }

// « ← Étape précédente » (D revient à C, E revient à D).
function etapePrecedente(vers) {
  if (vers === "C") _etapeCPasseeManuel = false;
  else if (vers === "D") _etapeDPasseeManuel = false;
}

function majMiseEnRouteSuite(s, present, active, bridgeActif) {
  const suite = document.getElementById("fwCaptureSuite");
  if (!suite) return;
  // Pas pendant une capture Windows en cours (repartir propre) : voir
  // fwCaptureContinuer(), qui masque cet encart au lancement d'une nouvelle
  // tentative — sans cette garde, ce calcul le referait apparaître au poll
  // suivant (400 ms) si un plugin d'une INSTALLATION PRÉCÉDENTE est déjà là.
  // Pas non plus une fois le bridge RÉELLEMENT démarré : #miseEnRouteTerminee
  // (majParametresGma3) prend le relais avec un résumé — retour auteur
  // (18/09/2026) : cliquer « Démarrer le bridge » laissait tout le fil C/D/E
  // affiché à l'identique au lieu de disparaître.
  const capActive = !!(s.capture && s.capture.actif);
  const montrer = present && !capActive && !bridgeActif;
  suite.style.display = montrer ? "" : "none";
  if (!montrer) return;

  // 🐛 Vécu en test réel (18/09/2026, avec l'auteur) : « j'ai cliqué sur
  // relancer le plugin, ça m'a encore renvoyé en E ». La sonde tombée puis
  // relancée avec succès reconstituait TOUTES les conditions réelles
  // (present, active, oscOk, shcuts_horodate déjà envoyés plus tôt) — donc E
  // redevenait légitimement prête, mais _etapeCPasseeManuel restait posé
  // depuis un passage antérieur de C, sans que l'auteur ait rien revérifié
  // cette fois. Une sonde tombée = quelque chose s'est cassé = redemander la
  // vérification depuis C plutôt que de sauter dessus en silence. Même
  // principe pour D : une sonde retombée corrèle souvent avec un
  // redémarrage de MA3 (qui remet ShCuts à son état par défaut).
  if (!active) { _etapeCPasseeManuel = false; _etapeDPasseeManuel = false; }

  // Ligne d'état du plugin (sonde), à l'étape C SEULEMENT — voir
  // _pluginStatutLigne() plus bas. La sonde qui tombe se dit en silence (MA3
  // ne le signale nulle part) : le wizard recule à C (ligne ci-dessus), et
  // c'est là que l'avertissement + « Relancer » s'affichent. Pas à D ni E :
  // ils y seraient inatteignables (le recul les masque avant tout affichage).
  _pluginStatutLigne("pluginStatutTxtC", "wizRelancerBtn", s, active);

  // Pas pendant (ni juste après) un envoi : shcutsEnvoyer() écrit ICI MÊME du
  // texte vivant (« envoi… », collision, ⛔ non appliqué, échec…) — un poll
  // (400 ms) qui écraserait ça par le seul horodate reviendrait au bug du
  // 19/09/2026 (feedback invisible), sous une autre forme. Fenêtre fixe
  // (_shcutsWizardEnvoiJusqua, posée par shcutsEnvoyerWizard() ci-dessus),
  // PAS l'état `disabled` du bouton : ce dernier est réactivé dès la fin de
  // l'envoi, avant même que ce poll-ci ne repasse — s'y fier effaçait le
  // message aussitôt affiché (constaté en test réel).
  const etapeEtat = document.getElementById("shcutsEtapeEtat");
  if (etapeEtat && Date.now() >= _shcutsWizardEnvoiJusqua) {
    const h = s.shcuts_horodate;
    etapeEtat.textContent = formatHorodateRelatif(h);
    etapeEtat.style.color = h ? "" : "var(--accent)";
  }

  // Sous-étape D : Accessibilité macOS pour Wing Keyboard — voir le
  // commentaire du balisage (#accessEtapeMac). ABSENTE sous Windows
  // (console.windows), pas juste verte : rien à vérifier ni à faire là-bas.
  const cons = s.console || {};
  // 🐛 Vécu en test réel (18/09/2026) : « ça passe à l'étape E, sauf que ça
  // ignore que l'accessibilité n'est pas autorisée pour le clavier ». Sans
  // Accessibilité accordée, macOS refuse en silence l'injection des frappes
  // (CGEvent) — les raccourcis envoyés n'ont AUCUNE chance d'arriver à MA3,
  // même une fois « prêt » par ailleurs. Sur Windows, `cons.windows` rend
  // `cons.trusted` toujours vrai (SendInput ne demande aucune permission,
  // voir #accessEtapeMac) : cette condition ne bloque donc jamais là-bas.
  const accessOk = !!(cons.windows || cons.trusted);
  const accessBloc = document.getElementById("accessEtapeMac");
  if (accessBloc) {
    accessBloc.style.display = cons.windows ? "none" : "";
    if (!cons.windows) {
      const accessEtat = document.getElementById("accessEtapeEtat");
      if (accessEtat) {
        if (!cons.enabled) {
          accessEtat.textContent = t("ui.param.fw.access_etape_absent");
          accessEtat.style.color = "";
        } else if (cons.trusted) {
          accessEtat.textContent = t("ui.param.fw.access_etape_ok");
          accessEtat.style.color = "var(--green)";
        } else {
          accessEtat.textContent = t("ui.param.fw.access_etape_ko");
          accessEtat.style.color = "var(--red)";
        }
      }
    }
  }

  // oscOk/active/shcuts_horodate/accessOk restent un diagnostic AFFICHÉ
  // (#finalBloqueOsc) tant que D est visible — ils NE GATENT PLUS D→E depuis
  // le 🐛 au-dessus de _etapeDPasseeManuel : shcuts_horodate survit à un
  // rechargement complet de l'app, donc « prêt » ne veut pas dire « vu à
  // CETTE traversée du wizard ».
  const oscOk = _oscConfigOk(s.osc && s.osc.ma3) === true;

  // C passée : UNIQUEMENT le bouton manuel (etapeCSuivante() ci-dessus, ou
  // configGuideeTerminer() plus bas, qui le pose aussi à la fin de la
  // configuration guidée). 🐛 Vécu en test réel (18/09/2026, avec l'auteur) :
  // `!!s.shcuts_horodate` servait AUSSI de bascule implicite pour gérer le
  // retour sur une config déjà faite — mais shcuts_horodate est un
  // horodatage qui survit à une RÉINSTALLATION du plugin (B relancé pendant
  // un test), donc ça sautait direct à E dès que B repassait actif, sans
  // jamais laisser voir C ni D. `_etapeCPasseeManuel` seul se réinitialise à
  // chaque rechargement de page — page acceptable : le résumé
  // #miseEnRouteTerminee prend de toute façon le relais dès que le bridge
  // est réellement démarré (voir majParametresGma3()).
  const cPassee = _etapeCPasseeManuel;
  // D passée : UNIQUEMENT le bouton manuel (etapeDSuivante(), voir le 🐛
  // au-dessus de sa déclaration) — jamais déduit de pretReel.
  const dPassee = _etapeDPasseeManuel;

  const blocC = document.getElementById("etapeCBloc");
  if (blocC) blocC.style.display = cPassee ? "none" : "";

  const blocD = document.getElementById("etapeDRaccourcis");
  if (blocD) blocD.style.display = (cPassee && !dPassee) ? "" : "none";

  // Diagnostic honnête, purement informatif tant que D est affichée : tout
  // est fait (plugin actif, raccourcis envoyés) SAUF la confirmation OSC
  // complète — sans ce message, rien ne dit pourquoi (voir le commentaire du
  // balisage, #finalBloqueOsc). Ne bloque plus le passage (D→E est manuel
  // désormais) : c'est un avertissement, pas un verrou.
  const bloque = document.getElementById("finalBloqueOsc");
  if (bloque) bloque.style.display = (cPassee && !dPassee && !oscOk && active && !!s.shcuts_horodate) ? "" : "none";

  const finale = document.getElementById("miseEnRouteFinale");
  if (finale) finale.style.display = (cPassee && dPassee) ? "" : "none";
}

// ── grandMA3 : cible OSC + plugin (sonde Lua) ─────────────────────────
// Appelée par poll() (bridge.js) à chaque tick, isolée dans son try — même
// principe que majFirmware / majEncMa3 : une info secondaire ne doit jamais
// emporter le header.
//
// CINQ situations — MA3 joignable ? s.sonde.present (fichiers .lua dans le pool
// MA3, lisible même MA3 éteint) ? sonde qui tourne ?
//   sonde active                           → ● plugin actif — N executors · Page X
//   MA3 joignable + fichiers là + inactive → ⚠️ plugin inactif — relance-le (sans
//                                            citer de numéro de slot : il varie)
//   MA3 joignable + fichiers absents       → ⚠️ plugin non installé (le <details>
//                                            s'ouvre tout seul, procédure)
//   MA3 éteint + fichiers là               → ○ plugin installé — grandMA3 éteint
//   MA3 éteint + fichiers absents          → ○ plugin non installé — grandMA3 éteint
// L'alerte défilante visible est dans la barre d'activité (bridge.js), pas ici.
let _sondeVuePrec = null;

// ── Emplacement (slot) du plugin — SETTINGS["plugin_slot"] ───────────────
let _pluginSlotAffiche = null;   // dernière valeur rendue dans la procédure manuelle

// Ne pas écraser une saisie en cours (même principe que oscFieldsBusy, voir ui/core.js).
function _pluginSlotFieldsBusy() {
  const a = document.activeElement;
  return a && a.id === "pluginSlotInput";
}

// Rend la procédure manuelle (<details> de la carte grandMA3) avec le slot
// RÉEL. Pas de data-i18n-html sur cet élément : voir le commentaire dans
// wing_ui.html (le passage générique d'appliquerLangue() n'interpole pas).
function majPluginProcedureManuelle(slot) {
  const body = document.getElementById("gma3PluginBody");
  if (!body) return;
  body.innerHTML = tHtml("ui.param.gma3.hplugin.body", { slot: slot });
  _pluginSlotAffiche = slot;
}

// Appelée par savePluginSlot() ET par majParametresGma3() (poll) : pose la
// valeur dans le champ (sauf s'il est en cours d'édition) et ne re-rend la
// procédure manuelle que si le slot a changé — coûteux à refaire à chaque tick.
function _majPluginSlotUI(slot) {
  const a = document.getElementById("pluginSlotInput");
  if (a && document.activeElement !== a) a.value = slot;
  if (slot !== _pluginSlotAffiche) majPluginProcedureManuelle(slot);
}

// Enregistre le réglage — appelée par le bouton « Appliquer » (carte grandMA3).
async function savePluginSlot(valeur, msgElId) {
  const msg = msgElId ? document.getElementById(msgElId) : null;
  let r;
  try { r = await api("/api/plugin_slot", { slot: valeur }); }
  catch (e) {
    if (msg) { msg.textContent = t("ui.param.echec_requete"); msg.style.color = "var(--red)"; }
    return;
  }
  if (r && r.ok) {
    _majPluginSlotUI(r.slot);
    if (msg) {
      msg.textContent = r.avertissement ? "⚠️ " + r.avertissement : "";
      msg.style.color = r.avertissement ? "var(--accent)" : "";
    }
  } else if (msg) {
    msg.textContent = "✗ " + ((r && r.raison) || t("firmware.msg.echec"));
    msg.style.color = "var(--red)";
  }
}

function majParametresGma3(s) {
  if (!s) return;
  if (!_pluginSlotFieldsBusy()) _majPluginSlotUI(s.plugin_slot);
  // Bridge RÉELLEMENT démarré (pas juste « l'utilisateur a cliqué une fois ») :
  // remplace tout le fil post-firmware par un résumé (voir #miseEnRouteTerminee
  // et majMiseEnRouteSuite ci-dessous). Dérivé de l'état serveur, pas d'un
  // indicateur côté client — redevient vrai tout seul si le bridge s'arrête,
  // et reste vrai après un relancement de l'app si le bridge repart seul
  // (want_connected), sans qu'on ait besoin de mémoriser « configuration
  // faite une fois » séparément.
  const bridgeActif = s.mode === "bridge";
  const r = s.osc ? s.osc.reachable : null;

  // Cible OSC : pastille ● connecté / ○ absent
  const oscDot = document.getElementById("gma3OscDot");
  const oscTxt = document.getElementById("gma3OscTxt");
  if (oscDot && oscTxt && s.osc) {
    if (r === "ok")        { oscDot.className = "dot on";   oscTxt.textContent = t("ui.param.gma3.osc_ok"); }
    else if (r === "muet") { oscDot.className = "dot warn"; oscTxt.textContent = t("ui.sante.osc.muet", { port: s.osc.port }); }
    else if (r === "off")  { oscDot.className = "dot";      oscTxt.textContent = t("ui.sante.osc.absent"); }
    else                   { oscDot.className = "dot";      oscTxt.textContent = t("ui.param.gma3.osc_distant", { cible: s.osc.target }); }
  }

  // Sonde Lua : les 5 situations
  const active = !!(s.sonde && s.sonde.actif);
  const present = !!(s.sonde && s.sonde.present);
  const ma3La = (r === "ok" || r === "muet");
  const sDot = document.getElementById("gma3SondeDot");
  const sTxt = document.getElementById("gma3SondeTxt");
  if (sDot && sTxt) {
    if (active) {
      sDot.className = "dot on";
      sTxt.textContent = plural("ui.sante.sonde.actif", s.sonde.executors || 0)
        + (s.sonde.page ? t("ui.sante.sonde.page", { page: s.sonde.page }) : "");
    } else if (ma3La && present) {
      sDot.className = "dot warn";
      sTxt.textContent = t("ui.param.gma3.sonde_inactif");
    } else if (ma3La) {
      sDot.className = "dot warn";
      sTxt.textContent = t("ui.param.gma3.sonde_non_installe");
    } else if (present) {
      sDot.className = "dot";
      sTxt.textContent = t("ui.sante.sonde.installe_eteint");
    } else {
      sDot.className = "dot";
      sTxt.textContent = t("ui.sante.sonde.non_installe_eteint");
    }
  }

  // Le <details> de la procédure : déplié tout seul UNIQUEMENT quand les
  // fichiers sont absents (vraie install à faire). « Inactif » ne le déplie
  // pas — une relance suffit, la pastille le dit déjà. Jamais forcé à chaque
  // tick : l'utilisateur peut ouvrir/fermer à sa guise.
  const aInstaller = !active && ma3La && !present;
  const det = document.getElementById("gma3PluginDetails");
  const sum = document.getElementById("gma3PluginSummary");
  if (det && aInstaller !== _sondeVuePrec) det.open = aInstaller;
  if (det) det.className = aInstaller ? "help warn" : "help";
  if (sum) sum.textContent = (active || present)
    ? t("ui.param.gma3.hplugin.summary_maj")
    : t("ui.param.gma3.hplugin.summary");
  _sondeVuePrec = aInstaller;

  // Bouton « Relancer le plugin » de la carte grandMA3, juste sous la pastille :
  // visible SEULEMENT quand les fichiers sont posés, la sonde inactive et
  // grandMA3 joignable — c'est le seul cas où « relancer » a du sens.
  const relZone = document.getElementById("gma3RelancerZone");
  if (relZone) relZone.style.display = (!active && present && ma3La) ? "" : "none";

  // Encart « installer le plugin » de la carte Firmware : mise en route —
  // firmware configuré ET fichiers PAS encore posés sur le disque MA3.
  //
  // 🐛 Avant, la condition portait aussi `!active` : elle échouait dès qu'une
  // sonde tournait ENCORE dans la mémoire de grandMA3 (sa boucle Lua + `_G`
  // survivent à la suppression des .lua/.xml — `present` passe à false, mais
  // `actif` reste true tant que MA3 réécrit wingbridge_state.json ; idem
  // pendant les ~5 s de grâce `_MA3_ALIVE_DEPUIS` après un (re)démarrage de
  // MA3). L'encart d'installation restait alors masqué alors que le plugin
  // n'est PAS installé sur le disque. On ne teste donc plus que `!present` :
  // dès que les fichiers sont là, c'est le bouton « Relancer » de la carte
  // grandMA3 qui distingue « tourne » de « arrêté ».
  //
  // Masqué aussi tant que l'aiguillage de fin de wizard est à l'écran : il
  // propose déjà l'installation, inutile de doubler.
  const aig = document.getElementById("fwCaptureAiguillage");
  const aigVisible = !!(aig && aig.style.display !== "none");

  // Étape A (OSC) → étape B (plugin) : désormais SÉQUENTIELLES, pas montrées
  // ensemble. Deux signaux, on prend le meilleur des deux :
  //   oscReady    (osc.reachable === "ok") : le seul dispo AVANT que le
  //               plugin tourne (poule-et-œuf, voir _oscConfigOk ci-dessus).
  //   oscOkFull   (_oscConfigOk === true) : la PREUVE complète, dispo dès que
  //               la sonde est active — y compris une sonde ORPHELINE
  //               (actif=true, present=false : le script Lua tourne encore
  //               en mémoire dans MA3 alors que ses fichiers ont disparu du
  //               disque, cf. le commentaire plus bas sur `present`).
  // 🐛 Vécu en test réel (18/09/2026, avec l'auteur) : reachable coincé sur
  // "muet" (heuristique socket, lsof) alors que la sonde — orpheline — avait
  // DÉJÀ confirmé la config OSC correcte (oscOkFull true). Ne gater que sur
  // oscReady bloquait A→B indéfiniment malgré une preuve plus forte
  // disponible. D'où le OU : dès que l'UN des deux signaux est bon, B prend
  // le relais — jamais A et B en même temps.
  const oscReady = r === "ok";
  const oscOkFull = _oscConfigOk(s.osc && s.osc.ma3) === true;
  const oscPret = oscReady || oscOkFull;
  // 🐛 Vécu en test réel Windows (19/09/2026) : l'étape A apparaissait DÈS
  // que le firmware était sauvegardé sur disque (wing_init.enregistrer_firmware,
  // capturer_firmware() l'appelle en tout début de ses phases 5-7 : fermer
  // grandMA2 onPC, débrancher/rebrancher la wing, retirer USBPcap — s.firmware.
  // configure passe donc à true LONGTEMPS avant que capture.actif ne retombe
  // et que l'aiguillage ne s'affiche), pendant que la barre de progression de
  // capture était ENCORE à l'écran (phase 5/7, 6/7…) : les deux se chevauchaient.
  // `!capActive` referme ce trou, même motif que majMiseEnRouteSuite() plus haut.
  const capActive = !!(s.capture && s.capture.actif);
  const enPhaseMiseEnRoute = !!(s.firmware && s.firmware.configure) && !present && !capActive && !aigVisible;
  majOscEtape(s, enPhaseMiseEnRoute && !oscPret);

  const etape = document.getElementById("pluginEtape");
  if (etape) {
    const montrer = enPhaseMiseEnRoute && oscPret;
    etape.style.display = montrer ? "" : "none";
    if (montrer) {
      const bInstall = document.getElementById("pluginInstallBtn");
      const manuel = document.getElementById("pluginEtapeManuel");
      if (bInstall) bInstall.style.display = ma3La ? "" : "none";
      if (manuel) manuel.textContent = ma3La
        ? t("ui.param.plugin.manuel_ma3")
        : t("ui.param.plugin.manuel_no_ma3");
    }
  }

  // Suite (vérifie ta wing → envoie les raccourcis → démarre le bridge) :
  // dès que le plugin est POSÉ, quelle que soit la plateforme ou le chemin
  // d'installation emprunté (aiguillage Windows ou #pluginEtape général).
  majMiseEnRouteSuite(s, present, active, bridgeActif);

  // Résumé « configuration terminée » (#miseEnRouteTerminee) : seulement une
  // fois le plugin déjà posé UNE fois (`present`) ET le bridge réellement
  // actif — pas avant, sinon un bridge démarré par ailleurs sans être passé
  // par ce wizard afficherait un résumé qui n'a rien résumé.
  const termine = document.getElementById("miseEnRouteTerminee");
  if (termine) termine.style.display = (present && bridgeActif) ? "" : "none";

  // Repère de progression A → E (voir le commentaire du balisage,
  // #mercWizStepbar) : masqué hors de cette phase (firmware pas encore
  // configuré, aiguillage de fin de capture Windows à l'écran, OU bridge déjà
  // démarré — voir #miseEnRouteTerminee juste au-dessus, qui prend le relais).
  const wizBar = document.getElementById("mercWizStepbar");
  if (wizBar) {
    // Même garde-fou que ci-dessus (capActive) : la barre de progression A-E
    // ne doit pas apparaître pendant qu'une capture de firmware est encore en
    // cours (phases 5-7, firmware déjà configuré mais capture pas terminée).
    const dansLaPhase = !!(s.firmware && s.firmware.configure) && !capActive && !aigVisible && !bridgeActif;
    wizBar.style.display = dansLaPhase ? "" : "none";
    if (dansLaPhase) {
      const stepCDVisible = present && !capActive;
      // Même calcul que dans majMiseEnRouteSuite() (voir son commentaire sur
      // le 🐛 du 18/09/2026) — UNIQUEMENT les boutons manuels, jamais déduit
      // de shcuts_horodate (persisté sur disque, donc pas fiable pour savoir
      // si CETTE traversée du wizard a vu C et D). _etapeCPasseeManuel et
      // _etapeDPasseeManuel sont déclarées juste au-dessus de
      // majMiseEnRouteSuite() dans ce fichier (portée globale).
      const cPassee = _etapeCPasseeManuel;
      const stepEVisible = stepCDVisible && cPassee && _etapeDPasseeManuel;
      // Étape A rétroactivement fausse : marquée « done » sur la foi du seul
      // oscReady (partiel), mais une fois la sonde active la preuve complète
      // (_oscConfigOk) dit non — voir #finalBloqueOsc.
      const oscBloque = present && active && !oscOkFull;
      _mercWizStepbar({
        A: oscBloque ? "warn" : (!present && !oscPret ? "current" : "done"),
        B: !present && oscPret ? "current" : (present ? "done" : "pending"),
        C: !stepCDVisible ? "pending" : (cPassee ? "done" : "current"),
        D: !stepCDVisible ? "pending" : (stepEVisible ? "done" : (cPassee ? "current" : "pending")),
        E: stepEVisible ? "current" : (oscBloque ? "warn" : "pending"),
      });
    }
  }
}

// Relance l'amorce PAR SON NOM en OSC (`Plugin "WingLoader"` — pas de numéro
// de slot), ~2 s côté serveur. Factorisé pour avoir DEUX boutons (carte
// grandMA3, et l'étape C du wizard — voir _pluginStatutLigne() ci-dessous)
// qui appellent EXACTEMENT le même code : des copies auraient
// fini par diverger (déjà arrivé ailleurs dans ce projet — GUIDE_PROJET.md, boutons
// d'executor).
async function _relancerPlugin(msgElId, btnElId) {
  const btn = btnElId ? document.getElementById(btnElId) : null;
  const msg = msgElId ? document.getElementById(msgElId) : null;
  if (btn) btn.disabled = true;
  if (msg) { msg.textContent = t("ui.param.plugin.relance_en_cours"); msg.style.color = ""; }
  let r;
  try { r = await api("/api/plugin/relaunch", {}); }
  catch (e) {
    if (msg) { msg.textContent = t("ui.param.echec_requete"); msg.style.color = "var(--red)"; }
    if (btn) btn.disabled = false;
    return;
  }
  if (r && r.ok) {
    if (msg) { msg.textContent = "✓ " + (r.message || t("err.ma3.sonde_relancee")); msg.style.color = "var(--green)"; }
  } else {
    if (msg) { msg.textContent = "✗ " + ((r && r.raison) || t("firmware.msg.echec")); msg.style.color = "var(--red)"; }
    const det = document.getElementById("gma3PluginDetails");
    if (det) det.open = true;
  }
  if (btn) btn.disabled = false;
}
// Bouton « 🔁 Relancer le plugin dans grandMA3 » (carte grandMA3, sous la pastille).
function pluginRelancer() { return _relancerPlugin("gma3RelancerMsg", "gma3RelancerBtn"); }
// Même bouton, DEPUIS l'étape C du wizard (voir _pluginStatutLigne()
// ci-dessous), sans jamais dupliquer le CODE
// de relance. Feedback affiché sur place, pas besoin d'aller chercher la
// carte grandMA3 plus haut dans l'onglet.
function relancerPluginWizard() {
  return _relancerPlugin("wizRelancerMsg", "wizRelancerBtn");
}

// Ligne d'état compacte du plugin (sonde) — voir le commentaire du balisage
// (#pluginStatutTxtC). Visible EN CONTINU à l'étape C, pas seulement à
// l'échec : l'utilisateur doit voir que tout va bien aussi, pas juste être
// averti quand ça casse. Appelée par majMiseEnRouteSuite().
function _pluginStatutLigne(txtElId, btnElId, s, active) {
  const txt = document.getElementById(txtElId);
  if (txt) {
    if (active) {
      // Pas de "✓ " concaténé en dur : la couleur verte porte déjà le sens
      // (même motif que la pastille de la carte grandMA3, jamais de coche
      // ajoutée devant plural() — smoke test (e), pas d'assemblage de phrase).
      txt.textContent = plural("ui.sante.sonde.actif", (s.sonde && s.sonde.executors) || 0)
        + ((s.sonde && s.sonde.page) ? t("ui.sante.sonde.page", { page: s.sonde.page }) : "");
      txt.style.color = "var(--green)";
    } else {
      txt.textContent = t("ui.param.fw.plugin_arrete_court");
      txt.style.color = "var(--accent)";
    }
  }
  const btn = document.getElementById(btnElId);
  if (btn) btn.style.display = active ? "none" : "";
}

// Bouton « 🧩 Installer automatiquement » (carte Firmware). Copie + import OSC
// + vérif sonde côté serveur (~3,5 s). Échec → message actionnable + on
// déplie la procédure manuelle de la carte grandMA3.
async function pluginInstaller() {
  const btn = document.getElementById("pluginInstallBtn");
  const msg = document.getElementById("pluginEtapeMsg");
  if (btn) btn.disabled = true;
  if (msg) { msg.textContent = t("ui.param.plugin.install_en_cours"); msg.style.color = ""; }
  let r;
  try { r = await api("/api/plugin/install", {}); }
  catch (e) {
    if (msg) { msg.textContent = t("ui.param.echec_requete"); msg.style.color = "var(--red)"; }
    if (btn) btn.disabled = false;
    return;
  }
  if (r && r.ok) {
    if (msg) { msg.textContent = "✓ " + (r.message || t("err.ma3.plugin_installe")); msg.style.color = "var(--green)"; }
    // majParametresGma3 masquera l'étape au prochain tick (sonde active).
  } else {
    if (msg) { msg.textContent = "✗ " + ((r && r.raison) || t("firmware.msg.echec")); msg.style.color = "var(--red)"; }
    const det = document.getElementById("gma3PluginDetails");
    if (det) det.open = true;
  }
  if (btn) btn.disabled = false;
}

// ── DMX ───────────────────────────────────────────────────────────────
let dmxEnabled = false;
let dmxGridOuverte = false;
let _dmxGrids = null;           // {a, b, ta, tb} — barres et titres des 2 univers
async function toggleDMX() {
  dmxEnabled = !dmxEnabled;
  await api("/api/dmx/config", {enabled: dmxEnabled});
}
// « Local uniquement » : réglage machine persistant (voir wing_ui.SETTINGS).
async function setDmxLocal() {
  const cb = document.getElementById("dmxLocal");
  await api("/api/dmx/config", {local: !!(cb && cb.checked)});
}
async function setDmxUni() {
  await api("/api/dmx/config", {
    universe:  +document.getElementById("dmxUni").value,
    universe2: +document.getElementById("dmxUni2").value
  });
}
// Bouton « Voir les 512 canaux » : montre/masque la grille complète. Tant
// qu'elle est fermée, pollDMX ne construit ni ne rafraîchit les 1024 barres.
// ⚠️ À l'ouverture on CONSTRUIT et on RAFRAÎCHIT tout de suite (pollDMX direct),
//    sans attendre le tick de 300 ms — sinon la grille apparaît vide une
//    fraction de seconde, ce qui donne l'impression que le bouton ne fait rien.
function dmxToutVoir() {
  dmxGridOuverte = !dmxGridOuverte;
  const view = document.getElementById("dmxView");
  const btn = document.getElementById("dmxVoirBtn");
  if (!view) return;
  view.style.display = dmxGridOuverte ? "" : "none";
  if (btn) btn.textContent = dmxGridOuverte ? t("ui.param.dmx.masquer")
                                            : t("ui.param.dmx.voir");
  if (dmxGridOuverte) {
    _dmxConstruireGrille(view);
    pollDMX();                      // remplit les barres immédiatement
  } else {
    view.innerHTML = "";
    _dmxGrids = null;
  }
}
// Grille des 512 canaux, un bloc par univers (XLR A, XLR B). Construite une
// seule fois ; ensuite pollDMX ne fait que régler la hauteur de chaque barre.
function _dmxConstruireGrille(view) {
  view.innerHTML = "";
  _dmxGrids = {};
  [["a", "ta", "A"], ["b", "tb", "B"]].forEach(([gk, tk, lbl]) => {
    const bloc = document.createElement("div");
    bloc.style.marginBottom = "10px";
    const titre = document.createElement("div");
    titre.className = "muted";
    titre.style.cssText = "font-size:11px;margin-bottom:4px";
    titre.textContent = t("ui.param.dmx.xlr_titre", { lbl: lbl });
    const g = document.createElement("div");
    g.style.cssText = "display:grid;grid-template-columns:repeat(32,1fr);gap:2px";
    for (let i = 0; i < 512; i++) {
      const c = document.createElement("div");
      c.title = t("ui.param.dmx.canal_tip", { n: i + 1 });
      c.style.cssText = "height:22px;background:var(--card2);border-radius:2px;"
        + "display:flex;align-items:flex-end;overflow:hidden";
      const b = document.createElement("div");
      b.style.cssText = "width:100%;background:var(--accent);height:0%";
      c.appendChild(b);
      g.appendChild(c);
    }
    bloc.appendChild(titre);
    bloc.appendChild(g);
    view.appendChild(bloc);
    _dmxGrids[gk] = g;
    _dmxGrids[tk] = titre;
  });
}
function _dmxMajBarres(g, vals) {
  for (let i = 0; i < vals.length && i < g.children.length; i++)
    g.children[i].firstChild.style.height = Math.round(vals[i] / 255 * 100) + "%";
}
async function pollDMX() {
  const tab = document.getElementById("tab-parametres");
  if (!tab || !tab.classList.contains("active")) return;
  try {
    const d = await api("/api/dmx");
    if (!d || typeof d !== "object") return;   // réponse inattendue : on ne casse rien
    dmxEnabled = !!d.enabled;
    const cbLocal = document.getElementById("dmxLocal");
    if (cbLocal && document.activeElement !== cbLocal) cbLocal.checked = !!d.local;

    const btn = document.getElementById("dmxBtn");
    if (btn) {
      btn.textContent = d.enabled ? t("ui.param.dmx.couper") : t("ui.param.dmx.activer");
      btn.className   = d.enabled ? "btn big danger" : "btn big green";
    }

    const dot = document.getElementById("dmxDot");
    const src = document.getElementById("dmxSrc");
    const a = d.actifs || 0, b = d.actifs2 || 0;
    const u1 = d.universe != null ? d.universe : "?";
    const u2 = d.universe2 != null ? d.universe2 : "?";
    if (d.pps > 0) {
      if (dot) dot.className = "dot on";
      if (src) src.textContent = t("ui.param.dmx.signal_recu",
        { source: d.source || "?", total: a + b, u1: u1, a: a, u2: u2, b: b });
    } else {
      if (dot) dot.className = "dot";
      if (src) src.textContent = t("ui.param.dmx.aucun_signal_u", { u1: u1, u2: u2 });
    }

    if (dmxGridOuverte) {
      const view = document.getElementById("dmxView");
      if (view && !_dmxGrids) _dmxConstruireGrille(view);
      if (_dmxGrids) {
        _dmxGrids.ta.textContent = t("ui.param.dmx.grille_u", { xlr: "A", u: u1 });
        _dmxGrids.tb.textContent = t("ui.param.dmx.grille_u", { xlr: "B", u: u2 });
        _dmxMajBarres(_dmxGrids.a, d.channels || []);
        _dmxMajBarres(_dmxGrids.b, d.channels2 || []);
      }
    }
  } catch (e) {
    console.warn("pollDMX:", e);
  }
}

// ── LEDs ──────────────────────────────────────────────────────────────
// `ledDetecting` et `ledSlot` retirés : restes de la cartographie LED
// manuelle. Plus personne ne les écrivait.
let vegasOn = false;

async function setLedFeedback() {
  await api("/api/led", {feedback: document.getElementById("ledFeedback").checked});
}

async function toggleVegas() {
  vegasOn = !vegasOn;
  await api("/api/led/vegas", {on: vegasOn});
  const b = document.getElementById("vegasBtn");
  if (vegasOn) { b.textContent = t("ui.param.led.chenillard_arret"); b.className = "btn big danger"; }
  else { b.textContent = t("ui.param.led.chenillard"); b.className = "btn big primary"; }
}

async function ledRestore() {
  await api("/api/led", {restore: true});
}

// ⏹ Un curseur « niveau d'éclairage » (allumer TOUTES les LED à un niveau
//    donné) a vécu ici une journée, puis a été retiré — de l'interface comme
//    de l'API (le mode {"all": V} de /api/led est parti avec, plus aucun
//    appelant). NE PAS le réintroduire. Trois raisons :
//      1. inutile — le chenillard juste au-dessus fait déjà le test « toutes
//         les LED s'allument-elles ? » d'un coup d'œil ;
//      2. la wing a décroché du bus pendant son essai : 3 fois en 15 s,
//         revenue seule à chaque fois. Cause non prouvée (le curseur ne
//         journalisait rien), mais il allumait les 119 slots à fond en même
//         temps, là où le chenillard n'en allume jamais plus de 6 ;
//      3. `oninput` tirait des dizaines de POST/s, chacun réécrivant 119
//         slots, sans limitation de débit (la leçon existait déjà :
//         FADER_INTERVALLE).
//    🔑 Devant un bouton mort : « doit-il exister ? » avant « comment le faire
//    marcher ».

// ── Cartographie LED : RETIRÉE ───────────────────────────────────────
// La carte bouton → slot est désormais intégrée (slot = 2 × btn_id, sauf
// les executors) : elle a été retrouvée dans a-1.pcapng, donc il n'y a plus
// rien à cartographier à la main. L'assistant pas-à-pas n'avait d'ailleurs
// jamais servi : zéro entrée dans les profils de référence.
// Voir docs/HARDWARE.md, « Carte des LEDs ».

// ── Détection USB ─────────────────────────────────────────────────────
async function scanUSB() {
  const el = document.getElementById("scanResult");
  el.innerHTML = tHtml("ui.param.scan.en_cours");
  const list = await api("/api/usb/scan");
  if (list.error) { el.innerHTML = "<span style='color:var(--red)'>" + esc(list.error) + "</span>"; return; }  // TODO i18n Phase 2 : list.error (API)
  if (!list.length) { el.innerHTML = tHtml("ui.param.scan.aucun"); return; }

  el.innerHTML = "";
  list.forEach(d => {
    const badge = d.status === "supported"
      ? tHtml("ui.param.scan.badge_supportee")
      : d.status === "candidate"
      ? tHtml("ui.param.scan.badge_candidate")
      : "<span class='muted'>○</span>";
    const name = (d.product || t("ui.param.scan.inconnu")) +
                 (d.manufacturer ? " — " + d.manufacturer : "");
    const eps = d.endpoints.map(e => e.addr + " " + e.type + " " + e.dir).join(", ");
    const card = document.createElement("div");
    card.className = "encgroup";
    card.innerHTML =
      "<div style='display:flex;align-items:center;gap:12px;flex-wrap:wrap'>" +
        badge +
        // 🔒 esc() : produit, fabricant et raison viennent des DESCRIPTEURS USB
        // du périphérique — n'importe quel appareil branché choisit ces textes.
        "<b>" + esc(name) + "</b>" +
        "<code>" + esc(d.vid) + ":" + esc(d.pid) + "</code>" +
        tHtml("ui.param.scan.classe", { classe: d.class }) +
      "</div>" +
      (d.reason ? "<div class='muted' style='margin-top:6px;font-size:12.5px'>" + esc(d.reason) + "</div>" : "") +
      (eps ? tHtml("ui.param.scan.endpoints", { eps: eps }) : "") +
      "<div class='probe-zone' style='margin-top:10px'></div>";

    const pz = card.querySelector(".probe-zone");
    if (d.status === "candidate" || d.status === "supported") {
      const btn = document.createElement("button");
      btn.className = "btn";
      btn.textContent = t("ui.param.scan.tester");
      btn.onclick = async () => {
        btn.disabled = true; btn.textContent = t("ui.param.scan.test_en_cours");
        const r = await api("/api/usb/probe", {vid: d.vid, pid: d.pid});
        btn.disabled = false; btn.textContent = t("ui.param.scan.tester");
        const box = document.createElement("div");
        box.style.cssText = "margin-top:8px;padding:10px;background:var(--bg);border-radius:8px;font-size:12.5px";
        if (r.error) {
          box.innerHTML = "<span style='color:var(--red)'>" + esc(r.error) + "</span>";
        } else {
          box.innerHTML = "<div>" + esc(r.verdict || "") + "</div>";
          if (r.response_hex) {
            const hexShort = r.response_hex.slice(0,120) + (r.response_hex.length > 120 ? "…" : "");
            box.innerHTML += tHtml("ui.param.scan.reponse", { n: r.response_len, hex: hexShort });
            const cp = document.createElement("button");
            cp.className = "btn"; cp.style.marginTop = "8px";
            cp.textContent = t("ui.param.scan.copier");
            cp.onclick = () => {
              navigator.clipboard.writeText(JSON.stringify({device: d, probe: r}, null, 2))
                .then(() => cp.textContent = t("ui.param.scan.copie"));
            };
            box.appendChild(cp);
          }
        }
        pz.innerHTML = "";
        pz.appendChild(box);
      };
      pz.appendChild(btn);
    }
    el.appendChild(card);
  });
}

// ── Désinstallation ───────────────────────────────────────────────────
// Le bouton de l'onglet Paramètres n'efface RIEN : il ouvre cette fenêtre.
// L'endpoint /api/uninstall renvoie d'abord {deleted, kept, residue} puis se
// ferme (os._exit) 0,3 s plus tard — la réponse arrive donc avant la fermeture.
function desinstallEtape(id) {
  ["desinstallChoix", "desinstallTout", "desinstallConserver", "desinstallFin"]
    .forEach(e => document.getElementById(e).hidden = (e !== id));
}
function ouvrirDesinstall() {
  desinstallEtape("desinstallChoix");
  document.getElementById("voileDesinstall").classList.add("ouvert");
}
function fermerDesinstall(ev) {
  if (ev && ev.target && ev.target.id !== "voileDesinstall") return;
  document.getElementById("voileDesinstall").classList.remove("ouvert");
}
function desinstallVoieTout() { desinstallEtape("desinstallTout"); }
function desinstallVoieConserver() { desinstallEtape("desinstallConserver"); }

async function desinstallExecuter() {
  // La voie « Conserver » est celle dont le panneau est visible ; sinon
  // « Tout supprimer » = on ne garde rien.
  const conserver = !document.getElementById("desinstallConserver").hidden;
  const keep = conserver ? {
    profiles:   document.getElementById("duProfiles").checked,
    log:        document.getElementById("duLog").checked,
    ma3_plugin: document.getElementById("duPlugin").checked
  } : {profiles: false, log: false, ma3_plugin: false};

  let r;
  try {
    r = await api("/api/uninstall", {keep: keep, dry_run: false});
  } catch (e) {
    r = null;
  }
  const ul = document.getElementById("desinstallResidu");
  ul.innerHTML = "";
  const lignes = (r && r.error) ? [r.error]
    : (r && r.residue && r.residue.length) ? r.residue
    : [t("ui.modale.desinstall.corbeille")];
  lignes.forEach(t => {
    const li = document.createElement("li");
    li.textContent = t;
    ul.appendChild(li);
  });
  desinstallEtape("desinstallFin");
}
