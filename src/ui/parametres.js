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
  // Deux emplacements : la carte Firmware, et la ligne de retour de
  // l'assistant de mise en route (#mrMsg) quand il est ouvert.
  ["fwMsg", "mrMsg"].forEach(function (id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = txt || "";
    el.style.color = cls === "err" ? "var(--red)"
                   : cls === "ok" ? "var(--green)" : "";
  });
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
function majFirmware(fw, cap) {
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
      // Windows x64 (cap non null) : on renvoie vers « Capturer », pas vers l'import.
      etat.textContent = t(cap ? "ui.param.fw.aucun_capture" : "ui.param.fw.aucun");
      etat.style.color = "var(--accent)";
    }
  }
}
// ── Capture intégrée du firmware (Windows x64 uniquement, PAS ARM) ──────
// Le gros du travail (élévation, installation/désinstallation éphémère de
// USBPcap, capture, extraction) est côté serveur (wing_firmware_capture.py) —
// ce JS ne fait que : afficher l'encart de confirmation, lancer la capture,
// refléter ses 7 cartons (pollés via /api/status → s.capture, toutes les
// 400 ms comme le reste du panneau santé, voir ui/init.js) et transmettre le
// clic « Suivant » — sans jamais décider lui-même de l'avancement.
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
  // Repartir propre : réarmer Annuler.
  _fwAnnulDemande = false;
  _fwSuivantMsgFige = false;
  const annMsg = document.getElementById("fwCaptureAnnulerMsg");
  if (annMsg) annMsg.textContent = "";
  const suivMsg = document.getElementById("fwCaptureSuivantMsg");
  if (suivMsg) suivMsg.textContent = "";
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
// ── Les 7 cartons de l'assistant semi-automatique (13/11/2026) ─────────────
// Décision de l'auteur : plus rien n'avance tout seul. Le serveur
// (wing_firmware_capture._attendre_suivant) publie dans s.capture le carton
// courant (`phase`), ses détections (`pastilles`), s'il attend un clic
// (`attente_utilisateur`) et si ce clic est possible (`suivant_possible`).
// Ici on ne fait QUE refléter : jamais de décision locale sur l'avancement.

// Décision PURE : le bouton « Suivant » n'est actif que si une capture est
// active, que le serveur ATTEND un clic et que la détection du carton est
// verte (suivant_possible). Exécutée telle quelle dans node par le contrôle 49
// (smoke_firmware.py) ; la réinjection « return true » le fait tomber au rouge.
function fwSuivantActif(cap) {
  return !!(cap && cap.actif && cap.attente_utilisateur && cap.suivant_possible);
}

// État d'un carton i d'après le carton courant `phase` : fait / en cours /
// à venir — ou « sauté » (fait sans l'avoir été : l'assistant a été interrompu
// à `interrompu_au` et a filé au retrait d'USBPcap). Pure, testée dans node.
function fwEtatCarton(i, cap) {
  const phase = (cap && cap.phase) || 0;
  if (i === phase) return "en_cours";
  if (i > phase) return "a_venir";
  return (cap && cap.interrompu_au && i > cap.interrompu_au) ? "saute" : "fait";
}

// Décision PURE de l'affichage de l'assistant (chantier F, 16/11/2026), exécutée
// telle quelle dans node par le contrôle 49. cap = s.capture (null hors Windows
// x64).
//  - bloc     : #fwCaptureBloc (confirmation, cartons, résultat) n'existe que là
//    où la capture intégrée existe ;
//  - modal    : panneau modal « étape N/7 » PENDANT la capture seulement ;
//  - progress : cartons visibles pendant la capture, et APRÈS un ÉCHEC (pastille
//    rouge + « Réessayer ») — mais plus après un succès ni une annulation
//    (avant : le panneau et son « Annuler » restaient jusqu'à F5) ;
//  - capturer : le bouton « Capturer… » disparaît pendant la capture ;
//  (les imports .pcapng/.bin n'ont plus de décision d'affichage : ils sont
//  toujours là, dans le <details> « Repli manuel », dernier de la carte.)
function fwAffichageCapture(cap) {
  const actif = !!(cap && cap.actif);
  const echec = !!(cap && !cap.actif && cap.phase && cap.ok === false && !cap.annule);
  return {
    bloc: !!cap,
    modal: actif,
    progress: actif || echec,
    capturer: !!cap && !actif,
  };
}
let _fwCaptureDernier = null;

// Composants de cartons PARTAGÉS entre l'assistant de capture (ci-dessous) et
// l'assistant de mise en route (assistantMiseEnRoute, plus bas) : mêmes
// couleurs de pastille, même ligne « ● texte ». Une seule version.
const CARTON_COULEUR_PASTILLE = { vert: "var(--green)", rouge: "var(--red)", orange: "var(--accent)" };
function cartonLignePastille(etat, texte) {
  const row = document.createElement("div");
  const dot = document.createElement("span");
  dot.textContent = "●";
  dot.style.color = CARTON_COULEUR_PASTILLE[etat] || "var(--border)";
  dot.style.marginRight = "6px";
  row.appendChild(dot);
  row.appendChild(document.createTextNode(texte || ""));
  return row;
}

