/* ui/bridge.js — onglet Bridge : poll() de l'état, santé OSC/MA3, quitter/réinitialiser
   ─────────────────────────────────────────────────────────────
   Sorti de wing_ui.js lors du découpage du JS par onglet.
   ⚠️ PORTÉE GLOBALE : ces fichiers sont des <script> CLASSIQUES,
      jamais des modules ES — une quarantaine de gestionnaires
      inline du balisage (onclick=…) en dépendent.
   ⚠️ ORDRE DE CHARGEMENT IMPOSÉ : core en premier, init en
      dernier. Voir l'ordre des <script defer> dans wing_ui.html. */

// ── Status polling ────────────────────────────────────────────────────
async function poll() {
  try {
    const s = await api("/api/status");
    currentMode = s.mode;

    // ── Panneau santé (état de la chaîne) ──
    // Cadence réelle de la boucle qui lit la wing. Affichée parce qu'elle
    // s'est révélée INSTABLE entre deux démarrages (30 Hz ou 2,8 Hz, cause non
    // élucidée) : mieux vaut pouvoir le constater d'un coup
    // d'œil que se demander si « ça rame ».
    const hz = (s.boucle && s.boucle.hz) ? t("ui.sante.bridge.hz", { hz: s.boucle.hz }) : "";
    const lent = s.boucle && s.boucle.hz && s.boucle.hz < 12;
    // Quand c'est lent, on dit CE QU'ON MESURE plutôt que « lent » tout court.
    // « 0 réponse » = la wing ne répond pas du tout (piste : interface USB non
    // revendiquée après un redémarrage) ; sinon elle répond, mais lentement.
    let detail = "";
    if (lent && s.boucle) {
      detail = plural("ui.sante.bridge.detail", s.boucle.vides, { ms: s.boucle.t_read });
      if (s.boucle.claim) detail += t("ui.sante.bridge.claim");
    }
    // 👁 Ce que la boucle avalait en silence avant l'audit du 25/09/2026 :
    // écritures DMX/LED refusées par la wing, tours abandonnés sur erreur.
    // Affiché dès qu'il y en a — un compteur qu'on ne voit pas ne sert à rien.
    if (s.boucle && s.boucle.ecritures_ko > 0) {
      detail += plural("ui.sante.bridge.ecritures_ko", s.boucle.ecritures_ko,
                       { err: s.boucle.ecriture_err || "?" });
    }
    if (s.boucle && s.boucle.erreurs_tour > 0) {
      detail += plural("ui.sante.bridge.erreurs_tour", s.boucle.erreurs_tour);
    }
    // ⚠️ PRIORITAIRE sur tout le reste de la pastille : un thread mort ne se
    // corrige JAMAIS tout seul, contrairement à « LENT » ou « apprentissage ».
    // Rouge fixe (cls: ""), volontairement distinct du orange clignotant
    // (« warn ») déjà utilisé pour muette/bootloader — un état qui peut
    // encore se rétablir seul ne doit pas ressembler à un qui ne le peut pas.
    const tm = s.thread_mort || {};
    if (tm.usb_loop) {
      setHealth("hBridge", "", t("ui.sante.bridge.usb_morte"));
    } else if (tm.dmx_listener) {
      setHealth("hBridge", "", t("ui.sante.bridge.dmx_morte"));
    } else if (s.mode === "bridge") {
      setHealth("hBridge", lent ? "warn" : "on",
                (lent ? t("ui.sante.bridge.lent") : t("ui.sante.bridge.actif")) + hz + detail);
    } else if (s.mode === "learn") {
      setHealth("hBridge", "warn", t("ui.sante.bridge.apprentissage") + hz + detail);
    } else {
      setHealth("hBridge", "off", t("ui.sante.bridge.arrete") + hz + detail);
    }
    // « connectée » et « qui parle » sont deux choses distinctes. Une wing
    // dont la poignée USB tient mais qui n'envoie plus un paquet passait pour
    // saine : pastille verte, zéro appui, aucune explication.
    // « suivreEncMa3 » de retour : cette fois `s.encodeurs_ma3` existe côté
    // serveur et la case pilote réellement.
    [["suivreMa3", s.suivre_ma3], ["faderPickup", s.fader_pickup],
     ["ledMa3", s.led_ma3], ["verbeCible", s.verbe_cible],
     ["suivreEncMa3", s.encodeurs_ma3]].forEach(([id, v]) => {
      if (v === undefined) return;
      const cb = document.getElementById(id);
      if (cb && document.activeElement !== cb) cb.checked = !!v;
    });
    // ⚠️ ISOLÉ : l'affichage des encodeurs est une info secondaire. S'il
    // plante (champ renommé, forme inattendue), il ne doit JAMAIS emporter le
    // header ni les pastilles — c'est déjà arrivé.
    try { majEncMa3(s.encodeurs); } catch (err) {
      console.warn("majEncMa3:", err);
    }
    // Firmware pas configuré : la wing ne peut pas démarrer. On le dit DANS la
    // pastille « Wing USB » — c'est là qu'on cherche pourquoi elle ne répond
    // pas. Le message défile (setHealth) et le bandeau de l'onglet Bridge
    // (majFirmware) reste le renvoi cliquable.
    const fwManque = s.firmware && s.firmware.configure === false;
    if (s.wing_replug) {
      // ⚠️ UN SEUL GESTE, physique, sans théorie ni script : seule une coupure
      //    d'alimentation sort la wing de son bootloader (reset de port USB
      //    inefficace, vérifié). Le pourquoi va dans le journal, pas ici.
      //    → docs/GRANDMA3_SYNC.md#la-pastille-bootloader-un-seul-geste-pas-de-theorie
      setHealth("hWing", "warn", t("ui.sante.wing.bootloader"));
    } else if (s.wing && s.wing_muette) {
      setHealth("hWing", "warn",
        t("ui.sante.wing.muette")
        + (s.wing_erreur ? " (" + s.wing_erreur + ")" : ""));
    } else if (fwManque) {
      setHealth("hWing", "warn", t("ui.sante.wing.fw_manque"));
    } else {
      setHealth("hWing",
                s.wing ? "on" : ((s.connecting || s.want) ? "warn" : ""),
                s.wing ? t("ui.sante.wing.connectee")
                       : (s.connecting ? t("ui.sante.wing.connexion")
                                       : (s.want ? t("ui.sante.wing.reconnexion") : t("ui.sante.wing.deconnectee"))));
    }
    // Le plugin (sonde Lua) est une étape d'installation REQUISE : sans lui,
    // l'app envoie l'OSC à l'aveugle (pas de retour LED, pas de pickup).
    // CINQ situations, à partir de trois signaux : MA3 joignable ?
    // s.sonde.present (fichiers .lua posés dans le pool MA3, cf. plugin_present —
    // lisible même MA3 éteint) ? sonde qui tourne ?
    //   1. sonde active                       → verte, « plugin actif — N exec. »
    //   2. MA3 joignable + fichiers là        → ambre, « plugin inactif —
    //      relance-le dans grandMA3 » (alerte défilante ; on ne cite PAS de
    //      numéro de slot, il varie selon l'installation)
    //   3. MA3 joignable + fichiers absents   → ambre, « plugin non installé —
    //      Paramètres → 🎛️ » : l'alerte d'install, ici et nulle part ailleurs
    //      (décision auteur : pas dans le paramétrage)
    //   4. MA3 éteint + fichiers là           → neutre, « plugin installé —
    //      grandMA3 éteint » (pas d'alerte : rien à faire tant que MA3 est fermé)
    //   5. MA3 éteint + fichiers absents      → neutre, « plugin non installé —
    //      grandMA3 éteint » (pas d'alerte : l'install a besoin de MA3 lancé)
    const oscR = s.osc && s.osc.reachable;
    const ma3La = (oscR === "ok" || oscR === "muet");
    const pluginLa = !!(s.sonde && s.sonde.present);
    if (s.sonde && s.sonde.actif) {
      const err = s.sonde.erreurs || 0;
      setHealth("hSonde", "on",
        plural("ui.sante.sonde.actif", s.sonde.executors || 0)
        + (s.sonde.page ? t("ui.sante.sonde.page", { page: s.sonde.page }) : "")
        + (s.sonde.duree_ms != null ? t("ui.sante.sonde.duree", { ms: s.sonde.duree_ms }) : "")
        + (err ? plural("ui.sante.sonde.erreurs", err) : ""));
    } else if (ma3La && pluginLa) {
      setHealth("hSonde", "warn", t("ui.sante.sonde.inactif"));
    } else if (ma3La) {
      setHealth("hSonde", "warn", t("ui.sante.sonde.non_installe"));
    } else if (pluginLa) {
      setHealth("hSonde", "", t("ui.sante.sonde.installe_eteint"));
    } else {
      setHealth("hSonde", "", t("ui.sante.sonde.non_installe_eteint"));
    }
    // « MA3 lancé » et « MA3 écoute l'OSC » sont deux choses distinctes :
    // l'état "muet" (lancé mais port fermé) a déjà causé une panne où tout
    // semblait normal. Le message doit dire quoi faire, pas juste alerter.
    if (s.osc.reachable === "ok")        setHealth("hOsc", "on",  t("ui.sante.osc.detecte"));
    else if (s.osc.reachable === "muet") setHealth("hOsc", "warn",
        t("ui.sante.osc.muet", { port: s.osc.port }) + oscPourquoi(s));
    else if (s.osc.reachable === "off")  setHealth("hOsc", "",    t("ui.sante.osc.absent"));
    else                                 setHealth("hOsc", "off", t("ui.sante.osc.distant", { cible: s.osc.target }));
    if (!oscFieldsBusy()) {
      document.getElementById("oscIp").value = s.osc.target;
      document.getElementById("oscPort").value = s.osc.port;
    }
    if (!s.console.enabled)                                     setHealth("hKbd", "off",  t("ui.sante.kbd.desactive"));
    else if (s.console.connected && s.console.trusted)          setHealth("hKbd", "on",   t("ui.sante.kbd.pret"));
    else if (s.console.connected)                              setHealth("hKbd", "warn", t("ui.sante.kbd.a_autoriser"));
    else                                                       setHealth("hKbd", "warn", t("ui.sante.kbd.absent"));

    // ── Numéro de build ──
    // Forme compacte « b43c30 » : b = moteur, c = assistant clavier. Les deux
    // sont buildés séparément, donc les deux doivent être lisibles d'un coup
    // d'œil pour comparer deux machines. En ambre quand ils diffèrent — ce
    // n'est pas une erreur (un build serveur seul ne touche pas l'assistant),
    // mais ça doit se voir.
    if (s.build) {
      const bt = document.getElementById("buildTag");
      const kb = s.build.keyboard;
      const ecart = kb && kb !== s.build.server;
      bt.textContent = "b" + s.build.server + (kb ? "c" + kb : "");
      bt.style.color = ecart ? "var(--accent)" : "";
      bt.title = t("ui.entete.build_titre", { srv: s.build.server, date: s.build.date })
        + (kb ? t("ui.entete.build_kbd", { kb: kb }) : "")
        + (ecart ? t("ui.entete.build_ecart") : "");
    }

    // Bandeau de récupération (absent en fonctionnement normal)
    const rb = document.getElementById("recoveryBar");
    if (s.recovery) {
      rb.style.display = "";
      document.getElementById("recoveryTxt").textContent =
        t("ui.bridge.recuperation.txt", {
          nom: s.recovery.name,
          quand: (s.recovery.when || "?").replace("T", " à "),
        });
    } else {
      rb.style.display = "none";
    }

    // ── Firmware configuré ? ── ISOLÉ dans son try : si l'affichage firmware
    // plante, il ne doit JAMAIS emporter le header ni les pastilles (même
    // principe que majEncMa3). majFirmware vit dans parametres.js.
    try { if (typeof majFirmware === "function") majFirmware(s.firmware); }
    catch (err) { console.warn("majFirmware:", err); }

    // Capture intégrée du firmware (Windows) — même principe d'isolation.
    try { if (typeof majCapture === "function") majCapture(s.capture); }
    catch (err) { console.warn("majCapture:", err); }

    // Onglet Paramètres, carte grandMA3 : pastilles OSC / sonde + procédure
    // d'installation du plugin. Isolé de la même façon. majParametresGma3
    // vit dans parametres.js.
    try { if (typeof majParametresGma3 === "function") majParametresGma3(s); }
    catch (err) { console.warn("majParametresGma3:", err); }

    // Onglet Touches : ligne « raccourcis envoyés il y a X » (#shcutsHorodate),
    // séparée de #shcutsEtat (repeint seulement par shcutsRafraichir(), pas à
    // chaque poll) pour qu'elle avance toute seule. majShcutsHorodate vit dans
    // ui/touches.js.
    try { if (typeof majShcutsHorodate === "function") majShcutsHorodate(s); }
    catch (err) { console.warn("majShcutsHorodate:", err); }

    // Un seul bouton, dont le LIBELLÉ suit l'état — au lieu de trois boutons
    // dont deux ne s'affichaient jamais ensemble.
    document.getElementById("wingBtn").textContent =
      s.wing ? t("ui.bridge.wing.reconnecter") : t("ui.bridge.wing.connecter");

    document.getElementById("profTxt").textContent = s.profile;
    // Indicateur "modifié" + mise en avant du bouton Enregistrer
    window._dirty = s.dirty;
    document.getElementById("dirtyDot").style.display = s.dirty ? "" : "none";
    const shb = document.getElementById("saveHdrBtn");
    shb.className = s.dirty ? "btn primary" : "btn";
    // Badge "dernière config sûre" (onglet Profils)
    const rw = document.getElementById("refWhen");
    if (rw && s.reference) rw.textContent = s.reference.when || t("ui.profils.ref_jamais");

    // ── État de la chaîne clavier — ce n'est plus un « mode »
    //
    // La bascule « Activer le mode console » a disparu. Démarrer
    // le bridge démarre tout. Ce bloc ne fait plus que RAPPORTER l'état, et
    // nommer précisément ce qui manque quand ça coince.
    // ── Le bandeau d'autorisation ne s'affiche QUE s'il y a quelque chose
    //    à faire. L'état permanent, lui, est dans la pastille « Clavier » de
    //    la barre du haut : l'afficher deux fois n'apprenait rien de plus et
    //    occupait un encart entier (dissous).
    const barre = document.getElementById("barreAccess");
    if (barre) {
      const aAutoriser = s.console.connected && !s.console.trusted;
      barre.style.display = aAutoriser ? "" : "none";
    }

    // ── Bouton Bridge ──────────────────────────────────────────────────────
    // TANT QU'AUCUNE WING N'EST LÀ et que le bridge n'est pas lancé, on garde le
    // libellé d'ACCUEIL du balisage : « ▶ Démarrer Wing Bridge », le nom du
    // produit (décision auteur). Comme c'est EXACTEMENT le texte statique du
    // HTML, le premier poll() n'en change pas la largeur → plus de pulsation au
    // F5. Il ne bascule qu'au premier vrai événement :
    //   • wing branchée, bridge pas encore lancé  → « ▶ Démarrer le bridge »
    //   • bridge en marche                        → « ⏹ Arrêter le bridge »
    // ⚠️ PAS `s.want` dans la condition : `want_connected` est l'intention
    // d'auto-reconnexion, TOUJOURS armée en fond dès le lancement de l'app —
    // ce n'est pas un événement utilisateur.
    const bb = document.getElementById("bridgeBtn");
    if (s.mode === "bridge") {
      bb.textContent = t("ui.bridge.bouton.arreter"); bb.className = "btn big danger";
    } else if (!s.wing) {
      bb.textContent = t("ui.bridge.bouton.demarrer_wing"); bb.className = "btn big green";
    } else {
      bb.textContent = t("ui.bridge.bouton.demarrer"); bb.className = "btn big green";
    }

    // Learn button
    const lb = document.getElementById("learnBtn");
    const lz = document.getElementById("learnZone");
    if (s.mode === "learn") {
      lb.textContent = t("ui.touches.bouton.apprentissage_arret");
      lz.classList.add("waiting");
    } else {
      lb.textContent = t("ui.touches.bouton.apprentissage");
      lz.classList.remove("waiting");
    }

    // Buffer + log
    const bufEl = document.getElementById("bufTxt");
    const bufLbl = bufEl.previousElementSibling;
    if (s.console.enabled) {
      bufLbl.textContent = t("ui.bridge.buf.label_console");
      bufEl.textContent = t("ui.bridge.buf.console_txt");
      bufEl.style.opacity = "0.6";
    } else {
      bufLbl.textContent = t("ui.bridge.buf.label_interne");
      bufEl.textContent = s.cmd_buf || "\u00a0";
      bufEl.style.opacity = "1";
    }
    const lb2 = document.getElementById("logbox");
    const atBottom = lb2.scrollTop + lb2.clientHeight >= lb2.scrollHeight - 30;
    lb2.textContent = s.log.join("\n");
    if (atBottom) lb2.scrollTop = lb2.scrollHeight;

    // Chemin réel du journal sur disque : dépend du mode de lancement
    // (sources vs app figée), donc jamais codé en dur dans le balisage.
    const logPathEl = document.getElementById("logFilePath");
    if (logPathEl && s.log_file) logPathEl.textContent = s.log_file;

    // Last event (learn)
    if (s.mode === "learn" && s.last_event) {
      const ev = s.last_event;
      // ⏹ Une branche appelant `ledAssignDetected()` (fonction depuis
      //    supprimée) vivait ici — ne pas la ré-appeler sans la fonction.
      if (ev.kind === "button" && assistant.actif) {
        // Configuration guidée : la touche qu'on vient de presser reçoit
        // l'étape courante, et on enchaîne. Le formulaire manuel n'apparaît
        // pas — c'est tout l'intérêt.
        await api("/api/learn/clear", {});
        await assistantAssigner(ev.key);
      } else if (ev.kind === "button") {
        showAssignForm(ev.key);
      } else if (ev.kind === "fader") {
        document.getElementById("learnHint").textContent =
          t("ui.touches.learn.fader", { n: ev.index + 1 });
        highlightFader(ev.index);
        await api("/api/learn/clear", {});
      } else if (ev.kind === "encoder") {
        document.getElementById("learnHint").textContent =
          t("ui.touches.learn.roue", { n: ev.index + 1 });
        await api("/api/learn/clear", {});
      }
    }
  } catch(e) { /* serveur pas prêt */ }
}

