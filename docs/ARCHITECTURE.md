# ARCHITECTURE — comment les pièces s'emboîtent

> 🇫🇷 This reference document is in French. Translation contributions are
> welcome — see `CONTRIBUTING.md`.

**Le fichier à relire en premier après deux semaines de pause**, pour se
rappeler qui parle à qui sans replonger dans 5 000 lignes de Python.

> 🧭 **Index de toute la doc technique** : [`README.md`](README.md) (quelle
> question → quel fichier). Avant de toucher au code : [`CONTRIBUTING.md`](../CONTRIBUTING.md)
> à la racine (méthode, règles de modification, pièges).

---

## Le schéma

```
     ┌───────────────┐
     │  WING (USB)   │  command wing MA2 onPC · VID 0x03EB / PID 0x160B
     └───────┬───────┘
             │ bulk EP 0x02 (out) / 0x81 (in)
             │
    ┌────────▼─────────┐   wing_init.py — CONNEXION seulement
    │   wing_init.py   │   bootloader ? firmware ? poignée de main ?
    └────────┬─────────┘   rend une poignée `dev` utilisable, puis s'efface
             │ dev
    ┌────────▼──────────────────────────────────────────────────┐
    │         wing_ui.py + les modules wing_*.py extraits        │
    │  ⭐ CE FLUX — tout passe par ces fichiers ensemble         │
    │  (usb_loop/cycle_dmx → wing_connexion.py · routes HTTP →   │
    │   wing_handler.py · voir « Qui fait quoi » plus bas pour    │
    │   le détail précis, fichier par fichier)                   │
    │                                                           │
    │   usb_loop() ~30 Hz  ──►  cycle_dmx(dev)                  │
    │        │                    ├─ POLL     → paquet d'état   │
    │        │                    ├─ LED_A/B  ← tampon DMX      │
    │        │                    └─ CMD_264  ← carte des LEDs  │
    │        │                                                  │
    │        ├─► décodage : wing_bridge.parse_state/parse_events │
    │        ├─► mapping  : PROFILE (chargé par wing_mapper)     │
    │        └─► envoi    : OSC /cmd  ─────────────────────────► grandMA3
    │                                                     ▲     │  (UDP 8000)
    │   osc_in_loop()  ◄───────── retour OSC de MA3 ──────┘     │
    │   ma3_etat()     ◄───────── wingbridge_state.json ◄───────┼── sonde Lua
    │   HTTP :8765     ◄───────── /api/keystrokes ──────────────┼── Wing Keyboard.app
    │        │                                                  │   (CGEventPostToPid)
    └────────┼──────────────────────────────────────────────────┘
             │ /api/status (JSON)
    ┌────────▼─────────┐
    │  wing_ui.html    │  interface web, 127.0.0.1:8765
    │  + ui/*.js       │  (balisage / JS par onglet, fichiers séparés)
    └──────────────────┘
```

## ⚠️ Quatre pièges sur ce schéma

Quatre erreurs *plausibles* sur ce schéma — les noms de fichiers invitent à s'y
tromper, et on refera l'erreur sans ce garde-fou.

| Ce qu'on croyait | Ce que fait le code (vérifié) |
|---|---|
| `wing_bridge.py` parle à l'USB | **Non** : c'est une bibliothèque passive — définitions de paquets (`POLL`, `LED_A/B`, `CMD_264`) et décodeurs (`parse_state`, `parse_events`, `enc_delta`). Aucune boucle. C'est `wing_ui.usb_loop()` qui pilote |
| `wing_mapper.py` envoie l'OSC | **Non** : il ne fait que charger/sauver/migrer les **profils**. L'OSC part de `wing_ui.py`, le seul module qui ouvre un client OSC |
| `wing_hw_state.json` = état interne | **Non** : un seul champ, `fw_envoye_t` — l'horodatage anti-martèlement de l'envoi de firmware. Rien à voir avec l'état de la wing |
| `wing_ui` lit l'état dans un fichier | **Non** : l'état vit **en mémoire**, dans l'objet `etat.E` (`etat.E.STATE`, `etat.E.DEV`). L'interface web l'obtient par HTTP `/api/status` |

## Qui fait quoi, en une ligne chacun