// Rend les 7 cartons : bordure/opacité selon l'état, pastilles et consigne
// dans le carton EN COURS seulement, et DÉPLACE le bloc d'actions unique
// (#fwCaptureActions : Suivant / Réessayer / Annuler) dans ce carton — un
// seul jeu de boutons, jamais deux affichages concurrents. Reconstruit à
// chaque poll (bon marché : 7 <li>, quelques <div>).
function _fwCaptureCartons(cap) {
  const total = cap.phase_total || 7;
  const libelle = {
    fait: t("ui.param.fw.carton.fait"),
    en_cours: t("ui.param.fw.carton.en_cours"),
    a_venir: t("ui.param.fw.carton.a_venir"),
    saute: t("ui.param.fw.carton.saute"),
  };
  const bordure = { fait: "var(--green)", en_cours: "var(--accent)", a_venir: "var(--border)", saute: "var(--border)" };
  const actions = document.getElementById("fwCaptureActions");
  for (let i = 1; i <= total; i++) {
    const li = document.getElementById("fwCarton" + i);
    if (!li) continue;
    const st = fwEtatCarton(i, cap);
    li.style.opacity = st === "a_venir" ? "0.5" : "1";
    li.style.borderColor = bordure[st];
    const etat = document.getElementById("fwCartonEtat" + i);
    if (etat) {
      etat.textContent = libelle[st];
      etat.style.color = st === "fait" ? "var(--green)" : st === "en_cours" ? "var(--accent)" : "";
    }
    const past = document.getElementById("fwCartonPastilles" + i);
    if (past) {
      past.textContent = "";
      if (st === "en_cours") {
        (cap.pastilles || []).forEach(function (pst) {
          past.appendChild(cartonLignePastille(pst.etat, pst.texte));
        });
      }
    }
    const cons = document.getElementById("fwCartonConsigne" + i);
    if (cons) {
      const montrer = st === "en_cours" && !!cap.etape;
      cons.style.display = montrer ? "" : "none";
      cons.textContent = montrer ? cap.etape : "";
    }
    const slot = document.getElementById("fwCartonActions" + i);
    if (slot && actions && st === "en_cours" && actions.parentNode !== slot) slot.appendChild(actions);
  }
  if (actions) actions.style.display = cap.phase ? "" : "none";

  // « Suivant » : actif UNIQUEMENT sur suivant_possible (fwSuivantActif). Son
  // libellé dit ce que le clic déclenche (suivant_cle vient du serveur).
  const btn = document.getElementById("fwCaptureSuivantBtn");
  if (btn) {
    btn.style.display = cap.actif ? "" : "none";
    btn.disabled = !fwSuivantActif(cap);
    btn.textContent = t(cap.suivant_cle || "firmware.suivant.defaut");
  }
  const msg = document.getElementById("fwCaptureSuivantMsg");
  if (msg && cap.actif && !_fwSuivantMsgFige) {
    msg.textContent = cap.attente_utilisateur
      ? t("ui.param.fw.carton.attente_clic") : t("ui.param.fw.carton.automatique");
    msg.style.color = "";
  }
  // « Réessayer » : seulement après un ÉCHEC (pas une annulation, pas un
  // succès) — il relance la capture, donc repart du carton 1 (nettoyage déjà
  // fait par la fin propre côté serveur).
  const re = document.getElementById("fwCaptureReessayerBtn");
  if (re) re.style.display = (!cap.actif && cap.ok === false && !cap.annule) ? "" : "none";
}
let _fwSuivantMsgFige = false;   // un refus du serveur reste affiché jusqu'au prochain clic

// Clic « Suivant » : on ne décide rien ici. La route pose un événement que la
// boucle de capture consomme en revérifiant la détection à cet instant (un
// clic au rouge est ignoré et journalisé côté serveur). 409 = rien à valider.
async function fwCaptureSuivant() {
  const btn = document.getElementById("fwCaptureSuivantBtn");
  const msg = document.getElementById("fwCaptureSuivantMsg");
  if (btn) btn.disabled = true;      // réarmé par le prochain poll (fwSuivantActif)
  _fwSuivantMsgFige = false;
  let r;
  try { r = await api("/api/firmware/capture/suivant", {}); }
  catch (e) {
    if (msg) { msg.textContent = t("ui.param.fw.suivant_echec_requete"); msg.style.color = "var(--red)"; }
    _fwSuivantMsgFige = true;
    return;
  }
  if (!(r && r.ok) && msg) {
    msg.textContent = t("ui.param.fw.suivant_refuse", { raison: (r && r.raison) || "?" });
    msg.style.color = "var(--red)";
    _fwSuivantMsgFige = true;
  }
}
// ── Assistant de mise en route UNIQUE (chantier 3a, passage 1) ───────────────
// Même gabarit que l'assistant de capture : fenêtre modale floue, cartons,
// pastilles vert / rouge / orange, « Suivant » actif seulement quand le carton
// courant est en place. Chaque étape s'affiche TOUJOURS : verte « déjà en
// place » si c'est fait, rouge avec l'action pour la faire sinon — jamais
// sautée en silence. Cartons : Firmware, OSC, Plugin, Vérification (passage 1),
// puis Raccourcis clavier et Sauvegarde / Démarrage (passage 2a). Elle a
// remplacé l'ancien fil en 5 étapes A à E (retiré au passage 2b).
//
// Tout le calcul est dans des fonctions PURES (detectionsMiseEnRoute,
// plateformeMiseEnRoute, cartonsMiseEnRoute, mrSuivantActif), exécutées telles
// quelles dans node par le contrôle 49. Le reste ne fait que les afficher.