// ── Bridge ────────────────────────────────────────────────────────────
async function toggleBridge() {
  const m = currentMode === "bridge" ? "idle" : "bridge";
  await api("/api/mode", {mode: m});
}

// ⏹ saveEncMa3() retirée avec la case et son endpoint.
// ⚠️ Une fonction supprimée dont un appel subsiste tue TOUT le script à partir
// de sa ligne (ReferenceError au niveau supérieur) — panne déjà vécue. Le seul
// appelant était le `onchange` de la case, parti avec elle ; le contrôle
// test_js_execute du test de fumée le vérifie en exécutant le script.

// Ce que MA3 a réellement sous ses roues — mis à jour à chaque poll. Montre
// aussi les limites (page déduite) plutôt que de les cacher.
// ⚠️ PHASE D'OBSERVATION. La sonde remonte les vrais attributs du projecteur
// sélectionné (canaux), pas un pilotage : le mapping roue→attribut n'est pas
// encore établi. On AFFICHE, on ne commande pas.
//
// 🐛 Ce qui a coûté « plus de moteur, ni de version » : cette
// fonction lisait « e.roues », renommé « e.canaux » côté serveur. e.roues
// undefined → .map() lève → poll() saute dans son catch → header et pastilles
// jamais rendus. Une fonction d'affichage secondaire NE DOIT PAS pouvoir tuer
// le header : l'appel est désormais protégé (voir poll), et cette fonction ne
// suppose plus la forme des données.
// ── Pourquoi MA3 n'écoute-t-il pas l'OSC ? ─────────────────────────────────
//
// 🐛 L'app détectait juste (aucun socket sur le port visé) mais accusait
// TOUJOURS une machine virtuelle — y compris quand aucune ne tournait.
// Relevé : MA3 lancé, zéro socket UDP sur 8000, pas de
// VM. Un diagnostic correct doublé d'une explication fausse est pire qu'un
// simple constat : il envoie chercher au mauvais endroit.
//
// Désormais on répond avec ce que la SONDE lit dans MA3. Sans elle, on
// n'invente pas : on donne la liste des choses à vérifier, sans en désigner
// une comme « la cause ».
// ⚠️ TEXTE BRUT, PAS DE HTML. `setHealth` écrit avec `textContent` : toute
// balise s'afficherait littéralement (« <b>Enable Input</b> » visible tel
// quel à l'écran). Et on ne passe PAS à innerHTML : ces chaînes contiennent des
// noms venus de MA3, qu'on ne veut pas interpréter comme du balisage.
function oscPourquoi(s) {
  const c = s.osc && s.osc.ma3;
  if (c && c.actif) {
    const dits = [];
    if (c.entree === false)
      dits.push(t("err.osc.enable_input_off"));
    // ⚠️ NE JUGER QUE les lignes OSCData portant le port sur lequel on envoie,
    //    et il suffit qu'UNE soit correcte. MA3 en a plusieurs, une par usage :
    //    accuser la mauvaise a fait relancer grandMA3 plusieurs fois pour rien.
    //    → docs/GRANDMA3_SYNC.md#ne-jamais-accuser-une-ligne-oscdata-qui-n-est-pas-sur-le-bon-port
    const ports = (c.configs || []).map(x => x.port).filter(p => p != null);
    const surLePort = (c.configs || []).filter(x => x.port === c.port_attendu);
    const nomme = l => (l.nom ? l.nom : "port " + l.port);
    if (!surLePort.length) {
      if (ports.length)
        dits.push(t("err.osc.aucune_ligne",
                    { port: c.port_attendu, ports: ports.join(", ") }));
    } else if (surLePort.every(x => x.recoit === false)) {
      dits.push(t("err.osc.receive_off", { ligne: nomme(surLePort[0]) }));
    } else if (surLePort.every(x => x.rec_cmd === false)) {
      dits.push(t("err.osc.receive_cmd_off", { ligne: nomme(surLePort[0]) }));
    }
    if (dits.length)
      return t("err.osc.sonde_diagnostic",
               { liste: dits.join(t("err.osc.sep_clauses")) });
    // ⚠️ Config OSC correcte et MA3 muet quand même : la cause est le RÉSEAU
    //    GLOBAL de MA3 (Menu → Network), pas l'OSC. Conseiller « relance
    //    grandMA3 » ici a fait relancer une dizaine de fois pour rien.
    //    Réseau global d'abord, redémarrage en dernier.
    //    → docs/GRANDMA3_SYNC.md#config-osc-correcte-et-ma3-muet-quand-meme-le-reseau-global
    return t("err.osc.config_correcte_muet");
  }
  // ── Sans la sonde, on ne sait pas ce que MA3 a dans sa config. Mais on
  //    peut MESURER quelque chose qui départage les deux causes : le nombre de
  //    sockets réseau que MA3 a ouverts.
  //
  //    ⚠️ C'est une SIGNATURE, pas une preuve. On dit ce qu'on a mesuré et ce
  //    que ça évoque — jamais « ton réseau est coupé ». Un diagnostic juste
  //    doublé d'une explication fausse a déjà coûté une journée ici.
  const n = s.osc && s.osc.sockets;
  if (n === 0) {
    return t("err.osc.aucun_socket");
  }
  if (n > 0) {
    return t("err.osc.sockets_mais_port_absent",
             { n, port: (s.osc ? s.osc.port : "8000") });
  }
  // Pas de sonde : on ne prétend pas savoir.
  const vm = (s.osc && s.osc.vm) ? t("err.osc.vm_avertissement") : "";
  return t("err.osc.cause_indeterminee",
           { port: (s.osc ? s.osc.port : "8000"), vm });
}

