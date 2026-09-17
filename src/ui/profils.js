/* ui/profils.js — onglet Profils : chargement, rendu et gestion des profils
   ─────────────────────────────────────────────────────────────
   Sorti de wing_ui.js lors du découpage du JS par onglet.
   ⚠️ PORTÉE GLOBALE : ces fichiers sont des <script> CLASSIQUES,
      jamais des modules ES — une quarantaine de gestionnaires
      inline du balisage (onclick=…) en dépendent.
   ⚠️ ORDRE DE CHARGEMENT IMPOSÉ : core en premier, init en
      dernier. Voir l'ordre des <script defer> dans wing_ui.html. */

// ── Profile rendering ─────────────────────────────────────────────────
async function loadProfile() {
  // ⚠️ CHARGEMENT INSTRUMENTÉ.
  //
  // Signalé plusieurs fois : les raccourcis n'apparaissent pas — et même le
  // message d'erreur ne s'affiche pas. Donc `renderConsoleKeys()` n'est JAMAIS
  // atteinte : cette fonction s'interrompt avant, dans CE navigateur mais pas
  // en test (où chaque getElementById rend un objet, jamais null).
  //
  // Plutôt que de continuer à deviner, on dit à quelle ÉTAPE ça casse, à
  // l'écran. Un silence ne donne aucune prise ; un numéro d'étape, si.
  let __etape = t("ui.profils.etape.demarrage");
  try {
  profile = await api("/api/profile");
  // Les raccourcis dépendent du profil ACTIF : en changer peut créer un écart
  // avec MA3. On réévalue à chaque chargement plutôt qu'au seul démarrage.
  shcutsRafraichir();

  __etape = t("ui.profils.etape.touches");
  // Touches
  const tb = document.getElementById("btnTable");
  tb.innerHTML = "";
  Object.keys(profile.buttons).sort((a,b)=>parseInt(a,16)-parseInt(b,16)).forEach(k => {
    const tr = document.createElement("tr");
    const ref = profile.executor_ref[k] || "";
    // ⌨️ LA COLONNE RACCOURCI, ajoutée ici plutôt que dans une grille à part :
    //    tout ce qui concerne une touche tient maintenant sur UNE ligne — son
    //    code, ce qu'elle envoie, son executor, et la frappe clavier qui la
    //    porte. C'était réparti sur deux onglets.
    const tok = profile.buttons[k];
    // ⚠️ LE CHAMP EST OFFERT À TOUT TOKEN D'UN SEUL MOT, même s'il n'a pas
    //    encore de raccourci enregistré.
    //
    // 🐛 1re version : le champ n'apparaissait que si le token figurait DÉJÀ
    //    dans la table. Dix tokens assignables (Flash, Swap, Toggle, Kill,
    //    Label, Load, Exchange, Collect, Insert, EditSetting) affichaient donc
    //    « — » et ne POUVAIENT PAS recevoir de raccourci, alors que le moteur
    //    en accepte un pour n'importe quel mot seul. Ajouter une touche à sa
    //    wing et ne pas pouvoir lui donner de frappe : exactement ce qu'il ne
    //    faut pas, puisque chaque exemplaire de wing est différent.
    //
    // « — » reste juste dans deux cas, et seulement ceux-là :
    //   • commande COMPOSÉE (« Go+ Executor 105 ») : elle part en OSC, aucune
    //     frappe ne peut la produire ;
    //   • clic de roue (`__ENC1_PUSH__`) : c'est local à l'app, MA3 n'est même
    //     pas au courant.
    const composee = tok.indexOf(" ") >= 0;
    const clicRoue = tok.indexOf("__ENC") === 0;
    const tipRac = clicRoue ? t("ui.touches.rac.tip_clic_roue")
                            : t("ui.touches.rac.tip_commande_composee");
    const tipFrappeMa3 = t("ui.touches.rac.tip_frappe_ma3");
    const celluleRac = (composee || clicRoue)
      ? "<td class='muted' style='font-size:11.5px' title='" + tipRac + "'>—</td>"
      : "<td><input type='text' class='rac' value='" +
        esc((profile.console_keys || {})[tok] || "") +
        "' placeholder='—' title='" + tipFrappeMa3 + "' " +
        "style='width:74px;text-align:center;font-size:12px;padding:4px'></td>";
    // ⚡ DOUBLE-APPUI : commande MA3 envoyée en OSC quand cette
    // touche est pressée deux fois rapidement. Indexée par TOKEN, pas par
    // code — voir wing_mapper.py::migrate_profile. Offerte à tout token SAUF
    // le clic de roue (`__ENCn_PUSH__`) : son double-clic est câblé en dur
    // sur les groupes 5-8 (wing_boutons.py), pas configurable ici. Une
    // commande composée PEUT en recevoir une : la commande part en OSC de
    // toute façon, indépendamment du mécanisme de raccourci clavier.
    const tipDblVerrouille = t("ui.touches.dbl.tip_verrouille");
    const tipDblComplet = t("ui.touches.dbl.tip_complet");
    const celluleDbl = clicRoue
      ? "<td class='muted' style='font-size:11.5px' title='" + tipDblVerrouille + "'>—</td>"
      : "<td><input type='text' class='dbl' value='" +
        esc((profile.double_clic || {})[tok] || "") +
        "' placeholder='ex. SaveShow' title='" + tipDblComplet + "' " +
        "style='width:110px;text-align:center;font-size:12px;padding:4px'></td>";
    // 🔒 esc() : code, commande et executor viennent du PROFIL — donc
    // potentiellement d'un fichier importé (voir esc() dans ui/core.js).
    tr.innerHTML = "<td><code>" + esc(k) + "</code></td><td>" + esc(tok) +
      "</td><td class='muted'>" + esc(ref) + "</td>" + celluleRac + celluleDbl +
      "<td><button class='mini' title='Supprimer'>✕</button></td>";
    tr.querySelector(".mini").onclick = async () => {
      await api("/api/assign", {key:k, type:"clear", value:""});
      loadProfile();
    };
    const champRac = tr.querySelector(".rac");
    if (champRac) champRac.onchange = async (e) => {
      await api("/api/console/key", {token: tok, key: e.target.value});
      profile.console_keys[tok] = e.target.value.trim();
      shcutsRafraichir();            // l'écart avec MA3 change : on le redit
    };
    const champDbl = tr.querySelector(".dbl");
    if (champDbl) champDbl.onchange = async (e) => {
      await api("/api/double_clic", {token: tok, commande: e.target.value});
      profile.double_clic = profile.double_clic || {};
      profile.double_clic[tok] = e.target.value.trim();
    };
    tb.appendChild(tr);
  });

  // Faders — chaque fader a un "type" de master MA3, calqué EXACTEMENT sur la
  // liste "Select Function" que MA3 propose pour la propriété Fader d'un
  // executor (Menu Executor → Fader). "faderspeed" (Speed, propriété Fader
  // de l'executor) et "speed" (Speed Master séparé, pool Master 3.N) sont
  // deux mécanismes distincts malgré le nom proche.
  const FADER_EXEC_KINDS  = ["executor","crossfade","crossfadeA","crossfadeB",
                              "temp","rate","time","faderspeed"];
  const FADER_UNIT_KINDS  = ["speed","faderspeed"];   // BPM/Hz/Secondes + Min/Max
  const fg = document.getElementById("faderGrid");
  fg.innerHTML = "";
  profile.faders.forEach((f, i) => {
    const kind = f.kind || "executor";
    const d = document.createElement("div");
    d.className = "fader-item";
    d.id = "fader-" + i;
    d.innerHTML = tHtml("ui.faders.item", { i: i + 1 });

    const sel   = d.querySelector(".fkind");
    const fExec = d.querySelector(".f-exec");
    const fNum  = d.querySelector(".f-num");
    const fUnit = d.querySelector(".f-unit");
    const fMin  = d.querySelector(".f-min");
    const fMax  = d.querySelector(".f-max");
    const fSel    = d.querySelector(".f-sel");
    const fSuivre = d.querySelector(".f-suivre");
    const subSel  = d.querySelectorAll(".sub-sel");
    fSel.value    = f.num ?? 2;
    fSuivre.checked = f.suivre !== false;
    const fNom  = d.querySelector(".f-nom");
    fNom.value = (profile.fader_noms || [])[i] || "";
    fNom.onchange = () => api("/api/fader/nom", {index: i, nom: fNom.value});
    const subExec     = d.querySelectorAll(".sub-exec");
    const subSpeed    = d.querySelectorAll(".sub-speed");
    const subSpeedNum = d.querySelectorAll(".sub-speednum");

    sel.value   = kind;
    fExec.value = FADER_EXEC_KINDS.includes(kind) ? (f.exec || 101) : 101;
    fNum.value  = f.num  ?? 1;
    fUnit.value = f.unit ?? "bpm";
    fMin.value  = f.min  ?? 0;
    fMax.value  = f.max  ?? 225;   // plage native du Speed Master MA3 (0-225 BPM)

    const refresh = () => {
      const k = sel.value;
      subExec.forEach(el     => el.style.display = FADER_EXEC_KINDS.includes(k) ? "" : "none");
      subSpeed.forEach(el    => el.style.display = FADER_UNIT_KINDS.includes(k) ? "" : "none");
      subSpeedNum.forEach(el => el.style.display = (k === "speed") ? "" : "none");
      subSel.forEach(el      => el.style.display = (k === "selected") ? "" : "none");
      // « suit MA3 » coché : MA3 décide du type réellement envoyé (voir
      // wing_faders.kind_selon_ma3) — le sélecteur ne fait plus rien tant que
      // la case reste cochée, on le grise pour ne pas laisser croire le contraire.
      const suivi = FADER_EXEC_KINDS.includes(k) && fSuivre.checked;
      sel.disabled = suivi;
      sel.title = suivi ? t("ui.faders.suit_ma3_grise") : "";
    };
    refresh();

    const send = async () => {
      const k = sel.value;
      if (k === "gm") {
        await api("/api/fader", {index:i, kind:"gm"});
      } else if (k === "speed") {
        await api("/api/fader", {index:i, kind:"speed",
          num:+fNum.value, unit:fUnit.value, min:+fMin.value, max:+fMax.value});
      } else if (k === "faderspeed") {
        // `suivre` est bien transmis : c'est un fader d'executor, la case
        // « suit MA3 » est affichée pour lui et doit donc agir.
        await api("/api/fader", {index:i, kind:"faderspeed",
          exec:+fExec.value, unit:fUnit.value, min:+fMin.value, max:+fMax.value,
          suivre: fSuivre.checked});
      } else if (k === "selected") {
        await api("/api/fader", {index:i, kind:"selected", num:+fSel.value});
      } else {   // toutes les kinds "FaderX Executor N At %"
        await api("/api/fader", {index:i, kind:k, exec:+fExec.value,
                                 suivre: fSuivre.checked});
      }
    };
    sel.onchange = () => { refresh(); send(); };
    fSuivre.onchange = () => { refresh(); send(); };
    [fExec, fNum, fUnit, fMin, fMax, fSel].forEach(el => el.onchange = send);
    fg.appendChild(d);
  });
  if (hlFader >= 0) {
    const el = document.getElementById("fader-" + hlFader);
    if (el) el.classList.add("hl");
  }

  __etape = t("ui.profils.etape.encodeurs");
  // Encodeurs
  const eg = document.getElementById("encGroups");
  eg.innerHTML = "";
  // Groupes 1-4 : clic simple sur la roue N. Groupes 5-8 : double-clic sur
  // la roue N-4 — même mécanisme d'édition,
  // juste un geste différent. Le seuil (4) correspond à
  // wing_bridge.py::ENC_GROUPES_SIMPLE, pas d'API pour le lire depuis ici.
  const ENC_GROUPES_SIMPLE = 4;
  profile.enc_groups.forEach((g, gi) => {
    const d = document.createElement("div");
    d.className = "encgroup";
    const roueN = (gi % ENC_GROUPES_SIMPLE) + 1;
    const geste = gi < ENC_GROUPES_SIMPLE
      ? t("ui.encodeurs.geste_clic", { n: roueN })
      : t("ui.encodeurs.geste_dbl", { n: roueN });
    let inner = tHtml("ui.encodeurs.groupe_titre", { n: gi + 1, geste: geste });
    for (let i = 0; i < 4; i++) {
      inner += tHtml("ui.encodeurs.roue_case",
        { n: i + 1, g: gi, i: i, val: g[i] || "" });
    }
    inner += "</div>";
    d.innerHTML = inner;
    eg.appendChild(d);
  });
  // Retenir la dernière case touchée : un clic sur un nom du répertoire y va.
  document.querySelectorAll("#encGroups input").forEach(inp => {
    inp.addEventListener("focus", () => { encFocus = inp; });
    inp.addEventListener("input", () => markAttr(inp));
    // ⚠️ « change » = la modification part AUSSITÔT, comme pour les faders.
    //    Sans ça, elle restait dans le navigateur et le profil enregistré ne
    //    la contenait pas (signalé).
    inp.addEventListener("change", appliquerEncodeurs);
    markAttr(inp);
  });
  const _encDef = document.getElementById("encDefault");
  const _encPas = document.getElementById("encStep");
  _encDef.value = profile.enc_default_group;
  _encPas.value = profile.enc_step;
  _encDef.onchange = appliquerEncodeurs;
  _encPas.onchange = appliquerEncodeurs;

  __etape = t("ui.profils.etape.profil_courant");
  // ⏹ `profName` a disparu avec l'encart « Profil courant » : le
  //    nom du profil actif est déjà en permanence dans l'en-tête. Le lire ici
  //    aurait planté loadProfile() en entier — donc plus de touches, plus de
  //    faders, plus de raccourcis. Le contrôle test_ids l'a attrapé.

  // LEDs cartographiées

  __etape = t("ui.profils.etape.raccourcis");
  // Table des raccourcis console
  renderConsoleKeys();
    __etape = t("ui.profils.etape.termine");
  } catch (e) {
    const msg = tHtml("ui.profils.chargement_interrompu",
                      { etape: __etape, erreur: e.message });
    console.error(msg, e);
    const g = document.getElementById("consoleKeys");
    if (g) g.innerHTML = "<div style='grid-column:1/-1;color:var(--red)'>" + msg
                       + t("ui.profils.chargement_interrompu_signale") + "</div>";
    const j = document.getElementById("logbox");
    if (j) j.innerHTML = "<div style='color:var(--red)'>" + msg + "</div>" + j.innerHTML;
  }
}

