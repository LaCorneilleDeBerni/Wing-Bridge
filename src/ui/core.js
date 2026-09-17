/* ui/core.js — socle : globales, api(), setHealth(), onglets, aides repliables
   ─────────────────────────────────────────────────────────────
   Sorti de wing_ui.js lors du découpage du JS par onglet.
   ⚠️ PORTÉE GLOBALE : ces fichiers sont des <script> CLASSIQUES,
      jamais des modules ES — une quarantaine de gestionnaires
      inline du balisage (onclick=…) en dépendent.
   ⚠️ ORDRE DE CHARGEMENT IMPOSÉ : core en premier, init en
      dernier. Voir l'ordre des <script defer> dans wing_ui.html. */

let profile = null;
let currentMode = "idle";
let hlFader = -1, hlTimer = null;

// Fermeture volontaire (quitApp / hardReset) : ne PAS re-déclencher le dialogue
// « voulez-vous fermer ? » ni le beacon d'extinction pendant qu'on quitte ou
// qu'on relance nous-mêmes. Voir les écouteurs beforeunload/pagehide (ui/init.js).
let arretVolontaire = false;

// ── Tabs ──────────────────────────────────────────────────────────────
document.querySelectorAll("nav button").forEach(b => {
  b.onclick = () => {
    document.querySelectorAll("nav button").forEach(x => x.classList.remove("active"));
    document.querySelectorAll("main section").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    document.getElementById("tab-" + b.dataset.tab).classList.add("active");
    // Onglet Profils : on DÉSIGNE le profil actif dans l'en-tête plutôt que de
    // le réafficher dans un encart. Trois pulsations, puis plus rien.
    if (b.dataset.tab === "profils") {
      const p = document.getElementById("profTxt");
      if (p) { p.classList.remove("designe");
               void p.offsetWidth;          // relance l'animation
               p.classList.add("designe"); }
    }
  };
});

// ── Radio type ────────────────────────────────────────────────────────
document.querySelectorAll("#typeRow label").forEach(l => {
  l.onclick = () => {
    document.querySelectorAll("#typeRow label").forEach(x => x.classList.remove("sel"));
    l.classList.add("sel");
    const ph = {
      cmd:   t("ui.touches.assign.ph_cmd"),
      exec:  t("ui.touches.assign.ph_exec"),
      push:  t("ui.touches.assign.ph_push"),
      clear: t("ui.touches.assign.ph_clear")
    };
    document.getElementById("assignVal").placeholder = ph[l.dataset.v];
    document.getElementById("assignFunc").style.display = (l.dataset.v === "exec") ? "" : "none";
  };
});
function selectedType() {
  return document.querySelector("#typeRow label.sel").dataset.v;
}

// ── API helpers ───────────────────────────────────────────────────────
// 🔒 JETON D'API (audit du 25/09/2026). Le serveur exige sur tout POST le
// jeton de ce lancement, qu'il injecte dans la page (<meta name="wing-jeton">,
// wing_handler._get_page). Toute écriture passe par api() — ou joint le jeton
// elle-même (sendBeacon, ui/init.js). Contrôle test_jeton_api.
function jetonApi() {
  try {
    const m = document.querySelector('meta[name="wing-jeton"]');
    const v = m && m.content;
    return (typeof v === "string") ? v : "";
  } catch (e) { return ""; }
}
async function api(path, body) {
  const entetes = {"X-Wing-Jeton": jetonApi()};
  const opt = body
    ? {method:"POST", headers:Object.assign({"Content-Type":"application/json"}, entetes),
       body: JSON.stringify(body)}
    : {headers: entetes};
  const r = await fetch(path, opt);
  const d = await r.json();
  // Paramètre refusé par le moteur (wing_validation) : la raison est aussi
  // dans le journal de l'onglet Bridge. Ici, pour qui ouvre la console.
  if (r.status === 400 && d && d.detail) console.warn(path + " : " + d.detail);
  // L'app a été RELANCÉE depuis l'ouverture de cet onglet : son jeton est
  // périmé et chaque clic serait refusé en silence. On recharge la page (qui
  // apporte le jeton neuf) — au plus une fois toutes les 10 s, pour qu'un
  // refus persistant ne se transforme jamais en boucle de rechargements.
  if (r.status === 403 && d && d.error === "jeton invalide") {
    try {
      const avant = +(sessionStorage.getItem("wingRechargeJeton") || 0);
      if (Date.now() - avant > 10000) {
        sessionStorage.setItem("wingRechargeJeton", String(Date.now()));
        location.reload();
      }
    } catch (e) { /* stockage indisponible : on laisse l'erreur remonter */ }
  }
  return d;
}

