/* ui/touches.js — onglet Touches : apprentissage, configuration guidée, raccourcis MA3
   ─────────────────────────────────────────────────────────────
   Sorti de wing_ui.js lors du découpage du JS par onglet.
   ⚠️ PORTÉE GLOBALE : ces fichiers sont des <script> CLASSIQUES,
      jamais des modules ES — une quarantaine de gestionnaires
      inline du balisage (onclick=…) en dépendent.
   ⚠️ ORDRE DE CHARGEMENT IMPOSÉ : core en premier, init en
      dernier. Voir l'ordre des <script defer> dans wing_ui.html. */


// ── Configuration guidée ──────────────────────────────────────────────
// L'app annonce une touche, l'utilisateur appuie dessus, on enchaîne. C'est
// l'inverse du mode apprentissage classique (appuyer PUIS choisir), et c'est
// ce qu'il faut quand on part d'une wing vierge : plus besoin de se souvenir
// de ce qu'on voulait mettre où.
//
// La liste des étapes vient du SERVEUR (/api/assistant) : elle est écrite et
// vérifiée à un seul endroit, et le test de fumée s'assure qu'aucune étape ne
// propose une commande que l'app ne saurait pas envoyer.
let assistant = {actif: false, etapes: [], i: 0, faites: 0};

async function assistantDemarrer() {
  if (assistant.actif) return;
  let d;
  try { d = await (await fetch("/api/assistant")).json(); }
  catch (e) { return; }
  assistant = {actif: true, etapes: d.etapes, i: 0, faites: 0};
  if (currentMode !== "learn") await api("/api/mode", {mode: "learn"});
  await api("/api/learn/clear", {});
  document.getElementById("assistantPanneau").style.display = "";
  document.getElementById("assignForm").style.display = "none";
  document.getElementById("btnAssistant").disabled = true;
  assistantAfficher();
}

function assistantAfficher() {
  const e = assistant.etapes[assistant.i];
  if (!e) return assistantArreter(true);
  document.getElementById("assistantGroupe").textContent = e.groupe;
  document.getElementById("assistantCible").textContent = e.libelle;
  document.getElementById("assistantProgres").textContent =
    plural("ui.touches.assistant.progres", assistant.faites,
           { i: assistant.i + 1, total: assistant.etapes.length });
  document.getElementById("learnHint").textContent = t("ui.touches.hint.guidee");
}

async function assistantAssigner(key) {
  const e = assistant.etapes[assistant.i];
  if (!e) return;
  const body = {key: key, type: e.type, value: e.valeur};
  // Un bouton d'executor reçoit sa fonction de déclenchement par défaut ;
  // elle reste modifiable ensuite dans le tableau, et le suivi de MA3 la
  // corrigera de toute façon si la console dit autre chose.
  if (e.type === "exec") body.func = "Go+";
  await api("/api/assign", body);
  assistant.faites++;
  assistant.i++;
  await loadProfile();
  assistantAfficher();
}

async function assistantPasser() {
  assistant.i++;
  await api("/api/learn/clear", {});
  assistantAfficher();
}

async function assistantReculer() {
  if (assistant.i > 0) assistant.i--;
  await api("/api/learn/clear", {});
  assistantAfficher();
}

async function assistantArreter(fini) {
  assistant.actif = false;
  document.getElementById("assistantPanneau").style.display = "none";
  document.getElementById("btnAssistant").disabled = false;
  document.getElementById("assistantEtat").textContent =
    fini ? plural("ui.touches.assistant.fini", assistant.faites)
         : plural("ui.touches.assistant.arrete", assistant.faites);
  document.getElementById("learnHint").textContent = t("ui.touches.hint");
  await api("/api/learn/clear", {});
}

// ── Learn / assign ────────────────────────────────────────────────────
function showAssignForm(key) {
  document.getElementById("assignForm").style.display = "";
  document.getElementById("detKey").textContent = key;
  const cur = profile && profile.buttons[key];
  const ref = profile && profile.executor_ref[key];
  document.getElementById("detCur").textContent =
    cur ? (ref ? t("ui.touches.assign.actuel_ref", { cur: cur, ref: ref })
               : t("ui.touches.assign.actuel", { cur: cur }))
        : t("ui.touches.assign.non_assignee");
  document.getElementById("learnHint").textContent = t("ui.touches.hint.detectee");
}

async function toggleLearn() {
  const m = currentMode === "learn" ? "idle" : "learn";
  await api("/api/mode", {mode: m});
  document.getElementById("assignForm").style.display = "none";
  document.getElementById("learnHint").textContent =
    m === "learn" ? t("ui.touches.hint.appuie") : t("ui.touches.hint.active");
}