function majEncMa3(e) {
  const z = document.getElementById("encMa3Etat");
  if (!z) return;
  if (!e || !e.actif) {
    z.innerHTML = tHtml("ui.encodeurs.ma3_attente");
    return;
  }
  const canaux = Array.isArray(e.canaux) ? e.canaux : [];
  if (e.selection === 0 || (!canaux.length && !e.feature)) {
    z.innerHTML = tHtml("ui.encodeurs.ma3_aucune_selection")
      + (e.note ? " <span class='muted'>(" + e.note + ")</span>" : "");
    return;
  }
  // 🔑 Tranché : `nom` (h.name) vaut
  // systématiquement le nom du FIXTURE, jamais celui du canal — vérifié en
  // direct (32/32 canaux identiques). On ne l'affiche donc plus comme
  // l'attribut : c'est `subattribut` (h.SUBATTRIBUTE) le champ fiable, celui
  // que les roues utilisent réellement pour piloter (enc_attr_selon_ma3,
  // wing_faders.py). `index` reste affiché à titre indicatif.
  const liste = canaux.length
    // esc() : noms lus dans le show MA3 (fixtures, attributs) — pas écrits par nous.
    ? canaux.map(c => "<code>" + esc(c.subattribut || "?") + "</code>"
        + " <span class='muted'>(INDEX="
        + esc(c.index != null ? c.index : "—") + ")</span>")
        .join("<br>")
    : tHtml("ui.encodeurs.ma3_liste_vide");
  const ma3Actif = t("ui.encodeurs.ma3_actif");
  const ma3Sel = e.selection != null ? t("ui.encodeurs.ma3_sel", { n: e.selection }) : "";
  z.innerHTML = "🎡 <b>Encoder Bar</b> : " + esc(e.feature || "?")
    + (e.attribut ? " · " + ma3Actif + " <b>" + esc(e.attribut) + "</b>" : "")
    + (e.fixture ? " · " + esc(e.fixture) : "")
    + (e.selection != null ? " · " + ma3Sel : "")
    + "<br><span class='muted'>" + t("ui.encodeurs.ma3_attributs_titre") + "</span><br>" + liste
    + "<br><span class='muted' style='opacity:.7'>" + (e.pilote
        ? t("ui.encodeurs.suivi_actif")
        : t("ui.encodeurs.suivi_inactif"))
    + "</span>";
}