// ── Profils ───────────────────────────────────────────────────────────
// Crée un profil NOMMÉ à partir des réglages actuels.
//
// ⚠️ Remplace l'ancien encart « Profil courant » (champ + bouton Sauvegarder),
// retiré parce qu'il redisait ce que l'en-tête montre déjà. La
// CAPACITÉ, elle, ne devait pas disparaître : sans elle on ne pourrait plus
// créer de profil, seulement écraser l'actif.
async function enregistrerSous() {
  const nom = prompt(t("ui.profils.prompt_nom"),
                     (profile && profile.name) || "");
  if (nom === null) return;                 // annulé
  const propre = nom.trim();
  if (!propre) return;
  await api("/api/profile/save", {name: propre});
  loadProfiles(); loadProfile();
}
async function newProfile() {
  await api("/api/profile/new", {});
  loadProfile();
}

// 📥 Import d'un profil venu d'ailleurs. Le navigateur lit le fichier et
// envoie son contenu : pas de boîte de dialogue native à gérer, et ça marche
// depuis n'importe quel dossier (AirDrop, clé USB, Téléchargements).
// 📥 Import par le SÉLECTEUR NATIF de macOS, ouvert dans le dossier des
// profils de l'app.
//
// 🔑 Un `<input type="file">` ne peut PAS choisir son dossier de
// départ — le navigateur l'interdit. L'utilisateur atterrissait donc dans
// « Documents » alors que ses profils sont dans ~/Library/Application Support,
// dossier CACHÉ dans le Finder : introuvable en pratique.
//
// Le sélecteur macOS, lui, accepte un `default location`. On part donc du bon
// dossier, tout en laissant naviguer ailleurs.
async function importProfile() {
  const r = await api("/api/profile/parcourir", {});
  if (r.annule) return;                       // annulation : pas une erreur
  if (!r.ok) { alert(t("ui.profils.import_refuse", { raison: r.raison || t("ui.profils.raison_inconnue") })); return; }
  await loadProfiles();
  alert(t("ui.profils.importe", { nom: r.name }));
}