async function doAssign() {
  const key  = document.getElementById("detKey").textContent;
  const val  = document.getElementById("assignVal").value;
  const type = selectedType();
  const body = {key: key, type: type, value: val};
  if (type === "exec") body.func = document.getElementById("assignFunc").value;
  await api("/api/assign", body);
  document.getElementById("assignForm").style.display = "none";
  document.getElementById("assignVal").value = "";
  document.getElementById("learnHint").textContent = t("ui.touches.hint.assignee");
  await loadProfile();
}

async function skipAssign() {
  await api("/api/learn/clear", {});
  document.getElementById("assignForm").style.display = "none";
  document.getElementById("learnHint").textContent = t("ui.touches.hint.appuie");
}

// ── Frappe clavier vers MA3 ───────────────────────────────────────────
// (plus de bascule : le mode console est le comportement)

async function consoleTest() {
  const v = (document.getElementById("testKey").value || "s").trim();
  await api("/api/console/test", {key: v});
}

async function openAccessibility() {
  const btn = document.getElementById("accessBtn");
  btn.textContent = t("ui.bridge.access.attente");
  await api("/api/console/open_settings", {});
  setTimeout(() => { btn.textContent = t("ui.bridge.access.bouton"); }, 15000);
}


async function resetConsoleKeys() {
  await api("/api/console/reset", {});
  await loadProfile();
}

function renderConsoleKeys() {
  const el = document.getElementById("consoleKeys");
  if (!el) return;
  const keys = (profile && profile.console_keys) || {};

  // ⚠️ ICI, UNIQUEMENT LES RACCOURCIS SANS BOUTON.
  //
  // Depuis que la colonne « Raccourci clavier » existe dans le tableau
  // ci-dessus, un token assigné à une touche s'édite sur SA ligne. Cette
  // grille ne garde que le reste — et ce reste compte : l'app connaît une
  // soixantaine de raccourcis pour une quarantaine de touches physiques, et
  // elle les pousse TOUS vers MA3. Les cacher parce qu'aucun bouton ne les
  // porte reviendrait à modifier la console depuis un réglage invisible.
  //
  // 🔑 C'est aussi ce qui rend le projet utilisable sur une AUTRE wing : une
  // touche absente chez toi peut exister chez quelqu'un d'autre.
  const assignes = new Set(Object.values((profile && profile.buttons) || {}));
  const restants = Object.keys(keys).filter(tok => !assignes.has(tok)).sort();

  el.innerHTML = "";
  restants.forEach(tok => {
    const d = document.createElement("div");
    d.style.cssText = "display:flex;align-items:center;gap:6px";
    d.innerHTML = "<span class='muted' style='font-size:12px;min-width:60px'>" +
      esc(tok) + "</span><input type='text' value='" + esc(keys[tok] || "") +
      "' placeholder='—' style='width:60px;text-align:center;font-size:12px;padding:5px'>";
    d.querySelector("input[type=text]").onchange = async (e) => {
      await api("/api/console/key", {token: tok, key: e.target.value});
      profile.console_keys[tok] = e.target.value.trim();
      shcutsRafraichir();
    };
    el.appendChild(d);
  });

  const titre = document.getElementById("titreAutresRac");
  if (titre) {
    titre.textContent = restants.length
      ? plural("ui.touches.rac.autres_n", restants.length)
      : t("ui.touches.rac.autres_toutes");
  }
  // ⚠️ Une grille vide doit DIRE pourquoi. Vide + silencieuse, on croit à une
  //    panne — signalé deux fois.
  if (!restants.length && !Object.keys(keys).length) {
    el.innerHTML = tHtml("ui.touches.rac.aucun");
  }
}

async function renumeroterRangee() {
  const r = await api("/api/bouton/rangee", {
    rangee: +document.getElementById("btnRangee").value,
    base:   +document.getElementById("btnBase").value});
  document.getElementById("btnRangMsg").textContent =
    plural("ui.touches.renum.msg", r.n || 0);
  loadProfile();
}