async function saveSuivreMa3() {
  // ⏹ Le message de confirmation écrivait dans un `suivreMsg` disparu avec
  //    l'ancien encart. Il n'apportait rien : la case cochée EST la
  //    confirmation, et le journal garde la trace.
  await api("/api/suivre_ma3",
            {actif: document.getElementById("suivreMa3").checked});
}

async function saveSuivreEncMa3() {
  // Même moule que saveSuivreMa3().
  await api("/api/encodeurs_ma3",
            {actif: document.getElementById("suivreEncMa3").checked});
}

async function saveOscTarget() {
  const ip = document.getElementById("oscIp").value.trim();
  const port = document.getElementById("oscPort").value.trim();
  const msg = document.getElementById("oscMsg");
  // ⚠️ Passe par api() (comme saveSuivreMa3/saveSuivreEncMa3) ET reste sous
  // try/catch : sans ça, un fetch qui échoue (serveur bloqué, réseau coupé)
  // levait une exception non rattrapée DANS cette fonction async — `msg`
  // n'était jamais mis à jour, et l'utilisateur ne voyait ni succès ni
  // erreur. Cette fonction existe justement pour montrer les deux.
  let d;
  try {
    d = await api("/api/osc/target", {ip: ip, port: port});
  } catch (e) {
    msg.textContent = t("ui.commun.echec");
    msg.style.color = "var(--red)";
    setTimeout(() => { msg.textContent = ""; }, 4000);
    return;
  }
  if (d.ok) {
    msg.textContent = t("ui.commun.applique");
    msg.style.color = "var(--green)";
  } else {
    msg.textContent = "✗ " + (d.error || t("ui.commun.erreur"));
    msg.style.color = "var(--red)";
  }
  setTimeout(() => { msg.textContent = ""; }, 4000);
}