// ── Panneau santé : met à jour une pastille (cls: on|warn|off|"") ──────
// Met à jour une pastille de la barre d'états.
//
// ⚠️ C'EST ICI QUE SE DÉCIDE LE DÉFILEMENT, et nulle part ailleurs : le CSS ne
// sait pas si un texte déborde, seul le DOM le sait (scrollWidth vs
// clientWidth). On ne fait donc défiler QUE ce qui dépasse réellement — une
// animation permanente sur un message court serait du mouvement pour rien,
// et en régie ça fatigue l'œil pour rien.
function setHealth(id, cls, val) {
  const el = document.getElementById(id);
  if (!el) return;
  el.querySelector(".hdot").className = "hdot" + (cls ? " " + cls : "");
  const zone  = el.querySelector(".hzone");
  const piste = el.querySelector(".hdefile");
  if (!zone || !piste) return;
  const [texte, copie] = piste.children;
  if (texte.textContent === val) return;

  // ⚠️⚠️ NE PAS RELANCER L'ANIMATION QUAND SEUL UN NOMBRE A CHANGÉ.
  //
  // 🐛 La 1re version repartait de zéro dès que le texte différait.
  // Or les messages qui ont besoin de défiler sont justement ceux qui portent
  // un compteur VIVANT — « sonde silencieuse depuis 445 s — le plugin MA3
  // est-il lancé ? » change chaque seconde. L'animation redémarrait donc une
  // fois par seconde : à l'écran, ça saute d'un message à l'autre en décalé.
  //
  // 🔑 On compare une CLÉ DE MISE EN PAGE — le message avec ses nombres
  // neutralisés. Même clé = même forme = on remplace le texte sans toucher à
  // l'animation, qui garde sa phase. Clé différente = vrai changement de
  // message, on recalcule.
  const cle = val.replace(/\d+/g, "#");
  texte.textContent = val;
  texte.title = val;
  if (zone.dataset.cle === cle) {
    if (zone.classList.contains("defile")) copie.textContent = val;
    return;
  }
  zone.dataset.cle = cle;
  copie.textContent = "";
  zone.classList.remove("defile");
  zone.style.removeProperty("--duree");

  requestAnimationFrame(() => {
    if (texte.scrollWidth <= zone.clientWidth + 4) return;   // ça tient
    // ⚠️ La durée est posée AVANT la classe : changer `animation-duration` sur
    //    une animation qui tourne déjà provoque une rupture visible.
    const largeur = texte.scrollWidth + 46;     // une copie, espace compris
    zone.style.setProperty("--duree",
                           Math.max(8, largeur / 55).toFixed(1) + "s");
    copie.textContent = val;                    // la 2e copie ferme la boucle
    zone.classList.add("defile");
  });
}
// ── Cible OSC (réglage machine, pas profil) ───────────────────────────
// Les champs ne sont remplis par poll() que si l'utilisateur n'est PAS en
// train de les éditer — sinon le rafraîchissement 400 ms écraserait sa saisie
// à chaque caractère tapé.
function oscFieldsBusy() {
  const a = document.activeElement;
  return a && (a.id === "oscIp" || a.id === "oscPort");
}

// ── Écoute OSC entrante : RETIRÉE DE L'INTERFACE ─────────────────────
// Les endpoints restent (outil de diagnostic, voir docs/GRANDMA3_SYNC.md) ;
// c'est seulement le panneau et son rafraîchissement qui disparaissent —
// personne ne le regardait, et un tableau qu'on rafraîchit pour rien coûte
// des requêtes à chaque tick.

