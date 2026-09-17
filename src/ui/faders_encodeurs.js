/* ui/faders_encodeurs.js — onglets Faders et Encodeurs : entrées CONTINUES (cf. docs/FADERS_ENCODERS.md)
   ─────────────────────────────────────────────────────────────
   Sorti de wing_ui.js lors du découpage du JS par onglet.
   ⚠️ PORTÉE GLOBALE : ces fichiers sont des <script> CLASSIQUES,
      jamais des modules ES — une quarantaine de gestionnaires
      inline du balisage (onclick=…) en dépendent.
   ⚠️ ORDRE DE CHARGEMENT IMPOSÉ : core en premier, init en
      dernier. Voir l'ordre des <script defer> dans wing_ui.html. */

async function remplirRangee() {
  const depuis = +document.getElementById("rangDepuis").value;
  const base   = +document.getElementById("rangBase").value;
  const r = await api("/api/fader/rangee", {depuis: depuis, base: base});
  document.getElementById("rangMsg").textContent =
    plural("ui.faders.rang.msg", r.n || 0);
  loadProfile();
}

async function saveFaderPickup() {
  await api("/api/fader_pickup",
            {actif: document.getElementById("faderPickup").checked});
}

async function saveVerbeCible() {
  await api("/api/verbe_cible",
            {actif: document.getElementById("verbeCible").checked});
}

function highlightFader(i) {
  hlFader = i;
  document.querySelectorAll(".fader-item").forEach(x => x.classList.remove("hl"));
  const el = document.getElementById("fader-" + i);
  if (el) el.classList.add("hl");
  clearTimeout(hlTimer);
  hlTimer = setTimeout(() => {
    hlFader = -1;
    if (el) el.classList.remove("hl");
  }, 4000);
}

// ── Types de fader ────────────────────────────────────────────────────
// Les 8 fonctions de fader d'executor viennent du manuel MA3 installé
// (pages keyword_fader*.html). Wing Bridge les offre toutes ; la coche
// dit que le mot-clé est confirmé par le manuel présent sur CETTE machine.
async function loadFaderFuncs() {
  let d;
  try { d = await (await fetch("/api/fader/functions")).json(); }
  catch (e) { return; }

  let html = "<table class='fftab'><tr><th>" + t("ui.faders.types.th_type")
             + "</th><th>" + t("ui.faders.types.th_motcle")
             + "</th><th>" + t("ui.faders.types.th_cmd") + "</th><th></th></tr>";
  d.fonctions.forEach(f => {
    const coche = (f.confirme === true) ? tHtml("ui.faders.types.coche") : "";
    const mot = f.motcle
      ? "<code>" + esc(f.motcle) + "</code>" +
        (f.court ? " <span class='muted'>(" + esc(f.court) + ")</span>" : "")
      : "<span class='muted'>" + t("ui.faders.types.pas_executor") + "</span>";
    html += "<tr><td><b>" + esc(f.libelle) + "</b><div class='muted'>" + esc(f.desc) +
            "</div></td><td>" + mot + "</td><td><code>" + esc(f.cmd) +
            "</code></td><td>" + coche + "</td></tr>";
  });
  html += "</table>";
  document.getElementById("ffList").innerHTML = html;

  const src = document.getElementById("ffSrc");
  const note = document.getElementById("ffNote");
  if (d.source === "ma3") {
    src.textContent = d.version
      ? t("ui.faders.types.src_ma3_v", { v: d.version })
      : t("ui.faders.types.src_ma3");
    note.innerHTML = tHtml("ui.faders.types.note_ma3")
      + (d.manquants && d.manquants.length
          ? tHtml("ui.faders.types.note_manquants", { liste: d.manquants.join(", ") })
          : "");
  } else {
    src.textContent = "";
    note.innerHTML = tHtml("ui.faders.types.note_absent");
  }
}

// ── Répertoire des attributs MA3 ──────────────────────────────────────
// La liste vient du MA3 installé (attribute_definitions.xml) — pas d'une
// copie figée dans l'app, qui vieillirait à chaque version de MA3.
// Elle sert à trois choses : autocomplétion des cases, répertoire cliquable,
// et signalement d'un nom inexistant. Voir le bug « Focus » (docs/FADERS_ENCODERS.md).
let ATTRS = null;          // réponse de /api/attributes
let ATTRSET = null;        // Set des noms valides, ou null si liste de repli
let encFocus = null;       // dernière case de roue touchée

// ── Répertoire des mots-clés de commande MA3 ──────────────────────────
// Alimente la liste proposée sous le champ d'assignation. La casse est de
// toute façon corrigée à l'enregistrement côté serveur : cette liste sert à
// ne pas avoir à deviner les mots, pas à se protéger d'une faute de frappe.
async function loadKeywords() {
  let d;
  try { d = await (await fetch("/api/keywords")).json(); }
  catch (e) { return; }
  const dl = document.getElementById("cmdOptions");
  // esc() : ces noms sont lus dans les fichiers de MA3, pas écrits par nous.
  if (dl) dl.innerHTML = d.mots.map(m => "<option value='" + esc(m) + "'>").join("");
}