⚠️ **Depuis l'audit du 25/09/2026 (D1), l'état partagé ne vit plus dans
`wing_ui.py`** : il est dans `etat.py` (voir « L'état partagé » plus bas). La
colonne « Ne fait PAS » ne liste donc plus « X reste dans `wing_ui.py` ».
`core.X` (`import wing_ui as core`) ne sert plus qu'aux **fonctions** et
**constantes** que `wing_ui.py` réexporte.

| Module | Rôle | Ne fait PAS |
|---|---|---|
| `etat.py` | **L'état mutable partagé** : un objet `Etat` (28 champs : `STATE`, `SETTINGS`, `PROFILE`, `LOCK`, `DEV`, `OSC`, `BOUCLE`, `DMX`, `LED`…), instance courante `etat.E`, `etat.injecter()` pour les tests | aucune logique, aucune constante |
| `wing_ui.py` | **Chef d'orchestre** : point d'entrée (`main()`), accesseurs `etat_poser`/`reglage_poser`/`mark_dirty`, `save_settings`, réexport des fonctions des modules, page d'accueil et fichiers `ui/*.js` | ne détient plus l'état (ses anciens noms `wing_ui.STATE`… **lèvent**) |
| `wing_init.py` | Connexion USB : détecte bootloader/applicatif, envoie le firmware, poignée de main | ne lit aucune touche, ne parle pas à MA3 ; fichiers firmware et anti-martèlement délégués (ci-dessous) |
| `wing_firmware.py` | Fichiers firmware : chemin du cache, résolution, statut, enregistrement d'un blob importé | n'envoie rien à la wing |
| `wing_etat_materiel.py` | Anti-martèlement du firmware et blocage connu (`wing_hw_state.json`) | ne touche pas à l'USB |
| `wing_bridge.py` | Paquets et décodeurs du protocole USB, `LED_BASE`. Bibliothèque pure | pas de boucle, pas d'USB, pas d'OSC |
| `wing_diagnostic.py` | Rapport de diagnostic complet, capture des exceptions non rattrapées | n'écrit rien dans l'état |
| `wing_profils.py` | Config sûre, sauvegarde auto, import/chargement de profil (confiné au dossier des profils : `chemin_profil`), profil favori | — |
| `wing_ma3.py` | Sonde MA3 (état, attributs, mots-clés, fonctions de fader), machine virtuelle, sockets réseau | ne pilote rien, observation seule |
| `wing_raccourcis.py` | Compare et envoie la table de raccourcis clavier de l'app vers MA3 (fichier XML + `Set KeyboardShortcut`) | `MA3_SHCUTS_DIR` (constante de chemin) reste dans `wing_ui.py`, monkeypatchée par `smoke_test.py` |
| `wing_touches_leds.py` | File de frappes vers l'assistant clavier, retour LED des boutons | — |
| `wing_faders.py` | Envoi des faders vers MA3, suivi de la config réelle, rattrapage (« pickup »), `config_fader` (validation d'une config de fader) | — |
| `wing_boutons.py` | Anti-rebond, appui/relâchement bouton, mode console, `affectation` et `renumeroter_rangee` (sorties du handler) | — |
| `wing_reglages.py` | OSC entrant (observation), cible OSC, réglages machine, **journal serveur** (`log`, écriture disque différée) | — |
| `wing_connexion.py` | Connexion USB (`connect_wing`), redémarrage du moteur, santé du flux, **la boucle USB** (`usb_loop`/`cycle_dmx`), écoute DMX réseau (filtre « local uniquement ») | `connect_wing`/`cycle_dmx`/`full_init` monkeypatchés en réassignation complète par `smoke_test.py` |
| `wing_handler.py` | **La classe `Handler`** : toutes les routes `/api/...` et la page d'accueil. Lit le corps, valide, appelle, répond | plus de logique métier : validation, désinstallation, dialogues, statut sont sortis (D3) |
| `wing_validation.py` | Lecture typée d'un corps JSON (`entier`, `hexa`, `reel`, `booleen`, `texte`, `choix`, `groupes_encodeurs`) → `EntreeInvalide` → réponse 400 | ne corrige rien en silence |
| `wing_desinstall.py` | Plan de désinstallation, résidu manuel, exécution (`plan`/`residu`/`executer`) | — |
| `wing_dialogues.py` | Sélecteur de fichier natif (`choisir_fichier`, macOS et Windows) | — |
| `wing_statut.py` | Construit la réponse de `/api/status` (`statut`) et de la capture (`capture_statut`) | n'écrit rien |
| `wing_jeton.py` | Jeton d'API : génération, fichier 0600, lecture, requête signée (`ouvrir`) | — |
| `wing_demenagement.py` | `garder()` : fait lever tout accès à un nom déménagé d'un module | — |
| `wing_mapper.py` | Profils : charger, sauver, migrer. Table des raccourcis | pas d'USB, pas d'OSC |
| `wing_detect.py` | Scan USB, identification des wings compatibles | n'initialise rien |
| `wing_keyboard.py` | App séparée : consomme la file de frappes et les poste au PID de MA3 | ne touche pas à l'USB |
| `wing_ui.html` | Le BALISAGE de l'interface | aucune logique métier, et plus aucun JavaScript |
| `ui/*.js` | Le JavaScript, **un fichier par onglet** : `core` (socle), `aides`, `bridge`, `touches`, `faders_encodeurs`, `profils`, `parametres`, `init` | servis par `/ui/<nom>.js` en `no-store`, **liste blanche** de noms. **Portée globale**, jamais des modules ES. ⚠️ Ordre imposé : `core` en 1er, `init` en dernier |
| `plugin_ma3/wingbridge.lua` | Sonde qui tourne **dans** MA3, publie un JSON | ne reçoit rien de l'app |

## Les quatre frontières, et pourquoi elles comptent

C'est le découpage de cette doc : **chaque frontière est un protocole
différent**, et quand l'un casse on doit pouvoir lire l'autre sans le traverser.

| Frontière | Sens | Transport | Doc |
|---|---|---|---|
| Wing ↔ app | ↔ | **USB bulk**, paquets binaires | `HARDWARE.md` |
| App → MA3 | → | **OSC/UDP 8000**, `/cmd "…"` | `GRANDMA3_SYNC.md` |
| App → MA3 (frappes) | → | HTTP interne → **CGEvent** au PID de MA3 | `KEYBOARD_MAPPING.md` |
| MA3 → app | ← | **fichier JSON** écrit par la sonde Lua, + retour OSC | `GRANDMA3_SYNC.md` |

⚠️ **La dernière est la moins évidente et la plus utile.** MA3 ne sait pas
« répondre » à une app tierce : la sonde Lua écrit
`~/MALightingTechnology/gma3_library/wingbridge_state.json`, que `ma3_etat()`
relit (périmé au-delà de 5 s). C'est ce canal qui a débloqué quatre fonctions
classées impossibles — page courante, état réel des executors, rattrapage de
fader, fonction réelle des touches.

Un échange par fichier est légitime **parce que la cible est MA3 onPC
uniquement** : la console tourne forcément sur la même machine que l'app.

## Où vivent les données

| Quoi | Où (app figée) | Où (lancé depuis les sources) |
|---|---|---|
| Profils de mapping | `~/Library/Application Support/Wing Bridge/profiles/` | `src/profiles/` |
| Journal | `~/Library/…/Wing Bridge/wing_server.log` | `src/wing_server.log` |
| Anti-martèlement firmware | `~/Library/…/Wing Bridge/wing_hw_state.json` | `src/wing_hw_state.json` |
| État publié par MA3 | `~/MALightingTechnology/gma3_library/wingbridge_state.json` | idem |
| Jeton d'API (pour l'assistant clavier, 0600) | `~/Library/…/Wing Bridge/api_jeton` — Windows : `%LOCALAPPDATA%\Wing Bridge\api_jeton` | **idem** (emplacement fixe : l'assistant ne connaît pas le mode du serveur) |

Le basculement se joue dans `wing_mapper._default_profile_dir()`, sur
`sys.frozen`. **Corollaire à retenir** : après un plantage de l'app, le journal
utile est celui de `~/Library`, pas celui de `src/`.

## Désinstallation

`POST /api/uninstall` — corps `{"keep": {"profiles": b, "log": b,
"ma3_plugin": b}, "dry_run": b}`. Même forme que `_post_quit` : la réponse
`{deleted, kept, residue}` part **avant** le ménage, qui se fait dans un
`threading.Timer(0.3, …)` finissant par `os._exit(0)`.

- **`dry_run: true`** — renvoie les listes sans rien toucher ni quitter. C'est
  ce que teste le test de fumée (`test_desinstallation`), et ce que l'UI
  pourrait utiliser pour un aperçu.
- **Ménage réel** (`wing_desinstall.executer`, dans le Timer) : `arreter_usb()` +
  `stop_keyboard_helper()`, puis suppression fichier par fichier, puis
  `shutil.rmtree` du dossier de données s'il ne reste rien d'utile. Réservé à
  l'app **figée** (`sys.frozen`) — lancé depuis les sources,
  `PROFILE_DIR.parent` est `src/`, un garde-fou refuse (`400`). ⚠️ Windows :
  `executer` coupe l'écriture disque du journal (`wing_reglages._arret_en_cours`)
  **avant** de supprimer — sinon un fil de fond qui journalise recrée
  `LOG_FILE.parent` (`mkdir`) juste après le `rmtree` et laisse une coquille
  vide derrière. Le `rmtree` est aussi réessayé quelques fois : un fichier tout
  juste fermé (journal clavier de l'assistant qu'on vient de tuer) peut rester
  « delete-pending » un instant et bloquer le `rmdir` de la coquille.
  `executer` prend le verrou du journal (`_log_file_lock`) après avoir posé
  le drapeau d'arrêt — l'écrivain différé ne peut plus être au milieu d'une
  écriture — et vide la file du journal ; `os._exit(0)` est dans un
  `finally` : une erreur du ménage ne laisse jamais un moteur à moitié arrêté.
- **Toujours supprimé, quel que soit `keep`** : `__reference__.json`,
  `__autosave__.json`, `wing_hw_state.json`, `settings.json`, `.DS_Store`, tout
  fichier interne. Seuls **profils** (`profiles/*.json` hors `__*`), **journal**
  (`*.log*`) et **plugin grandMA3** (`wing{bridge,loader}.{lua,xml}` +
  `wingbridge_state.json` + `.bak`) sont des choix.
- **Windows : deux dossiers de données**, pas un. Le moteur écrit ses profils et
  son journal serveur dans `%APPDATA%\Wing Bridge` (= `PROFILE_DIR.parent`),
  mais l'assistant clavier écrit `wing_keyboard.log` dans
  `%LOCALAPPDATA%\Wing Bridge`, un dossier séparé. `wing_desinstall.dossier_local()` le
  renvoie (et `None` sur macOS, où le journal clavier est déjà sous
  `PROFILE_DIR.parent`) ; `plan` le balaie comme une seconde racine
  et `executer` le retire s'il ne reste rien d'utile. Le journal clavier suit
  donc la case **journal** comme les autres `*.log`.
- **Résidu manuel** (`wing_desinstall.residu`, adapté à `sys.platform`) : macOS →
  autorisation Accessibilité + corbeille de `Wing Bridge Officiel/` ; Windows →
  retrait du pilote WinUSB (Gestionnaire de périphériques) + corbeille de
  `dist-windows\`. Dans les deux cas, retrait du plugin du pool MA3. ⚠️
  `wingbridge_state.json` est réécrit ~4×/s par le plugin **encore chargé dans
  grandMA3** : l'app le supprime, MA3 le recrée dans la seconde — d'où la
  consigne « supprime le plugin du pool » dans le résidu.
- Le décideur unique est `wing_desinstall.plan(keep)` : endpoint réel
  et test de fumée passent par lui, il n'y a pas deux logiques à tenir d'accord.

## Les fils d'exécution de `wing_ui.py`

Sept, tous démons, lancés au démarrage :

| Fil | Rôle | Cadence |
|---|---|---|
| `usb_loop` | le cycle wing (poll, LEDs, DMX) — **le cœur** | ~30 Hz |
| `osc_in_loop` | écoute le retour OSC de MA3 | événementiel |
| `autosave_loop` | sauvegarde de récupération du profil | 5 s |
| `vegas_loop` | chenillard de test des LEDs | à la demande |
| `vie_loop` | arrêt à la fermeture de l'onglet (voir « Cycle de vie ») | 0,5 s |
| serveur HTTP | interface web + file de frappes | événementiel |
| `journal_disque` | écrit le journal sur disque par lots (voir « Journal différé ») | événementiel |

⚠️ **`usb_loop` ne meurt jamais volontairement** : le moteur redémarre **en
place** (`os.execv`, même PID). Conséquence documentée au prix fort : toute
poignée USB non libérée sur un chemin d'erreur devient un **verrou permanent**
sur le matériel, pas une simple fuite mémoire. Règle : tout chemin qui rend
`None` doit d'abord libérer ce qu'il tient (voir `CONTRIBUTING.md`, « Règles de
modification »).

⚠️ **Nuance depuis la relecture de sécurité du 13/09/2026** : « ne meurt jamais
volontairement » veut dire tenir en continu, pas qu'un SEUL fil `usb_loop`
existe pour toute la vie du process. `connect_wing()` (`wing_connexion.py`)
peut, lui, l'arrêter puis le relancer — voir juste en dessous.

### `connect_wing()` : verrou atomique et protocole d'arrêt de `usb_loop`

`connect_wing()` peut être appelé en même temps par **trois origines
distinctes** : `usb_loop` lui-même (auto-reconnexion, appel direct dans son
propre fil), un thread lancé par `_flux_muet()` (wing muette-mais-énumérée), et
la route HTTP `_post_wing_connect` (clic « Connecter la wing »). Deux garde-fous
protègent ces appels concurrents contre le même device :

1. **Test-et-pose atomique sous `etat.E.LOCK`** — le test de `STATE["connecting"]`
   et sa pose sont regroupés dans le MÊME bloc `with etat.E.LOCK:`. Avant, c'était
   deux instructions séparées : deux appels concurrents pouvaient tous les deux
   lire `connecting=False` avant que l'un des deux ne le pose, et passaient donc
   tous les deux — deux `full_init()` sur le même device au même instant.
2. **Le device n'est jamais relâché pendant qu'`usb_loop` peut encore le
   toucher.** Si un device est tenu (`DEV[0] is not None`), `connect_wing()`
   suit EXACTEMENT le protocole d'`arreter_usb()` : poser `USB_ARRET`, attendre
   `USB_SORTIE` (jusqu'à 2 s) — PUIS SEULEMENT relâcher. Contrairement à
   `arreter_usb()` (utilisé pour un arrêt définitif du moteur), `connect_wing()`
   **relance** ensuite un `usb_loop` neuf dans son `finally`, une fois la
   (re)connexion terminée (succès ou échec) — sans quoi plus personne ne
   piloterait la wing ni l'auto-reconnexion après un simple clic « Connecter ».
   ⚠️ Cette dérogation ne s'applique QUE si un device est déjà tenu : si
   `DEV[0]` est `None`, c'est `usb_loop` lui-même qui appelle `connect_wing()`
   depuis sa propre branche « dev is None » — attendre sa propre sortie serait
   un blocage mutuel, donc ce chemin saute la pause/relance.

Contrôle `test_connect_wing_verrou_et_boucle` (smoke_hardware.py) — vérifié
comportementalement (concurrence réelle sur `full_init`, ordre relâchement/
sortie de boucle) ET par audit de source pour le verrou (la fenêtre de course
est trop étroite pour qu'un test à 6 threads l'expose de façon fiable via le
seul GIL).

### Génération, filet par tour et superviseur de `usb_loop` (25/09/2026)

Trois défauts de l'audit du 25/09/2026, trois mécanismes :

- **Génération** (`etat.E.USB_GEN`). Si `USB_SORTIE.wait()` expire
  (`USB_SORTIE_ATTENTE_S`, 2 s), l'ancienne boucle est encore dans un tour
  long ; effacer `USB_ARRET` la laissait repartir à côté de la neuve — **2 fils
  mesurés**, chaque geste envoyé deux fois à MA3. `connect_wing()` incrémente
  donc la génération (sous LOCK, **avant** d'effacer `USB_ARRET`) et passe la
  nouvelle à la boucle qu'il lance. Chaque boucle vérifie la sienne en début de
  tour, juste après sa lecture USB, et avant de relâcher la poignée sur
  `WingUnplugged` : une boucle périmée se retire sans rien toucher. ⚠️ Ne règle
  pas la libération de la poignée pendant une lecture en cours si le délai
  expire (voir ETAT_PROJET, 25/09/2026). Contrôle `test_une_seule_boucle_usb`.
- **Filet par tour** (`_erreur_tour`). Le corps de `_usb_boucle` est dans un
  `try` : un tour qui lève est abandonné, compté (`BOUCLE["erreurs_tour"]`),
  journalisé au plus toutes les 10 s, et la boucle repart d'une ligne de base
  neuve (`prev_faders = None`, même règle que les valeurs fantômes).
- **Superviseur** (`usb_loop`, point d'entrée du fil). Relance `_usb_boucle`
  si elle meurt quand même (délai croissant, `BOUCLE["relances"]`) ; au-delà de
  5 morts en 60 s il **abandonne** et laisse l'exception remonter →
  `THREAD_MORT`, affiché. Une sortie volontaire (`USB_ARRET`) ou une génération
  périmée n'est jamais relancée. Contrôle `test_profil_mal_type`.

### 🔒 Règle du projet : `etat.E.LOCK` ne protège JAMAIS un appel lent

Pas une note locale à une fonction — une règle qui s'applique à **tout**
`with etat.E.LOCK:`, dans **tout** fichier `wing_*.py` : ce verrou ne doit
couvrir qu'une **copie rapide** d'état partagé (`STATE`/`SETTINGS`/`PROFILE`),
jamais un appel réseau, disque, socket ou sous-processus. `usb_loop` (~30 Hz)
prend le même verrou à chaque tour ne serait-ce que pour lire faders et
roues : le moindre appel lent tenu sous ce même verrou ailleurs — un
`ma3_sockets()` (`pgrep`/`lsof`), une écriture de profil sur disque, une
réponse HTTP écrite sur le socket — bloque toute la wing pendant sa durée,
en silence.

**Motif systémique, pas un bug isolé.** Une 1ʳᵉ revue de code (Lot B,
14/09/2026) avait corrigé `_get_status` (§57 du test de fumée). Une 2ᵉ revue
(Lot C, même jour) a trouvé le MÊME défaut répété ailleurs, non couvert :
`usb_loop` lui-même (le plus grave — `enc_attr_selon_ma3()` → `ma3_reachable()`
→ `pgrep`, tenu dans SA PROPRE boucle à 30 Hz), `_get_profile` (écriture
socket), `_post_profile_save`/`_post_reference_set` (écriture disque),
`_post_mode` (TOCTOU résiduel : test et écriture dans deux blocs `with
etat.E.LOCK:` séparés, relâché entre les deux).

**Méthode** : copier les champs partagés SOUS le verrou, faire tout le reste
(réseau, fichiers, formatage, appel lent) HORS verrou, sur cette copie figée.

🔒 Contrôle **permanent et automatique** — `test_lock_sans_appel_lent`
(smoke_hardware.py, §60) : un audit de SOURCE (AST) qui balaie CHAQUE
`with etat.E.LOCK:` de CHAQUE fichier `wing_*.py` et échoue si son corps
contient un appel de la liste noire (`subprocess.*`, `self._json(`,
`self.wfile`, `open(`/`.write_text(`/`.read_text(`, `save_profile(`,
`save_reference(`, `save_settings(`, `enc_attr_selon_ma3(`, `ma3_reachable(`,
`ma3_sockets(`, `ma3_etat(`, `dev.read(`/`dev.write(`, `pgrep`,
`time.sleep(`). Contrairement aux contrôles ponctuels ci-dessus, celui-ci
couvre tout le projet d'un coup, régressions futures comprises.

## L'état partagé : `etat.py`, verrou et accesseurs (audit du 25/09/2026, I8 et D1)

**Où il vit.** Tout l'état mutable partagé est un attribut de `etat.E`
(instance courante de `etat.Etat`). Le code l'écrit `etat.E.STATE`,
`etat.E.PROFILE`… — jamais `from etat import E`, qui figerait l'instance.
Les constantes restent dans leur module ; l'état lu par un seul module
(`wing_reglages.OSC_IN`, `wing_connexion.WING_FLUX`…) reste chez lui.

**Pourquoi.** Avant, cet état était un ensemble de variables de module de
`wing_ui.py`, lues par ~165 `import wing_ui as core` paresseux, et
l'emplacement de certains champs était dicté par l'endroit où le test de fumée
les remplaçait. Un test injecte désormais un état neuf et isolé :
`with etat.injecter() as e:` — plus de liste de noms à sauver et restaurer.
⚠️ Seules les fonctions d'aide de `smoke_securite.py` utilisent déjà
l'injection ; les autres tests lisent et écrivent `etat.E` directement. Les
**fonctions** remplacées par les tests (`connect_wing`, `log`…) restent, elles,
monkeypatchées sur `wing_ui` : hors du périmètre de D1.

**Les anciens noms lèvent.** `wing_ui.STATE` (lecture ou écriture) lève
`AttributeError` avec la nouvelle adresse — voir « Déménagements gardés ».
Une variable locale ne s'appelle jamais `etat` : elle masquerait le module
(`UnboundLocalError`). Contrôle `test_etat_injecte`.

**Toute écriture passe sous `LOCK`.** Soit dans un bloc `with etat.E.LOCK:`,
soit par un accesseur de `wing_ui.py` qui prend le verrou et écrit tous ses
champs d'un coup : `etat_poser(**champs)` (STATE), `reglage_poser(**champs)`
(SETTINGS), `mark_dirty()`. L'audit avait relevé 38 écritures hors verrou ;
il n'en reste aucune. `save_settings` sérialise (`json.dumps`) **sous** le
verrou, écrit hors verrou. ⚠️ `LOCK` n'est **pas réentrant** : un accesseur
appelé sous `with LOCK:` bloque tout le moteur. Contrôle
`test_ecritures_etat_sous_verrou` (analyse AST : écriture hors verrou,
accesseur sous verrou, vérification transitive sur 3 niveaux d'appel).

## Journal différé (audit du 25/09/2026, I7)

`log()` ne touche plus le disque : `_log_to_file` dépose la ligne dans une
file bornée (`_FILE_DISQUE`, 10 000 lignes ; au-delà, les pertes sont
comptées) et le fil `journal_disque` écrit par lots. Un disque lent ne bloque
plus l'appelant — `usb_loop` journalise depuis son tour. Mesure : 40 lignes
sur un disque ralenti coûtent 0,2 ms à l'appelant, contre 1,02 s pour 4
lignes en écriture synchrone.

⚠️ **Avant toute sortie brutale, vider la file** : `vider_journal()` est
appelé par `arret_propre`, avant `os.execv` (`restart_self`), par
`_relancer_process_neuf` et par `atexit`. Un nouveau chemin qui termine le
process par `os._exit` ou `os.execv` doit faire de même, sinon les dernières
lignes — souvent celles qui expliquent l'arrêt — sont perdues. Contrôle
`test_journal_hors_boucle`.

## Déménagements gardés (`wing_demenagement.garder`)

Déplacer un nom d'un module vers un autre casse en silence les tests qui le
remplaçaient : `wi.ETAT_FICHIER = dossier_jetable` réussit encore, mais crée
un attribut que plus personne ne lit — le test écrit alors dans le vrai
fichier. `garder(module, {nom: "nouvelle adresse"})` fait **lever** toute
lecture ou écriture d'un nom déplacé. Posée sur `wing_ui` (état → `etat.E`),
`wing_init` (firmware, anti-martèlement) et `wing_handler` (désinstallation,
dialogues, statut, validation). Quand on déplace un nom, on l'ajoute à la
garde du module d'origine. Contrôle `test_handler_mince`.

## Le serveur HTTP : deux garde-fous (Origin/Host, puis jeton d'API)

1. **`_origine_sure`** (`wing_handler.py`) : refuse une requête dont l'en-tête
   `Origin` ou `Host` trahit un autre site (y compris le DNS rebinding).
   Elle laisse passer une requête SANS `Origin` : tout programme local.
2. **Jeton d'API** (25/09/2026, `wing_jeton.py`) : exigé sur **tout POST** et
   sur `GET /api/keystrokes` (en-tête `X-Wing-Jeton`, ou `?jeton=` pour
   `sendBeacon`). Un par lancement de l'app, conservé à travers `os.execv`.
   L'onglet le reçoit dans la page (`<meta name="wing-jeton">`) et `api()`
   (ui/core.js) le joint ; l'assistant clavier le lit dans le fichier 0600
   (tableau ci-dessus) et le relit sur un refus 403.

⚠️ **Limite assumée** : la page contient le jeton — un programme local qui la
lit d'abord l'obtient. Le jeton arrête les requêtes aveugles, pas une attaque
écrite pour cette app ; choix fait pour que taper l'adresse à la main marche
toujours. Contrôle `test_jeton_api`.

Aucune route de débogage n'est exposée (`test_pas_de_route_debug`).

**Une requête reçoit toujours une réponse** (25/09/2026). Chaque route passe
par `Handler._executer` : une entrée refusée donne un **400** JSON, une
exception imprévue un **500** JSON journalisé — plus jamais une connexion
coupée sans réponse. `_read_body` refuse un corps illisible, négatif ou
supérieur à `CORPS_MAX` (5 Mo). Contrôle `test_handler_robuste`.

**Les entrées sont validées, pas corrigées.** Les routes lisent leur corps via
`wing_validation` : un type ou une plage invalide lève `EntreeInvalide` → 400
avec un message traduit, journalisé (`journal.http.entree_refusee`). Défauts
réels trouvés : un index de fader à 10 000 créait 9 993 étiquettes, un index
à -1 écrivait dans la dernière, `bool("false")` valait `True`. Contrôle
`test_validation_entrees`.

## Cycle de vie : instance unique, réutilisation d'onglet, arrêt à la fermeture

Deux comportements voulus, **universels** — aucune dépendance à un navigateur
précis ni au mode `--app`, identiques sous Safari/Firefox :

**1. Relancer l'app n'ouvre pas un 2ᵉ onglet.** Au tout début de `main()` (avant
threads, fichiers, USB, serveur), `wing_ui._instance_deja_active()` sonde
`GET /api/instance` sur le port :

| Réponse | Ce que fait le nouveau process |
|---|---|
| `ui_active: true` (un onglet a pingé < 6 s) | log « déjà lancé, onglet actif », `sys.exit(0)` — rien ouvert |
| `ui_active: false` (serveur sans onglet) | `webbrowser.open(url)` puis `sys.exit(0)` — l'onglet se raccroche au serveur en place |
| rien ne répond | démarrage normal |

Sauté quand `WING_ATTENDRE_PID` est présent (on est le successeur d'un
redémarrage moteur : c'est à nous de reprendre le port).

**Battement de cœur** : l'onglet appelle `GET /api/status` toutes les 400 ms
(`ui/init.js`) et **rien d'autre ne l'appelle** — l'assistant clavier ne sonde
que `/api/keystrokes`. `_get_status` horodate donc `UI_VIE["dernier_ping"]` ;
`_ui_active()` n'est vrai que si ce ping est frais. Un assistant clavier seul ne
le rend jamais vrai.

**`launcher.sh` (macOS) ne fait plus aucun `open`** : la décision « ouvrir ou
non le navigateur » vient uniquement du moteur (`_ouvrir_url`, qui détourne par
la session graphique de l'utilisateur en repli admin/root).

**2. Fermer la fenêtre = éteindre l'app proprement.** `ui/init.js` :

- `beforeunload` → déclenche le dialogue **générique** du navigateur (texte non
  personnalisable, limite navigateur assumée) ;
- `pagehide` → `navigator.sendBeacon("/api/fermeture-onglet")` ;
- un encart permanent de l'onglet Bridge (`ui.bridge.vie.encart`) explique la
  conséquence : la wing repart en **bootloader**, comme « ⏻ Quitter ».

Côté serveur, `POST /api/fermeture-onglet` **arme** un arrêt différé
(`UI_VIE["arret_t"] = monotonic()`). Le fil `vie_loop` (0,5 s) applique
`_vie_verdict(now, arret_t, dernier_ping, grace≈5 s)` :

| Verdict | Quand | Effet |
|---|---|---|
| `arret` | grâce écoulée, échéance dépassée | `wing_ui.arret_propre()` |
| `annule` | un ping d'onglet est arrivé **après** l'armement (= F5, la page est revenue) | désarme, log « rechargement détecté » |
| `rien` | rien d'armé, ou on attend encore | — |

`arret_propre()` est **le chemin d'arrêt unique** : rend la wing en vol
(`arreter_usb`), coupe l'assistant clavier, `os._exit(0)`. « ⏻ Quitter »
(`wing_handler._post_quit`) le partage mot pour mot.

⚠️ **Seul le beacon explicite éteint l'app.** Un simple arrêt du poll — veille de
l'ordinateur, coupure réseau — ne passe pas par là : la veille ne tue rien.
`quitApp` / `hardReset` posent `arretVolontaire = true` pour ne pas redéclencher
le dialogue ni le beacon quand c'est **nous** qui quittons/relançons.
