# GRANDMA3 SYNC — parler à la console, et l'écouter

> 🇫🇷 This reference document is in French. Translation contributions are
> welcome — see `CONTRIBUTING.md`.

**Ce fichier = tout ce qui traverse la frontière vers MA3** : configuration
OSC, ce que la console renvoie, et la sonde Lua qui tourne DEDANS.

🚫 **Rien d'USB ici** — voir `HARDWARE.md`.

⚠️ **Un mot-clé MA3 ne s'invente pas.** Il se vérifie dans le manuel installé
(`<install MA3>/gma3_<version>/shared/language/HTML`, une page `keyword_*.html` par mot-clé).
Un nom faux, ou mal capitalisé, est rejeté **en silence**.

> 🧭 **Index de toute la doc technique** : [`README.md`](README.md) (quelle
> question → quel fichier). Avant de toucher au code : [`CONTRIBUTING.md`](../CONTRIBUTING.md)
> à la racine (méthode, règles de modification, pièges).
>
> ⚠️ **Deux protocoles à ne pas mélanger** : l'USB de la wing (`HARDWARE.md`) et
> l'OSC vers MA3 (`GRANDMA3_SYNC.md`). Quand l'un casse, on doit pouvoir lire
> l'autre sans le traverser.

---

## ✅ MA3 ne répond pas — la liste à vérifier, dans l'ordre

Établie après un faux diagnostic qui a fait redémarrer grandMA3 plusieurs fois
pour rien. **Suivre l'ordre** : chaque point est plus rare que le précédent.

### 0. 🔴 LE RÉSEAU DE MA3 EST-IL ACTIVÉ ? (Menu → Network)

> ✅ **Cause d'un cas réel, confirmée** : `MA-Net Interface` réglé sur
> l'interface réellement connectée (ici le Wi-Fi) → MA3 a ouvert le port
> **immédiatement**, sans redémarrage. Chaîne complète vérifiée dans la
> foulée : `/cmd "Page 2"` → la sonde voit page 2 → page remise à 1. **MA3
> exécute.**

**À vérifier AVANT tout le reste.** MA3 a un **interrupteur réseau global**,
totalement indépendant de la page OSC. S'il est coupé, MA3 n'ouvre **aucun
socket réseau** — la config OSC peut être parfaite, `Enable Input` sur Yes,
rien ne se passera.

> Manuel MA3 installé (`network.html`) : *« The network needs to be enabled to
> communicate. Turning network On or Off is done from the Network menu. In the
> **lower right corner** of the network menu, there is a button to toggle the
> network connection. **If the icon is red, the network is turned Off. If it is
> green, it is On.** »*

👉 **Menu → Network → bouton d'alimentation en bas à droite. Fond rouge = coupé.**

⚠️ **Et s'il refuse de passer au vert, regarder la colonne `IP` de la station.**
Cas réel : elle affichait **« No Cable »**, Type « Undefined », et l'icône
**MA-Net Interface** était rouge.

**Cause** : `MA-Net Interface` pointait vers un adaptateur **filaire non
branché**. Sur cette machine, une seule interface était connectée :

| Interface | Nature | IP | État |
|---|---|---|---|
| **en0** | **Wi-Fi** | 192.168.50.66 | ✅ active |
| en4, en5, en6, en11 | Ethernet / USB LAN | — | inactive |
| en1–en3 | Thunderbolt | — | inactive |

**Remède** : dans le menu Network, mettre `MA-Net Interface` sur l'interface
réellement connectée (ici le Wi-Fi, 192.168.50.66), **puis** activer le réseau.

🔍 **Le diagnostic en une commande, côté Mac** — quelle interface a un lien :

```bash
for i in $(ifconfig -l | tr ' ' '\n' | grep -E '^en[0-9]+$'); do
  printf "%-5s %-16s %s\n" "$i" \
    "$(ifconfig $i | awk '/inet /{print $2}')" \
    "$(ifconfig $i | awk '/status:/{print $2}')"
done
```

⚠️ Beaucoup d'utilisateurs MA3 dédient un adaptateur **USB-Ethernet** au MA-Net.
Débranché, MA3 affiche « No Cable » et **tout le réseau reste coupé** — y compris
l'OSC, qui n'a pourtant rien à voir avec le MA-Net.

**Le symptôme qui doit y faire penser** — cas réel :

| Ce qu'on observe | |
|---|---|
| MA3 tourne, la sonde le lit | ✅ |
| `Enable Input` = Yes, ligne OSCData sur le bon port, Receive + Receive Command = Yes | ✅ |
| **Aucun socket sur le port OSC** (`lsof -nP -iUDP:8000` vide) | ❌ |
| Relancer MA3 n'y change rien | ❌ |

⚠️ **Ne pas chercher ailleurs tant que ce point n'est pas vérifié.** Sur le cas
réel, on a successivement soupçonné la config OSC (correcte), un VPN (réfuté :
coupé, sans effet), et le « Preferred IP » — trois pistes, plusieurs
redémarrages de grandMA3, avant de lire le manuel installé. **Le manuel local
fait autorité et il est à portée de `grep`.**

---

### 1. Le message de l'app est-il fiable ?

⚠️ **Le diagnostic « Receive Command est désactivé » a déjà été FAUX.** Il
criait dès qu'**une seule** ligne OSCData avait Receive Command à No — y compris
la ligne de SORTIE, qui n'en a pas besoin. Config typique :

| Ligne | Port | Receive | Receive Command | Rôle |
|---|---|---|---|---|
| OSCData 1 | 8001 | No | **No** ← normal | MA3 **envoie** vers l'app |
| OSCData 2 | **8000** | Yes | **Yes** ← c'est celle-ci qui compte | MA3 **reçoit** de l'app |

Corrigé : seule la ligne portant le **port sur lequel l'app envoie** est jugée.
Contrôle `test_diagnostic_osc`, qui rejoue cette configuration exacte.

### 2. La ligne du port 8000 (Menu → In & Out → OSC)

| Réglage | Valeur | Pourquoi |
|---|---|---|
| **Port** | `8000` | doit correspondre à `MA3_PORT`. Une ligne DOIT porter ce port |
| **Receive** | `Yes` | sans lui MA3 ne lit rien sur ce port |
| **Receive Command** | `Yes` | **c'est lui qui exécute les `/cmd`**. Sans lui, MA3 reçoit et ignore |
| Destination IP | `127.0.0.1` | MA3 et l'app sur le même Mac |
| Mode | `UDP` | |

### 3. Le bandeau du haut de la fenêtre OSC

| Réglage | Valeur | Piège |
|---|---|---|
| **Enable Input** | activé | **obligatoire** — c'est lui qui autorise la réception |
| **Interface** | **jamais `<None>`** | `lo0 (127.0.0.1)` convient pour du local. ⚠️ Ce réglage **saute parfois au chargement d'un show** — première chose à revérifier si tout marchait hier |
| Enable Output | activé | nécessaire seulement pour le retour vers l'app |

### 4. MA3 écoute-t-il vraiment ? (vérifiable hors de l'app)

```bash
netstat -an -p udp | grep '\.8000'      # une ligne = MA3 écoute
lsof -nP -iUDP:8000                     # qui tient le port
```

Rien du tout alors que MA3 tourne et que la config est bonne ⇒ MA3 n'a pas
rebindé son port. **Relancer grandMA3** est alors justifié — mais seulement à
ce stade, pas avant.

### 5. Une VM **ou un VPN** est-il monté ?

Corrélation constante, jamais démontrée causalement : à chaque fois que MA3
s'est retrouvé « lancé mais n'écoute pas », des interfaces réseau s'étaient
ajoutées sous lui — **Parallels** dans deux cas, un **VPN** dans un autre.
➜ Le couper **puis** relancer MA3.

#### 🔬 Un cas mesuré — à relire avant de rechercher

MA3 lancé (`app_gma3`, pid 4583), sonde vivante, et une config **correcte** :

```
entree: true          ← Enable Input activé
OSCData 1 · port 8001 · recoit false · rec_cmd false   ← MA3 envoie
OSCData 2 · port 8000 · recoit true  · rec_cmd true    ← MA3 devrait recevoir
```

Et pourtant, **aucun socket sur 8000** :

```
lsof -nP -p 4583 -a -iUDP
  UDP *:8005    UDP *:53020   UDP *:59592   UDP *:10669   UDP *:61541
```

Présents ce jour-là, et **contradictoires entre eux** :

| Réglage / fait | Valeur |
|---|---|
| `Preferred IP` dans MA3 | `10.0.0.0/8` |
| `Interface` dans MA3 | `lo0 (127.0.0.1)` |
| VPN monté | `utun4` en **10.5.0.2** — soit **dans** 10.0.0.0/8 |

Le « Preferred IP » désignait donc le VPN pendant que l'« Interface » disait
lo0. **Hypothèse non tranchée** : MA3 choisit une interface d'après le Preferred
IP, ne trouve pas de quoi binder de façon cohérente, et n'ouvre pas le port.

#### ❌ Hypothèse VPN — RÉFUTÉE sur ce cas

VPN coupé (plus aucune `utun` avec adresse IPv4, vérifié), grandMA3 relancé
plusieurs fois : **MA3 n'ouvre toujours pas le port 8000**. La corrélation
VM/VPN reste vraie pour d'autres cas, mais **elle n'explique pas celui-ci**.
Ne pas s'y arrêter.

#### 📌 Ce qui est ÉTABLI sur ce cas (mesuré deux fois, méthodes indépendantes)

| Fait | Méthode |
|---|---|
| MA3 écoute `8005` et `10669`, **jamais 8000** | `lsof -p <ma3> -a -iUDP`, et refus ICMP sur socket UDP connecté |
| Ces deux ports sont **stables** entre deux lancements de MA3 | comparaison pid 4583 / pid 13990 |
| **`8005` n'est PAS l'entrée OSC** | `/cmd "Page 2"` envoyé sur 8005 → la sonde voit toujours page 1. Aucun effet |
| La sonde lit pourtant `entree: true` et une ligne `port 8000, recoit: true, rec_cmd: true` | sonde Lua |