// ── Raccourcis clavier : app → grandMA3 ────────────────────────────────────
// L'état est RELU après chaque envoi : le libellé du bouton dit toujours la
// vérité du moment, pas ce qu'on espérait obtenir.
//
// `btnId`/`txtId` : PARAMÉTRÉS (19/09/2026) pour être appelables aussi bien
// depuis l'onglet Touches (#btnShcuts/#shcutsEtat, valeurs par défaut) que
// depuis l'Étape D du wizard (#btnShcutsWizard/#shcutsEtapeEtat, voir
// shcutsEnvoyerWizard(), ui/parametres.js). 🐛 Avant : ces ids étaient EN DUR
// — appelée depuis le wizard, la fonction écrivait bien dans MA3, mais tout
// son retour (« envoi… », succès, collision, échec) atterrissait dans
// #shcutsEtat, un élément de l'onglet Touches invisible depuis Paramètres. Le
// bouton du wizard semblait ne rien faire alors que l'appel avait eu lieu.
async function shcutsRafraichir(btnId = "btnShcuts", txtId = "shcutsEtat") {
  const z = document.getElementById(txtId);
  const b = document.getElementById(btnId);
  let d;
  try { d = await (await fetch("/api/shcuts")).json(); }
  catch (e) { z.textContent = t("ui.touches.rac.etat_indispo"); return; }
  if (!d.possible) { z.textContent = d.erreur || t("ui.touches.rac.ma3_absent");   // TODO i18n Phase 2 : d.erreur (API)
                     b.disabled = true; return; }
  b.disabled = false;
  // Les touches volontairement NON poussées sont TOUJOURS annoncées. Une
  // exclusion muette a déjà piégé : « Assign » modifié à la main n'était pas
  // envoyé, et le bouton affichait « déjà d'accord ».
  const hors = (d.ecartees || []).length
    ? tHtml("ui.touches.rac.hors_html", { liste:
        d.ecartees.map(e => e.touche + " (" + e.frappe + ")").join(", ") })
    : "";
  // ⚠️ LA COLLISION PASSE AVANT TOUT : c'est le cas qui trompe le plus. Une
  // frappe déjà prise par une autre touche de MA3 ne fait pas « rien » — elle
  // déclenche L'AUTRE fonction, et on croit à une panne de la wing. Vécu :
  // Assign mis sur Ctrl+Alt+F, déjà attribué à SelectFixtures.
  if ((d.collisions || []).length) {
    z.innerHTML = tHtml("ui.touches.rac.collision_msg", {
      n: d.collisions.length,
      // brut() : la liste est du HTML déjà construit (et échappé) par tHtml.
      liste: brut(d.collisions.map(c => tHtml("ui.touches.rac.collision_item", {
        touche: c.touche, frappe: c.frappe,
        occupee: c.occupee_par.join(", ") })).join(" · ")),
    }) + hors;
    return;
  }
  // 🎯 LA PREUVE : la sonde tourne DANS MA3. Si elle dit que la console tient
  // autre chose que ce qu'on lui a envoyé, on le sait — c'est exactement la
  // panne déjà vécue, où l'app annonçait le succès en relisant son propre
  // fichier pendant que MA3 gardait l'ancienne valeur.
  if ((d.non_applique || []).length) {
    z.innerHTML = tHtml("ui.touches.rac.non_applique_msg", {
      n: d.non_applique.length,
      liste: brut(d.non_applique.slice(0, 6).map(x =>
        tHtml("ui.touches.rac.non_applique_item",
              { touche: x.touche, dans_ma3: x.dans_ma3, voulu: x.voulu })
      ).join(", ")),
    }) + hors;
    return;
  }
  if (d.a_jour) {
    // ⚠️ Deux formulations, parce que les deux situations ne se valent pas :
    // avec la sonde on PROUVE, sans elle on ne fait que relire le fichier que
    // l'app a écrit elle-même. Ne jamais présenter le second comme le premier.
    z.innerHTML = d.sonde
      ? tHtml("ui.touches.rac.confirme_sonde", { confirmes: d.confirmes })
      : tHtml("ui.touches.rac.rien_a_envoyer", {
          geres: d.geres, intacts: d.intacts,
          osc_suffix: brut((d.osc && d.osc !== "ok")
            ? tHtml("ui.touches.rac.osc_muet_suffix") : ""),
        });
    z.innerHTML += hors;
  } else if (!d.actif) {
    z.innerHTML = tHtml("ui.touches.rac.desactivee");
  } else {
    z.innerHTML = tHtml("ui.touches.rac.ecarts_msg", {
      n: d.ecarts.length,
      liste: brut(d.ecarts.slice(0, 6).map(e => tHtml("ui.touches.rac.ecart_item",
        { touche: e.touche, ma3: e.ma3 || "—", app: e.app })).join(", ")),
      suite: d.ecarts.length > 6 ? "…" : "",
    }) + hors;
  }
}