// Détections (une seule définition de « OSC prêt », « sonde posée / active »).
//  - oscPret   : OSC joignable (signal partiel) OU confirmé par la sonde ;
//  - oscOkFull : la preuve complète (la sonde voit la bonne ligne OSC) ;
//  - ma3La     : grandMA3 écoute (ok ou muet) ;
//  - present   : fichiers du plugin posés ; active : la sonde répond.
function detectionsMiseEnRoute(s) {
  s = s || {};
  const r = s.osc ? s.osc.reachable : null;
  const oscReady = r === "ok";
  const oscOkFull = _oscConfigOk(s.osc && s.osc.ma3) === true;
  return {
    oscReady: oscReady,
    oscOkFull: oscOkFull,
    oscPret: oscReady || oscOkFull,
    ma3La: (r === "ok" || r === "muet"),
    present: !!(s.sonde && s.sonde.present),
    active: !!(s.sonde && s.sonde.actif),
  };
}

// Windows x64 avec capture intégrée ⇔ s.capture n'est pas null (voir
// wing_statut) ; sinon Mac / Linux, où le firmware s'apporte.
function plateformeMiseEnRoute(s) {
  return (s && s.capture != null) ? "windows" : "autre";
}

// Les cartons, dans l'ordre. `local` = ce que seul le navigateur sait :
// { verifFaite, verifPassee }. Texte et libellés sont des CLÉS i18n.
// Chaque carton : { id, pastille: vert|rouge|orange, texte, actions: [{id, cle}],
// suivantPossible }. Aucun carton n'est jamais retiré de la liste.
function cartonsMiseEnRoute(s, plateforme, local) {
  s = s || {};
  local = local || {};
  const d = detectionsMiseEnRoute(s);
  const fwOk = !!(s.firmware && s.firmware.configure);
  const windows = plateforme === "windows";
  const carton = function (id, pastille, texte, actions, suivantPossible) {
    return { id: id, pastille: pastille, texte: texte, actions: actions || [],
             suivantPossible: !!suivantPossible };
  };

  let fw;
  if (fwOk) {
    fw = carton("firmware", "vert", "ui.mr.fw.vert",
      windows ? [{ id: "exporter", cle: "ui.mr.fw.exporter" }] : [], true);
  } else if (windows) {
    fw = carton("firmware", "rouge", "ui.mr.fw.rouge_windows",
      [{ id: "capturer", cle: "ui.mr.fw.capturer" }], false);
  } else {
    fw = carton("firmware", "rouge", "ui.mr.fw.rouge_autre",
      [{ id: "import_bin", cle: "ui.mr.fw.import_bin" },
       { id: "import_capture", cle: "ui.mr.fw.import_capture" }], false);
  }

  const osc = d.oscPret
    ? carton("osc", "vert", "ui.mr.osc.vert", [], true)
    : carton("osc", "rouge", d.ma3La ? "ui.mr.osc.rouge" : "ui.mr.osc.rouge_sans_ma3",
        [{ id: "aide_osc", cle: "ui.mr.osc.aide" }], false);

  let plugin;
  if (d.active) {
    plugin = carton("plugin", "vert", "ui.mr.plugin.vert", [], true);
  } else if (!d.oscPret) {
    plugin = carton("plugin", "rouge", "ui.mr.plugin.rouge_sans_osc", [], false);
  } else if (!d.ma3La) {
    plugin = carton("plugin", "rouge", "ui.mr.plugin.rouge_sans_ma3", [], false);
  } else if (!d.present) {
    plugin = carton("plugin", "rouge", "ui.mr.plugin.rouge_absent",
      [{ id: "installer_plugin", cle: "ui.mr.plugin.installer" }], false);
    // Champ de l'emplacement (pool Plugins) AVANT le bouton, avec l'avertissement
    // Overwrite / Merge / Cancel : l'app ne peut pas savoir si la case est prise.
    plugin.champ = "plugin_slot";
    plugin.note = "ui.mr.plugin.slot_avert";
    plugin.aide = "pluginSlot";
  } else {
    plugin = carton("plugin", "rouge", "ui.mr.plugin.rouge_arrete",
      [{ id: "relancer_plugin", cle: "ui.mr.plugin.relancer" }], false);
  }

  // Vérification : rien ne la détecte, et l'auteur la veut facultative —
  // « Passer » la met en orange et ne bloque jamais.
  let verif;
  if (local.verifFaite) {
    verif = carton("verification", "vert", "ui.mr.verif.vert", [], true);
  } else if (local.verifPassee) {
    verif = carton("verification", "orange", "ui.mr.verif.orange",
      [{ id: "config_guidee", cle: "ui.mr.verif.lancer" }], true);
  } else {
    verif = carton("verification", "rouge", "ui.mr.verif.rouge",
      [{ id: "config_guidee", cle: "ui.mr.verif.lancer" },
       { id: "passer", cle: "ui.mr.verif.passer" }], false);
  }

  // Raccourcis clavier : détection par
  // shcuts_horodate (dernier envoi RÉUSSI, persisté sur disque) et
  // l'Accessibilité de Wing Keyboard (console.trusted ; sous Windows,
  // console.windows la rend sans objet). ShCuts actif dans grandMA3 n'est PAS
  // détecté par l'app : la note le dit, rien n'est affirmé.
  const cons = s.console || {};
  const accesOk = !!(cons.windows || cons.trusted);
  let rac;
  if (!s.shcuts_horodate) {
    rac = carton("raccourcis", "rouge", "ui.mr.rac.rouge_envoi",
      [{ id: "envoyer_raccourcis", cle: "ui.mr.rac.envoyer" }], false);
    rac.aideSujet = "raccourcis";
  } else if (!cons.windows && !cons.enabled) {
    rac = carton("raccourcis", "rouge", "ui.mr.rac.rouge_clavier",
      [{ id: "envoyer_raccourcis", cle: "ui.mr.rac.envoyer" }], false);
    rac.aideSujet = "accessibilite";
  } else if (!accesOk) {
    rac = carton("raccourcis", "rouge", "ui.mr.rac.rouge_acces",
      [{ id: "envoyer_raccourcis", cle: "ui.mr.rac.envoyer" }], false);
    rac.aideSujet = "accessibilite";
  } else {
    rac = carton("raccourcis", "vert", "ui.mr.rac.vert",
      [{ id: "envoyer_raccourcis", cle: "ui.mr.rac.envoyer" }], true);
    rac.aideSujet = "raccourcis";
  }
  rac.note = "ui.mr.rac.shcuts";

  // Sauvegarde / Démarrage : le bridge tourne-t-il
  // (s.mode === "bridge", comme majParametresGma3) ? La sauvegarde, elle, ne
  // se détecte pas : le bouton est proposé, jamais exigé.
  const demarre = s.mode === "bridge";
  // Deux cartons distincts, une action chacun : d'abord enregistrer, ensuite
  // démarrer. Détection réelle : s.dirty (« modifié depuis le dernier
  // enregistrement », le même point que dans l'en-tête). Vert = rien à
  // enregistrer ; orange = des modifications non enregistrées (conseillé).
  const sauv = s.dirty === false
    ? carton("sauvegarde", "vert", "ui.mr.sauvegarde.vert",
        [{ id: "sauvegarder", cle: "ui.mr.sauvegarde.sauvegarder" }], true)
    : carton("sauvegarde", "orange", "ui.mr.sauvegarde.orange",
        [{ id: "sauvegarder", cle: "ui.mr.sauvegarde.sauvegarder" }], true);
  const dem = demarre
    ? carton("demarrage", "vert", "ui.mr.demarrage.vert", [], true)
    : carton("demarrage", "rouge", "ui.mr.demarrage.rouge",
        [{ id: "demarrer", cle: "ui.mr.demarrage.demarrer" }], false);
  // Dernier carton : félicitations. Toujours vert, sans action ; on n'y arrive
  // qu'en passant « Suivant » sur le carton Démarrage, lui-même verrouillé tant
  // que le bridge ne tourne pas.
  const fin = carton("fin", "vert", "ui.mr.fin.vert", [], true);
  return [fw, osc, plugin, verif, rac, sauv, dem, fin];
}