async function loadAttrs() {
  try {
    const r = await fetch("/api/attributes");
    ATTRS = await r.json();
  } catch (e) { return; }
  const noms = [];
  ATTRS.groupes.forEach(([g, liste]) => liste.forEach(n => noms.push(n)));

  // Autocomplétion native des cases de roue
  const dl = document.getElementById("attrOptions");
  if (dl) dl.innerHTML = noms.map(n => "<option value='" + esc(n) + "'>").join("");

  // ⚠️ On ne signale un nom « inconnu » QUE si la liste vient vraiment de
  // MA3. Avec la liste de repli (MA3 absent de cette machine), un nom
  // parfaitement valide serait marqué en rouge à tort — une alerte fausse
  // coûte plus cher que pas d'alerte du tout.
  ATTRSET = (ATTRS.source === "ma3") ? new Set(noms) : null;

  const src = document.getElementById("attrSrc");
  const path = document.getElementById("attrPath");
  if (ATTRS.source === "ma3") {
    src.textContent = t("ui.encodeurs.attrs.src_ma3");
    // Idem : on nomme la source, jamais le chemin (nom de compte).
    path.textContent = t("ui.encodeurs.attrs.path_ma3");
  } else {
    src.textContent = t("ui.encodeurs.attrs.src_reduite");
    path.innerHTML = tHtml("ui.encodeurs.attrs.path_absent");
  }
  renderAttrs();
  document.querySelectorAll("#encGroups input").forEach(markAttr);
}

function markAttr(inp) {
  const v = (inp.value || "").trim();
  inp.classList.toggle("bad", !!(v && ATTRSET && !ATTRSET.has(v)));
}

function renderAttrs() {
  const box = document.getElementById("attrList");
  if (!box || !ATTRS) return;
  const q = (document.getElementById("attrFind").value || "").trim().toLowerCase();
  let html = "", vus = 0;
  ATTRS.groupes.forEach(([grp, liste]) => {
    const gardes = q ? liste.filter(n => n.toLowerCase().includes(q)) : liste;
    if (!gardes.length) return;
    vus += gardes.length;
    html += "<div class='attrgrp'><div class='gtitle'>" + esc(grp) + "</div><div class='attrchips'>";
    gardes.forEach(n => {
      html += "<button type='button' onclick='pickAttr(this)'>" + esc(n) + "</button>";
    });
    html += "</div></div>";
  });
  box.innerHTML = html || tHtml("ui.encodeurs.attr_aucun");
  document.getElementById("attrCount").textContent =
    plural("ui.encodeurs.attr_count", vus, { total: ATTRS.total });
}

function pickAttr(btn) {
  const nom = btn.textContent;
  // Cible : la dernière case touchée, sinon la 1re case vide, sinon rien.
  let cible = encFocus;
  if (!cible || !document.body.contains(cible)) {
    cible = [...document.querySelectorAll("#encGroups input")]
              .find(x => !x.value.trim()) || null;
  }
  const hint = document.getElementById("attrHint");
  if (!cible) {
    hint.innerHTML = tHtml("ui.encodeurs.hint_pleines");
    return;
  }
  cible.value = nom;
  markAttr(cible);
  encFocus = cible;
  cible.focus();
  hint.innerHTML = tHtml("ui.encodeurs.hint_place", {
    nom: nom, groupe: +cible.dataset.g + 1, roue: +cible.dataset.i + 1 });
}

// ── Encodeurs save ────────────────────────────────────────────────────
// 🐛 Signalé : « j'ai mis Pan en roue 1, en testant
// j'ai toujours Dimmer » — et « du moment où on fait une modif, je dois pouvoir
// l'enregistrer dans le profil, ce n'est pas le cas ».
//
// LES DEUX SYMPTÔMES AVAIENT LA MÊME CAUSE : les cases de cet onglet n'étaient
// câblées que sur `focus` et `input` (le marqueur de nom invalide). Rien ne
// partait vers le serveur tant qu'on n'avait pas cliqué un bouton
// « Enregistrer » PROPRE À CET ONGLET — différent de celui de l'en-tête, qui
// enregistre le profil. On éditait, on cliquait celui de l'en-tête, et on
// sauvegardait un profil qui n'avait jamais reçu la modification.
//
// ⚠️ Les faders, eux, appliquent au changement (`el.onchange = send`) depuis
// toujours. Deux onglets qui se ressemblent ne doivent pas se comporter
// différemment : c'est ça qui a piégé.
//
// → docs/FADERS_ENCODERS.md#editer-un-groupe-doit-s-appliquer-tout-de-suite
async function appliquerEncodeurs() {
  // Pas de taille figée (4 groupes → 8) : construit
  // à partir des cases réellement affichées, quel que soit leur nombre.
  const groups = [];
  document.querySelectorAll("#encGroups input").forEach(inp => {
    const gi = +inp.dataset.g;
    if (!groups[gi]) groups[gi] = [];
    groups[gi][+inp.dataset.i] = inp.value.trim() || null;
  });
  await api("/api/encoders", {
    groups: groups,
    default: +document.getElementById("encDefault").value,
    step: +document.getElementById("encStep").value
  });
  // ⚠️ PAS de loadProfile() ici : il re-rendrait les cases pendant la saisie et
  // ferait perdre le focus au champ qu'on vient de quitter.
}