Autrement dit : **MA3 se croit à l'écoute et ne l'est pas.** (Sur ce cas
précis, la cause était le **réseau global coupé** — point n°0. La piste
« Preferred IP » désignant une interface disparue était cohérente mais n'a pas
tranché ; ne pas s'y arrêter.)

**Si le réseau global est vert et MA3 n'écoute toujours pas**, essayer dans cet
ordre, en revérifiant `lsof -nP -iUDP:8000` après chaque étape (**une seule
variable à la fois**) :

1. Couper VPN / VM, relancer MA3.
2. **`Preferred IP` → une valeur qui correspond à une interface réelle**
   (`127.0.0.0/8` si `Interface = lo0` et destination `127.0.0.1`, ou le
   sous-réseau de l'interface active). Relancer MA3.
3. Sinon, **`Interface` → l'interface active** au lieu de `lo0`. Relancer MA3.
4. Sinon, basculer **Enable Input** sur No puis Yes (force un rebind sans
   relancer MA3) et revérifier `lsof` aussitôt.

### 6. La sonde Lua est-elle vivante ?

Sans elle, l'app ne peut **pas** lire la config de MA3 et ne doit rien affirmer :
elle liste les points à vérifier au lieu de désigner un coupable. Si l'app dit
« la sonde ne remonte pas la configuration OSC », relancer le plugin dans MA3
(l'exécuter deux fois — la 1ʳᵉ le stoppe s'il tournait, la 2ᵉ le relance).

> ⚠️ **Ne pas coller un numéro de slot dans les messages utilisateur.**
> L'installation Wing Bridge pose l'amorce en `Plugin 3`, mais un plugin déjà
> présent chez l'utilisateur peut être ailleurs. Le bouton « Relancer le
> plugin » de l'app vise donc le **nom** (`Plugin "WingLoader"`, syntaxe
> `Plugin ["Nom" or Numéro]` du manuel 2.5), pas le numéro ; les textes
> disent « relance le plugin », sans chiffre.

> 🔁 **Le plugin est à RELANCER après CHAQUE lancement de grandMA3.** La sonde
> ne survit pas au redémarrage du process : l'état global `_G.WingBridgeEtat`
> **et** le `Timer` qui écrit le fichier meurent avec MA3. Au rechargement du
> showfile, MA3 recompile le code du plugin (cf. `keyword_reloadallplugins.html`,
> « When the show file is loaded, the external Lua files … are reloaded ») mais
> **ne l'EXÉCUTE pas** — lancer un plugin passe toujours par le mot-clé `Plugin`
> ou un appui. **Vérifié dans le manuel installé** : `plugins.html`,
> `keyword_plugin.html`, `keyword_reloadallplugins.html` et la liste
> `grandMA3_lua_functions.txt` ne documentent **aucun** démarrage automatique de
> plugin au chargement du show (pas de `autostart`, `OnLoad`, `ExecuteOnLoad`,
> ni propriété d'objet `Plugin` en ce sens). Le seul hook proche, `HookObjectChange`,
> suppose un plugin **déjà en cours**. Conséquence pratique : après fermeture /
> réouverture de MA3, l'app affiche pendant ~2 min (péremption + fichier figé
> d'une session passée) le message directif **« Sonde MA3 arrêtée : relance le
> plugin dans grandMA3 »** jusqu'à ce que l'opérateur le fasse.
> Si un jour MA Lighting documente un vrai hook de chargement, ré-ouvrir la
> question.

### 6 bis. Champs publiés par la sonde (après le ménage v13)

Le fichier d'état (`wingbridge_state.json`) contient, à la racine :

| Champ | Contenu |
|---|---|
| `version` | numéro de sonde (13) — sert à vérifier un redéploiement |
| `horodate` | epoch `os.time()` de l'écriture (entier exact depuis v12) |
| `tours`, `erreurs`, `duree_ms` | compteurs internes : relevés faits, `pcall` ratés, coût du dernier relevé |
| `page` | `{no, nom, addr}` de la page executor courante |
| `executors[]` | `{no, nom, fader, texte, fonction, touche, actif, objet, classe, tourne, active, cue}` |
| `masters` | `{selected:{}, grand:{}, speed:{}}` — valeur 0..100 par `no` (v9+) |
| `raccourcis[]` | `{no, keycode, frappe}` — `keycode` = garde interne, `frappe` = seul champ lu (v13 : `executor`/`special` retirés) |
| `raccourcis_via`, `raccourcis_note` | voie d'accès qui a marché / note d'échec |
| `encodeurs` | `{selection, attribut, feature, fixture, canaux:[{nom, subattribut, index}], note}` (v13 : `feature_enfants`, `fixture_index`, `canaux[].feature` retirés) |
| `osc` | `{via, entree, sortie, configs:[{nom, port, recoit, envoie, rec_cmd, env_cmd, dest}]}` (v13 : `interface` retiré) |
| `*_note` | une note d'échec par lecture optionnelle (`masters_note`, `osc_note`…) — journalisée une fois par l'app (`wing_ma3.ma3_etat`) |

⚠️ **Tout champ ajouté ici doit être recopié dans `wing_ma3.ma3_etat()`
(`base.update(...)`)**, sinon la sonde le publie et il n'atteint jamais l'app.

### 6 ter. Les 5 situations du plugin dans l'interface

L'app ne se contente plus de « sonde active / pas active ». Elle croise **trois**
signaux :

- `ma3_reachable()` — grandMA3 est-il joignable ? (`off` / `muet` / `ok`)
- `plugin_present()` (`wing_ma3.py`) — les deux `.lua` (`wingloader.lua` **et**
  `wingbridge.lua`) sont-ils posés dans
  `<base MA3>/gma3_library/datapools/plugins/` ? Test de **fichiers**, pas de
  process — **lisible même grandMA3 éteint** (les fichiers restent sur le
  disque). Exposé dans `/api/status` → `sonde.present`.
- la sonde tourne-t-elle ? (`ma3_etat()["actif"]`)

| MA3 joignable | fichiers `.lua` | sonde `actif` | Pastille « Sonde MA3 » | Alerte défilante |
|---|---|---|---|---|
| oui | — | oui | ● plugin actif — N executors · Page X | — |
| oui | oui | non | ⚠️ plugin inactif — relance-le dans grandMA3 | « plugin inactif — relance-le » |
| oui | non | non | ⚠️ plugin non installé — Paramètres → 🎛️ | « plugin non installé » |
| non | oui | — | ○ plugin installé — grandMA3 éteint | aucune |
| non | non | — | ○ plugin non installé — grandMA3 éteint | aucune |

⚠️ « installé » = **fichiers présents sur le disque**. Ça ne garantit pas que
l'entrée du pool soit dans le showfile courant : un show importé sans copier les
`.lua`, ou l'inverse, existe. Si MA3 est relancé et que la relance ne charge
rien malgré les fichiers, le message de `relancer_plugin()` (« … réinstalle le
plugin ») prend le relais.

⚠️ **Aucun numéro de slot dans les messages utilisateur.** L'install Wing Bridge
pose l'amorce en `Plugin 3`, mais l'emplacement d'un plugin déjà présent varie.
`relancer_plugin()` exécute donc l'amorce **par son nom** —
`/cmd 'Plugin "WingLoader"'` (syntaxe `Plugin ["Nom" or Numéro]`,
`keyword_plugin.html` 2.5) — et les textes disent « relance le plugin », sans
chiffre.

**Conséquences UI** (`ui/bridge.js`, `ui/parametres.js`) :

- Le `<details>` « Installer le plugin » de la carte grandMA3 ne s'ouvre **tout
  seul** que dans le cas *fichiers absents*. « Plugin inactif » ne le déplie
  pas — une relance suffit.
- **Bouton « 🔁 Relancer le plugin dans grandMA3 »**, dans la **carte grandMA3**
  juste sous la pastille du plugin, visible seulement quand *fichiers posés +
  sonde inactive + grandMA3 joignable*. Endpoint `POST /api/plugin/relaunch` →
  `wing_ma3.relancer_plugin()` : un seul `/cmd 'Plugin "WingLoader"'` en OSC (par
  le NOM de l'amorce, pas un numéro de slot), pas de re-copie, pas de ré-import,
  pas de `SaveShow`.
- L'encart « Installer le plugin » de la **carte 🧩 Firmware** ne sert plus qu'à
  la **mise en route** (firmware configuré + sonde inactive + fichiers PAS
  encore posés) : bouton **« 🧩 Installer automatiquement »**
  (`/api/plugin/install`, réinstallation complète). Dès que les fichiers sont
  là, il disparaît au profit du bouton « Relancer » de la carte grandMA3.

### 7. Le mot-clé envoyé existe-t-il ?

Si MA3 reçoit bien mais que **rien ne se passe sur une commande précise**, ce
n'est plus un problème de transport. Un mot-clé faux ou mal capitalisé est
rejeté **en silence**. Vérifier dans le manuel installé
(`<install MA3>/gma3_<version>/shared/language/HTML`, une page `keyword_*.html` par mot-clé).

## 🔧 Écouter ce que MA3 envoie — outil de diagnostic (sans interface)

Retiré de l'interface : un panneau que seul celui qui débogue l'app utilise n'a
pas sa place dans une app de régie. Il avait servi une fois à identifier une
boucle OSC (deux cues sautées par Go+), puis n'a plus été rouvert.

**Les endpoints restent** — ils ne coûtent rien tant que le port vaut 0 :

```bash
H='-H "Origin: http://127.0.0.1:8765" -H "Host: 127.0.0.1:8765"'

# démarrer l'écoute (choisir un port ≠ 8000, celui sur lequel MA3 écoute)
curl -s -X POST -H "Origin: http://127.0.0.1:8765" \
     -H "Content-Type: application/json" \
     -d '{"port": 8001}' http://127.0.0.1:8765/api/osc/listen

# voir ce qui arrive (adresses, nombre, dernière valeur, étendue, âge)
curl -s -H "Origin: http://127.0.0.1:8765" http://127.0.0.1:8765/api/osc/in

# vider la liste, puis arrêter
curl -s -X POST -H "Origin: http://127.0.0.1:8765" -d '{}' \
     http://127.0.0.1:8765/api/osc/listen/clear
curl -s -X POST -H "Origin: http://127.0.0.1:8765" \
     -H "Content-Type: application/json" \
     -d '{"port": 0}' http://127.0.0.1:8765/api/osc/listen
```

**Côté MA3, pour qu'il émette** : `Menu → In & Out → OSC` → `Enable Output`, et
sur une ligne OSCData mettre `Destination IP` = l'IP de ce Mac (ou `127.0.0.1`)
et `Send` = `Yes`. ⚠️ Choisir un **port différent** de celui d'envoi : sur la
même machine, 8000 est déjà celui où MA3 écoute. 8001 convient — l'app refuse le
port d'envoi pour éviter ce piège.

**À quoi s'attendre** : le retour natif de MA3 est indexé par **numéro de
séquence**, pas d'executor (adresses du type `/11.14.1.5.99`). Des retours plus
lisibles (`/Page/Fader/202`) existent mais demandent un plugin Lua dans MA3.

Si rien n'arrive : bouger un fader d'executor dans MA3 pour provoquer du trafic.

## Configuration grandMA3

### OSC — configuration validée (Menu → In & Out → OSC)

**Bandeau du haut :**
| Réglage | Valeur | Note |
|---------|--------|------|
| Preferred IP | `10.0.0.0/8` (défaut) | pas critique |
| **Interface** | l'interface réseau du Mac (ex. `en0`) | **jamais `<None>`** ⚠️ saute parfois au chargement d'un show — 1ʳᵉ chose à vérifier si plus rien ne répond |
| **Enable Output** | activé | recommandé (feedback futur vers l'app) |
| **Enable Input** | activé | **obligatoire** — c'est lui qui autorise la réception |

**Ligne OSCData** (bouton *Insert New OSC Data* si la liste est vide) :
| Colonne | Valeur | Note |
|---------|--------|------|
| Destination IP | `127.0.0.1` | MA3 et l'app sur le même Mac. Sinon : IP de la machine qui fait tourner Wing Bridge |
| Mode | `UDP` | |
| Port | `8000` | doit correspondre à `MA3_PORT` du bridge |
| Prefix | *(vide)* | le bridge envoie `/cmd` sans préfixe |
| Data Pool / Page / Fader / Executor Knob / Key | défauts (`DataPool`/`Page`/`Fader`/`Encoder`/`Key`) | |
| Fader Range | `100` | correspond aux `/Page1/FaderN` 0-100 du bridge |
| Receive / Send | `Yes` / `Yes` | |
| **Receive Command** | `Yes` | **c'est lui qui exécute les `/cmd`** |
| Send Command | `Yes` | |
| Echo Input / Echo Output | `Yes` | facultatif (debug) |

**Cible OSC (IP + port) — réglable dans l'interface**, onglet **Paramètres →
« 🎯 Cible OSC »** (`POST /api/osc/target`, mémorisé dans `settings.json` :
`ma3_ip` / `ma3_port`). Rien à recompiler. Défaut : `127.0.0.1:8000`, MA3 et
l'app sur le même Mac — la configuration visée par le projet. La sonde Lua, elle,
écrit un fichier **local** : elle suppose de toute façon la même machine.

Adresses utilisées par le bridge :
- `/cmd` avec argument string (ex: `"Please"`, `"Go+ Exec 1.1"`, `"Menu"`)
- `/Page{N}/Fader{N}` avec entier 0-100

### Paramètres réseau MA3
- MA-Net Interface : `en0 (192.168.1.85)`
- Session créée localement (IdleMaster)

---


## Limitations OSC

### Encodeurs — comportement non natif
Via `/cmd`, les encodeurs ne peuvent envoyer que des commandes texte discrètes
(`Attribute <nom> at +N` par tick). Répliquer une vraie roue d'attribut
(contextuelle, proportionnelle, continue) n'est pas possible par OSC.

Une alternative **MIDI Remote** (CC relatifs via IAC Driver) a été explorée puis
**abandonnée** : aucune interface externe — OSC, MIDI, ni clavier USB — ne peut
lire la fonction réellement assignée à un executor ; seul le matériel reconnu
nativement par MA3 le peut (voir `docs/FADERS_ENCODERS.md`, « RÈGLE CRITIQUE »).

---


## Retour OSC de MA3 — ce que la console renvoie vraiment

**À l'origine, l'app était sourde** : elle ne faisait qu'émettre (seuls sockets
en réception = DMX sACN/Art-Net). D'où : LEDs qui ne reflètent pas MA3, aucune
notion de page, pas de fader pickup.

### Ce qui est en place — et ce que ça ne fait PAS

`osc_in_loop()` écoute un port configurable et **résume** ce qui arrive :
une ligne par adresse OSC (compteur, dernière valeur, types, source, âge).
**Aucune interprétation, aucune action déclenchée.** C'est délibéré : on veut
constater ce que MA3 envoie vraiment avant de construire dessus.

**Retiré de l'interface** (voir « Écouter ce que MA3 envoie » plus haut) — les
endpoints restent : `POST /api/osc/listen {port}` (0 = stop),
`POST /api/osc/listen/clear`, `GET /api/osc/in`. Port mémorisé dans
`settings.json` (`osc_in_port`, 0 par défaut = écoute désactivée).

**Garde-fou** : l'app REFUSE d'écouter sur le port d'envoi de MA3 quand la
cible est locale — sur la même machine c'est le port où MA3 écoute déjà.
Message d'erreur explicite. 8001 est le choix conseillé.

Robustesse vérifiée : un paquet non-OSC est signalé sous la pseudo-adresse
`<non-OSC>` plutôt qu'avalé en silence, et **ne tue pas le thread** (écoute
toujours fonctionnelle après). Garde-fou mémoire à 200 adresses distinctes.

### Résultats de l'observation

Config MA3 nécessaire (même machine) : **DEUX lignes OSCData**, car une seule
ligne ne peut pas servir les deux sens (un seul champ `Port`) :

| | Ligne « nos commandes → MA3 » | Ligne « retour MA3 → nous » |
|---|---|---|
| Destination IP | `127.0.0.1` | `127.0.0.1` |
| Port | `8000` | `8001` |
| Receive / Receive Command | `Yes` | `No` |
| Send / Send Command | `Yes` | `Yes` |

Piège vécu : avec une seule ligne sur 8000, MA3 s'envoie son retour **à
lui-même** (8000 = son propre port d'écoute) et on ne reçoit jamais rien.

**Format observé** (MA3 2.x) :

```
/14.14.1.6.<EXECUTOR>   [<fonction>, <état 1|0>, <libellé>]

00:07:15  /14.14.1.6.3    [Go+, 1, Sequence 3 1 Cue]    ← appui
00:07:15  /14.14.1.6.3    [Go+, 0, Sequence 3 2 Cue]    ← relâchement
00:07:29  /14.14.1.6.3    [Off, 1]
          /14.14.1.6.201  [FaderMaster, 3, 0.0]         ← fader, étendue 0.0 → 100.0
```

| Question | Réponse |
|---|---|
| Indexation | **par numéro d'EXECUTOR** — pas par séquence (les forums annonçaient `/11.14.1.5.<seq>`, faux ici) |
| Échelle des faders | **0 → 100**, identique à celle qu'on envoie |
| État des boutons | entier **1 = appui, 0 = relâchement** |
| Libellé + cue courante | oui, en clair, 3ᵉ paramètre |
| **Changement de page** | **AUCUN message** — résultat négatif net, vérifié |

**Conséquences :**
- **Fader pickup : FAISABLE** — on connaît la valeur réelle côté MA3 dans la
  même échelle. → implémenté, voir section dédiée.
- **LEDs d'état de séquence : ABANDONNÉ.** On reçoit les appuis/relâchements
  et le libellé, mais **aucun booléen « cette séquence tourne »** ni
  rafraîchissement périodique. Une séquence qui s'arrête seule ne serait pas
  signalée. Décision : ne pas construire dessus.
- **Suivi des pages : IMPOSSIBLE** par cette voie.

**✅ Résolu : le `Go+` qui avançait de 2 cues.**

Observé ici comme 1→2 puis 3→4 sur les libellés. **Cause : une BOUCLE OSC
entrée/sortie côté MA3** — une ligne OSCData dont la Destination pointe sur le
port d'écoute de MA3 lui-même, avec `Send = Yes`. Chaque action d'executor
partait en OSC puis **revenait dans MA3, qui l'exécutait une seconde fois**.
Confirmé par le forum MA Lighting (thread 68484, réponse d'un modérateur).

**Correction** : sur la ligne OSCData qui REÇOIT nos commandes (port 8000),
mettre `Send = No` et `Send Command = No`. Elle n'a pas à réémettre.

**Vérifié en réel** : un `Go+` avance désormais d'exactement une cue.

⭐ Ça clôt le vieux dossier « Go+ saute des cues aléatoirement », signalé au
tout début du projet et classé « comportement MA3 » faute de cause trouvée.
Ce n'était ni l'app, ni un caprice de MA3 : c'était cette configuration, et
elle affectait TOUTES les commandes d'executor, pas seulement celles de la
wing. Leçon : « c'est l'autre logiciel » n'est pas un diagnostic tant qu'on
n'a pas le mécanisme.

➜ Le retour OSC natif ne suffit pas (pas de changement de page, pas d'état
« cette séquence tourne »). C'est la **sonde Lua** qui a débloqué la suite —
section suivante.


## La sonde Lua MA3 — ce qu'elle débloque

**Les quatre fonctions enterrées sont débloquées** : LED reflétant l'état réel
de MA3, conscience de la page courante, rattrapage de fader, et avertissement
de désaccord sur la fonction d'un fader (en lecture seule).

### API MA3 — ce qui a été établi par l'expérience. NE PAS RE-SUPPOSER.

**Accès aux executors** — une seule voie marche :

| Tentative | Résultat |
|---|---|
| `page:Children()` parcouru avec `pairs()` | ✅ **la seule qui marche** |
| `GetExecutor(n)` | ⚠️ marche, mais **relatif à la page COURANTE** — rendait `nil` pour 101-240 tant que la page affichée était vide |
| `GetObject("Page 2.201")` | ❌ nil |
| `ObjectList("Page 2.*")` | ❌ 0 |
| `page:Ptr(i)` | ❌ nil, quel que soit i |

🪤 **`page:Count()` est la CAPACITÉ de la page (390), pas le nombre
d'executors.** Contresens qui a fait boucler la sonde dans le vide. La valeur
avait l'air plausible — c'est ce qui la rendait dangereuse.

🪤 **Ne jamais compter `Children()` avec `#`** : rend 0 sur une table à clés
non séquentielles, même pleine. `pairs()`, toujours.

**Lectures qui fonctionnent, sur l'executor :**

| Appel | Rend | Sert à |
|---|---|---|
| `ex:GetFader({})` | 0..100 | rattrapage de fader |
| `ex:GetFaderText({})` | `"42%"` | affichage |
| `ex.no` / `ex.name` | n° / nom de l'objet assigné | identification |
| `ex.fader` | `"Master"`, `"X"`, `"Temp"`… | **fonction réglée dans MA3** |
| `ex.key` | `"Go+"`, `"Flash"`… | fonction de la touche |
| `ex.object` | **poignée** de la séquence | accès à l'état |

🪤 **L'état de lecture se lit sur la SÉQUENCE, jamais sur l'executor :**
`ex:IsRunningPlayback()` rend **`nil`**, `ex.object:IsRunningPlayback()` rend
un booléen. Le piège aurait pu faire conclure « impossible », exactement comme
en OSC.

### Méthode qui a débloqué l'affaire

Cinq passes, chacune éliminant du définitif. Ce qui a fait la différence :

1. **`Dump()` avant toute hypothèse.** C'est lui qui a révélé en une ligne que
   la page n'avait qu'un enfant, alors que `Count()` disait 390.
2. **Ne jamais tester deux appels d'un coup.** `ToAddr(page:Ptr(1))` rendait
   `nil` sans dire lequel des deux échouait. Un test qui mélange deux appels
   ne prouve rien sur aucun des deux.
3. **Écrire le diagnostic dans un fichier**, pas dans la console — MA3 la fait
   défiler, et `Dump()` y imprime en plus de rendre sa chaîne.

### Pièges d'intégration MA3 (coûteux, tous vécus)

- **`ExportJson()` produit du JSON INVALIDE** (clés sans guillemets) — sa
  propre doc le prévient. On écrit le JSON à la main. Ne pas « simplifier ».
- **L'encodeur JSON écrit à la main doit formater les entiers en `%d`, jamais
  `%.6g`.** `%.6g` écrase tout entier de 7 chiffres ou plus en scientifique
  tronquée (`1787944439` → `« 1.78794e+09 »` → `1787940000` à la relecture) —
  casse un epoch et le compteur `tours` au-delà de 999999. Le « `Time()` renvoie
  un epoch arrondi par paquets de 10 000 s » qu'on a cru un moment était un
  **artefact de cet encodeur**, pas un comportement de MA3.
- **`Time()` renvoie l'UPTIME de la console, pas un epoch Unix.** Pour horodater,
  `os.time()` (résolution 1 s). Mesuré dans MA3 : `Time()` valait `17931`
  pendant que `os.time()` valait `1787944439`. Ne pas « corriger » `os.time()`
  vers `Time()`.
- **`Timer()` accepte les FRACTIONS de seconde — la doc de MA3 se trompe.**
  Elle affirme « The value is in seconds » avec un argument entier. Mesuré le
  sur les dates du fichier, avec `PERIODE_S = 0.2` : écarts réels
  0,194 / 0,198 / 0,198 / 0,212 / 0,194 s → **0,20 s**. La sonde tourne donc à
  5 Hz au lieu de 1 Hz. ⚠️ Ne pas « corriger » vers un entier en se fiant à la
  doc. Coût mesuré : 0 à 7 ms par relevé, soit 3,5 % d'un cœur au pire.
- **N'ajouter AUCUN attribut dans le XML d'import** (`Installed="Yes"` etc.) :
  MA3 bascule alors le composant en ressource interne, cherche le `.lua` dans
  le dossier de l'application et affiche la ligne en rouge. Format nu, réglages
  après import.
- **La fenêtre d'import liste les fichiers XML, pas les plugins** qu'ils
  contiennent. Un plugin = un XML si on veut le voir.
- **L'emplacement du plugin fait partie du SHOWFILE.** Sans sauvegarde, il
  disparaît au redémarrage (« illegal object: Plugin 1 »). Le `.lua` reste.
- **MA3 garde le code Lua chargé en mémoire.** Ni `ReloadAllPlugins`, ni la
  bascule `Installed` No/Yes, ni l'arrêt du plugin ne le remplacent — seul un
  redémarrage ou un ré-import. D'où **`wingloader.lua`** : une amorce de
  30 lignes qui relit `wingbridge.lua` du disque à chaque appel. Importée une
  fois, elle supprime le problème définitivement.
- **La ligne de commande MA3 avale certains caractères Unicode** (tiret
  cadratin, flèche). Messages de plugin en ASCII pur.
- L'état global `_G` **survit** au rechargement du code, pas le code. D'où le
  compteur de `generation` : sans lui, chaque démarrage empilait une chaîne de
  Timer sans tuer les précédentes (3230 relevés après deux « arrêts »).

### 🎯 Tout est pilotable EN OSC, y compris l'installation

Découvert en cherchant à installer le plugin à distance :
**`Import` existe en ligne de commande**, donc tout passe par `/cmd` — aucune
manipulation souris n'est nécessaire.

```
Import Plugin Library "wingloader.xml" At 3
Set Plugin 3.1 Property "Installed" "Yes"
Plugin 3
```

Syntaxe validée du premier coup. `3` est l'emplacement (slot) du pool
Plugins de MA3 — **configurable**, `SETTINGS["plugin_slot"]` (Paramètres →
🎛️ grandMA3, ou l'aiguillage de fin d'assistant firmware sous Windows), défaut
3 = comportement d'avant ce réglage. `wing_ma3._plugin_osc(slot)` génère cette
séquence pour le slot réglé. Nécessaire parce qu'OSC est à **sens unique** :
l'app ne peut pas lire quels slots sont déjà occupés avant d'importer, donc
pas de détection fiable d'une collision — un slot déjà pris ouvre dans MA3 un
dialogue **Overwrite / Merge / Cancel** qui bloque l'import **en silence**
(l'app attend une sonde qui ne démarrera jamais tant que ce dialogue reste
ouvert). D'où le message d'échec `err.ma3.sonde_muette_install`, qui pointe
maintenant cette piste en premier. Conséquences :

- l'installation chez un collègue tient en trois commandes copiables ;
- on peut installer, mettre à jour et relancer la sonde **sans accès physique à
  la machine**, tant que MA3 écoute l'OSC ;
- **la vérification aussi est automatisable** : si l'amorce fonctionne, le
  fichier d'état passe en `version: 3`. On n'a pas besoin de lire la ligne de
  commande de MA3 pour savoir si ça a marché.

Ce dernier point est le plus utile : il transforme une manip aveugle en
opération vérifiable.

### ⚠️ Installer à un DEUXIÈME slot sans retirer le premier — mesuré en réel

Test fait avec l'auteur, grandMA3 2.5, le 11/09/2026 — le point qui a motivé
le réglage `SETTINGS["plugin_slot"]`. **Un slot 3 déjà occupé** (install
précédente réelle, pas de test isolé), puis un import au slot 5 SANS retirer
le slot 3. **Ne pas re-deviner ce qui suit : c'est mesuré, deux fois, dans les
deux sens, avec le fichier d'état comme témoin (`tours` qui avance ou pas) —
pas la ligne de commande MA3 seule, qui affiche `OK` même quand rien ne se
passe.**

**Établi :**

- Import à un slot déjà occupé ⇒ dialogue **Overwrite / Merge / Cancel**
  (« Some targets already exist »). Confirmé : choisir **Overwrite** ne casse
  rien dans l'immédiat (la sonde répond juste après).
- Import à un slot **libre** ⇒ **aucun dialogue**, MA3 renomme tout seul
  l'objet en `<Nom>#2` (ici `WingLoader#2`) pour éviter une collision
  d'affichage avec l'objet existant `WingLoader` (slot 3).
- `Plugin <numéro>` et `Plugin "<nom exact>"` marchent de façon fiable et
  répétée pour le **second** objet (slot 5 / `WingLoader#2`) : plusieurs
  démarrages/arrêts propres, `tours` reparti de 0 à chaque fois.
- 🔴 **Le PREMIER objet (slot 3 / `WingLoader`) a cessé de répondre — à son
  NUMÉRO *et* à son NOM — après l'import du second.** Testé isolément (slot 5
  explicitement arrêté d'abord, par son numéro, confirmé silencieux) : ni
  `Plugin 3` ni `Plugin "WingLoader"` n'ont fait avancer `tours`, sur des
  fenêtres de 18 à 32 s. Aucune erreur affichée dans MA3 — juste `OK`, sans
  effet. Une ré-installation complète au slot 3 (nouveau dialogue Overwrite,
  accepté) a semblé le relancer un instant (le fichier s'est retrouvé « frais »
  dans une fenêtre de 5 s) mais **`tours` était de nouveau figé quelques
  secondes plus tard** — voir plus bas, ce symptôme précis a une deuxième
  cause, distincte, qu'on a trouvée en creusant celle-ci.

**Hypothèse, PAS établie** : les deux objets du pool exécutent le même
`wingbridge.lua`/`wingloader.lua` dans le même environnement Lua de MA3, et
partagent donc probablement le même état global (`_G.WingBridgeEtat`, le
compteur `generation`, le `Timer`) — un `Plugin` sur l'UN des deux basculerait
alors l'état de TOUS, ce qui expliquerait pourquoi `Plugin 5` a visiblement
**arrêté** ce que `Plugin 3` avait démarré (log MA3 : `sonde ARRETEE apres
1505 releves` juste après `Plugin 5`). Ça n'explique pas en revanche pourquoi
le slot 3 est resté **muet** ensuite même après réinstallation — cette partie
reste sans explication confirmée. Pas de source MA Lighting consultée pour
trancher ; à vérifier si le sujet revient.

**Conséquence pratique, actionnable dès maintenant** : après avoir changé
l'emplacement du plugin dans Paramètres → 🎛️ grandMA3 et réinstallé, si
l'ancien emplacement était déjà utilisé, **il peut cesser de répondre**, y
compris à une relance manuelle. Ce n'est pas juste une entrée fantôme inerte —
c'est un risque réel de perdre le retour d'état sans message d'erreur MA3. Le
retirer à la main dans MA3 (clic droit sur sa case dans le pool Plugins →
`Delete`) est la seule voie de nettoyage vérifiée dans ce test.
L'avertissement correspondant est dans l'UI, à côté du champ « Emplacement du
plugin » (Paramètres → 🎛️ grandMA3).

### 🪤 Bug distinct trouvé EN CREUSANT ce qui précède — `installer_plugin()` pouvait mentir

En essayant de comprendre pourquoi le slot 3 « semblait » repartir puis
retombait, mesure directe : `installer_plugin()` a renvoyé `{"ok": True, …}`
alors que `tours` était figé depuis **plus de trois minutes**. Cause : sa
vérification de succès lisait `ma3_etat().get("actif")`, qui ne teste que la
**fraîcheur du fichier** (`MA3_ETAT_PEREMPTION_S` = 5 s) — pas une vraie
progression. Un fichier abandonné mais réécrit une dernière fois dans les 5 s
précédentes suffit à le faire mentir. C'est **exactement** le piège déjà
documenté au-dessus de `relancer_plugin()` (§ 6 ter, commentaire
`_PLUGIN_RELANCE_CMD`) et déjà corrigé LÀ via `_sonde_avance()` (fenêtre de
2 s, lecture directe du compteur) — mais le correctif n'avait jamais été
reporté sur `installer_plugin()`. Corrigé le même jour : `installer_plugin()`
utilise maintenant `_sonde_avance()`, comme `relancer_plugin()`. Sans lien
direct avec le réglage `plugin_slot` en lui-même — un bug préexistant que ce
test a rendu visible, pas introduit par lui.

### ✅ LED d'état + rattrapage de fader

Les deux dernières fonctions que la sonde débloquait.

**LED des executors** — `niveau_led_ma3(key)` : `tourne` → plein feu,
`active` → `LED_MID` (0x0200), sinon veilleuse. Rafraîchies 3×/s dans
`usb_loop` (la sonde n'écrit qu'une fois par seconde, inutile d'aller plus
vite). ⚠️ Au relâchement d'un bouton on retombe sur le niveau MA3, **pas** sur
une veilleuse fixe — sinon la LED d'un executor qui tourne s'éteignait dès
qu'on lâchait le bouton.

**Rattrapage de fader** — ressuscité. Il avait été retiré parce que MA3 n'émet
rien au changement de page ; la sonde donne désormais la position réelle.
`pickup_autorise()` + `pickup_verifier_repos()`.

Principe, celui des vraies consoles : un fader prend le contrôle quand il
**atteint ou traverse** la valeur MA3 (tolérance 2 %). Il le garde tant qu'on
s'en sert. Il le perd si MA3 change alors qu'il est au repos depuis plus de
1,5 s — typiquement un changement de page. La détection de traversée compte :
sans elle, un fader qui passe vite au-dessus de la cible ne serait jamais
rattrapé.

⚠️ **Ne bloque JAMAIS sans information** : rattrapage désactivé, executor
absent de la sonde, ou `fader` inconnu → le fader passe. Sans plugin, le
comportement est celui d'avant, à l'identique.

Réglages `fader_pickup` et `LED["ma3"]`, deux cases dans l'onglet Bridge.

### Cadence dégradée après une réouverture de liaison — le mécanisme

**Le symptôme** : après une fermeture/réouverture de la liaison USB, la wing
revient parfois à **~2,7 Hz** (300 à 670 ms par lecture) au lieu de 30 Hz.
Alterne, environ une fois sur deux ou trois. Ce n'est **pas** notre code qui
choisit : la wing revient bien ou mal de sa re-énumération.

**Ce qui est établi, mesuré :**

- la wing **quitte le bus à CHAQUE fermeture de poignée USB** et re-énumère —
  visible même sur une sortie propre (`✗ Wing non trouvée` juste après la
  reconnexion, personne n'ayant touché au câble) ;
- pendant la panne : `tours sans réponse : 0` (chaque lecture réussit et rend
  un vrai paquet), `revendication USB : ok`, wing à 12 Mb/s firmware chargé —
  **la wing répond, ~800× trop lentement. Pas cassée, pas muette : lente** ;
- **`clear_halt` seul suffit** à la sortir de cet état, 3 fois sur 3. C'est un
  transfert de CONTRÔLE : il ne parle qu'à la wing, sans rien changer côté
  ordinateur. Qu'il suffise tranche la question : **l'état fautif est DANS la
  wing** — pas macOS, pas libusb, pas une condition de course côté hôte.

**Remède** (`_tenter_reveil`, deux étages) : refermer/rouvrir la liaison
(~0,3 s) d'abord ; reset de port USB (~10 s, + firmware si retour bootloader)
en dernier recours. La connexion n'est **jamais refusée** : on nomme le
problème et le remède, on ne décide pas à la place de l'utilisateur.

**On l'a aggravé un temps.** Le passage d'`os.execv` à un process neuf (sur
l'hypothèse « réservation d'interface perdue » — **réfutée**, `claim: ok`
mesuré pendant la panne) a transformé un **problème occasionnel en problème
systématique** : un process qui meurt fait fermer la liaison par le système,
donc re-énumérer. Retour à `os.execv` (même PID, ne meurt pas).

**Deux bugs de couture, corrigés :**

- `/api/hard_reset` appelait `_release_device()` directement, pendant que la
  boucle USB lisait — on **fabriquait à la fermeture** l'endpoint en HALT
  (`Pipe error`, errno 32) qu'on subissait à l'ouverture suivante. Corrigé :
  `arreter_usb()` (attend la fin de la lecture en vol) + `clear_halt(EP_IN/OUT)`
  à chaque `_open()`.
- au redémarrage, la nouvelle instance ouvrait la wing pendant que l'ancienne
  la tenait encore (~1 s de chevauchement) → `Pipe error` + message
  « débranche » injustifié. Corrigé : `WING_ATTENDRE_PID` — le successeur
  attend la mort de son prédécesseur avant de toucher à l'USB.

#### ❌ Pistes réfutées par la mesure — ne pas les reprendre

| Piste | Ce qui l'a tuée |
|---|---|
| réservation d'interface perdue par `os.execv` | `claim: ok` mesuré pendant la panne |
| une file de lectures en retard | mesuré, sans effet |
| le rechargement de firmware | deux relances sans rechargement, revenues lentes quand même |
| `set_configuration` à chaque `_open()` | le supprimer n'a rien changé à la fréquence (4/6 relances lentes) — correctif conservé (ne pas reconfigurer une wing déjà configurée reste correct), mais il ne règle rien |

#### 🔑 Les leçons de méthode (elles ont chacune coûté une session)

- **Avant de théoriser sur une régression, compter les occurrences
  avant/après.** Le journal contenait la réponse depuis le début — il suffisait
  de compter par build. Trois hypothèses cohérentes, trois réfutations par la
  mesure, parce qu'à chaque fois on a raisonné au lieu d'aller chercher un
  COMPTAGE dans les données déjà là.
- **Une hypothèse cohérente n'est pas un diagnostic.** « ✅ RÉSOLU » a été écrit
  sur la foi d'un raisonnement et d'une preuve partielle ; la mesure suivante
  l'a démenti en dix secondes. Tant qu'on n'a pas mesuré ce que l'hypothèse
  prédit, elle s'écrit « piste ».
- **Séparer les gestes avant de conclure.** La seule hypothèse qui a tenu a été
  tranchée en une heure — parce qu'on a construit une EXPÉRIENCE qui sépare
  deux causes (geste côté wing vs geste côté hôte), au lieu d'argumenter.
- **Un message d'échec qui demande une action physique doit décrire un VRAI
  échec définitif**, pas seulement constaté à l'instant t. Trois fois dans une
  même session, l'app a affirmé avec autorité quelque chose que la suite du
  MÊME journal contredisait cinq lignes plus bas (« DÉBRANCHE la wing » alors
  qu'elle repartait seule 5 s après).
- **`mesurer_poll()`** : le temps de réponse est mesuré à chaque connexion et
  journalisé. Avant, `repond_au_poll()` ne rendait qu'un oui/non : une wing à
  0,4 ms et une wing à 337 ms passaient toutes les deux pour « prête ».

➜ **La cause de fond était en amont de tout ça : un câble USB défectueux, partie
données.** Voir `HARDWARE.md`, « Chantier 1 — clos ». Un défaut sur la paire de
données se joue au niveau électrique — rien, côté hôte, ne pouvait le
distinguer. Ne pas rouvrir cette section pour y chercher une explication
logicielle sans nouvelle preuve.

### 🎹 Raccourcis en TEXTE LITTÉRAL

Un mot-clé écrit entre guillemets dans `console_keys` (`"If"`, `'Ifo'`) est
tapé caractère par caractère au lieu d'être traité comme un nom de touche.

Motif : MA3 complète ce qu'on tape dans sa ligne de commande, et une lettre
seule peut être ambiguë — `i` a déjà donné *IfOutput* au lieu de *If*.
L'assistant clavier savait déjà taper une chaîne (`type_items`, type
`"string"`) ; seule la porte d'entrée manquait dans `enqueue_key`.

⚠️ Ce n'est pas un défaut de l'app : on envoie bien une seule frappe. C'est
l'auto-complétion de MA3 qui tranche.

### 🐌 LA LATENCE : 17 Hz au lieu de 48, depuis toujours

Chenillard qui saute des pas, LED en retard, frappes molles : un seul symptôme,
une seule cause.

**Piège de méthode** : des heures passées à corriger des symptômes sans jamais
mesurer la boucle. Instrumenter aurait pris dix minutes et donné la réponse
tout de suite.

#### La mesure qui a tranché

`BOUCLE` (wing_ui.py) publie dans `/api/status` : cadence, durée du cycle USB,
durée du rafraîchissement LED, lectures vides. Premier relevé :

```
hz: 17.4   cycle_ms: 37.3   leds_ms: 0.17   vides: 0
```

**37 ms par tour dans l'échange USB** ; mes ajouts coûtaient moins d'1 ms. Tout
ce que je soupçonnais était hors sujet.

#### La cause

`cycle_dmx` envoyait **trois paquets à chaque tour** — deux univers DMX de
520 octets + la carte des LEDs — chacun suivi d'un `drain()` qui attend jusqu'à
10 ms. Or **la sortie DMX était désactivée** : on réémettait 1 040 octets de
blackout inchangé, 17 fois par seconde.

#### La correction — en DEUX temps, le premier était faux

**Premier essai (faux)** : ne plus envoyer les univers DMX inutiles **ni la
carte des LEDs si elle n'a pas changé**. Mesure immédiate : 48 Hz, 0,7 ms.
Excellent — sauf que la mesure avait été prise pendant que les LED changeaient
encore.

**Ce que ça a réellement produit** : au repos, plus AUCUN paquet ne partait, et
le cycle s'écroulait à **337 ms (2,8 Hz)**. C'est l'écriture, et le `drain()`
qui la suit, qui entretient l'échange avec la wing.

Le symptôme était trompeur : *« les boutons sont ultra réactifs, les faders
dans les choux »*. Appuyer sur un bouton change sa LED → un paquet part → la
boucle est vive. Bouger un fader ne change **aucune** LED → aucun paquet →
boucle à 2,8 Hz → fader échantillonné 3 fois par seconde.

**Correction retenue** : les univers DMX ne partent que si la sortie est active
(sinon une fois par seconde pour tenir le blackout), et **la carte des LEDs part
à chaque tour, même inchangée**. Résultat : **30,5 Hz constants**, cycle
12-13 ms, quelle que soit l'activité.

| | Au repos | Quand ça bouge | Stable |
|---|---|---|---|
| Origine (3 paquets) | 17 Hz | 17 Hz | oui |
| Premier essai | 2,8 Hz | 48 Hz | ❌ |
| **Retenu (1 paquet)** | **30,5 Hz** | **30,5 Hz** | ✅ |

**Leçon** : une mesure prise pendant une transition ne vaut rien. 48 Hz était
vrai — pendant deux secondes, et pour la mauvaise raison. Mesurer AU REPOS et
EN CHARGE, pas une seule fois.

#### 🪤 Piste ESSAYÉE ET RÉFUTÉE — ne pas y revenir

Réduire le `drain()` de 10 ms à 1 ms paraissait évident : c'est de l'attente
pure. **La cadence s'est effondrée à 2,8 Hz (324 ms par tour.)** Le drain ne
perd pas du temps, il VIDE la file de la wing ; sans lui les paquets
s'accumulent et la lecture suivante bloque. Mesuré, annulé.

**Leçon** : quand un symptôme résiste à plusieurs corrections, ce n'est pas
qu'elles étaient mal faites — c'est qu'on regarde au mauvais endroit.
Instrumenter avant de corriger.

#### 🔗 Et un effet de bord : accélérer la LECTURE a saturé l'ÉCRITURE

La boucle passée de 17 à 30 Hz échantillonne les faders deux fois plus souvent
— donc envoyait deux fois plus de commandes à MA3 pendant un mouvement, et sa
ligne de commande saturait.

`_send_throttled` limite désormais chaque fader à **25 envois par seconde**
(`FADER_INTERVALLE`), avec une valeur retenue libérée au créneau suivant :
`faders_vider_attente()`, appelée à chaque tour, garantit que **la position
finale part toujours**, même si on lâche le fader entre deux créneaux.

⚠️ **Règle** : la cadence de lecture de la wing et la cadence d'écriture vers
MA3 sont indépendantes et doivent le rester. Accélérer l'une ne doit jamais
accélérer l'autre.

### 🐛 `cycle_dmx` détectait un débranchement trop étroitement (13/09/2026)

`cycle_dmx()` (`wing_connexion.py`) lève `WingUnplugged` — la boucle repasse
alors proprement en « déconnecté » — quand `dev.write()` (l'écriture DMX/LEDs
de ce fichier) échoue. Le test ne regardait que `e.errno in (19, 5)` +
une comparaison de texte (`"No such device" in str(e)`) : plus étroit que
`wing_init._err_usb()`/`_partie_du_bus()`, le classificateur PARTAGÉ utilisé
partout ailleurs, qui regarde AUSSI `backend_error_code` — macOS le peuple
parfois à la place d'`errno`. Exactement le piège déjà documenté dans
`wing_init.py` : « USBError tout court ne dit rien ».

**Conséquence potentielle** : une wing débranchée PENDANT l'écriture DMX
pouvait ne jamais faire lever `WingUnplugged` ici, selon lequel des deux
champs libusb portait le code — la boucle serait restée bloquée sur un device
mort au lieu de basculer en reconnexion automatique.

**Correctif** : `cycle_dmx()` appelle désormais `wing_init._partie_du_bus(e)`,
le même classificateur que `wing_init.py` utilise pour ses propres décisions
(attendre le départ du bus, etc.) — une seule vérité sur ce qui constitue un
« départ du bus », pas deux logiques qui peuvent diverger. Contrôle
`test_cycle_dmx_classificateur_partage` (smoke_hardware.py, §56) : vérifié par
doublures USB (aucune vraie E/S), trois formes de « device parti »
(`errno`+`backend_error_code`), une erreur transitoire correctement ignorée.

### 🐛 `/api/status` pouvait bloquer la boucle USB pendant ~5 s (13/09/2026)

Même famille que la latence ci-dessus, mais côté HTTP plutôt que côté USB.
`Handler._get_status` (`wing_handler.py`) tenait `etat.E.LOCK` — **le même
verrou qu'`usb_loop` prend à chaque tour, à 30 Hz, en mode bridge** pour lire
faders/roues — pendant TOUTE la construction de la réponse JSON, y compris
`core.ma3_sockets()` : un enchaînement `pgrep` puis `lsof -i` (macOS) qui peut
prendre jusqu'à ~5 s. Cet appel n'a lieu que quand `ma3_reachable() == "muet"`
(MA3 lancé mais qui n'écoute pas l'OSC) — mais c'est justement le cas où on a
le plus besoin que le reste de l'app continue à répondre.

**Séquence de panne possible** : MA3 devient injoignable PILE pendant qu'un
onglet poll `/api/status` (toutes les 400 ms, `ui/init.js`) → `_get_status`
tient `etat.E.LOCK` ~5 s → `usb_loop`, qui prend le même verrou à chaque tour en
mode bridge, reste bloqué tout ce temps → faders, boutons et roues ignorés, en
pleine régie, sans aucune erreur visible.

**Correctif** : `_get_status` ne tient `etat.E.LOCK` que pour copier
l'instantané de `STATE`/`SETTINGS`/`PROFILE` (quelques lectures de dict, donc
quasi instantané) ; le reste de la réponse — réseau (`ma3_sockets`,
`ma3_reachable`, `osc_config_ma3`), fichiers, formatage du journal — se
construit HORS verrou. Contrôle `test_get_status_verrou_minimal`
(smoke_hardware.py, §57) : `ma3_sockets()` doublé par une fonction lente
contrôlée, vérifie que `etat.E.LOCK` reste ACQUÉRABLE pendant qu'elle tourne.

### 🐛 Le bouton qui ne faisait RIEN — une prudence mal placée

Un bouton réglé `Go+ Executor 105`, MA3 réglé sur `Flash`, et **aucun effet**.
Aucune ligne dans le journal non plus.

Cause : quand MA3 annonçait une fonction MAINTENUE et que le profil contenait
une commande MOMENTANÉE, on renvoyait `None` — par peur d'un `On` sans `Off`.
Le raisonnement était juste, la conclusion mauvaise :
**un bouton qui ne fait rien est pire que le problème qu'on évite.**

**Correction** : `token_selon_ma3(token, evenement)` prend désormais l'événement
(`"appui"` / `"relachement"`) et construit la paire lui-même :

| Fonction MA3 | Appui | Relâchement |
|---|---|---|
| maintenue (Flash, Temp, Swap, Black) | `Verbe On Executor n` | `Verbe Off Executor n` |
| momentanée (Go+, Toggle, Top…) | `Verbe Executor n` | rien |
| `Empty` / inconnue / absente | rien | rien |

Le suffixe écrit dans le profil devient **sans objet** quand le suivi est
actif : c'est MA3 qui sait si sa fonction est maintenue, donc c'est lui qui
décide de la forme. `handle_button_release` consulte donc MA3 au lieu de se
fier au seul texte du profil (`_MOMENTARY_RE` reste utilisé sans suivi).

**Leçon** : refuser d'agir est une décision, pas une abstention. Elle doit être
justifiée par le résultat attendu, pas seulement par le risque évité.

### 📌 Masters de la SÉQUENCE SÉLECTIONNÉE — pool `Master 1.x`

Relevé dans `masters_selected.html` : *« Selected masters give access to the
individual masters of the selected sequence. »* Ils suivent la séquence active,
sans executor fixe — c'est exactement ce que fait un fader **XFade**
sérigraphié sur une command wing.

| | | | |
|---|---|---|---|
| `Master 1.1` Master | `Master 1.4` XFadeB | `Master 1.7` Speed | `Master 1.10` Solo |
| `Master 1.2` **XFade** | `Master 1.5` Temp | `Master 1.8` Highlight | `Master 1.11` Time |
| `Master 1.3` XFadeA | `Master 1.6` Rate | `Master 1.9` Lowlight | |

🔁 **Corrige une conclusion antérieure.** On avait écrit que Highlight,
Lowlight et Solo n'avaient « pas de mot-clé de commande utilisable », après
avoir cherché des mots-clés `Fader*`. Ils existent — en `Master 1.8` à `1.10`.
La recherche s'était arrêtée à la mauvaise famille d'objets.

**Leçon** : « je n'ai pas trouvé » et « ça n'existe pas » ne sont pas la même
chose. Écrire le premier, jamais le second.

### 🎛️ Suivi de MA3 réglable FADER PAR FADER

Une case à cocher par fader : le drapeau `suivre` (défaut `True`) est stocké
dans chaque entrée de `PROFILE["faders"]`.

Les types `gm`, `speed` et `selected` ne suivent JAMAIS : ils ne pilotent aucun
executor, il n'y a rien à suivre. Seuls les types « executor » sont concernés.

Cas d'usage réel : F1 grandmaster, F2 XFade de la sélection, F3-F8 qui suivent
la console — plus la possibilité d'en forcer un seul quand la sérigraphie de la
wing ne correspond pas à la configuration du show.

### 🎯 MA3 fait autorité, silence compris

**Décision** : si MA3 n'a rien assigné, la wing n'envoie rien — MA3 seul fait
autorité.

Quand `suivi_actif()` (case cochée **ET** sonde qui répond), les cas suivants
n'envoient **RIEN** au lieu de retomber sur la configuration de l'app :

| Cas | Avant | Maintenant |
|---|---|---|
| Executor absent de la page | réglage de l'app | rien |
| Fonction vide / `Empty` | réglage de l'app | rien |
| Fonction non gérée par Wing Bridge | réglage de l'app | rien |
| MA3 maintenu / bouton momentané | réglage de l'app | rien (un `On` sans `Off` bloquerait l'executor) |

⚠️ **Sans sonde, repli sur le comportement « profil seul ».** Le plugin est une
étape d'installation requise ; ce repli existe pour que l'app ne plante pas s'il
manque, pas pour offrir une expérience équivalente (sans sonde : pas de retour
LED, pas de rattrapage des faders). Vérifié par test — l'app ne doit jamais
planter faute de plugin.

### 🐛 Le suivi des touches ne s'appliquait à AUCUN profil réel

`_RE_EXEC_CMD` n'acceptait qu'un seul mot avant `Executor`. Or les boutons
maintenus s'écrivent **`Flash On Executor 206`**. Le suivi ne s'appliquait donc
jamais, en silence, sur les profils réels. Grammaire réelle :
`<Verbe> [On|Off] Executor <n>`.

⚠️ Piège en corrigeant : **`Go+ On Executor 206`** — une commande qui n'existe
pas. Syntaxes relevées mot pour mot dans le manuel :

```
Flash (On/Off) [Object]     Toggle [Object]
Temp  (On/Off) [Object]     Top    [Object]
Swap  (On/Off) [Object]     Go+    [Object]
Black (On or Off) [Object]
```

Seules Flash, Temp, Swap et Black acceptent le suffixe. `On` est un mot-clé à
part entière, pas un suffixe — il figurait à tort dans `MA3_VERBES_MAINTENUS`.

### 📋 Table des fonctions de touche : 25 verbes vérifiés

Liste relevée dans MA3 (Assign Executor → Select Function), puis **chaque nom
vérifié** comme mot-clé réel par la présence de `keyword_<nom>.html` dans le
manuel installé. Méthode reproductible, pas une intuition.

Volontairement **absents** faute de certitude sur leur syntaxe appliquée à un
executor : `Time`, `LogIn`, `Rate1`, `<<<`, `>>>`. Les ajouter demandera une
vérification.

### 🧰 Rangées et étiquettes

- `/api/fader/rangee` et `/api/bouton/rangee` : renumérotent une rangée d'un
  coup en conservant l'ordre physique. Un numéro d'executor étant relatif à la
  page courante, une seule passe suffit — le suivi de page est automatique.
- `fader_noms` dans le profil : étiquette libre par fader, pour coller à la
  sérigraphie de la wing de l'utilisateur. Purement cosmétique. **Les copies de
  command wing n'ont ni le même nombre de faders ni la même disposition** :
  imposer « F1…F8 » ne marche que pour le modèle qu'on a sous la main.

### ✅ Suivi automatique de MA3

**Décision**, parmi quatre options : **suivre MA3 automatiquement**, faders ET
boutons d'executor. Motif : sur une vraie command wing, le fader physique EST
celui de l'executor. C'est le comportement fidèle, et c'est le but du projet.
(Ceci remplace une option antérieure « avertir seulement » — l'information
disponible s'est révélée plus riche que prévu.)

`kind_selon_ma3(exe, kind)` et `token_selon_ma3(token)` dans wing_ui.py.
Tables `MA3_FADER_KINDS` et `MA3_KEY_VERBES`.

**🚨 RÈGLE DE SÛRETÉ — ne pas l'affaiblir** : toute valeur annoncée par MA3
qui n'est pas dans les tables laisse le réglage de l'utilisateur INTACT et se
signale dans le journal. On ne fabrique jamais une commande au hasard. Les
tables ne contiennent que de l'observé (`Master`, `Go+`, `Flash`,
`SelectFixtures`) ou du documenté (les 8 fonctions de fader, cf.
`docs/FADERS_ENCODERS.md`).

Cas couverts, tous testés contre le showfile réel :

| Situation | Comportement |
|---|---|
| MA3 dit `Master`, l'app dit `crossfade` | envoie Master, le journal l'explique |
| MA3 dit `SelectFixtures` (verbe inconnu) | garde le réglage + avertit |
| Fonction de fader vide | garde le réglage + avertit |
| Executor absent de la sonde | garde le réglage, silencieux |
| Token qui n'est pas un executor (`Next Page`) | intact |
| Suivi décoché | rien ne change |
| `gm` et `speed` (pool) | jamais suivis — ce ne sont pas des faders d'executor |

Réglage `suivre_ma3` (settings.json, défaut `True`) et case à cocher dans
l'onglet Bridge. Anti-répétition des messages : un même constat n'est écrit
qu'une fois, remis à zéro quand on change le réglage.

### Côté Wing Bridge

`ma3_etat()` lit le JSON, `ma3_executor(no)` cible un executor. Pastille
**Sonde MA3** dans le panneau de santé.

⚠️ **Le plugin est une étape d'installation REQUISE** (au même titre que le
firmware) : sans lui, l'app envoie l'OSC à l'aveugle — pas de retour LED, pas de
rattrapage des faders, pas de conscience de page. La pastille reste éteinte sans
crier à la panne (c'est un réglage à faire, pas un plantage), mais l'app ne
fonctionne alors qu'en **dégradé**. Contrainte de conception : l'absence de
plugin ne doit jamais faire planter l'app.

Coût mesuré : **`duree_ms` = 0 à 3 ms** par relevé. Non-sujet.

### ✅ La sonde lit aussi les Masters — GrandMaster, Speed, Selected

**À l'origine, `lire_executors()` ne lisait QUE des objets Executor**
(`page:Children()` puis `ex:GetFader()`) — la ligne « `gm` et `speed` (pool) :
jamais suivis » ci-dessus n'était donc pas qu'un choix de suivi, c'était une
vraie absence de canal : aucune version du plugin n'avait jamais lu de Master.
Confirmé par une sonde **réelle**, pas supposé.

**API établie par sonde réelle, pas par la doc seule** (le fichier de
référence `grandMA3_lua_functions.txt`, section *Object-Free API*, donne
`MasterPool(nothing): light_userdata:handle` ; la doc HTML installée confirme
que `GetFader`/`GetFaderText` sont de l'**Object API générique**, pas propres
à Executor — exemple officiel sur `SelectedSequence()`, pas un executor).
Restait à savoir COMMENT MasterPool() s'adresse : sondé en direct.

`MasterPool():Children()` rend exactement **5 enfants**, chacun un POOL (pas
un master individuel) :

| `no` | Nom | Classe | Correspond à |
|---|---|---|---|
| 1 | Selected | `MasterPoolSelected` | `Master 1.x` |
| 2 | Grand | `MasterPoolGrand` | `Master 2.x` (**GrandMaster** = `Master 2.1`) |
| 3 | Speed | `MasterPoolSpeed` | `Master 3.x` |
| 4 | Playback | `MasterPoolPlayback` | `Master 4.x` — pas utilisé par Wing Bridge |
| 5 | Timing | `MasterPoolTiming` | `Master 5.x` — pas utilisé par Wing Bridge |

Chaque **enfant de ces enfants** est un master individuel, adressable par son
`.no` — **exactement** la numérotation de la syntaxe MA3 (`Master 2.1` = pool
Grand, enfant `no=1` ; `Master 3.7` = pool Speed, enfant `no=7` ; `Master 1.2`
= pool Selected, enfant `no=2` = XFade, cf. `MASTERS_SELECTION` dans
`wing_bridge.py`). `h:GetFader({})` sur cet enfant rend directement sa valeur
0..100 — **le même mécanisme** que `ex:GetFader({})` sur un executor, aucune
API parallèle inventée.

**Publié par la sonde** (`plugin_ma3/wingbridge.lua`, `lire_masters()`) dans une
clé séparée `masters`, sans toucher au format `executors` existant :
```json
"masters": {
  "selected": {"1": 78, "2": 0, "3": 0, …},
  "grand":    {"1": 100},
  "speed":    {"1": 71, "2": 50, …}
}
```

> **Revérifié sous grandMA3 2.5.0.3.** `MasterPool():Children()`
> rend toujours les mêmes pools : `selected` = 11 masters, `speed` = 16, `grand`
> variable selon le show (un show avec plusieurs GrandMasters expose `grand` =
> `{"1":…, "2":…, …}` — `lire_pool_masters()` itère `Children()` sans rien
> présumer, donc ça suit). Le **GrandMaster** reste `grand["1"]` (= `Master 2.1`),
> lu correctement. Aucun `masters_note` d'erreur, `duree_ms` ≤ 1.
Isolé par son propre `pcall` dans `releve()`, comme `raccourcis`/`encodeurs`/`osc` :
une panne de lecture des masters ne peut pas emporter le relevé des executors.

**Côté Wing Bridge** : `wing_ma3.ma3_master(pool, no)` (nouveau), même famille
que `ma3_executor(no)`. Utilisé par `pickup_autorise`/`pickup_verifier_repos`
(voir `docs/FADERS_ENCODERS.md`) pour étendre le rattrapage à `gm`/`speed`/`selected`.

**Latence mesurée** (OSC → valeur visible dans le fichier d'état, `Master 2.1`) :
**~90-145 ms** — même ordre de grandeur que sur les executors (~110-135 ms).
Même pipeline (Timer Lua + cache Python).

⚠️ **`kind_selon_ma3` (adaptation de la FONCTION assignée par MA3) reste
NON applicable à `gm`/`speed`/`selected`** — ça n'a pas de sens technique pour
ces types : GrandMaster EST GrandMaster, MA3 ne lui « assigne » pas de fonction
différente comme il le fait pour le fader d'un executor. Seul le
**rattrapage** (le sujet de cette extension) les couvre désormais.

🪟 **Partagé avec Windows.** `plugin_ma3/wingbridge.lua` est le même fichier sur
les deux plateformes (voir `docs/WINDOWS.md`). L'API Lua est celle de MA3, donc
indépendante de l'OS ; le canal complet (plugin → fichier → lecture Python)
demande à être **retesté sous Windows** à chaque modification de ce fichier.

Confirmé sous Windows : rattrapage GrandMaster, Selected et Speed vérifiés au
journal (`⏸ en attente de rattrapage → ✓ Fader rattrapé`, lignes qui ne
s'écrivent que si `ma3_master(...)` a renvoyé une valeur), non-régression
executor OK.

### 🔬 Le lag Windows — localisation dans la chaîne

Lag perceptible en montant les faders sous Windows, imperceptible sous macOS.
Chaîne : MA3 → fichier → lecture Python. Mesures en lecture seule, **avant tout
correctif**.

- **① Timer Lua (MA3 → fichier)** : intervalle réel entre écritures ~**0,22 s**
  (pas 0,2 — `Timer()` MA3 n'est pas exact, cf. en-tête `wingbridge.lua`),
  **0 tick sauté**. Identique Mac et Windows (~215 ms des deux côtés).
- **② Accès fichier (Python)** : open+read+parse médiane **0,5 ms**. Windows
  Defender temps réel actif n'ajoute que des blips rares ≤ 11 ms. **I/O non
  coupable.**
- **③ Cache Python** : `ma3_etat()` mettait en cache **0,2 s**, indépendamment de
  la cadence d'écriture (~0,22 s) → **deux quanta ~0,2 s désynchronisés qui
  battent l'un contre l'autre** = 0 à ~420 ms selon la phase.

**Correctif : cache app 0,2 s → 0,05 s.** Une lecture coûtant ~0,5 ms, un TTL
long est inutile ; 0,05 s reste sous la période d'écriture, n'empile plus un
quantum complet. Effet mesuré : retard du lien cache **97 → 25 ms** (Mac
106 → 29), bimodalité end-to-end éliminée, pire cas **~420 → ~270 ms**.

⚠️ La divergence apparente « Mac resserré 92-144 ms vs Windows étalé » était un
**artefact d'échantillon** (n=8 côté Mac) : re-mesuré (n=60-140), le Mac est
aussi étalé, timer Lua identique. La **seule** vraie différence d'OS est la
contention `os.rename` ci-dessous, spécifique Windows.

### 🐛 Le trou d'écriture de la sonde — spécifique Windows

`ecrire()` fait `os.remove` puis `os.rename` (`os.rename` sur une cible
existante **échoue sous Windows**, d'où le `remove`+`rename`). Le fichier
**disparaît ~0,77 ms, ~4,5×/s**. Une lecture tombée pile dedans voit `stat()`
lever → `actif:False`, `executors:[]`. Symptôme : un executor allumé
**scintillait ~1×/min** (chute FULL→GLOW). Windows uniquement — POSIX remplace
en place, 0 trou côté Mac.

**Deux mécanismes indépendants, tous deux en place :**

- **Côté sonde (retry).** L'échec `os.rename` est transitoire (le lecteur
  relâche en ~0,5 ms) : `ecrire()` **retente jusqu'à 4 fois** avec un back-off
  court **actif** (Lua MA3 n'a pas de `sleep`), uniquement sur le chemin
  d'échec. POSIX inchangé (1er rename réussit). Ramène la contention des tests
  contrôlés à 0 ; une longue session réelle garde ~0,17 % (8/4747) dus à de
  rares pics de lecture. Le compteur `erreurs` (remonté dans la pastille santé)
  signale ce résiduel.
- **Côté app (tolérance).** `ma3_etat()` garde le **dernier état `actif:True`**
  et, sur un raté de lecture (`stat`, `read_text`, `json.loads` qui lève), le
  **ressert tel quel** tant que `now - last_good_t < MA3_ETAT_GRACE_S` (**1,5 s**,
  ≈ 7 cycles d'écriture), avec un champ `stale:True`. **Au-delà de la grâce, on
  retombe correctement sur l'état vide + message** : une sonde durablement
  absente reste une **vraie panne**, qu'on ne masque pas. Mesuré : chutes
  FULL→GLOW **16/10 min → 0/10 min**, même contention live, seule la grâce
  change. Contrôle `test_ma3_etat_transitoire`.

⚠️ **Le trou reste CÔTÉ SONDE et n'est pas corrigeable en Lua MA3** (pas de
remplacement de fichier atomique). L'app le **tolère**, elle ne le supprime pas.

⚠️ **Piège de lecture des mesures : le compteur « `.tmp` vu ».** `ecrire()` crée
un `.tmp` puis le renomme à **chaque** écriture — le `.tmp` existe donc ~1 ms
par tick en régime normal. Un compte élevé reflète la fréquence de sondage, pas
un échec. Le signal fiable : `erreurs` (doit être ~0) et un `.tmp` qui ne
s'attarde **jamais > 100 ms**.

### 🛑 Ne PAS baisser `PERIODE_S`

Le gain acquis (bimodalité éliminée, pire cas 470→270 ms) est solide et sans
risque. Descendre la période gagnerait ~×2 sur la latence mais trois risques
l'écartent, aucun caractérisable de l'extérieur de MA3 :

| Risque | Détail |
|---|---|
| **Contention Windows qui scale** | doubler les écritures = autant de spins de retry actif en plus, sur le thread Lua |
| **Coût CPU invérifiable côté MA3** | modèle de threads des plugins non documenté ; si les plugins tournent sur le thread de rendu, l'écriture + l'ordonnancement (~14 ms/cycle) pourraient provoquer un stutter en show chargé |
| **Direction sûre documentée** | l'en-tête `wingbridge.lua` dit d'**augmenter** `PERIODE_S` si la console peine, pas de le baisser |

**Piste alternative notée, non retenue** : garder `PERIODE_S` mais n'écrire que
si le snapshot a **changé** (dirty-check), avec un battement de sécurité ~2 s
pour le watchdog « sonde silencieuse » (péremption 5 s). Découplerait « latence
quand ça compte » de « coût au repos ». À reprendre seulement si la latence
redevient un sujet.

---

# 📒 Diagnostiquer « MA3 n'écoute pas » — l'histoire des mauvais conseils

> Accueille ce qui vivait en commentaires dans `src/ui/bridge.js`. Le code n'en
> garde que la règle. **Contrôle `test_renvois_doc`** : les renvois du code
> doivent résoudre, ces titres ne peuvent plus être renommés en silence.

## Ne jamais accuser une ligne OSCData qui n'est pas sur le bon port

Le diagnostic testait `.some(x => x.rec_cmd === false)` — « SI UNE SEULE ligne a
Receive Command à No ». Or MA3 a normalement **plusieurs lignes OSCData**, une
par usage. Configuration réelle, vérifiée sur capture d'écran :

```
OSCData 1 · port 8001 · Receive No  · Receive Command No   ← MA3 ENVOIE
OSCData 2 · port 8000 · Receive Yes · Receive Command Yes  ← MA3 REÇOIT
```

La ligne 1 (celle par laquelle MA3 nous parle) n'a évidemment pas besoin de
Receive Command. Le `.some()` la voyait et criait, alors que la ligne du port
8000 était parfaitement réglée. **L'auteur a redémarré grandMA3 plusieurs fois à
cause de ce message.**

🔑 On ne juge donc QUE les lignes qui portent le port sur lequel on envoie, et
il suffit qu'UNE d'elles soit correctement réglée.

## Config OSC correcte et MA3 muet quand même : le réseau global

Le conseil le plus coûteux. Ce cas — la sonde lit une config OSC
correcte, et pourtant MA3 ne reçoit rien — disait « relance grandMA3 ».
**L'auteur l'a relancé une dizaine de fois pour rien.**

La vraie cause, trouvée dans le manuel MA3 installé puis confirmée : le
**RÉSEAU GLOBAL de MA3 était coupé** (Menu → Network, bouton en bas à droite sur
fond rouge). Et il refusait de s'activer parce que « MA-Net Interface » pointait
vers un adaptateur filaire **non branché** — la station affichait « No Cable ».
Interface mise sur le Wi-Fi réellement connecté → MA3 a ouvert le port 8000
immédiatement.

⚠️ L'OSC n'a rien à voir avec le MA-Net, **mais il tombe avec le réseau
global**. D'où l'ordre des conseils : réseau global, puis « No Cable », et le
redémarrage en tout dernier.

## La pastille « bootloader » : un seul geste, pas de théorie

Ce message a renvoyé vers un SCRIPT de banc de test — inacceptable dans une app
de régie, et faux depuis que l'app fait elle-même ce que le script faisait.

Ce qui est vérifié : firmware renvoyé → la wing revient en
bootloader et y reste (45 s d'observation), et **un reset de port USB n'y change
rien**. Seule une coupure d'alimentation marche. Il ne reste donc qu'un geste,
physique, et il se dit en une phrase. Le « pourquoi » va dans le journal, pas
dans la pastille.

## Les raccourcis : attendre la preuve de la sonde, ne pas annoncer un succès

Après un envoi, l'app attend que la sonde repasse (elle relit la table de MA3
toutes les 3 s) et rapporte **ce qu'elle voit**. Sans sonde, elle dit ce qu'elle
a émis et que la vérification reste à faire sur la console.

⚠️ C'est la règle du projet : un « ✓ envoyé » mensonger coûte des heures — vécu
trois fois. La panne d'origine : `Import KeyboardShortcut Library` n'appliquait
rien, et l'app annonçait le succès **en relisant son propre fichier**.

### 🐛 « Fichier bon, MA3 en retard » : l'envoi doit AGIR, pas seulement détecter

Trouvé en test réel sur l'app buildée (#248), en déréglant 3 touches (PREV, NEXT,
SET) **dans MA3** par OSC (`Set KeyboardShortcut n Property "Shortcut" "…"`) puis
en cliquant « ⌨ Envoyer les raccourcis » (étape D). Constat, avant correctif :

| Ce qu'on voit | Valeur |
|---|---|
| `/api/shcuts` | `a_jour: False`, `non_applique` = NEXT, PREV, SET (la sonde les voit) |
| journal | `0 modified in WingBridge.xml, 0 command(s) sent to MA3` |
| réponse de l'envoi | `ok: True`, `inchange: False` (« envoyé ») |
| étape D | « Raccourcis envoyés à l'instant. » — **faux**, rien n'était parti |

**Cause** : `shcuts_etat()` compare aussi à la sonde (`non_applique` : fichier ≠
MA3), donc `a_jour` passait à faux ; mais `shcuts_envoyer()` calculait « quoi
envoyer » (`a_faire`) **uniquement d'après le fichier**. Fichier déjà bon ⇒
liste vide ⇒ aucune commande, succès annoncé. `force` n'y changeait rien.

**Correctif** : les touches de `non_applique` rejoignent `a_faire` (on ré-émet la
valeur du fichier, qui reste inchangé pour elles). Vérifié sur l'app buildée :
`3 command(s) sent to MA3`, puis `a_jour: True`, `confirmes: 64`,
`non_applique: []`. Contrôle : `smoke_raccourcis.py`, section 20 (b-bis), vu
ROUGE avant le correctif.

**Second défaut, mis au jour par le premier** : `shcutsEnvoyer()` (`ui/touches.js`)
abandonnait dès le 1ᵉʳ `non_applique` vu pendant l'attente de la sonde. Or MA3
applique les commandes espacées de 0,15 s et la sonde relit ensuite : ce retard
normal laissait « ⛔ MA3 N'A PAS APPLIQUÉ » affiché alors que la table était bonne.
Désormais on n'affirme l'échec qu'à la fin du délai (~5 s), sur ce que la sonde
dit ALORS. Après correctif : « ✅ Appliqué et vérifié dans MA3 — 3 commande(s)
envoyée(s), la sonde confirme 64 touches ». Contrôle : section 20, vu ROUGE.

⚠️ **Ce qui n'est PAS établi** : un redémarrage de MA3 (kill) a laissé la table
intacte (`a_jour: True` juste après). Le scénario « MA3 relancé ⇒ table remise à
zéro » est donc une hypothèse, pas un fait — le défaut a été reproduit par
dérèglement direct dans MA3, pas par redémarrage.

⚠️ **Prérequis, piège vécu** : l'option **ShCuts doit être ACTIVE dans MA3
lui-même**. Le fichier porte `KeyboardShortcutsActive="Yes"`, mais ça ne prouve
pas que la console l'a activée : sans cela, les frappes du mode console sont
relayées par l'assistant clavier (`✓ 1 frappe(s) → MA3`) et n'ont AUCUN effet.
Preuve du bon fonctionnement : `pageup` fait passer la sonde de `Page 2` à
`Page 3`, `pagedown` la ramène à `Page 2`.

---

## Départager « OSC mal réglé » de « réseau coupé »

**Pas par l'API Lua** : balayage des ~320 pages `lua_*.html` du manuel installé,
**aucune ne mentionne « network »**. La page `comad_network_switch` parle du
*switch réseau matériel* de MA, sans rapport.

**La voie qui marche ne demande ni plugin ni Lua** : compter les sockets réseau
que MA3 a ouverts.

| Mesure | Lecture |
|---|---|
| **0 socket** | signature d'un **réseau global coupé** (Menu → Network, bouton en bas à droite) |
| **n > 0, mais pas le port OSC** | le réseau va bien → c'est la **configuration OSC** |

**Relevés réels :**

| Quand | Sockets | Port 8000 |
|---|---|---|
| MA3 sain | **13** (8000, 8001, 8005, 8080, 10669, 30020, 30021, 30027…) | ✅ présent |
| OSC mal réglé | **5** (8005, 53020, 59592, 10669, 61541) | ❌ absent |

⚠️ **SIGNATURE, PAS PREUVE.** Le manuel dit que le réseau doit être activé
« pour communiquer » ; il ne dit pas littéralement « aucun socket ». Le texte
affiché rapporte donc la MESURE et ce qu'elle évoque, jamais « ton réseau est
coupé ». C'est la faute exacte déjà payée : diagnostic juste, explication
fausse, une dizaine de redémarrages de grandMA3 pour rien.

⚠️ Le cas « 0 socket » **n'a pas encore été observé** — il demande d'éteindre le
réseau de MA3 exprès. À confirmer à l'occasion.

🔧 Mesuré seulement quand MA3 tourne **et** n'écoute pas : `lsof` coûte ~60 ms,
et l'immense majorité du temps il n'y a rien à expliquer. Gardé par le
contrôle `test_diagnostic_reseau`.

## 🪤 RÉGRESSION macOS 27 — `netstat` ne voit plus rien, `_port_ecoute()` basculée sur `lsof`

Trouvé en test réel avec l'auteur le 17/09/2026, en voulant vérifier le point
1 de la liste tout en haut de ce fichier. Constat : `ma3_reachable()`
répondait **« muet »** alors que grandMA3 tournait ET écoutait réellement sur
le port 8000 — l'auteur venait de confirmer dans le menu OSC que tout y était
déjà correct (Interface ≠ `<None>`, Enable Input, ligne 8000 Receive +
Receive Command = Yes).

**Mesuré, cinq fois de suite, à l'instant même où le problème se produisait :**

| Outil | Résultat |
|---|---|
| `lsof -nP -iUDP:8000` (à la main, dans un Terminal) | ✅ voit `app_gma3 … UDP *:8000` à chaque essai |
| `netstat -an -p udp` lancé en sous-processus Python (venv **et** Python système) | ❌ **sortie VIDE**, à chaque essai — sans exception, sans code de retour non nul |
| `netstat -an -p udp` tapé directement dans le Terminal (pas via Python) | ✅ voit la ligne `udp4 … *.8000 *.*` |

**Établi** : sur macOS 27 (« Tahoe » et suivants), `netstat` lancé en
sous-processus par un binaire Python ne renvoie plus la liste complète des
connexions UDP des autres applications — silencieusement, sans indiquer
d'erreur. `lsof`, lui, reste fiable dans les mêmes conditions (5/5).

⚠️ **Cause non tranchée — pas d'hypothèse présentée comme un fait.** Deux
pistes cohérentes, aucune confirmée : une permission macOS « Réseau local »
non accordée à ce binaire (vérifié : il n'apparaît même pas dans Réglages
Système → Confidentialité et sécurité → Réseau local — le popup de demande ne
s'est jamais déclenché), ou une restriction plus large de `netstat` sur cette
version d'OS. Les deux pistes prédisent le même symptôme ; aucune n'a été
départagée. À reprendre si le sujet revient.

**Conséquence, avant correctif** : `_port_ecoute()` (donc `ma3_reachable()`,
donc toute la détection OSC de l'app — pastille santé, nouvelle étape « Active
l'OSC » de l'assistant de mise en route, diagnostic réseau) était **cassée en
permanence** sur cette version de macOS, pas seulement pour ce test-ci. Un
utilisateur sur macOS 27 aurait vu « OSC injoignable » en confirmation, quoi
qu'il règle dans MA3.

**Correctif** : `_port_ecoute()` utilise désormais `lsof -nP -iUDP:<port>`
sur macOS — `netstat` reste inchangé pour la branche Windows, jamais concernée
(testée séparément, `netstat` y fonctionne). L'argument d'origine du choix de
`netstat` (« deux fois plus rapide, 26 ms contre 54 ms ») ne tient plus : un
outil deux fois plus rapide qui ne renvoie rien n'est pas plus rapide, il est
faux. `ma3_sockets()` utilisait déjà `lsof` sur macOS pour une raison
voisine — même outil, pour cohérence. Contrôle `test_port_ecoute_macos`
(smoke_ma3_sync.py, §63) : mocke `subprocess.run` pour rejouer exactement ce
symptôme (netstat = sortie vide même sur un port réellement occupé) et
vérifie que le code ne l'appelle plus du tout sur macOS.

**Vérifié en réel après correctif**, même machine, même show grandMA3 :
`osc.reachable` passe de `"muet"` à `"ok"` ; l'installation automatique du
plugin, qui échouait au bout de ~4,6 s (sonde muette — la commande OSC
n'atteignait jamais MA3, silencieusement injoignable côté app), réussit du
premier coup dès que la détection est correcte.

## L'assistant de mise en route sait désormais dire « active l'OSC d'abord »

**Ordre de dépendance vérifié en réel, pas supposé.** `installer_plugin()`
(wing_ma3.py) accepte `ma3_reachable() in ("ok", "muet")` — donc TENTE
l'import même si MA3 n'écoute pas encore — mais un import qui n'atteint
jamais MA3 ne peut pas faire avancer la sonde. Reproduit le 17/09/2026, MA3
lancé mais OSC coupé : l'installation échoue **systématiquement** au bout de
~4,6 s avec « sonde muette », après avoir quand même copié les fichiers du
plugin sur le disque (`present` devient vrai même sur cet échec — à savoir si
on relance le test). **L'étape OSC doit donc précéder l'étape plugin dans le
parcours de l'assistant**, pas l'inverse.

Onglet Paramètres → carte 🧩 Firmware de la wing, nouvelle étape « Active
l'OSC dans grandMA3 » (`#oscEtape`, `ui/parametres.js::majOscEtape`), affichée
dans les mêmes conditions que l'étape plugin mais AVANT elle dans le
balisage. Trois niveaux de vérification, jamais une hypothèse déguisée en
fait :

| État | Ce qu'on affiche | D'où ça vient |
|---|---|---|
| Sonde active, ligne 8000 confirmée (Receive + Receive Command) | ✅ complet | `osc_config_ma3()`, la sonde tourne DANS MA3 — une preuve |
| Sonde pas encore active, mais `ma3_reachable() === "ok"` | ✅ **partiel**, dit explicitement qu'il manque encore la confirmation par la sonde | poule-et-œuf : la sonde vient de l'étape suivante (l'install du plugin) |
| Sonde pas active, `ma3_reachable() === "muet"` | ⚠️ MA3 tourne mais n'écoute pas | idem |
| MA3 pas lancé | ○ invite à le lancer | `ma3_reachable() === "off"` |

Une fois le plugin installé et actif, une étape « Envoie les raccourcis
clavier vers grandMA3 » apparaît (capture d'écran réelle du bouton
`#btnShcuts`, encadrée), puis une étape finale « Tout est configuré » —
visible seulement quand les TROIS conditions réelles sont vraies (OSC
confirmé par la sonde, plugin actif, raccourcis déjà envoyés au moins une
fois) — avec un bouton vers l'onglet Bridge qui ne déclenche PAS
`toggleBridge()` : démarrer reste un geste de l'utilisateur. Tout ça est
recalculé à CHAQUE poll (400 ms) à partir de l'état réel, pas déclenché une
fois pour toutes : revenir sur l'assistant après avoir déjà tout fait montre
directement les bonnes coches. Vérifié en réel, les deux sens (parcours à
froid OSC coupé → activé, et retour sur l'onglet après coup).

Voir aussi `docs/KEYBOARD_MAPPING.md` pour l'étape « Envoie les raccourcis »
et l'horodatage du dernier envoi.
