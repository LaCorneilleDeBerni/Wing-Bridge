# FADERS & ENCODEURS — les entrées continues

> 🇫🇷 This reference document is in French. Translation contributions are
> welcome — see `CONTRIBUTING.md`.

**Ce fichier = faders et roues encodeuses** : quelle commande chaque type de
fader envoie, le rattrapage, et les attributs des roues.

Les touches (entrées discrètes) sont dans `KEYBOARD_MAPPING.md`.
Les **octets** d'où sortent ces valeurs sont dans `HARDWARE.md` (paquet
d'état : faders en 80-95, roues en 32-44).

⚠️ **Deux pièges silencieux, tous deux vécus :**
1. un **nom d'attribut** de roue se prend dans `attribute_definitions.xml` de
   MA3, balises `<Attribute>` uniquement — jamais le libellé de l'Encoder Bar
   (c'est le champ `Pretty`). Un nom faux échoue **en silence** ;
2. le `kind` d'un fader doit correspondre à la fonction **réellement réglée**
   sur cet executor dans MA3 — c'est la commande qu'on envoie qui impose le
   comportement, pas l'inverse.

> 🧭 **Index de toute la doc technique** : [`README.md`](README.md) (quelle
> question → quel fichier). Avant de toucher au code : [`CONTRIBUTING.md`](../CONTRIBUTING.md)
> à la racine (méthode, règles de modification, pièges).
>
> ⚠️ **Deux protocoles à ne pas mélanger** : l'USB de la wing (`HARDWARE.md`) et
> l'OSC vers MA3 (`GRANDMA3_SYNC.md`). Quand l'un casse, on doit pouvoir lire
> l'autre sans le traverser.

---

**Faders → niveau d'executor** : mot-clé **`FaderMaster`** obligatoire —
`FaderMaster Executor <n> At <pct>`. `Executor <n> At <pct>` SEUL est accepté
sans erreur (OK dans l'historique) mais n'a **aucun effet visible** : la
syntaxe MA2 a changé en MA3 (confirmé doc officielle malighting.com/help +
forum MA Lighting). Snap immédiat (pas de fade, sauf séquences/presets). Numéro
d'executor = **complet** (105, 205…), pas page+rang.

**Faders → couverture complète de la liste MA3 "Select Function"** (Menu
Executor → Fader) : chaque fader physique a un `kind` choisi dans l'UI (menu
déroulant). Format profil : `PROFILE["faders"][i] = {"kind": ..., ...}`.
Deux familles dans `wing_ui.py` :
- `FADER_KEYWORDS` (dict kind→mot-clé) — toutes suivent le moule
  `Fader<Mot> Executor <n> At <pct>` : `executor`→FaderMaster, `crossfade`→
  FaderCrossFade (X), `crossfadeA`→FaderCrossFadeA (XA), `crossfadeB`→
  FaderCrossFadeB (XB), `temp`→FaderTemp, `rate`→FaderRate, `time`→FaderTime.
  **Ce sont exactement, et SEULEMENT, les 8 mots-clés Fader* de la page
  officielle "General Keywords"** (vérifié sur 2 versions de la doc, 2.0 et
  2.3 — liste identique et exhaustive les deux fois). Dispatch générique dans
  `send_fader()` via `elif kind in FADER_KEYWORDS`, plus besoin d'un bloc par
  kind.
  **Highlight/Lowlight/Solo retirés** : proposés dans le sélecteur "Select
  Function" de MA3 pour la propriété Fader d'un executor, mais AUCUN mot-clé
  FaderX dédié n'existe pour eux dans la doc officielle — une première
  tentative d'extrapolation du motif de nommage s'est révélée fausse (vérifiée
  et corrigée après recherche ciblée). Mieux vaut ne pas proposer l'option
  que d'envoyer une commande invalide. Si MA Lighting documente un jour la
  bonne syntaxe, ajouter à `FADER_KEYWORDS`.
- Cas spéciaux (valeur = unité, pas %) : `gm` → `{"kind":"gm"}` →
  `Master 2.1 At %` (fixe, pas d'unité) ; `faderspeed` →
  `{"kind":"faderspeed","exec":N,"unit":...,"min":lo,"max":hi}` →
  `FaderSpeed Executor N At BPM|Hz|Seconds <valeur>` (propriété Fader DE
  L'EXECUTOR — différent de `speed`) ; `speed` →
  `{"kind":"speed","num":N,"unit":...,"min":lo,"max":hi}` →
  `Master 3.N At BPM|Hz|Seconds <valeur>` (pool Speed Master SÉPARÉ, pas lié
  à un executor précis). Les deux valeurs sont mappées linéairement depuis
  min/max configurés (jamais un %, doc officielle : `Master 3.1 At BPM 42`,
  `FaderSpeed Sequence 1 at bpm 120`).

> ### `_mapped_speed_value` — valeur ABSOLUE avec mot-clé d'unité
>
> Pour les kinds `faderspeed` / `speed`, `_mapped_speed_value(cfg, cv)`
> (`wing_faders.py`) mappe la position du fader **linéairement entre `cfg["min"]`
> et `cfg["max"]`**, et l'envoie avec le mot-clé d'unité explicite.
>
> **Pourquoi absolu, et pas un pourcentage.** Le manuel MA3 installé
> (`keyword_faderspeed.html`, `keyword_bpm.html`, `keyword_hz.html`,
> `keyword_seconds.html`) documente `At <UNITÉ> <valeur>` — mot-clé d'unité
> EXPLICITE — comme une valeur **absolue** dans ses propres exemples
> (« Master 3.1 At BPM 75 » → 75 BPM). À ne pas confondre avec `At <nombre>`
> **sans** mot-clé d'unité (`keyword_at.html`), qui, lui, EST un pourcentage
> (« FaderMaster Sequence 1 At 30 » → 30 %). Deux commandes distinctes malgré la
> ressemblance — un retour de forum laissant croire à un facteur ~2,5× portait
> presque sûrement sur la seconde forme.
>
> **`unit` / `min` / `max` ne miment PAS un réglage lu dans MA3.** La sonde Lua
> n'expose aucune plage de vitesse — seulement `GetFader()` (0-100 %) et le nom
> de la fonction. `masters_speed.html` confirme que la plage d'un Speed Master
> est de toute façon FIXE côté MA3 (0-225 BPM), pas configurable par master.
> `min` / `max` sont donc la seule source disponible : le choix de
> l'UTILISATEUR, pas une lecture de MA3.
>
> ⚠️ Ne pas confondre avec `kind_selon_ma3` / `token_selon_ma3` (mêmes fichier
> et voisinage), qui n'ont jamais été concernés par ce bug — `send_fader()`
> appelait une fonction inexistante, `NameError` garanti sur `faderspeed` /
> `speed`.

Anti-flood unifié `FADER_LAST`. Migration automatique des anciens formats
(liste `["GM",0]` / `[page,exe]`) → dict, idempotente, dans `wm.migrate_profile()`.

**⚠️ RÈGLE CRITIQUE (comprise après le détour MIDI abandonné)** :
le `kind` choisi dans l'app DOIT correspondre exactement à la fonction
RÉELLEMENT réglée sur cet executor dans MA3 (Assign menu → Handle page, ou
`Set Page X.N Property "Fader" <Fonction>`). L'OSC n'a AUCUNE visibilité sur
la config interne de MA3 — c'est la commande qu'on envoie qui impose le
comportement, pas l'inverse. Même limite structurelle que pour les boutons
executor : aucune interface externe — OSC, MIDI, ni même un clavier USB comme
`cmd_key` — ne peut lire automatiquement la fonction assignée à un executor ;
seul le matériel reconnu nativement par MA3 (protocole propriétaire non
documenté) le peut. C'est pour ça que la tentative MIDI V3 a été abandonnée.

> ⚠️ **Cette limite a été LEVÉE depuis, par la sonde Lua** : l'API Lua de MA3
> donne la fonction réelle d'un executor, ce que ni l'OSC ni le MIDI ne
> pouvaient. Voir `GRANDMA3_SYNC.md`. La règle ci-dessus reste vraie **tant que
> le plugin n'est pas installé** — et il l'est en principe, c'est une étape de
> mise en route.

**GrandMaster** : commande `Master 2.1 At X`. Un fader peut cibler le GrandMaster
(case GM dans l'onglet Faders) → stocké `["GM", 0]`, envoi throttlé au % entier.


Faders : `/Page{p}/Fader{n}` — obsolète, voir section FaderMaster plus haut.

## 🎯 Rattrapage de fader (« pickup »)

**Le principe, celui d'une vraie console** : un fader physique déconnecté de
la valeur MA3 courante (changement de page, rechargement de show, ou tout
simplement MA3 qui a bougé sans que ce fader-là ait suivi) **n'envoie rien**
tant qu'il n'a pas **rejoint ou traversé** cette valeur. Sans ça, le premier
contact ferait sauter le niveau — visible depuis la salle.

**Comment on lit la valeur MA3.** Le retour OSC entrant ne suffit pas : MA3
n'émet rien au changement de page. Le rattrapage repose donc sur la **sonde
Lua**, qui donne la position réelle des executors une fois dépassé ce blocage
OSC. Les types `gm`, `speed` et `selected` (GrandMaster, Speed Masters, masters
de sélection) n'avaient **jamais** eu de canal de lecture — pas une régression,
une vraie absence, comblée en étendant la sonde à `MasterPool()` (voir
`docs/GRANDMA3_SYNC.md`).

**Mécanique** (`wing_faders.py`) :
- `pickup_autorise(i, cfg, pct)` — appelée à chaque mouvement d'un fader.
  Bloque l'envoi (et journalise `⏸ … en attente de rattrapage`) tant que
  l'écart avec MA3 dépasse `PICKUP_TOLERANCE` (2 %) ; laisse passer dès que
  rejoint OU **traversé** (changement de signe de l'écart) — journalisé
  `✓ … rattrapé`. Ne bloque **jamais** en l'absence d'info côté MA3 (sonde
  éteinte, fader désactivé) : comportement d'avant, jamais un fader muet sans
  raison.
- `pickup_verifier_repos(faders_phys=None)` — appelée par la boucle USB (~8 Hz,
  couplée au rafraîchissement des LED depuis MA3 : `etat.E.LED["ma3"]` doit être
  actif et Vegas éteint — sinon cette vérification ne tourne PAS, silencieusement).
  Réaccorde un fader au repos avec MA3, **dans les deux sens** :
  - **Ré-armement** — un fader qui a déjà la main, **au repos depuis ≥1,5 s**
    (`PICKUP_REPOS_S`), la reperd si MA3 a dérivé de plus de 4 % sans lui —
    journalisé `↔ … MA3 est passé à X% sans lui … rattrapage redemandé`. C'est ce
    qui rend le rattrapage **permanent** (pas seulement réarmé au changement de
    page, même si un changement de page réarme aussi tout, immédiatement, via
    `pickup_page_changee()`).
  - **Auto-rattrapage au repos** — un fader armé dont la position physique
    RÉELLE (`faders_phys`, 0-1023, fournie par la boucle USB) COÏNCIDE déjà avec
    la valeur MA3 (dans `PICKUP_TOLERANCE`) est rattrapé **sans exiger de
    mouvement** — journalisé `✓ … déjà en place (X%) — rattrapage acquis sans
    mouvement`. 🐛 Corrige l'aller-retour de page **1 → 2 → 1** : au retour, les
    boutons restaient à clignoter alors que rien n'avait bougé (le changement de
    page réarme TOUT, et le rattrapage par mouvement ne se déclenche qu'au
    mouvement). On lit la position physique réelle, pas `st["envoye"]` (périmée
    sur un fader armé bougé sans le rattraper). `faders_phys=None` → ancien
    comportement. Vérifié en réel : Page 1→2 (6 faders réarmés), retour Page 1 →
    6 lignes `✓ … déjà en place`.
- `_valeur_ma3_du_fader(cfg)` — point d'entrée UNIQUE vers la valeur MA3
  courante, quel que soit le type. Lit `ma3_executor(exec)` pour `executor`,
  `ma3_master("grand", 1)` pour `gm`, `ma3_master("speed", num)` pour `speed`,
  `ma3_master("selected", num)` pour `selected`. Même mécanisme partout, pas
  de logique parallèle par type.

**Types couverts** : `executor`, `gm`, `speed`, `selected` — plus aucun type de
fader n'est « en direct » par construction. `faderspeed` (la fonction Speed d'un
executor, distincte du pool Speed Master) reste hors périmètre, non demandé.

**Latence mesurée** (OSC → sonde → fichier d'état → Python) : **~112-144 ms**,
identique pour un executor et pour un Master (voir `docs/GRANDMA3_SYNC.md`).
⚠️ **Limite connue, pas un bug** : un changement MA3 suivi d'un mouvement
physique **trop rapproché** (moins de temps que cette latence, plus le
délai de la prochaine vérification à ~8 Hz) peut faire sauter le fader — le
mécanisme n'a pas encore « vu » le changement. Confirmé en réel : en laissant
passer moins d'une seconde entre les deux gestes, le rattrapage fonctionne
normalement.

## 🐛 Attributs d'encodeur : « Focus » n'existe pas

**Symptôme** : la roue 4 du groupe 2 ne fait rien. Rien d'anormal côté Wing
Bridge — la commande part, le journal l'affiche. C'est **MA3** qui refuse, sur
**sa propre ligne de commande** :

```
illegal object : attribute "focus" at +1
```

Wing Bridge n'en sait rien : l'OSC est unidirectionnel ici, MA3 ne renvoie
aucune erreur. **Une roue mal nommée est donc indiscernable d'une roue en
panne.** Si quelqu'un signale un encodeur mort, la première chose à regarder
est la ligne de commande de MA3, pas le journal de l'app.

### La cause : le libellé de l'Encoder Bar n'est PAS le nom de l'attribut

MA3 range ses attributs en trois niveaux : `FeatureGroup` › `Feature` ›
`Attribute`. Seul le dernier est adressable par `Attribute <nom> at + N`.

`Focus` existe bien dans MA3 — mais comme **FeatureGroup**, et comme
**Feature**. L'attribut réel s'appelle `Focus1`… et son champ `Pretty` vaut
justement `Focus`. Autrement dit **l'Encoder Bar affiche « Focus » pour un
attribut qui s'appelle `Focus1`**. Le commentaire du code disait exactement
quoi faire pour se tromper : *« Noms MA3 exacts : sélectionne une fixture →
regarde l'Encoder Bar »*. Il a été corrigé.

### Source de vérité (installée avec MA3, pas besoin d'Internet)

```
<install MA3>/gma3_<version>/shared/resource/attribute_definitions.xml
```

346 attributs relevés (relevé fait en 2.4.2 ; la lecture suit la version
installée — vérifiée aussi en 2.5.x). Les 15 noms des groupes par défaut ont
été vérifiés un par un contre ce fichier. **Deux étaient faux :**

| Écrit dans les défauts | Vrai nom | Ce que montre l'Encoder Bar |
|---|---|---|
| `Focus` | `Focus1` | Focus |
| `Shutter` | `Shutter1` | Sh1 |

`Shutter` était faux **depuis toujours** et personne ne l'avait remarqué —
illustration directe du problème : l'échec silencieux ne se signale jamais
tout seul, il attend qu'on tombe dessus par hasard.

### Les trois corrections

1. `ENC_GROUPS` (wing_bridge.py) corrigé, commentaire trompeur remplacé.
2. `ATTR_RENAMES` + migration dans `migrate_profile()` : les profils **déjà
   enregistrés** sont corrigés à l'ouverture. Vérifié sur les 3 profils
   installés. Ne touche que ces deux noms invalides — aucune personnalisation
   valide n'est écrasée.
3. **Contrôle `test_attributs` du smoke test** : chaque attribut des groupes est confronté à
   `attribute_definitions.xml`, et le build est annulé si l'un n'existe pas.
   Le message propose le nom le plus proche (`« Focus » — vouliez-vous
   « Focus1 » ?`). Sauté proprement si MA3 n'est pas installé sur la machine.
   **Vérifié en réinjectant le bug** : le contrôle l'attrape et désigne
   « groupe 2, roue 4 » — exactement la roue signalée.

Une aide repliable a été ajoutée dans l'onglet Encodeurs, avec les
correspondances Encoder Bar → nom réel et le chemin du fichier de référence.

### Suite : le répertoire des attributs dans l'interface

Corriger deux noms ne suffisait pas — il fallait que l'utilisateur puisse
**trouver le bon nom sans le deviner**. L'onglet Encodeurs affiche donc la
liste complète, sous les 4 groupes.

**Elle n'est PAS recopiée dans le code.** `ma3_attributes()` (wing_ui.py) lit
`attribute_definitions.xml` du MA3 installé, prend la version la plus récente
si plusieurs cohabitent, et regroupe par FeatureGroup dans l'ordre de MA3
(Dimmer, Position, Gobo, Color, Beam, Focus, Control, Shapers, Video). ~346
attributs, ~6 Ko de JSON, lu une seule fois puis mis en cache.
Conséquence voulue : **la liste suit la version de MA3 installée, sans
maintenance ici.**

## 🐛 Le même piège, version dynamique : `h.name` ≠ le canal

**Contexte** : en câblant le suivi de l'Encoder Bar (les roues reflètent le
projecteur réellement sélectionné dans MA3, plutôt qu'un groupe statique),
la sonde Lua (`lire_encodeurs()`, `wingbridge.lua`) lisait `h.name` sur
chaque handle de `GetUIChannels(fix, true)` pour obtenir le nom de
l'attribut — exactement le même geste que le bug Focus/Focus1 ci-dessus,
mais sur une lecture *dynamique* cette fois, pas deux noms figés dans un
profil.

**Vérifié en direct, pas supposé** : une lecture brute de `/api/status` sur
un vrai projecteur sélectionné (« Spot 1 », 32 canaux) a montré `nom` valant
**« Spot 1 » pour les 32 canaux, sans exception** — le nom du **fixture**,
jamais celui du canal. Si ce champ avait été câblé sur un pilotage OSC tel
quel, chaque roue aurait envoyé `Attribute "Spot 1" at ±N` — un
`illegal object` silencieux sur *tous* les attributs, pas deux comme dans le cas
figé plus haut.

**La cause, trouvée dans le manuel MA3 installé** :
`lua_objectfree_getuichannels.html` documente lui-même, dans son exemple
officiel, la lecture de `value.SUBATTRIBUTE` (et `value.INDEX`) — **jamais
`.name`** — sur les handles rendus par `GetUIChannels(fixtureHandle, true)`.
`SUBATTRIBUTE` a été confirmé exact sur le même relevé : `Focus1`,
`Shutter1` (les vrais mots-clés, pas les libellés Pretty), et — réponse en
passant à une question posée plus tôt dans le même chantier —
`ColorRGB_R`/`ColorRGB_G`/`ColorRGB_B` : `GetUIChannels()` remonte bien les
canaux virtuels du mélange de couleur indirect quand le fixture type les
expose.

**La correction** : `lire_encodeurs()` remonte désormais `nom` (h.name),
`subattribut` (h.SUBATTRIBUTE) et `index` (h.INDEX) par canal ;
`enc_attr_selon_ma3()` (wing_faders.py), qui décide ce qui part réellement
en OSC, lit **exclusivement `subattribut`**. `nom` reste affiché dans le
relevé brut (diagnostic) mais n'est plus utilisé pour piloter quoi que ce soit.

Ce que ça donne dans l'interface :

- **autocomplétion** dans les 4×4 cases (`<datalist>` natif) — taper « foc »
  propose Focus1, Focus2… ;
- **répertoire cliquable** filtrable, un clic pose le nom dans la case
  sélectionnée ;
- **cadre rouge** sur un nom inexistant.

⚠️ **Le cadre rouge n'apparaît QUE si la liste vient réellement de MA3.**
Quand MA3 n'est pas sur la machine (console séparée), on retombe sur
`ATTRS_REPLI` — 61 attributs courants — et **tout signalement est désactivé** :
avec une liste partielle, un nom parfaitement valide serait marqué en rouge.
Une alerte fausse coûte plus cher que pas d'alerte : c'est la même règle que
pour les messages de succès mensongers.

`ATTRS_REPLI` est écrite à la main, donc **elle aussi est vérifiée par le
smoke test** contre le fichier de MA3. Ce n'est pas de la précaution
théorique : deux noms inventés de bonne foi s'y trouvaient à l'écriture
(`ColorRGB_A` et `ColorMacro1` — le vrai nom est `ColorMacro`, sans indice).

Piège attrapé au passage par le contrôle `test_ids` du smoke test : le `<datalist>`
était créé en JavaScript alors que les `<input list="attrOptions">` le
référencent par son id. Il est désormais déclaré dans le HTML.

### Même traitement pour les faders — et une affirmation fausse corrigée

Question posée : « la même chose pour les faders ? ». La réponse a été une
bonne surprise — **la liste était déjà complète** — et une mauvaise : **une
phrase de l'interface était fausse.**

MA3 installe son manuel en HTML : `<version>/shared/language/HTML`. Deux
sources y ont tranché la question définitivement :

- `executor_assign.html`, section **« Select Function for faders »** : un fader
  d'executor accepte **exactement 8 fonctions** — Master, X, XA, XB, Temp,
  Rate, Speed, Time ;
- une page par mot-clé, `keyword_fader*.html`, qui donne le nom canonique
  (`FaderMaster`) et le raccourci frappé (`Faderm`).

**Wing Bridge offrait déjà les 8.** En revanche l'onglet Faders affirmait :
*« MA3 propose aussi Highlight/Lowlight/Solo dans son sélecteur, mais ces
fonctions n'ont pas de mot-clé documenté »*. **C'est faux** : Highlight,
Lowlight et Solo sont des fonctions de **touche**, pas de fader — elles ne
figurent pas dans la liste des faders. La phrase laissait croire à un manque
qui n'existe pas. Supprimée. **Ne pas refaire chercher de ce côté.**

`ma3_fader_functions()` (wing_ui.py) lit ces pages et renvoie, pour chaque type
proposé par Wing Bridge : libellé, mot-clé, raccourci MA3, commande réellement
envoyée, et `confirme` (True / None). L'onglet Faders l'affiche en tableau, ce
qui remplace la longue liste en prose de l'intro.

⚠️ `confirme` vaut **None**, jamais False, quand le manuel n'est pas lisible —
même règle que le cadre rouge des attributs : pas d'alerte plutôt qu'une
fausse. Et `gm` / `speed` ont `confirme = None` par nature : ce ne sont pas des
fonctions de fader d'executor mais des `Master N.M`, un mécanisme différent
malgré le nom proche.

**Contrôle `test_faders` du smoke test**, dans les deux sens :
1. un mot-clé qu'on envoie et que MA3 ne connaît pas → **échec du build** ;
2. un mot-clé `Fader*` que MA3 connaît et qu'on n'offre pas → **note**.

Le second point regarde vers l'avenir : si MA3 2.5 ajoute une fonction de
fader, le prochain build le dira. Sans ça on le découvrirait par hasard, des
mois plus tard. Les deux sens ont été vérifiés en réinjectant un faux mot-clé
(`FaderRateX`) : échec correct, et note signalant que `FaderRate` n'est plus
proposé.

**Ce que ça ne résout pas** : le type choisi dans Wing Bridge doit correspondre
à la fonction réglée sur l'executor **dans MA3**. Aucun fichier local ne le
dit — c'est la config du showfile. L'avertissement de l'onglet reste donc
entier. Note pour plus tard : le manuel documente
`Assign FaderRate At Executor 209` et
`Set Page 1.201 Property "Fader" "Empty"` — Wing Bridge *pourrait* forcer la
fonction côté MA3 pour garantir l'accord. Non fait : ça modifierait le
showfile de l'utilisateur sans qu'il l'ait demandé.

### Ce que ça dit du reste du projet

Encore un échec silencieux de la série, après le cache d'autorisation
Accessibilité et le PID de MA3 figé. Le motif est constant : **une couche
externe refuse quelque chose et Wing Bridge continue comme si de rien
n'était.** Quand on ajoute un chemin vers MA3, la question à se poser est
« qu'est-ce qui me le dit si MA3 refuse ? » — et si la réponse est « rien »,
il faut un contrôle au build ou une aide dans l'interface.

---

## Éditer un groupe doit s'appliquer tout de suite

🐛 **Piège** : l'onglet Encodeurs ne s'appliquait pas au réel — changer le motif
d'une roue était censé être pris en compte immédiatement, et ne l'était pas.

**Ce qui se passait**, reproduit en simulation :

1. clic sur la roue 3 → les roues jouent le groupe 3 (`Gobo1…`) ;
2. l'utilisateur édite le groupe 3 et clique « Enregistrer » ;
3. `/api/encoders` appelait `reset_enc_attr()`, qui repart du groupe **par
   DÉFAUT** → les roues sautaient sur le groupe 2 (`Pan, Tilt, Zoom, Focus1`).

La modification était bien enregistrée dans le profil. Mais les roues ne la
prenaient pas : elles avaient changé de groupe.

**Cause** : l'app retenait les **valeurs** des 4 roues (`STATE["enc_attr"]`) et
jamais **quel groupe est actif**. `reset_enc_attr()` n'avait donc aucun moyen de
revenir au groupe courant — sa seule option était le groupe par défaut.

⚠️ **Bug ancien** : présent de longue date. Il est resté invisible parce qu'il
ne casse rien de bruyant — il change de groupe **en silence**, et on croit que
le réglage n'a pas été pris.

**Correctif** : `STATE["enc_group"]` retient l'index du groupe actif, et tout
changement de groupe passe par `appliquer_groupe_enc()`. Après une édition, on
ré-applique le groupe **courant**.

| Appelant | Comportement attendu |
|---|---|
| clic sur une roue (1-4) | active ce groupe |
| **enregistrement de l'onglet Encodeurs** | **ré-applique le groupe COURANT** |
| chargement de profil, démarrage, config sûre | repart du groupe par DÉFAUT |

🔒 Gardé par le **contrôle `test_groupe_encodeur_applique`** du test de fumée.

## Configurer un fader depuis l'interface : validé, pas corrigé (25/09/2026)

`POST /api/fader` passe par `wing_faders.config_fader(body)`, qui rend
`(configuration, libellé MA3 pour le journal, suivre)`. Chaque champ est lu par
`wing_validation` : `kind` doit figurer dans `wm.KINDS_FADER`, `num` et `exec`
sont bornés (1-99, 1-99999), `unit` doit être une unité de `SPEED_UNITS`, et
`suivre` est un vrai booléen (`"false"` est refusé, alors qu'avant
`bool("false")` valait `True`). Une valeur invalide donne une réponse **400**
avec un message traduit, sans rien écrire dans le profil. `/api/fader/nom`
borne l'index à la liste des faders : avant, un index à 10 000 créait 9 993
étiquettes vides, et un index à -1 écrivait dans la dernière. Contrôle
`test_validation_entrees` (smoke_securite.py).
