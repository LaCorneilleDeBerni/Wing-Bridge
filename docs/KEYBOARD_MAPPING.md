# KEYBOARD MAPPING — touches physiques → MA3

> 🇫🇷 This reference document is in French. Translation contributions are
> welcome — see `CONTRIBUTING.md`.

**Ce fichier = les entrées DISCRÈTES** : les touches de la wing, ce qu'elles
envoient à MA3, et le mode console (frappes clavier injectées dans la vraie
ligne de commande).

Les entrées **continues** — faders et roues — sont dans `FADERS_ENCODERS.md` :
ce sont deux mécaniques différentes, qu'on fait évoluer séparément.

⚠️ **La règle qui coûte le plus cher ici** : la ligne de commande de MA3
n'est **pas** un champ de texte. Chaque lettre y insère un MOT-CLÉ (E=Edit,
c=Channel, u=Update…). Une commande composée passe par **OSC**, jamais par le
clavier.

> 🧭 **Index de toute la doc technique** : [`README.md`](README.md) (quelle
> question → quel fichier). Avant de toucher au code : [`CONTRIBUTING.md`](../CONTRIBUTING.md)
> à la racine (méthode, règles de modification, pièges).
>
> ⚠️ **Deux protocoles à ne pas mélanger** : l'USB de la wing (`HARDWARE.md`) et
> l'OSC vers MA3 (`GRANDMA3_SYNC.md`). Quand l'un casse, on doit pouvoir lire
> l'autre sans le traverser.

---

## ⌨️ Appui court / appui long — automatique, pour TOUTES les touches

**Il n'y a rien à régler.** Chaque touche de la wing enfonce sa touche clavier à
l'appui et la relâche au relâchement : **la vraie durée est relayée**, et
grandMA3 décide seul de ce qu'il en fait.

Décision : appui court / appui long relayés **par défaut**, pour toutes les
touches, sans case à cocher — le comportement doit être transparent. (Une
première version enfermait ça dans une case « long » par touche.)

### Pourquoi c'est la bonne conception

Le comportement de maintien est **natif côté MA3**, pas côté wing :

| Touche MA3 | Appui court | Appui maintenu |
|---|---|---|
| `Clear` | efface la sélection | **ClearAll** |
| `Oops` | annule un pas | ouvre **l'historique** |

*(Pages officielles Clear Key / Oops Key du manuel installé.)*

On ne choisit donc pas une commande différente : on relaie fidèlement, MA3
tranche. **Conséquence** : si MA Lighting ajoute demain un comportement de
maintien sur une autre touche, **c'est déjà implémenté** — rien à cocher, rien
à mettre à jour.

### Comment c'est câblé

| Moment | Ce qui part |
|---|---|
| Appui sur le bouton wing | `hold_down` → la touche est **enfoncée** dans MA3 |
| Relâchement du bouton | `hold_up` → la touche est **relâchée** |