// ── Diagnostic ────────────────────────────────────────────────────────
async function makeDiagnostic() {
  const m = document.getElementById("diagMsg");
  m.textContent = t("ui.bridge.diag.collecte"); m.style.color = "";
  const d = await api("/api/diagnostic", {});
  if (d.ok) {
    m.textContent = t("ui.bridge.diag.ok", { nom: d.name });
    m.style.color = "var(--green)";
  } else {
    m.textContent = "✗ " + (d.error || t("ui.commun.erreur"));
    m.style.color = "var(--red)";
  }
}

// ⚠️ Un appel resté après la suppression de sa fonction tue TOUT le script à
//    partir de cette ligne (ReferenceError au niveau supérieur) — panne déjà
//    vécue. Les minuteurs sont regroupés dans ui/init.js pour être vus.

// ── Récupération après sortie non propre ──────────────────────────────
async function recoverProfile() {
  await api("/api/profile/recover", {});
  await loadProfile();
}
async function discardRecovery() {
  if (!confirm(t("ui.bridge.confirm.abandon_recovery"))) return;
  await api("/api/profile/discard_recovery", {});
}

// Un seul geste côté interface : « fais marcher la wing ». C'est le SERVEUR
// qui décide s'il faut une connexion simple ou une ré-initialisation forcée —
// le navigateur ne peut donc plus demander la mauvaise.
async function wingAction() { await api("/api/wing/connect", {}); }
async function quitApp() {
  if (!confirm(t("ui.bridge.confirm.quitter"))) return;
  arretVolontaire = true;   // l'arrêt vient de NOUS : pas de 2ᵉ dialogue, pas de beacon
  await api("/api/quit", {});
  document.body.innerHTML = tHtml("ui.bridge.arrete_page");
}

async function hardReset() {
  if (!confirm(t("ui.bridge.confirm.hard_reset"))) return;
  arretVolontaire = true;   // redémarrage moteur voulu : l'onglet doit rester, sans prompt
  await api("/api/hard_reset", {});
  document.body.innerHTML = tHtml("ui.bridge.reset_page");
  const tryReload = async () => {
    try {
      const r = await fetch("/api/status", {cache: "no-store"});
      if (r.ok) { location.reload(); return; }
    } catch (e) { /* moteur pas encore reparti */ }
    setTimeout(tryReload, 700);
  };
  setTimeout(tryReload, 1200);   // laisse le temps au process de repartir
}