// « Suivant » : actif seulement si le carton est en place (vert), ou orange
// (vérification remise à plus tard). Jamais au rouge.
function mrSuivantActif(carton) {
  return !!(carton && carton.suivantPossible
            && (carton.pastille === "vert" || carton.pastille === "orange"));
}

// ── Affichage (aucune décision ici : tout vient des fonctions pures) ────────
let _mr = { ouvert: false, i: 0, signature: "" };
let _mrStatut = null;                // dernier /api/status vu par le poll
let _mrVerifPassee = false;          // « Passer cette étape » cliqué
let _mrVerifFaite = false;           // configuration guidée allée jusqu'au bout
let _mrRouvrirApresGuide = false;    // la configuration guidée a été lancée d'ici

function _mrCartons() {
  return cartonsMiseEnRoute(_mrStatut, plateformeMiseEnRoute(_mrStatut),
    { verifFaite: _mrVerifFaite, verifPassee: _mrVerifPassee });
}

function assistantMiseEnRouteOuvrir(i) {
  _mr.ouvert = true;
  _mr.i = i || 0;
  _mr.signature = "";
  const fond = document.getElementById("mrFond");
  const modal = document.getElementById("mrModal");
  if (fond) fond.classList.add("ouvert");
  if (modal) modal.classList.add("ouvert");
  _mrMsgVider();
  assistantMiseEnRouteRendre();
}

// Fermer ne fait rien d'irréversible : aucune action n'est lancée, l'état
// (verte / rouge) se recalcule à la réouverture.
function assistantMiseEnRouteFermer() {
  _mr.ouvert = false;
  const fond = document.getElementById("mrFond");
  const modal = document.getElementById("mrModal");
  if (fond) fond.classList.remove("ouvert");
  if (modal) modal.classList.remove("ouvert");
}