// `btnId`/`txtId` : voir le commentaire de shcutsRafraichir() ci-dessus —
// même motif, mêmes deux appelants.
async function shcutsEnvoyer(btnId = "btnShcuts", txtId = "shcutsEtat") {
  const b = document.getElementById(btnId);
  const z = document.getElementById(txtId);
  b.disabled = true;
  z.textContent = t("ui.touches.rac.envoi");
  let r = null;
  try { r = await api("/api/shcuts/envoyer", {}); }
  finally { b.disabled = false; }
  // On RELIT l'état avant d'annoncer quoi que ce soit : le message dit ce qui
  // est, pas ce qu'on espérait. (Règle du projet : jamais de « ✓ envoyé »
  // sans avoir vérifié.)
  await shcutsRafraichir(btnId, txtId);
  if (!r || !r.ok) {
    z.innerHTML = tHtml("ui.touches.rac.echec",
                        { erreur: (r && r.erreur) || "?" });
    return;
  }
  if (r.inchange) {
    z.innerHTML = t("ui.touches.rac.rien_a_faire") + z.innerHTML;
    return;
  }
  const n = (r.commandes || []).length;
  const muet = r.etat && r.etat.osc && r.etat.osc !== "ok";
  if (muet) {
    z.innerHTML = tHtml("ui.touches.rac.envoi_muet", { n }) + z.innerHTML;
    return;
  }
  // ⚠️ On attend que la SONDE confirme dans MA3 plutôt que d'annoncer un
  //    succès qu'on ne peut pas constater. Un « ✓ envoyé » mensonger a coûté
  //    des heures, trois fois. → docs/GRANDMA3_SYNC.md#les-raccourcis-attendre-la-preuve-de-la-sonde-ne-pas-annoncer-un-succes
  b.disabled = true;
  // 🐛 Un `non_applique` VU pendant l'attente n'est PAS un échec : MA3 applique
  // les commandes espacées de 0,15 s et la sonde relit ensuite. Conclure au
  // premier tick laissait « ⛔ MA3 N'A PAS APPLIQUÉ » affiché pour un envoi
  // qui avait pris (constaté en test réel, 3 touches). On n'affirme l'échec
  // qu'une fois le délai écoulé, et sur ce que la sonde dit ALORS.
  let refuse = false;
  try {
    for (let essai = 0; essai < 10; essai++) {          // ~5 s
      await new Promise(res => setTimeout(res, 500));
      const d = await (await fetch("/api/shcuts")).json();
      if (!d.sonde) continue;
      refuse = (d.non_applique || []).length > 0;
      if (d.a_jour) {
        z.innerHTML = tHtml("ui.touches.rac.applique_verifie",
                            { n, confirmes: d.confirmes });
        return;
      }
    }
  } finally { b.disabled = false; }
  await shcutsRafraichir(btnId, txtId);
  if (refuse) return;      // le ⛔ « MA3 n'a pas appliqué » est déjà peint
  z.innerHTML = tHtml("ui.touches.rac.non_verifie", { n }) + z.innerHTML;
}

// Formate l'horodate (epoch, secondes) du dernier ENVOI réussi de
// shcuts_envoyer() en « à l'instant / il y a X / jamais envoyés ». Partagé
// entre #shcutsHorodate (onglet Touches, ci-dessous) et #shcutsEtapeEtat
// (étape « Envoie les raccourcis » de l'assistant, ui/parametres.js) : UN
// SEUL calcul, deux affichages — ils ne doivent jamais pouvoir diverger.
function formatHorodateRelatif(epoch) {
  if (!epoch) return t("ui.touches.rac.horodate_jamais");
  const s = Math.max(0, Math.floor(Date.now() / 1000 - epoch));
  if (s < 60) return t("ui.touches.rac.horodate_instant");
  const min = Math.floor(s / 60);
  if (min < 60) return plural("ui.touches.rac.horodate_min", min);
  const h = Math.floor(min / 60);
  if (h < 24) return plural("ui.touches.rac.horodate_h", h);
  const j = Math.floor(h / 24);
  return plural("ui.touches.rac.horodate_j", j);
}

// Appelée par poll() (bridge.js → majParametresGma3, ui/parametres.js) à
// CHAQUE tick (400 ms) : contrairement à #shcutsEtat (repeint seulement par
// shcutsRafraichir(), au chargement ou après un clic), cette ligne doit
// AVANCER TOUTE SEULE — « il y a 2 min » devenir « il y a 3 min » sans action
// de l'utilisateur.
function majShcutsHorodate(s) {
  const el = document.getElementById("shcutsHorodate");
  if (!el) return;
  const h = s && s.shcuts_horodate;
  el.textContent = formatHorodateRelatif(h);
  el.style.color = h ? "" : "var(--accent)";
}