⚠️ **L'appariement se fait par BOUTON PHYSIQUE** (`MAINTIENS[btn_id] = spec`),
jamais en relisant le profil au relâchement. Le profil peut changer entre les
deux (mode apprentissage, chargement d'un autre profil) : relire donnerait un
autre raccourci, et **la touche d'origine resterait enfoncée dans MA3** — bien
pire qu'une frappe manquée. Le contrôle `test_appui_long_universel` rejoue précisément ce scénario.

🛟 **Filet** : l'assistant clavier relâche automatiquement toute touche tenue
plus de `HOLD_MAX_S`, au cas où un relâchement se perdrait (app redémarrée en
plein maintien, événement manqué).

### ❌ Ce qui a disparu avec ce choix

- la case **« long »** dans la carte Mode console ;
- l'endpoint `/api/console/hold` ;
- le champ de profil `console_hold` — **retiré automatiquement des profils
  existants** à la migration, pour ne pas laisser un réglage mort qui ferait
  croire qu'il agit encore.

## Mode console — écrire dans la vraie ligne de commande MA3

Objectif : Store / chiffres / Please s'affichent dans la ligne de commande MA3
(session Admin) et **Store + clic écran** fonctionne comme sur une console.

### Ce qui NE marche pas (impasses vérifiées)
- **OSC `/cmd`** : exécute les commandes mais ne les écrit jamais dans la ligne
  de commande interactive (conception MA3).
- **Web remote (port 8080, WebSocket keyboardEvent)** : c'est une session
  utilisateur SÉPARÉE (`Remote[Fixture]`, pas `Admin`), et les frappes n'y
  atteignent même pas la ligne de commande. Plus : limite de connexions basse
  qui entre en conflit avec l'accès navigateur de l'utilisateur. Abandonné.

### Ce qui marche : injection clavier système

Un événement clavier système posté directement au process MA3
(`CGEventPostToPid` sur macOS, `SendInput` sur Windows). Deux process :

> 🔒 **Depuis le 25/09/2026, l'assistant présente un jeton d'API** à chaque
> requête (`wing_jeton.ouvrir`), lu dans le fichier `api_jeton` que le serveur
> écrit en 0600 au démarrage, et relu sur un refus 403 (app relancée). Un
> assistant **ancien**, sans jeton, est refusé : **plus aucune frappe ne part**.
> Toute modification du serveur qui touche au jeton impose donc de
> reconstruire l'assistant (`build_app.sh`). Voir `ARCHITECTURE.md`, « Le
> serveur HTTP : deux garde-fous ».

```
wing_server (utilisateur)        assistant clavier (utilisateur)
  ├ USB / OSC / DMX / LED           ├ poll GET /api/keystrokes
  └ file de frappes  ──HTTP──▶      └ frappe posée au PID de MA3
```

- l'assistant clavier est un **bundle séparé** : c'est lui qui détient
  l'autorisation Accessibilité, liée à sa signature (voir `ARCHITECTURE.md`).
- frappes : chiffres / lettres, Please → Enter, Oops → Backspace… ; caractères
  consécutifs regroupés en une frappe.
- table token → touche dans le profil (`console_keys`, Store = « s » par défaut).
- **Prérequis macOS** : l'assistant clavier autorisé dans Réglages Système →
  Confidentialité et sécurité → Accessibilité. Sinon l'injection est bloquée.
- **Prérequis MA3** : ShCuts actif, et la frappe attendue assignée au mot-clé
  côté MA3 (« s » → Store, par exemple).
- ⚠️ **macOS n'exige pas que MA3 soit au premier plan** (`CGEventPostToPid`) ;
  **Windows si** — voir `WINDOWS.md`, « Assistant clavier Windows ».

---


## Changement de page + migration des raccourcis

### Les deux chemins, par un seul token

Relevé sur la Command Section de MA3 : **`Page +` = `PageUp`**, **`Page -` =
`PageDown`**. Ajoutés aux défauts :

```python
"Next Page":     "pageup",
"Previous Page": "pagedown",
```

**Astuce de nommage, à ne pas défaire** : le TOKEN est la commande MA3 valide
(`Next Page`, doc officielle), et la table le traduit en frappe. Le même
bouton marche donc par les deux chemins, sans configuration :

| Mode | Chemin |
|---|---|
| console | frappe `PageUp` / `PageDown` |
| OSC pur | commande `Next Page` telle quelle |

Nommer le token `Page+` aurait cassé le second cas : c'est un **libellé de
touche**, pas une commande de ligne de commande. ⚠️ `Previous Page` comme
commande OSC reste **non vérifiée** (la frappe, elle, est confirmée).

### Piège : `migrate_profile` n'ajoutait pas les nouveaux raccourcis

Un profil déjà enregistré restait éternellement privé de tout ajout à la table
par défaut : la nouveauté ne profitait qu'aux profils NEUFS.

**Règle** : `migrate_profile()` complète les raccourcis manquants depuis
`CONSOLE_KEY_DEFAULTS`, en `setdefault` — **jamais d'écrasement** (une
personnalisation `Store=F5` est conservée, un désassignement volontaire `""` est
respecté, la migration est idempotente).

➡️ Conséquence : **tout ajout à `CONSOLE_KEY_DEFAULTS` se propage
automatiquement** aux profils existants au prochain chargement.


## Commandes complètes en mode console

**Question de départ** : « pour mapper Page+/Page−, il suffit de le mapper comme
n'importe quel hardkey, non ? » — **oui pour l'OSC, non pour le mode console**,
et la vérification a révélé un piège plus large.