function _mrMsgVider() {
  const el = document.getElementById("mrMsg");
  if (el) el.textContent = "";
  const sh = document.getElementById("mrShcutsEtat");
  if (sh) sh.textContent = "";
}

// Appelée par poll() via majParametresGma3 : mémorise l'état et réaffiche si
// l'assistant est ouvert et que quelque chose a changé.
function majMiseEnRoute(s) {
  _mrStatut = s;
  if (_mr.ouvert) assistantMiseEnRouteRendre();
}

function assistantMiseEnRouteRendre() {
  const liste = document.getElementById("mrCartons");
  if (!liste || !_mrStatut) return;
  const cartons = _mrCartons();
  if (_mr.i >= cartons.length) _mr.i = cartons.length - 1;
  const sig = JSON.stringify([cartons, _mr.i]);
  if (sig === _mr.signature) return;      // rien de changé : on ne reconstruit pas
  _mr.signature = sig;

  const titre = document.getElementById("mrTitre");
  if (titre) titre.textContent = t("ui.mr.etape", { n: _mr.i + 1, total: cartons.length });
  const libelle = { fait: t("ui.param.fw.carton.fait"), en_cours: t("ui.param.fw.carton.en_cours"),
                    a_venir: t("ui.param.fw.carton.a_venir") };
  const bordure = { fait: "var(--green)", en_cours: "var(--accent)", a_venir: "var(--border)" };
  liste.textContent = "";
  cartons.forEach(function (c, idx) {
    const st = idx < _mr.i ? "fait" : (idx === _mr.i ? "en_cours" : "a_venir");
    const li = document.createElement("li");
    li.style.cssText = "padding:8px 10px;border:1px solid " + bordure[st]
      + ";border-radius:8px;background:var(--card2);opacity:" + (st === "a_venir" ? "0.5" : "1");
    const tete = document.createElement("div");
    tete.style.cssText = "display:flex;justify-content:space-between;gap:8px;align-items:baseline";
    const b = document.createElement("b");
    const num = document.createElement("span");
    num.textContent = (idx + 1) + " · ";
    const nom = document.createElement("span");
    nom.textContent = t("ui.mr." + c.id + ".titre");
    b.appendChild(num);
    b.appendChild(nom);
    const etat = document.createElement("span");
    etat.className = "muted";
    etat.style.cssText = "font-size:11.5px;white-space:nowrap";
    etat.textContent = libelle[st];
    if (st === "fait") etat.style.color = "var(--green)";
    tete.appendChild(b);
    tete.appendChild(etat);
    li.appendChild(tete);
    // Les cartons déjà passés gardent leur pastille : on voit ce qui est vert.
    if (st !== "a_venir") {
      const past = document.createElement("div");
      past.style.cssText = "margin-top:4px;line-height:1.7";
      past.appendChild(cartonLignePastille(c.pastille, t(c.texte)));
      li.appendChild(past);
    }
    if (st === "en_cours") {
      if (c.id === "firmware" && c.pastille === "rouge" && c.actions[0] && c.actions[0].id === "import_bin") {
        const note = document.createElement("div");
        note.className = "muted";
        note.style.cssText = "margin-top:4px;font-size:12.5px";
        note.textContent = t("ui.mr.fw.note_autre");
        li.appendChild(note);
      }
      if (c.champ === "plugin_slot") {
        // Même réglage et même route (/api/plugin_slot, savePluginSlot) que le
        // champ de la carte grandMA3 : rien n'est dupliqué, seulement affiché.
        const ligne = document.createElement("div");
        ligne.className = "toolbar";
        ligne.style.marginTop = "8px";
        const lib = document.createElement("span");
        lib.className = "muted";
        lib.textContent = t("ui.mr.plugin.slot_label");
        const champ = document.createElement("input");
        champ.type = "number";
        champ.id = "mrSlotInput";
        champ.min = "1";
        champ.max = "9999";
        champ.style.cssText = "width:70px;text-align:center";
        champ.value = (_mrStatut && _mrStatut.plugin_slot != null) ? _mrStatut.plugin_slot : "";
        champ.onchange = function () { savePluginSlot(champ.value, "mrMsg"); };
        const aideBtn = document.createElement("button");
        aideBtn.className = "aide";
        aideBtn.textContent = "?";
        aideBtn.title = t("ui.commun.en_savoir_plus");
        aideBtn.onclick = function () { aide(c.aide); };
        ligne.appendChild(lib);
        ligne.appendChild(champ);
        ligne.appendChild(aideBtn);
        li.appendChild(ligne);
        const avert = document.createElement("div");
        avert.className = "muted";
        avert.style.cssText = "margin-top:4px;font-size:12.5px";
        avert.textContent = t(c.note);
        li.appendChild(avert);
      }
      if (c.id === "raccourcis") {
        const avert = document.createElement("div");
        avert.className = "muted";
        avert.style.cssText = "margin-top:4px;font-size:12.5px";
        avert.textContent = t(c.note);
        li.appendChild(avert);
      }
      if (c.actions.length) {
        const bar = document.createElement("div");
        bar.className = "toolbar";
        bar.style.marginTop = "8px";
        c.actions.forEach(function (a) {
          const btn = document.createElement("button");
          btn.className = "btn";
          btn.textContent = t(a.cle);
          btn.onclick = function () { _mrAction(a.id); };
          bar.appendChild(btn);
        });
        if (c.aideSujet) {
          const aideBtn = document.createElement("button");
          aideBtn.className = "aide";
          aideBtn.textContent = "?";
          aideBtn.title = t("ui.commun.en_savoir_plus");
          aideBtn.onclick = function () { aide(c.aideSujet); };
          bar.appendChild(aideBtn);
        }
        li.appendChild(bar);
      }
    }
    liste.appendChild(li);
  });

  const cour = cartons[_mr.i];
  const suiv = document.getElementById("mrSuivantBtn");
  if (suiv) {
    suiv.disabled = !mrSuivantActif(cour);
    suiv.textContent = _mr.i === cartons.length - 1 ? t("ui.mr.terminer") : t("ui.mr.suivant");
  }
  const prec = document.getElementById("mrPrecedentBtn");
  if (prec) prec.style.display = _mr.i > 0 ? "" : "none";
}