// revealProfiles() retirée : « Ouvrir le dossier des
// profils » ne servait à rien — le nouvel import part directement
// dans ce dossier.

// ── En-tête : enregistrer sur le profil actif / recharger un profil propre ──
async function saveActiveProfile() {
  await api("/api/profile/save", {});   // sans nom → enregistre sur le profil actif
  loadProfiles();
}
// ── Filet de sécurité : config sûre (référence verrouillée) ──
async function restoreReference() {
  // Instantané si rien à perdre ; on ne confirme que s'il y a des modifs.
  if (window._dirty && !confirm(t("ui.profils.confirm_restore"))) return;
  const r = await api("/api/reference/restore", {});
  if (r.error) { alert(r.error); return; }
  loadProfile(); loadProfiles();
}
async function setReference() {
  if (!confirm(t("ui.profils.confirm_figer"))) return;
  const r = await api("/api/reference/set", {});
  if (r.when) { const w = document.getElementById("refWhen"); if (w) w.textContent = r.when; }
}
async function loadProfiles() {
  const list = await api("/api/profiles");
  const el = document.getElementById("profList");
  if (!list.length) { el.innerHTML = tHtml("ui.profils.aucun_sauve"); return; }
  el.innerHTML = "";
  list.forEach(p => {
    const d = document.createElement("div");
    d.className = "profile-row";
    // ⭐ Favori = le profil chargé au démarrage. Deux wings n'ont pas la même
    // disposition (ordre des faders, touches présentes, rôle des roues) :
    // retomber sur les défauts à chaque lancement obligeait à recharger son
    // profil à la main.
    d.innerHTML = "<button class='btn fav-btn' title='" +
      (p.favori ? t("ui.profils.fav_tip_actif") : t("ui.profils.fav_tip_inactif")) + "'" +
      " style='padding:4px 9px" + (p.favori ? ";color:var(--accent)" : "") + "'>" +
      (p.favori ? "★" : "☆") + "</button>" +
      // 🔒 esc() : le nom vient du JSON du profil, donc d'un fichier importé.
      // Posé brut, `<img src=x onerror=…>` s'exécutait à l'affichage de la
      // liste, sur l'origine de l'app (contrôle test_xss_profil_importe).
      "<b>" + esc(p.name) + "</b> <span class='muted'>" + esc(p.file) + "</span>" +
      (p.favori ? tHtml("ui.profils.au_demarrage") : "") +
      "<span style='margin-left:auto;display:flex;gap:6px'>" +
      (p.protege ? tHtml("ui.profils.protege") : tHtml("ui.profils.del_btn")) +
      "<button class='btn load-btn'>" + t("ui.profils.charger") + "</button></span>";
    d.querySelector(".fav-btn").onclick = async () => {
      await api("/api/profile/favori", {file: p.favori ? "" : p.file});
      loadProfiles();
    };
    d.querySelector(".load-btn").onclick = async () => {
      await api("/api/profile/load", {file: p.file});
      loadProfile();
    };
    const supp = d.querySelector(".del-btn");
    if (supp) supp.onclick = async () => {
      if (!confirm(t("ui.profils.confirm_delete", { nom: p.name }))) return;
      await api("/api/profile/delete", {file: p.file});
      loadProfiles();
    };
    el.appendChild(d);
  });
}