Le formulaire d'assignation a **déjà un champ libre** (`assignVal`, type
« Commande MA3 ») : n'importe quel texte peut être assigné à n'importe quel
bouton. Rien à ajouter de ce côté. Mot-clé officiel pour la page suivante :
**`Next Page`** ([doc MA](https://help.malighting.com/grandMA3/2.2/HTML/keyword_page.html)),
`Page 2` pour une page précise. ⚠️ `Previous Page` est une **déduction par
symétrie, NON vérifiée** — à tester dans la ligne de commande MA3.

**Le piège** : en mode console, un token sans raccourci clavier était
**ignoré en silence**. Toute commande assignée hors de la liste figée de la
carte Mode console devenait donc muette dès le mode console activé, avec pour
seule trace une ligne de journal.

**Règle adoptée, calquée sur une vraie console** :

| Valeur assignée | Mode console | OSC pur |
|---|---|---|
| **un seul mot** connu (`Store`) | frappe clavier | mise en buffer |
| **un seul mot** sans raccourci (`Inconnu`) | ignoré *(inchangé)* | OSC |
| **plusieurs mots** (`Next Page`, `Go+ Exec 5`) | **OSC direct** | OSC |

Un mot = une TOUCHE de la ligne de commande. Plusieurs mots = une COMMANDE
complète, qui s'exécute. Testé en isolation sur les deux modes et les cinq cas.

⚠️ C'est le même chemin de code que le bug du `Go+` tapé en toutes lettres : le
contrôle OSC-direct des executors reste **avant** la recherche de raccourci, et
cette nouvelle règle vient **après**, en dernier recours. Ne pas réordonner.

⚠️ **Ce contrôle OSC-direct lui-même reconnaissait trop peu de commandes**
(corrigé le 13/09/2026) : `handle_button_bridge` le décidait par une liste
figée de préfixes (`"Go+"`, `"Go-"`, `"Pause"`, `"Top"`) au lieu de
`core._RE_EXEC_CMD`, la regex générale (`<Verbe> [On|Off] Executor <n>`) déjà
utilisée par `handle_button_release` et par la branche bridge. Une commande
libre comme `Flash Executor 105` échappait donc à `token_selon_ma3` en mode
console — elle partait en OSC BRUTE, sans le suffixe `On` que MA3 exige pour
une fonction maintenue — alors qu'elle y serait passée normalement partout
ailleurs. Corrigé : même regex aux trois endroits. Contrôle
`test_verbe_executor` (smoke_ma3_sync.py, §14).

💡 Piège de TEST : l'anti-rebond (60 ms) filtre deux appuis successifs sur la
même touche. Dans un test automatisé, vider `_btn_last_event` entre les passes,
sinon la seconde série semble ne rien faire.


### Autres pièges du mode console

- **AZERTY** : lettres seules = disposition réelle du clavier (UCKeyTranslate) ;
  raccourcis à modificateur (Ctrl+Z…) = **position US/QWERTY** (MA3 range ses
  défauts comme ça). Touches F = flag **Fn** forcé (sinon macOS = volume).
- **Règle d'or** : dans la table console, écrire exactement ce que MA3 affiche.
- Table MA3 lue depuis
  `<install MA3>/gma3_library/userprofiles/keyboardshortcuts/KeyboardShortCuts.xml`.
- **Prérequis, vécu en test réel Windows (19/09/2026)** : sur un profil
  utilisateur MA3 tout neuf (jamais touché aux raccourcis clavier), ce dossier
  est **vide** — `KeyboardShortCuts.xml` n'existe que si la console l'a
  **déjà exporté au moins une fois elle-même**. Sans ce fichier,
  `shcuts_envoyer()` (`wing_raccourcis.py`, `_shcuts_gabarit()`) répond
  `possible: false` et n'écrit rien — l'étape D du wizard l'affiche
  maintenant en clair. Ce n'est pas contournable côté app : sans gabarit
  MA3, impossible de connaître la numérotation des 82 raccourcis ni de
  préserver intacts les 33 que Wing Bridge ne gère pas (règle 3, en tête de
  `wing_raccourcis.py`) — écrire un fichier de zéro écraserait ces 33-là.
- `Ctrl+M` = piège Enter (irréparable). `Alt+A` = conflit Camera Pivot → Assign
  remis sur `Ctrl+Alt+V`. Backup (`0x05`) → `Menu` (F12).
- **Piège : ordre du check OSC-direct.** `handle_button_bridge()` vérifiait le
  raccourci clavier AVANT le cas exécutor OSC-direct. Un mapping clavier laissé
  sur le token exact `Go+` court-circuitait l'exécution réelle et **tapait
  littéralement** « Go+ » au lieu de l'exécuter. Règle : le check OSC-direct
  passe en premier ; `Go+` / `Go-` / `Pause` sont aussi retirés de la liste
  mappable de `renderConsoleKeys()` — les y laisser n'invite qu'à recréer le bug.
- **Piège : anti-rebond bouton.** Un seul appui physique sur Go+ déclenchait
  plusieurs Go+ (plusieurs cues sautées d'un coup) : le poll USB (~60 Hz)
  produit parfois plusieurs événements `pressed` pour un appui réel (rebond
  mécanique, duplication protocole). Règle : `_debounced(btn_id,
  "press"|"release")` ignore tout nouvel événement du MÊME type sur le MÊME
  bouton à moins de `BTN_DEBOUNCE_S` (0,06 s) du précédent — appui et
  relâchement suivis **séparément**, sinon le relâchement légitime d'un clic
  bref se fait avaler par le minuteur de son propre appui.

### Touches → executor : fonction configurable

Syntaxe MA3 : `Go+ Executor 101` (**pas** `Go+ Exec 1.101`). Boutons 101-106 →
Executor 101-106 ; boutons 1-6 → Executor **201-206**.

MA3 permet d'assigner à CHAQUE executor sa propre fonction de déclenchement —
`Go+` n'est qu'une option. L'onglet Touches, type « Executor 2-rôles », propose
un menu **Fonction** (`EXEC_FUNCS`) :

- **Coup unique** → `<Fonction> Executor N` : `Go+`, `Go-`, `Toggle`, `Off`,
  `Pause`.
- **Maintenu** (`MOMENTARY_FUNCS`) → `<Fonction> On Executor N` à l'appui,
  `<Fonction> Off Executor N` au relâchement (sinon l'executor **reste bloqué
  actif**) : `Flash`, `Temp`, `Swap`. Géré par `handle_button_release()`,
  détection par motif regex `_MOMENTARY_RE` sur la commande stockée.

⚠️ **`Swap`, pas `Swop`** : `Swap` agit au niveau executor/master (le bon) ;
`Swop` au niveau gradateur de fixture — deux mots-clés MA3 distincts, faux sens.
Syntaxes confirmées au manuel : `Flash On/Off Executor N`, `Temp On/Off
Executor N`, `Swap On/Off Executor N`, `Toggle Executor N` (un seul mot bascule
l'état). Migration : l'abréviation fautive `Go+ Exec 101` (sans « utor ») est
normalisée par `migrate_profile()`, comme le cas avec préfixe de page.

### Filet anti-touche-bloquée (assistant clavier)

Le maintien réel d'une frappe (`key_down` / `key_up`) passe par l'état `_held`
de l'assistant clavier. `release_stuck_holds()`, appelé à chaque tour de boucle,
relâche automatiquement toute touche maintenue plus de `HOLD_MAX_S` sans
relâchement reçu (release perdu, app redémarrée en plein maintien). Double appui
sur une touche déjà maintenue → ignoré. `key_down` sur un spec sans vrai keycode
(repli unicode) → repli sur un tap normal + avertissement journalisé, jamais
d'échec silencieux.

⚠️ Le minutage `press` / `release` doit rester **identique** au tap historique :
un refactor a déjà fusionné par erreur les délais `0,03 s` / `0,02 s`.

---

# 📒 La table des raccourcis — pourquoi chaque valeur est ce qu'elle est

> Ces sections accueillent ce qui vivait en commentaires dans
> `src/wing_mapper.py`. Le code n'en garde que la RÈGLE, en deux lignes, et un
> renvoi vers ici. **Le contrôle `test_renvois_doc` du test de fumée refuse tout
> renvoi qui ne résout pas** : ces titres ne peuvent donc plus être renommés en
> silence.

## Liste blanche des frappes (25/09/2026)

Une frappe de `console_keys` part dans le **XML des raccourcis de MA3** et dans
une commande **OSC** `Set KeyboardShortcut n Property "Shortcut" "<frappe>"`.
Avant l'audit du 25/09/2026, aucun filtre : un `<` corrompait le XML, un `"`
sortait de la chaîne OSC (la commande piégée d'un profil importé serait partie
telle quelle vers MA3 — reproduit dans le contrôle `test_raccourcis_filtres`).

`wing_mapper.raccourci_valide()` n'accepte plus que ce que l'assistant sait
taper : des modificateurs connus (`MODIFICATEURS_RACCOURCI`), puis une touche
nommée connue (`TOUCHES_NOMMEES`) ou **un** caractère seul — `é`, `ç`… d'une
disposition AZERTY restent permis, `< > " & \` jamais. Les deux ensembles
recopient les tables des deux assistants ; le contrôle vérifie qu'ils restent
identiques. Trois portes :

| Porte | Frappe refusée → |
|---|---|
| chargement / import d'un profil (`valider_types`) | remplacée par le défaut de l'app pour ce token, journalisée |
| route `/api/console/key` | refusée, avec une raison affichable |
| écriture vers MA3 (`wing_raccourcis`) | non écrite, journalisée (défense en profondeur) ; `<`/`>` échappés dans le XML |

⚠️ La table **`double_clic`** n'est pas concernée : elle contient des
**commandes** MA3, par conception — un profil importé reste l'équivalent d'une
macro, à ne charger que de source sûre.

## Un raccourci ne se corrige jamais sur la seule foi du fichier de MA3

`KeyboardShortCuts.xml` liste **une** liaison, pas la seule : MA3 en reconnaît
d'autres qui n'y figurent pas. Un écart avec ce fichier est une **information**,
jamais une preuve de faute — c'est pourquoi le contrôle `test_raccourcis_uniques` les signale en note
et n'échoue jamais dessus.

⚠️ **Payé une fois.** « Clear » a été « corrigé » de `Delete` en `Backspace` au
motif que les deux profils installés disaient Backspace pour le KeyCode OOPS.
**Régression immédiate** : `Ctrl+Z` fonctionnait parfaitement sur la console
(appui court = pas en arrière, appui long = menu). Le comportement observé sur la
console prime sur le fichier.

## Set valait « o », le raccourci de Off — le pire des deux

`Set` a été réglé un temps sur `o`, c'est-à-dire **exactement** le raccourci de
`Off` quinze lignes plus bas dans la même table. Un bouton réglé
sur Set **coupait donc l'executor** au lieu d'ouvrir la saisie de valeur : il ne
faisait pas *rien*, il faisait *autre chose* — le mode de panne le plus coûteux.

Trouvé en comptant les doublons de la table (un seul : « o » ×2), puis tranché
par le profil de raccourcis ACTIF de MA3 : `SET=Q`, `OFF=O`. C'est « Off » qui
avait raison. Le contrôle `test_raccourcis_uniques` interdit désormais tout doublon.

## Conflits de disposition clavier : Align et Assign

Deux valeurs ne sont pas celles qu'on attendrait, et c'est délibéré :

| Token | Valeur | Pourquoi pas l'évidente |
|---|---|---|
| `Align` | `Ctrl+B` | `Ctrl+A` pose problème dans MA3 selon la disposition (AZERTY/QWERTY) ; remappé ainsi dans le profil MA3 |
| `Assign` | `Ctrl+Alt+V` | `Alt+A` entrait en conflit avec « Camera Set Pivot » en vue 3D |

## « Next Page » : le token est la COMMANDE, pas le libellé de touche

Le token est `Next Page` — la commande MA3 valide de la doc officielle — et la
table le traduit en frappe `pageup`. Résultat : **le même bouton marche par les
deux chemins sans configuration.**

- mode console → frappe `PageUp` / `PageDown` (relevés sur la Command Section)
- OSC pur → la commande « Next Page » part telle quelle

⚠️ Le nommer « Page+ » aurait cassé le second cas : ce n'est pas une commande
valide en ligne de commande, seulement un libellé de touche. 🔎 `Previous Page`
en OSC reste **non vérifié** ; la frappe, elle, l'est.

## Les touches laissées VIDES exprès

`Fix`, `Temp`, `Top`, `View`, `Effect`, `Macro`, `Executor` n'ont **aucun**
raccourci clavier dans MA3 (vérifié dans sa table). Elles sont laissées vides,
pas retirées :

- elles apparaissent dans la carte Mode console, donc l'utilisateur voit
  qu'elles existent et peut y mettre son propre raccourci s'il en définit un ;
- en OSC pur elles fonctionnent déjà (le token part comme commande) ;
- en mode console sans raccourci, elles restent sans effet — **limite de MA3,
  pas de l'app**.

## Le nom vient de l'ÉTIQUETTE, pas du mot-clé — Exec, SelFix, Highlt

Piège de la même famille que « Focus » → « Focus1 ». Vérifié dans le manuel
installé :

| Écrit | Réel | Ce qui se passait |
|---|---|---|
| `Exec` | **`Executor`** | La TOUCHE de MA3 s'appelle bien « Exec » (manuel : « Press MA + X16 \| Exec »), mais le mot-clé de commande est `Executor`. Un bouton réglé sur « Exec » était **mort** : ni mot-clé valide, ni raccourci clavier |
| `SelFix` | **`SelectFixtures`** | idem, le mot-clé complet |
| `Highlt` | *(retiré)* | DOUBLON de `Highlight`, même frappe « h », et inexistant comme mot-clé |

Les profils existants sont migrés automatiquement (`TOKENS_RENOMMES`).

## Pourquoi « + » n'est pas dans TOKEN_VERS_KEYCODE

L'app note cette touche « + » (le pavé numérique, identique sur toutes les
dispositions) ; MA3 nomme la même touche `kpAdd`, et réserve `Equal` au clavier
principal. Les deux disent la même chose sous deux noms, **mais l'app ne sait
pas le prouver** — et l'ajouter faisait écrire « + » PAR-DESSUS « Equal », donc
perdre le « + » du clavier principal. Vu au banc d'essai, avant d'atteindre la
vraie console.

⚠️ Tant qu'on n'a pas la table d'équivalence des noms de touches de MA3, on n'y
touche pas : **ça fonctionne déjà.**

⚠️ Au passage : `GO_PLUS` et `GO_MINUS` **n'existent pas** dans MA3 — inventés
par symétrie avec les noms de l'app. Le fichier réel dit `GO` et `GOBACK`. Ces
deux touches passaient donc pour inconnues de MA3, donc n'étaient jamais
comparées ni envoyées.

## Les écarts assumés : un mécanisme vide, et c'est un résultat

`ECARTS_ASSUMES` permet de ne PAS pousser une touche vers MA3 quand l'app tape
volontairement autre chose et que ça marche. **Il est vide aujourd'hui.**

« Oops » y a figuré une demi-journée, au motif que l'app tapait `Ctrl+Z` quand
MA3 déclarait `Backspace`. En lisant le fichier COMPLET, la vérité est apparue :
**MA3 accepte plusieurs raccourcis pour un même KeyCode**, et OOPS en a bien
deux — `Ctrl+Z` ET `Backspace`. Il n'y avait jamais eu d'écart ; c'est le
parseur qui n'en gardait qu'un.

⚠️ **L'exclusion suit la VALEUR, pas le token.** La version précédente excluait
le token quoi qu'il arrive : « Assign » remplacé par Ctrl+Alt+B, clic « Envoyer
les raccourcis »… et rien ne partait, pendant que le bouton affichait « MA3 est
déjà d'accord ». Un réglage avalé en silence, doublé d'un message faux. Une
entrée de trop ici **supprime la possibilité de modifier la touche**.

## RACCOURCIS_CORRIGES : ne corriger que ce qui est DÉMONTRÉ faux

Cette table remet droit un défaut faux **déjà enregistré dans un profil**, et
seulement s'il est resté à sa valeur d'origine — si l'utilisateur a mis autre
chose, c'est son choix et on n'y touche pas.

Un simple `setdefault` ne suffisait pas : la clé EXISTE déjà dans les profils
enregistrés, avec la mauvaise valeur. Sans cette table, corriger un défaut
n'aurait profité qu'aux profils NEUFS — le piège rencontré avec « Next Page ».

⚠️ **N'y inscrire QUE des défauts démontrés faux.** « Oops : Ctrl+Z → Backspace »
y a figuré une heure, et c'était une régression (voir plus haut). Un écart avec
`KeyboardShortCuts.xml` ne suffit PAS : il faut que la touche soit constatée
cassée, ou qu'elle fasse le travail d'une autre.

## Double-appui → commande MA3 (table `double_clic`)

**Deux appuis rapprochés (≤ 0,45 s, `DOUBLE_APPUI_S`) sur la MÊME touche
envoient une commande MA3 dédiée en OSC** — indépendamment de ce que fait
l'appui simple sur cette touche. Défaut : **Menu ×2 → `SaveShow`**, comme sur
une command wing physique.

⚠️ **Ce que ce mécanisme n'est PAS.** La commande de double-appui part en OSC
(`/cmd`, comme n'importe quelle commande composée), **jamais par une frappe
clavier relayée** — contrairement à la colonne « Raccourci clavier » du même
tableau. Elle attend donc un **mot-clé MA3 complet** (`SaveShow`, `Highlight`,
son abréviation `Hi`…), pas une touche (`H`, `F5`…). Confusion déjà vécue : `H`
mis en pensant activer Highlight — MA3 a reçu la commande `H`, qui est
l'**abréviation du mot-clé `Help`** (manuel MA3,
`keyword_help.html` : *« Type the shortcut H »*), pas de Highlight (dont
l'abréviation est `Hi`, pas `H` — `keyword_highlight.html`). Le champ de
l'interface (onglet Touches) porte un placeholder et une info-bulle pour éviter
ce piège, en plus de cette section.

**Indexé par TOKEN** (`"Menu"`), **pas par code bouton brut** (`"0x05"`). Une
première version indexait par le code : un défaut réel, puisque **ce code est
propre à chaque wing** (`CONTRIBUTING.md` : « chaque wing est différente ») —
une autre wing peut avoir un code différent pour Menu, ou 0x05 sur un tout autre
bouton. Indexer par token
fait suivre le double-appui au BOUTON tel qu'assigné, jamais à sa position
physique. `wing_mapper.migrate_profile()` convertit les profils à l'ancienne
forme (`{"0x05": "SaveShow"}` → `{"Menu": "SaveShow"}`) via le mapping
`buttons` de CE MÊME profil — donc vers le token qu'IL a réellement à ce code,
pas une valeur supposée.

**Détection** (`wing_boutons.py::handle_button_bridge`) : le token du bouton
est résolu AVANT de décider quoi faire du double-clic (il faut le connaître
pour distinguer un `__ENCn_PUSH__`, qui a son propre mécanisme de bascule de
groupe 5-8, des autres boutons). Au premier appui, le flux normal s'exécute
sans savoir qu'un second va suivre — retarder chaque appui simple pour
« attendre de voir » introduirait une latence perceptible sur TOUS les appuis,
pas seulement les doubles. Au second appui dans la fenêtre, la fonction
retourne AVANT le traitement normal (mode console compris) et envoie la
commande de double-appui à la place.

⚠️ **Effet de bord du premier appui + correctif Escape.** Sur Menu
spécifiquement : le premier appui du double-clic tape quand même son F12 normal,
qui OUVRE l'écran Menu de MA3, avant que le second appui n'envoie `SaveShow`.
`SaveShow` sauvegarde mais ne referme pas cet écran déjà ouvert (« le menu reste
ouvert »). Corrigé en envoyant un `Escape` (tap, `enqueue_key`) juste après la
commande de double-appui. Escape est un « coup sec » sans effet de bord s'il n'y
a rien à fermer — envoyé pour TOUTE commande de double-appui, pas seulement
`SaveShow`. Non-régression vérifiée : un appui SIMPLE sur Menu ouvre toujours
l'écran normalement (le code qui envoie Escape est dans la branche `double`
uniquement) ; un appui simple sur une touche verbe du mode console (`Store`)
tape toujours sa frappe normalement, sans interférence.

**UI** (onglet Touches, colonne « Double-appui → commande MA3 ») : texte libre
par bouton, persistant dans le profil (`POST /api/double_clic`), vide =
désactivé (comme `console_keys`). Absent pour `__ENCn_PUSH__` (roues) : leur
double-clic est câblé en dur sur les groupes 5-8, pas configurable ici — voir
`FADERS_ENCODERS.md`.

⚠️ **Ne pas re-supprimer ce mécanisme en le croyant redondant.** Il l'a été
une fois, au motif que « Menu ×2 suffit désormais nativement dans MA3 » — écrit
comme un fait, sans preuve. Vérification faite ensuite : MA3 a **bien** un Quick
Save natif sur double-appui Menu (`sfh_save.html` : *« Pressing Menu 2x quickly
also creates a Quick Save »*), **mais il ne se déclenche QUE par le bouton Menu
à l'écran (souris)** — jamais par la frappe `F12`. Vérifié sur le clavier
physique du Mac, MA3 au premier plan, sans aucun relais : double-`F12` produit
deux entrées `Menu "MenuSelector"` dans l'historique de commande MA3, jamais un
`SaveShow`. Le relais maison (commande OSC `SaveShow` au double-appui) reste
donc **nécessaire**.

⚠️ **La casse n'était PAS corrigée à l'enregistrement** (corrigé le
13/09/2026) : `POST /api/double_clic` stockait la commande telle quelle,
contrairement à `POST /api/assign` qui applique `core.corriger_casse()`
depuis longtemps. Un mot-clé mal capitalisé (`saveshow` au lieu de
`SaveShow`) échoue en SILENCE — la commande de double-appui part justement en
OSC direct, jamais par une frappe relayée, donc exactement aussi exposée à ce
piège qu'une assignation normale. Corrigé : même correction de casse, même
convention de journal que `_post_assign` (`journal.console.double_appui_casse`
si une correction a eu lieu). Contrôle `test_double_clic_casse`
(smoke_raccourcis.py, §59).

### `cmd_buf` : lecture et écriture doivent rester cohérentes (13/09/2026)

Le buffer de commande du mode bridge (`STATE["cmd_buf"]`, Store/chiffres/
Please, voir `wing_boutons.handle_button_bridge`) est lu ET écrit depuis
**deux endroits distincts qui ne se coordonnaient pas** : `handle_button_bridge`
elle-même (une frappe en cours) et `POST /api/mode` (`_post_mode`, qui remet
`cmd_buf` à `""` au passage en mode bridge). `handle_button_bridge` lisait
`cmd_buf` une seule fois, tout en haut de la fonction, sous verrou — puis
écrivait dessus bien plus loin, HORS verrou, sur cette valeur potentiellement
périmée ; `_post_mode`, lui, n'écrivait jamais sous verrou du tout. Une frappe
en cours pendant un changement de mode pouvait donc faire réapparaître une
commande périmée juste après la remise à zéro voulue par `_post_mode`.

**Corrigé** : chaque écriture de `cmd_buf` dans `handle_button_bridge` relit
`STATE["cmd_buf"]` fraîchement et écrit dans le MÊME bloc `with etat.E.LOCK:` —
jamais sur une valeur lue plus tôt dans la fonction. `_post_mode` entoure de
même toutes ses écritures de `STATE` (`mode`, `resume_mode`, `last_event`,
`cmd_buf`) de `etat.E.LOCK`. Vérifié par AUDIT DE SOURCE, pas par un contrôle
comportemental : la fenêtre de course tient en quelques instructions, trop
étroite pour qu'un test à quelques threads l'expose de façon fiable via le
seul GIL (même limite déjà rencontrée pour le verrou de `connect_wing()` —
voir `docs/ARCHITECTURE.md`). Contrôle `test_cmd_buf_verrouille`
(smoke_raccourcis.py, §58).

## Horodatage du dernier envoi réussi des raccourcis

**Rien ne disait si le bouton « ⌨ Envoyer les raccourcis vers MA3 » (onglet
Touches) avait déjà été cliqué.** Un utilisateur qui installe le plugin puis
oublie cette étape voit une wing qui semble fonctionner (l'OSC pur marche
déjà) mais dont les touches « mode console » (Store, chiffres, Please…)
restent muettes dans MA3 — sans le moindre signal.

`SETTINGS["shcuts_horodate"]` (epoch, `time.time()`, `None` = jamais) est posé
par `_marquer_shcuts_envoyes()` (wing_raccourcis.py) aux DEUX points de succès
de `shcuts_envoyer()` — « déjà d'accord » (`inchange: true`) ET « vraiment
envoyé ». **Réglage MACHINE (`etat.E.SETTINGS`), jamais le profil** : c'est
CE grandMA3, sur CETTE machine, qui a reçu la table à cet instant précis — un
profil qui l'embarquerait mentirait dès qu'on l'importe sur une autre
installation. Persisté par `save_settings()`, exposé dans `/api/status`
(coût nul : c'est un champ de plus dans une réponse déjà polluée, pas un
appel réseau de plus — contrairement à `/api/shcuts`, qui compare à la sonde
et n'est donc PAS appelé à chaque poll).

Affiché à deux endroits, un seul calcul (`formatHorodateRelatif()`,
`ui/touches.js`) :
- **Onglet Touches**, `#shcutsHorodate` — sous `#shcutsEtat`, mis à jour à
  CHAQUE poll (400 ms) pour que « il y a 2 min » devienne vraiment « il y a
  3 min » sans action de l'utilisateur. Volontairement séparé de
  `#shcutsEtat` : celui-ci n'est repeint que par `shcutsRafraichir()` (au
  chargement ou après un clic), sa comparaison à la sonde étant plus coûteuse.
- **Assistant de mise en route** (Paramètres → carte Firmware), étape
  « Envoie les raccourcis clavier vers grandMA3 » → voir
  `docs/GRANDMA3_SYNC.md`, section sur l'assistant.

⚠️ « Jamais envoyés » est mis EN ÉVIDENCE (couleur d'alerte), pas juste
affiché neutre — c'est le cas qui doit sauter aux yeux, exactement le
problème qui a motivé cet ajout.

Contrôle `test_shcuts` (smoke_raccourcis.py, §19-e) : vérifie que l'horodate
avance sur un envoi réel ET sur un « déjà à jour », qu'elle est bien écrite
sur disque (settings.json, dans un bac de test — jamais le vrai fichier de la
machine qui lance le test), et se RÉINJECTE : `_marquer_shcuts_envoyes()`
neutralisée → l'horodate doit rester figée, sinon le contrôle ne prouverait
rien.

### Capture d'écran réelle dans l'assistant

L'étape « Envoie les raccourcis » embarque une capture d'écran RÉELLE du
bouton `#btnShcuts` (pas une image inventée) — prise avec l'app en marche,
encadrée en rouge pour le désigner sans ambiguïté, en data URI directement
dans `wing_ui.html` (pas de nouvelle route serveur ni de fichier statique
séparé pour une seule image d'onboarding).

## Affecter une touche : validation et renumérotation (25/09/2026)

`POST /api/assign` passe par `wing_boutons.affectation(body)`, qui décide de
l'action à mener (`poser`, `effacer` ou `rien` quand le champ a été vidé).
`type` doit être `cmd`, `exec`, `push` ou `clear`, et `key` doit être un code de
touche valide. Une entrée invalide donne une réponse **400** traduite, sans
rien modifier dans le profil. La renumérotation d'une rangée d'executors
(`/api/bouton/rangee`) est faite par
`wing_boutons.renumeroter_rangee` : l'ordre physique est conservé et l'appelant
tient `etat.E.LOCK`. Ces deux fonctions sont sorties de `wing_handler.py`
(audit du 25/09/2026, D3). Contrôle `test_validation_entrees`.