function assistantMiseEnRouteSuivant() {
  const cartons = _mrCartons();
  if (!mrSuivantActif(cartons[_mr.i])) return;   // garde-fou : jamais au rouge
  _mrMsgVider();
  if (_mr.i >= cartons.length - 1) {
    // « Terminer » : on referme la fenêtre et on emmène l'utilisateur sur
    // l'onglet Bridge (le bridge tourne déjà : le carton Démarrage était vert).
    assistantMiseEnRouteFermer();
    const b = document.querySelector('nav button[data-tab="bridge"]');
    if (b) b.click();
    return;
  }
  _mr.i++;
  _mr.signature = "";
  assistantMiseEnRouteRendre();
}

function assistantMiseEnRoutePrecedent() {
  if (_mr.i > 0) _mr.i--;
  _mr.signature = "";
  _mrMsgVider();
  assistantMiseEnRouteRendre();
}

// Enregistre d'abord le numéro saisi (le « change » du champ ne part qu'à la
// perte du focus), puis lance l'installation avec CE numéro.
async function _mrInstallerPlugin() {
  const champ = document.querySelector("#mrSlotInput");
  if (champ) await savePluginSlot(champ.value, "mrMsg");
  return pluginInstaller("mrMsg");
}

// Envoi des raccourcis : MÊME appel que le bouton de l'onglet Touches
// (shcutsEnvoyer, ui/touches.js, qui attend la preuve de la
// sonde avant d'annoncer quoi que ce soit). Le message vit dans #mrShcutsEtat,
// fixe (la liste de cartons est reconstruite à chaque poll) ; #mrShcutsBtn
// est un bouton caché, fixe lui aussi, que shcutsEnvoyer() grise pendant
// l'envoi (le bouton visible du carton, reconstruit, est gardé par
// _mrEnvoiEnCours).
let _mrEnvoiEnCours = false;
async function _mrEnvoyerRaccourcis() {
  if (_mrEnvoiEnCours) return;
  _mrEnvoiEnCours = true;
  try { await shcutsEnvoyer("mrShcutsBtn", "mrShcutsEtat"); }
  finally { _mrEnvoiEnCours = false; }
}

// Démarre le bridge SANS quitter la fenêtre (pas de bascule d'onglet) : le
// retour visuel est la pastille du carton Démarrage, pilotée par s.mode.
async function _mrDemarrer() {
  const msg = document.getElementById("mrMsg");
  if (msg) { msg.textContent = t("ui.mr.demarrage.en_cours"); msg.style.color = ""; }
  try { if (currentMode !== "bridge") await toggleBridge(); }
  catch (e) {
    if (msg) { msg.textContent = t("ui.param.echec_requete"); msg.style.color = "var(--red)"; }
  }
}

// Les actions REPRENNENT les fonctions existantes, rien n'est réécrit ici.
function _mrAction(id) {
  if (id === "capturer") {
    // L'assistant de capture a sa propre fenêtre modale : on referme celle-ci,
    // majCapture() rouvre l'assistant à la fin d'une capture réussie.
    assistantMiseEnRouteFermer();
    fwCaptureAmorcer();
    allerOnglet("parametres");
    const bloc = document.getElementById("fwCaptureConfirm");
    if (bloc) bloc.scrollIntoView({ behavior: "smooth", block: "center" });
  } else if (id === "import_bin") fwImportBin();
  else if (id === "import_capture") fwImportCapture();
  else if (id === "exporter") fwExport();
  else if (id === "aide_osc") aide("demarrage");
  else if (id === "installer_plugin") _mrInstallerPlugin();
  else if (id === "relancer_plugin") _relancerPlugin("mrMsg", null);
  else if (id === "envoyer_raccourcis") _mrEnvoyerRaccourcis();
  else if (id === "sauvegarder") sauvegarderConfigWizard("mrMsg");
  else if (id === "demarrer") {
    // On reste dans la fenêtre : le bridge est démarré sur place et le carton
    // passe au vert tout seul quand l'état serveur le confirme (poll).
    _mrDemarrer();
  }
  else if (id === "config_guidee") {
    assistantMiseEnRouteFermer();
    _mrRouvrirApresGuide = true;
    configGuideeDemarrer();
  } else if (id === "passer") {
    _mrVerifPassee = true;
    _mr.signature = "";
    assistantMiseEnRouteRendre();
  }
}