// 🔒 Échappe TOUT ce qui peut sortir d'un texte ou d'un attribut HTML.
//
// 🐛 Faille : `'` et `"` n'étaient pas échappés, alors que esc() remplit des
// attributs entre apostrophes (`value='…'`). Un profil importé portant
// `' autofocus onfocus='…` dans un raccourci sortait de l'attribut et
// exécutait du JavaScript sur l'origine de l'app — donc avec le droit d'appeler
// toute l'API (le contrôle d'Origin ne voit rien : c'est notre propre page).
// Contrôle test_xss_profil_importe (smoke_securite.py).
function esc(s) {
  return String(s == null ? "" : s).replace(/&/g, "&amp;")
    .replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

// Marque un fragment HTML DÉJÀ construit (par tHtml) comme sûr, pour qu'il
// traverse un tHtml() englobant sans être échappé une seconde fois.
// ⚠️ Ne JAMAIS envelopper une donnée venue d'un profil, de MA3 ou d'un
// périphérique USB : seulement du HTML produit par tHtml() lui-même.
function brut(html) {
  return { __htmlSur: String(html == null ? "" : html) };
}

// ── Blocs d'aide repliables ───────────────────────────────────────────
// Repliés par défaut (l'écran reste dégagé en régie), mais si quelqu'un en
// ouvre un, il le retrouve ouvert au rechargement suivant. localStorage est
// entouré d'un try : en cas d'indisponibilité, les blocs marchent quand même,
// ils ne se souviennent simplement de rien.
function initHelp() {
  document.querySelectorAll("details.help[id]").forEach(d => {
    const k = "wingHelp:" + d.id;
    try { if (localStorage.getItem(k) === "1") d.open = true; } catch (e) {}
    d.addEventListener("toggle", () => {
      try { localStorage.setItem(k, d.open ? "1" : "0"); } catch (e) {}
    });
  });
}


// ── Fenêtre d'aide ───────────────────────────────────────────────────────────
//
// L'aide se DEMANDE, elle ne s'impose plus. Avant, 11 blocs <details> — dont 7
// dans le seul onglet Bridge — occupaient l'écran en permanence pour un texte
// qu'on lit une fois. Le contenu vit dans ui/aides.js, source unique partagée
// avec l'onglet Aide.
function aide(cle) {
  if (typeof AIDES_SUJETS === "undefined" || !AIDES_SUJETS.has(cle)) return;
  // rubrique inconnue : on n'invente pas
  document.getElementById("aideTitre").textContent = t("aide." + cle + ".titre");
  document.getElementById("aideCorps").innerHTML = tHtml("aide." + cle + ".html");
  document.getElementById("voileAide").classList.add("ouvert");
}

// Fermeture : bouton, clic sur le voile, ou Échap. Une fenêtre qu'on ne sait
// pas fermer vite est une fenêtre qui agace.
function fermerAide(ev) {
  if (ev && ev.target && ev.target.id !== "voileAide") return;
  document.getElementById("voileAide").classList.remove("ouvert");
}
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") fermerAide();
});


// ── La page Aide ─────────────────────────────────────────────────────────────
//
// Construite à partir de la MÊME source que les « ? » (ui/aides.js). Recopier
// les textes ici aurait garanti qu'ils divergent : c'est la classe de bug la
// plus chère de ce projet.
function construireAide() {
  const box = document.getElementById("aideSommaire");
  if (!box || typeof AIDES_PAR_ONGLET === "undefined") return;
  let html = "";
  AIDES_PAR_ONGLET.forEach(([ongletCle, cles]) => {
    html += "<div class='card'><h2>" + t(ongletCle) + "</h2>";
    cles.forEach(cle => {
      if (!AIDES_SUJETS.has(cle)) return;   // rubrique absente : on n'invente pas
      html += "<details class='help'><summary>" + t("aide." + cle + ".titre")
            + "</summary>"
            + "<div class='hbody corps'>" + tHtml("aide." + cle + ".html")
            + "</div></details>";
    });
    html += "</div>";
  });
  box.innerHTML = html;
}