function majCapture(cap) {
  _fwCaptureDernier = cap || null;
  const aff = fwAffichageCapture(cap);
  const bloc = document.getElementById("fwCaptureBloc");
  if (bloc) bloc.style.display = aff.bloc ? "" : "none";
  if (!cap) {
    const fond0 = document.getElementById("fwCaptureFond");
    if (fond0) fond0.classList.remove("ouvert");
    return;
  }

  const btn = document.getElementById("fwCaptureBtn");
  const progress = document.getElementById("fwCaptureProgress");
  const removeBtn = document.getElementById("fwRemoveCaptureBtn");

  // Les cartons restent visibles APRÈS la fin (succès, échec, annulation) :
  // c'est là que vivent la pastille rouge qui dit pourquoi et « Réessayer ».
  // Masqués seulement tant qu'aucune capture n'a commencé (phase 0).
  if (btn) { btn.disabled = !!cap.actif; btn.style.display = aff.capturer ? "" : "none"; }
  if (progress) {
    progress.style.display = aff.progress ? "" : "none";
    progress.classList.toggle("fwModal", aff.modal);
  }
  const fond = document.getElementById("fwCaptureFond");
  if (fond) fond.classList.toggle("ouvert", aff.modal);
  const titre = document.getElementById("fwModalTitre");
  if (titre) {
    titre.style.display = aff.modal ? "" : "none";
    titre.textContent = aff.modal
      ? t("ui.param.fw.modal.titre", { n: cap.phase || 1, total: cap.phase_total || 7 }) : "";
  }
  _fwCaptureCartons(cap);
  if (removeBtn) removeBtn.style.display = cap.bouton_secours ? "" : "none";

  // Bouton « Annuler la démarche » : actif tout du long de la capture. Après
  // le clic on garde son libellé « annulation… » jusqu'à la fin du thread
  // (cap.actif repasse à false) — l'arrêt propre peut retirer USBPcap (~20 s).
  const annBtn = document.getElementById("fwCaptureAnnulerBtn");
  if (annBtn && !_fwAnnulDemande) {
    annBtn.disabled = !cap.actif;
    annBtn.style.display = cap.actif ? "" : "none";   // plus d'« Annuler » une fois fini
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
      // L'assistant de mise en route s'ouvre ici, firmware en vert. Son
      // action « Exporter le firmware » couvre le cas « autre ordinateur ».
      assistantMiseEnRouteOuvrir();
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

// Bouton « ← Retour aux Paramètres » de la carte Raccourcis (onglet Touches) :
// utile depuis la configuration guidée (étape 1/3, qui atterrit ici via
// assistantDemarrer()) — sans lui, aucun chemin de retour (signalé par
// l'auteur, 18/09/2026). Désigne la carte Firmware, où se trouve le bouton
// « Mise en route ».
function retourParametresRaccourcis() {
  const b = document.querySelector('nav button[data-tab="parametres"]');
  if (b) b.click();
  _designer(document.getElementById("firmwareCard"));
}

// ── Configuration guidée (carton « Vérification » de la Mise en route) ──────────────────────────────
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
// retour auteur) : l'envoi se fait désormais UNIQUEMENT depuis le carton
// « Raccourcis clavier » de la Mise en route (_mrEnvoyerRaccourcis), pour que
// le rappel ShCuts soit réellement vu avant l'envoi.
function configGuideeSuivant() {
  _guideEtat++;
  _guideAfficherEtape();
}

function configGuideeQuitter() {
  _guideEtat = 0;
  _mrRouvrirApresGuide = false;
  const banniere = document.getElementById("guideBanniere");
  if (banniere) banniere.style.display = "none";
}

// Fin des 3 étapes : referme la bannière et reprend le fil normal du wizard.
// Marque aussi la vérification comme faite (_mrVerifFaite) : être allé au
// bout de la configuration guidée EST la vérification de la wing que le
// carton « Vérification » de la Mise en route demande.
function configGuideeTerminer() {
  const reprendre = _mrRouvrirApresGuide;   // lancée depuis l'assistant de mise en route
  configGuideeQuitter();
  _mrVerifFaite = true;
  retourParametresRaccourcis();
  if (reprendre) assistantMiseEnRouteOuvrir(3);
}

// Carton « Sauvegarde » de la Mise en route : mince emballage autour de
// saveActiveProfile() (ui/profils.js, MÊME code que le bouton « 💾 Enregistrer »
// de l'en-tête, aucune logique dupliquée), avec un retour affiché sur place
// (#mrMsg, passé en argument) plutôt que de faire remonter l'utilisateur voir
// le point « modifié » de l'en-tête.
async function sauvegarderConfigWizard(msgId) {
  const msg = msgId ? document.getElementById(msgId) : null;
  if (msg) { msg.textContent = t("ui.param.guide.sauvegarde_en_cours"); msg.style.color = ""; }
  try {
    await saveActiveProfile();
  } catch (e) {
    if (msg) { msg.textContent = t("ui.param.echec_requete"); msg.style.color = "var(--red)"; }
    return;
  }
  if (msg) { msg.textContent = t("ui.param.guide.sauvegarde_ok"); msg.style.color = "var(--green)"; }
}

// ── OSC : est-il VRAIMENT activé dans grandMA3 ? ──────────
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
  return a && (a.id === "pluginSlotInput" || a.id === "mrSlotInput");
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
  const m = document.querySelector("#mrSlotInput");   // champ de l'assistant de mise en route
  if (m && document.activeElement !== m) m.value = slot;
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

// Bouton « Installer / réinstaller » de la carte grandMA3 : un clic = enregistre
// l'emplacement saisi PUIS installe (copie + import OSC + vérif sonde).
async function pluginSlotInstaller() {
  const champ = document.getElementById("pluginSlotInput");
  const bouton = document.getElementById("pluginSlotInstallBtn");
  if (bouton) bouton.disabled = true;
  try {
    if (champ) await savePluginSlot(champ.value, "pluginSlotMsg");
    await pluginInstaller("pluginSlotMsg");
  } finally { if (bouton) bouton.disabled = false; }
}

function majParametresGma3(s) {
  if (!s) return;
  majMiseEnRoute(s);   // assistant de mise en route (chantier 3a)
  // Sonde active : un « ✗ … la sonde ne répond pas » resté affiché est périmé.
  if (s.sonde && s.sonde.actif) {
    ["pluginSlotMsg", "mrMsg"].forEach(function (id) {
      const m = document.getElementById(id);
      if (m && m.textContent.trim().indexOf("✗") === 0) m.textContent = "";
    });
  }
  if (!_pluginSlotFieldsBusy()) _majPluginSlotUI(s.plugin_slot);
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
}

// Relance l'amorce PAR SON NOM en OSC (`Plugin "WingLoader"` — pas de numéro
// de slot), ~2 s côté serveur. Factorisé pour avoir DEUX boutons (carte
// grandMA3, et carton « Plugin » de la Mise en route) qui appellent
// EXACTEMENT le même code : des copies auraient fini par diverger (déjà
// arrivé ailleurs dans ce projet — GUIDE_PROJET.md, boutons d'executor).
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
// Installation du plugin (carton « Plugin » de la Mise en route, et bouton de
// la carte grandMA3). Copie + import OSC + vérif sonde côté serveur (~3,5 s).
// Échec → message actionnable + on déplie la procédure manuelle de la carte
// grandMA3. `msgElId` : l'élément où écrire le retour (#mrMsg, #pluginSlotMsg).
async function pluginInstaller(msgElId) {
  const msg = msgElId ? document.getElementById(msgElId) : null;
  if (msg) { msg.textContent = t("ui.param.plugin.install_en_cours"); msg.style.color = ""; }
  let r;
  try { r = await api("/api/plugin/install", {}); }
  catch (e) {
    if (msg) { msg.textContent = t("ui.param.echec_requete"); msg.style.color = "var(--red)"; }
    return;
  }
  if (r && r.ok) {
    if (msg) { msg.textContent = "✓ " + (r.message || t("err.ma3.plugin_installe")); msg.style.color = "var(--green)"; }
  } else {
    if (msg) { msg.textContent = "✗ " + ((r && r.raison) || t("firmware.msg.echec")); msg.style.color = "var(--red)"; }
    const det = document.getElementById("gma3PluginDetails");
    if (det) det.open = true;
  }
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
  // La bascule locale n'est entérinée qu'une fois le moteur d'accord : sinon
  // un échec réseau inversait `vegasOn` sans changer le libellé, et le bouton
  // mentait au clic suivant.
  const voulu = !vegasOn;
  try { await api("/api/led/vegas", {on: voulu}); }
  catch (e) { return; }
  vegasOn = voulu;
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
  let list;
  try { list = await api("/api/usb/scan"); }
  catch (e) { list = {error: t("ui.commun.moteur_injoignable")}; }   // sinon « Scan en cours… » à vie
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
        let r;
        try { r = await api("/api/usb/probe", {vid: d.vid, pid: d.pid}); }
        catch (e) { r = {error: t("ui.commun.moteur_injoignable")}; }
        finally { btn.disabled = false; btn.textContent = t("ui.param.scan.tester"); }
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
    // Moteur injoignable (déjà mort, requête échouée) : RIEN n'a été
    // supprimé. Avant, `r = null` tombait dans la ligne de succès « Mets le
    // dossier à la corbeille » — un bouton qui mentait (règle du GUIDE).
    r = {error: t("ui.modale.desinstall.echec_requete")};
  }
  const echec = !!(r && r.error);
  const fin = document.getElementById("desinstallFin");
  fin.querySelector("h4").textContent =
    t(echec ? "ui.modale.desinstall.echec_titre" : "ui.modale.desinstall.fin_titre");
  fin.querySelector("p:last-of-type").hidden = echec;   // « tu peux fermer… corbeille »
  const ul = document.getElementById("desinstallResidu");
  ul.innerHTML = "";
  const lignes = echec ? [r.error]
    : (r && r.residue && r.residue.length) ? r.residue
    : [t("ui.modale.desinstall.corbeille")];
  lignes.forEach(t => {
    const li = document.createElement("li");
    li.textContent = t;
    ul.appendChild(li);
  });
  desinstallEtape("desinstallFin");
}
