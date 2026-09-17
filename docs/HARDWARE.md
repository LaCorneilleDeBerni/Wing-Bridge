# HARDWARE — la wing, l'USB, le protocole bas niveau

> 🇫🇷 This reference document is in French. Translation contributions are
> welcome — see `CONTRIBUTING.md`.

**Ce fichier = ce que la wing fait et comment on lui parle en USB.** Faits
établis sur capture, stables.

🚫 **Rien de grandMA3 ici.** L'autre bout de la chaîne est dans
`GRANDMA3_SYNC.md` : les deux protocoles n'ont rien en commun, et les mélanger
rend le débogage plus dur quand l'un des deux casse.

📍 Captures : **non distribuées** (elles contiennent le firmware applicatif, qui
appartient à MA Lighting). Les noms cités dans ce fichier (`d.pcapng`, les 5 de
`Phase 2/`, `a-1`, `test 2-1`, `ts 3-1`, `testwing`) renvoient aux captures de
travail d'origine ; `d.pcapng` et les 5 de `Phase 2/` contenaient l'init à
froid, les autres non. Reconstituer une capture équivalente : voir la procédure
« Importer une capture » plus bas.

> 🧭 **Index de toute la doc technique** : [`README.md`](README.md) (quelle
> question → quel fichier). Avant de toucher au code : [`CONTRIBUTING.md`](../CONTRIBUTING.md)
> à la racine (méthode, règles de modification, pièges).
>
> ⚠️ **Deux protocoles à ne pas mélanger** : l'USB de la wing (`HARDWARE.md`) et
> l'OSC vers MA3 (`GRANDMA3_SYNC.md`). Quand l'un casse, on doit pouvoir lire
> l'autre sans le traverser.

---

## Ce qu'on sait avec certitude

### Le matériel
- Command wing grandMA2 onPC (matériel MA d'origine ou modèle compatible)
- VID=0x03EB / PID=0x160B  
- 1 interface USB (class=0xFF vendor-specific)
- EP_OUT=0x02 (Bulk, 512B max)  
- EP_IN=0x81 (Bulk, 512B max)
- MCU ARM → nécessite upload firmware à chaque démarrage à froid

### Protocole USB (reverse-engineered depuis d.pcapng)

📍 **Les captures d'origine ne sont pas distribuées** (firmware MA). Noms cités
ci-dessous, à ne pas confondre :
- **`d.pcapng`** — la première à contenir l'**init à froid** (bootloader,
  upload de firmware, reboot, poignée de main), et la référence historique
  pour tout ce qui touche à la connexion.
- **`Phase 2/*.pcapng`** (5 fichiers) — contiennent elles aussi l'init à froid,
  sur 5 connexions RÉUSSIES distinctes. Avec `d.pcapng`, ce sont les **6 seules
  à couvrir la connexion**.
- `a-1`, `test 2-1`, `ts 3-1`, `testwing` — captures de **régime établi** (wing
  déjà démarrée, boucle 30 Hz, DMX, LEDs). Elles ne contiennent **aucun**
  paquet Hello ni chunk de firmware : inutile d'y chercher un problème de
  connexion (vérifié au tshark).

#### Init à froid (obligatoire)
1. Hello packet : `0190040000000000`
2. **Réponse du bootloader : `0400079101000100`** ← voir l'encadré ci-dessous
3. Upload firmware : 34624 bytes en chunks de 512B (67 × 512 + 1 × 320)
4. End packet : `079004000000300000000000`
5. Config packet : `109004007c000000`
6. La wing reboot (re-énumération USB) — **~1,3 s** avant de réapparaître
7. Hello post-reboot : `0190040000000000`
8. **Réponse du firmware applicatif : `0791040001000200`** ← ≠ celle du bootloader
9. Config post-reboot : `109004007c000000`
10. ACK attendu : `19910000`

→ Géré par `wing_init.py` / `full_init()`

#### 🔑 LE HELLO DIT QUI RÉPOND — bootloader ou firmware

**Vérifié dans `d.pcapng`**, la capture d'origine de MA2 onPC. Le **même** paquet
Hello reçoit **deux réponses distinctes** selon l'interlocuteur :

| Interlocuteur | Réponse au Hello | Dans la capture |
|---|---|---|
| bootloader Atmel | `0400079101000100` | device 21, les 18 paquets d'entrée sans exception |
| firmware applicatif | `0791040001000200` | device 22, exactement une fois (poignée post-reboot) |

⚠️ **C'est une preuve de PROTOCOLE, pas une déduction.** `etat_wing()` lit la
VITESSE d'énumération (480 = bootloader, 12 = applicatif) — utile, mais
c'est une heuristique, et elle a un repli « inconnu → tenter et voir » qui
laissait passer un envoi de firmware. Ces signatures, elles, sont la wing qui
dit elle-même qui elle est. `upload_firmware` s'en sert pour refuser un envoi à
une wing qui tourne **même quand la vitesse est illisible**. Contrôle `test_poll_pkt`.

#### Ce que la capture confirme aussi

- **Le firmware embarqué est bit pour bit celui de MA2 onPC** : les 68 paquets
  de `d.pcapng` réassemblés donnent 34 624 o, sha256 identique à
  `wing_firmware.bin`. La promesse du README (« les mêmes octets que grandMA2
  onPC ») est donc vérifiée, plus seulement affirmée.
- **Aucun contrôle de flux pendant l'upload** : les 68 paquets partent en
  **7,6 ms**, sans une seule lecture intercalée. Notre implémentation (écriture
  en rafale, aucun ACK par chunk) est fidèle — inutile d'aller chercher un
  acquittement manquant de ce côté.
- **MA2 onPC ne vérifie pas l'état avant d'envoyer** : dans la capture il
  n'y a qu'un branchement à froid. Ça n'autorise rien : nous, on a un bouton
  « Réinitialiser » et une reconnexion automatique, donc des chemins que MA2
  onPC n'a pas — et envoyer le firmware sur l'un d'eux met la wing en
  bootloader.
- **Le bootloader continue de répondre ~1,3 s après l'End packet**, en paquets
  de 1024 o commençant par sa signature, avant de quitter le bus. C'est la
  raison d'être de la règle « attendre le DÉPART avant le RETOUR ».

#### ❌ NE PAS REFAIRE — récupération après un refus de démarrage du firmware

- **Remplacer le verrou `AUTO["attend_rebranchement"]` par un simple espacement
  des essais** (tenté 2 s → 30 s) : ça ne fait que ralentir un acharnement qui
  ne peut pas aboutir. Quand un chargement de firmware échoue à démarrer, les
  suivants échouent aussi tant que la wing n'a pas été mise **hors tension** — le
  verrou doit donc bloquer toute nouvelle tentative jusqu'à une disparition
  **réelle** du bus, pas juste temporiser. `full_init()` ne fait qu'**un** essai
  pour la même raison : chaque essai renvoie le firmware et fait rebooter la
  wing, ce qui l'entretient dans son blocage.
- **Renvoyer `FW_CFG_PKT` une seconde fois** après la ré-énumération : testé 3/3,
  la wing **accepte** le paquet (réponse `19910000`), **reboote**, et **retourne
  en bootloader** — jamais le Hello applicatif. Côté capture de réussite MA2
  onPC, ce second `FW_CFG` part alors que le firmware **tourne déjà** (Hello
  applicatif `0791040001000200` reçu avant, aucun chunk re-flashé) : c'est du
  polling opérationnel normal, pas une étape de récupération. La cause du non-
  démarrage était en amont — câble de données défectueux côté Mac (section
  « Chantier 1 — clos » plus bas), adaptateur USB-C générique côté Windows
  (`docs/WINDOWS.md`) — pas un paquet manquant dans la séquence.

#### ⚠️ Deux pièges du cooldown anti-martèlement, corrigés le 13/09/2026

Relevés par relecture de sécurité, dans `full_init()` (`wing_init.py`) :

- **Le cooldown s'horodatait même quand RIEN n'était parti.**
  `_marquer_firmware_envoye()` était appelé de façon INCONDITIONNELLE après
  `upload_firmware()`, y compris sur les chemins où celle-ci renvoie `False`
  AVANT d'avoir touché à un seul octet de firmware (Hello resté sans réponse,
  Hello applicatif refusé — le docstring d'`upload_firmware()` le dit
  lui-même). Un bootloader qui n'a RIEN reçu se voyait donc quand même frappé
  par `FW_REHAMMER_S`, et une reconnexion tout à fait légitime quelques
  secondes plus tard échouait sur un « firmware déjà envoyé » fictif.
  Correctif : `upload_firmware()` pose un drapeau `DERNIER_ECHEC["envoi_tente"]`
  juste avant sa boucle d'envoi des chunks (le premier octet RÉEL qui part) ;
  `full_init()` n'horodate que si `ok` est vrai OU si ce drapeau l'est —
  jamais sur un simple échec de poignée de main. Contrôle : le bloc « anti-
  martèlement » de `test_poll_pkt` (section 10 du test de fumée).
- **Le cooldown n'avait pas la dérogation `force` que `blocage_connu()` a.**
  `connect_wing()` documente `force=True` comme « le dernier recours garanti »
  qui passe outre tout blocage (clic délibéré sur « Connecter la wing »). Mais
  `full_init()` avait DEUX verrous distincts avant d'envoyer le firmware —
  `blocage_connu()` ET `_firmware_envoye_recemment()` (le cooldown) — et seul
  le premier avait `and not force`. Le second retenait donc encore le clic,
  sans qu'aucun message ne l'explique. Correctif : même dérogation sur les
  deux. Contrôle : `test_blocage_jamais_definitif` (section 35).
#### Cycle polling en régime établi (~30 Hz)
```
POLL     (4 bytes)   → STATE (140+ bytes)
LED_A    (520 bytes) → ACK  (4 bytes)
LED_B    (520 bytes) → ACK  (4 bytes)
CMD_264  (264 bytes) → ACK  (4 bytes)
```

### Le STATE packet
- Bytes 80-95 : 8 faders (uint16 LE, 0-1023)
- Bytes 32-35 : encodeur 1 (int32 LE, cumulatif)
- Byte  36    : encodeur 2 (uint8, delta mod256)
- Bytes 40-43 : encodeur 3 (int32 LE, cumulatif)
- Byte  44    : encodeur 4 (uint8, delta mod256)
- >140 bytes  : événements boutons (12 bytes chacun)
  Format : `[01/02][91][08][00][ts 4B LE][btn_id 4B LE]`
  `01` = press, `02` = release

---

## 💡 Carte des LEDs — un slot par bouton, sans configuration

**`slot = 2 × btn_id`** pour toutes les touches, **sauf les executors**
`0x70`–`0x7d` qui gardent leur bloc propre : `196 + 2 × (id − 0x70)`.

### D'où vient cette carte

Retrouvée dans **`a-1.pcapng`**, en corrélant les événements d'appui (paquets
d'état ≥ 140 o) avec les paquets LED de 264 o. Sur les
**7 boutons** pressés dans la capture, le même slot passe de **64** (veilleuse)
à **2040** (plein feu) :

| Bouton | Slot mesuré | 2 × id |
|---|---|---|
| `0x0e` | 28 | 28 |
| `0x26` | 76 | 76 |
| `0x2a` | 84 | 84 |
| `0x2b` | 86 | 86 |
| `0x3b` | 118 | 118 |
| `0x3c` | 120 | 120 |
| `0x42` | 132 | 132 |

**7 sur 7, sans exception.** Ces valeurs sont les références du contrôle `test_carte_led` :
ne pas les « corriger » sans une nouvelle capture à l'appui.

### Pourquoi ça comptait

Avant, seuls les executors s'allumaient. Les autres touches dépendaient d'une
**cartographie manuelle** (`PROFILE["leds"]`, assistant pas-à-pas dans
Paramètres → section « LEDs ») que **personne ne remplissait jamais** — d'où le symptôme « on appuie sur
un bouton, il ne s'allume pas ».

La méthode de mesure, si elle doit être rejouée : filtrer les slots qui changent
en permanence (clignotements pilotés par MA3), puis chercher celui qui **monte**
entre le paquet LED précédant l'appui et le suivant.

⚠️ **Pas de collision** : tous les boutons connus hors executors ont
`2 × id < 196`, vérifié sur les 49 boutons des profils. `2 × 0x70` vaudrait 224
et sortirait du bloc executor — d'où leur formule séparée.

## 🔌 Après l'End packet : ce que fait MA2 onPC, et ce qu'on faisait

Mesuré dans `d.pcapng`, en cherchant pourquoi le firmware refuse parfois de
démarrer.

**Séquence de référence (MA2 onPC), après l'End packet :**

| Quand | Quoi |
|---|---|
| +0 → +25 ms | le bootloader envoie **17 paquets, 17 408 o** ; le host les lit tous |
| +25 ms → +1,29 s | **silence total.** Aucun transfert de contrôle, aucune libération d'interface. Le host **garde la poignée ouverte** |
| +1,29 s | la wing quitte le bus et ré-énumère en mode applicatif |

**Ce que faisait Wing Bridge** : `_liberer(dev)` (release_interface + close)
environ **0,5 s après l'End packet** — donc **en plein reboot**. C'était le seul
écart net entre notre séquence et celle de la référence.

**Correctif** : la poignée est gardée pendant le reboot et rendue seulement
après le départ du bus — ou à l'expiration de l'attente, pour ne jamais la
garder indéfiniment (règle : tout chemin rend ce qu'il tient). Contrôle
`test_poignee_pendant_reboot`.

⚠️ **Ce n'est pas une cause démontrée du non-démarrage.** Ce qui est établi : la
référence ne ferme pas pendant le reboot, nous le faisions. Quand on ne comprend
pas une panne, se recaler sur l'implémentation qui marche coûte peu et **retire
une variable**. (La vraie cause du non-démarrage était ailleurs — voir
« Chantier 1 — clos ».)

## D'où vient `wing_firmware.bin` — et pourquoi ça n'est PAS dans la wing

Question fréquente : *« le firmware est celui présent dans la command wing qu'on
achète, non ? »* — **non**, et trois faits de ce projet le montrent :

| Fait | Ce qu'il prouve |
|---|---|
| Il est renvoyé **à chaque branchement** | s'il résidait dans la wing, ce serait inutile |
| La wing énumère en **bootloader (480 Mb/s) à chaque mise sous tension** | elle n'a pas d'applicatif à démarrer seule — c'est son état d'usine |
| Dans `d.pcapng`, les 34 624 o vont **`host → wing`**, à sens unique | le PC les avait déjà ; la wing ne les a jamais émis |

Le fichier vient donc de l'**installation de grandMA2 onPC**. C'est cohérent
avec la nature de l'appareil : une command wing (d'origine comme compatible) ne
contient qu'un **bootloader** et compte sur le logiciel de MA pour lui pousser
le reste **à chaque branchement**.

⚠️ **Ça ne change rien à l'innocuité** — RAM seule, mêmes octets que MA2 onPC
(sha256 vérifié), aucun débridage, aucune usure. Ça ne compte que si on
**redistribue** le `.bin`. Voir `README.md` (racine), « Sécurité de la wing ».

## Obtenir le firmware — configuration initiale (distribution OSS)

**La distribution open-source ne contient PAS `wing_firmware.bin`** : il
appartient à MA Lighting (voir la section précédente). Chaque utilisateur en
extrait donc SA copie, **une seule fois**, depuis une capture de grandMA2 onPC
poussant le firmware à sa wing. C'est indolore et vérifiable : à l'import, le
sha256 doit correspondre.

⚠️ **x64 Windows uniquement**, quelle que soit la voie. Le pilote `onpcwing.inf`
de MA n'a **pas de build ARM64** : la capture se fait forcément sur un PC
Windows Intel/AMD avec grandMA2 onPC installé. Un utilisateur Mac fait ça **une
fois** sur n'importe quel PC Windows, puis rapporte le `.bin` (bouton
« Exporter le firmware », section 3 plus bas).

### 1. Capturer — voie intégrée (recommandée)

**Paramètres → Configurer le firmware → « 📡 Capturer depuis grandMA2 onPC »**
— Wing Bridge fait tout : installe **temporairement** USBPcap (le composant de
capture USB, vendoré et vérifié par sha256, voir `docs/WINDOWS.md`,
« Capture firmware intégrée »), capture pendant que tu rebranches la wing avec
grandMA2 onPC lancé, extrait et vérifie le firmware, puis **retire** USBPcap
tout seul. Une seule invite Windows (élévation), un seul clic.

1. Clique le bouton, lis l'encart, clique **Continuer** (une invite Windows va
   demander la permission d'installer USBPcap — normal, c'est ça qu'on
   installe).
2. Assure-toi que **grandMA2 onPC** est lancé, puis **débranche puis rebranche**
   ta wing (à froid). L'upload dure ~2-3 s (les LED de la wing s'animent).
3. Attends : le message final dit si c'est bon (« Firmware configuré ») ou
   pourquoi ça a raté (« aucun upload détecté — grandMA2 onPC est-il lancé ? »).
   **Réessaie** au besoin — rien n'est laissé en place entre deux essais.

⚠️ **Ce qui « reste » n'est pas dans notre contrôle** : USBPcap installe un
**pilote noyau**, et un pilote-filtre actif sur un root hub **ne peut pas se
décharger à chaud** — Windows le retire à 99 % (dossier, outil en ligne de
commande) mais achève le retrait du fichier `.sys` lui-même **au prochain
redémarrage**. C'est le comportement normal de Windows pour n'importe quel
pilote actif, pas une fuite de notre code. Détail mesuré :
`docs/WINDOWS.md`, « Capture firmware intégrée ».

### 2. Capturer — repli manuel (Wireshark)

Si la voie intégrée échoue, ou sur une autre plateforme que Windows pour
**observer** une capture existante (l'extraction elle-même reste Windows x64
only, voir plus haut) :

1. Installe **Wireshark** — il propose d'installer **USBPcap** en cours de route
   (accepter ; un redémarrage peut être demandé).
2. Débranche la wing. Lance Wireshark, repère l'interface **`USBPcapN`** qui
   correspond au **hub où tu vas brancher la wing** (au besoin, teste : c'est
   celle où le trafic apparaît quand tu branches).
3. **Démarre la capture** sur cette interface.
4. **Branche la wing** (à froid) puis **ouvre grandMA2 onPC** — ou l'inverse ;
   ce qui compte, c'est que onPC pousse le firmware à une wing en bootloader.
   L'upload dure **~2-3 s** (les LED de la wing s'animent).
5. **Arrête la capture** et **enregistre en `.pcapng`**.
6. **Paramètres → Configurer le firmware → « Importer une capture (.pcapng) »** :
   Wing Bridge repère la séquence d'upload, réassemble les 34 624 o et vérifie
   le sha256. **Tu sauras que c'est bon : à l'import, le sha256 matche**
   (message vert « Firmware en place, empreinte confirmée »).
   Alternative si tu as déjà un `.bin` : **« Importer un firmware (.bin) »**
   (même vérification d'empreinte).

Le firmware est mis en **cache** (`<dossier de données>/wing_firmware.bin`) et
resservi à chaque branchement, quelle que soit la voie utilisée pour l'obtenir.

### 3. Rapporter sa copie sur une autre machine

Un utilisateur Mac qui a capturé sur un PC Windows (voie intégrée ou manuelle,
les deux produisent le même `.bin` vérifié) utilise **« Exporter le firmware »**
(visible une fois le firmware en cache) pour l'enregistrer, le copie sur son
Mac, puis fait **« Importer un firmware (.bin) »**. La capture n'est faite
qu'une fois, sur n'importe quel PC Windows x64 disponible.

### Ce que fait l'extracteur, en une ligne chacun

Module : `src/wing_firmware_extract.py` (pur Python, aucune dépendance — parseur
pcapng/pcap et pseudo-en-tête USBPcap inclus, pas besoin de tshark installé).

| Repère cherché | Valeur |
|---|---|
| Hello (hôte → wing, EP 0x02) | `0190040000000000` |
| Réponse bootloader (wing → hôte) | `0400079101000100` |
| Morceaux (bulk OUT, EP 0x02) | 67 × 512 o + 1 × 320 o = **34 624 o** |
| Borne de fin (End packet) | `079004000000300000000000` |

Il se cale sur le **device** du Hello, concatène les morceaux jusqu'au End
packet, et refuse tout ce qui ne fait pas exactement 34 624 o. En CLI :

```bash
python wing_firmware_extract.py capture.pcapng -o wing_firmware.bin
```

Contrôle du test de fumée : `test_firmware_extract` (capture synthétique sous
`src/fixtures/`, **jamais** le firmware réel).

## Sortie DMX (Paramètres → section « DMX ») — RÉSOLU

Découverte (capture `capture étapes.pcapng`, Windows + MA2 onPC + Wireshark) :
**le paquet USB de 520 octets "banque 01" envoyé à chaque cycle EST l'univers
DMX 1** : en-tête `0690040200020100` + 512 octets = canaux 1-512, un octet
par canal, sortis sur le XLR de la wing. La "banque 02" reste à zéro
(rôle inconnu — peut-être un 2e univers ou le port DMX in).

Chaîne complète : grandMA3 émet en sACN (E1.31, port 5568, multicast ou
unicast) ou Art-Net (port 6454) → `wing_connexion.py` écoute et remplit le buffer →
le cycle USB le transmet → le XLR sort le DMX.

**Source acceptée — option « local uniquement »** (audit du 25/09/2026).
L'écoute se fait sur toutes les interfaces : n'importe quelle machine du réseau
peut donc piloter les XLR. Paramètres → DMX → case « N'accepter le DMX réseau
que de cette machine » (`SETTINGS["dmx_local"]`, **désactivée par défaut** pour
ne pas casser une installation existante) : seuls les paquets venant de
`127.0.0.1`/`::1` sont acceptés (`_source_dmx_acceptee`), les autres sont
ignorés. ⚠️ Avec la case cochée, MA3 doit émettre en **unicast vers
127.0.0.1** : le multicast ne revient pas par l'adresse de bouclage. Les ports
`ARTNET_PORT`/`SACN_PORT` sont des constantes du module (pour que le test
écoute sur un port libre). Contrôle `test_dmx_local` : vrais paquets UDP,
`127.0.0.1` accepté, adresse du réseau local refusée. Non vérifié avec MA3 réel.

Config MA3 : Menu → In & Out → DMX Protocols → sACN → univers 1 en sortie.
Si le multicast ne passe pas : destination unicast = IP du Mac.

Vérifié par test bout-en-bout : paquet sACN → décodage → buffer (ch1=255,
ch2=128, ch3=64 retrouvés).

⛔ **Chaîne DMX jamais testée de bout en bout — bloquée par matériel externe.**
Faire sortir un univers DMX de grandMA3 onPC exige une **licence / un dongle
grandMA officiel**. Sans lui, MA3 onPC ne débloque aucun univers en sortie : la
partie « MA3 → réseau » de la
chaîne ne peut pas être alimentée, donc rien à valider en aval (wing, XLR,
projecteur). Ce n'est **pas une tâche en attente** : c'est hors de portée tant
que ce matériel n'est pas disponible. Seules les **LEDs** sont confirmées en
sortie de la wing.

---

## LEDs des boutons — RÉSOLU (capture leds_exec.pcapng)

Le paquet CMD_264 (264 o = en-tête `04900401` + 260 o) est **la carte des LEDs** :
- Un slot **16 bits little-endian par LED**, offsets pairs 6 à 242 (~100 LEDs)
- Valeurs : `0x0000` éteint, `0x0030` veilleuse, `0x07F8` plein feu (PWM 0-2047)
- **Boutons executor** : offset = 196 + 2 × (btn_id − 0x70) pour 0x70-0x7d
  (vérifié sur les 12 executors, corrélation parfaite appui/LED)
- Les autres slots (touches Store, Please, etc.) restent à cartographier :
  API `/api/led {"offset": N, "value": V}` pour tester slot par slot
- Implémenté dans wing_ui : rétro-éclairage complet au repos (payload de repos
  MA2 capturé) + feedback d'appui sur les executors

## Faders — ordre physique confirmé (capture fader_leds.pcapng)

| bytes | index | fader physique |
|-------|-------|----------------|
| 80-91 | 0-5   | F1 à F6 |
| 92-93 | 6     | **Master** |
| 94-95 | 7     | **Crossfade** |

## Banque 02 = 2e sortie DMX — CONFIRMÉ (capture test univers 2.pcapng)

La wing a **2 sorties DMX** (XLR 5 points) + 1 entrée DMX + MIDI in + LTC in.
- banque 01 (`…0100`) = XLR A = univers configurable (défaut 1)
- banque 02 (`…0200`) = XLR B = univers configurable (défaut 2)
Implémenté dans Paramètres → section « DMX » : chaque XLR a son univers sACN/Art-Net.
Reste inconnus : DMX in, MIDI in, LTC in (pas de matériel pour tester).

## Outils LED (Paramètres → section « LEDs »)

- **Chenillard "Vegas"** : tête lumineuse + traîne sur les ~119 slots —
  test visuel complet de toutes les LEDs
- **Cartographie touche ↔ LED — pas à pas guidé** : un scan automatique par
  minuteur (slots défilant seuls, choix de la touche dans une liste) a été testé
  puis retiré — le pas-à-pas doit être piloté par un VRAI appui physique, pas
  une liste déroulante. Design final :
  **Démarrer la détection** allume le slot courant ET passe en mode learn ;
  dès qu'un appui physique est détecté (`s.last_event`, réutilise le mécanisme
  existant), la touche est associée AUTOMATIQUEMENT au slot courant puis le
  pas-à-pas avance seul au slot suivant (le rallume, repasse en learn) — pas
  besoin de reconfirmer manuellement. **Rien à associer** avance sans
  attendre d'appui (LED inutilisée). **Fin de détection** arrête à tout
  moment. JS : `toggleLedDetect()`/`ledLightAndWait()`/`ledAssignDetected()`/
  `ledSkip()`/`stopLedDetect()`. S'arrête aussi automatiquement si on change
  d'onglet en pleine détection. Remplace l'ancien outil 3 boutons manuel
  (Détecter / naviguer ◀▶ / Associer) — aucun endpoint backend nouveau,
  réutilise `/api/mode` (learn), `/api/learn/clear`, `/api/led` (solo),
  `/api/led/map` déjà existants. Niveau réglable au curseur, inchangé.
- Le feedback d'appui utilise d'abord le mapping du profil, sinon la
  formule executor.

---

## Détection des wings compatibles (Paramètres → section « Détection »)

Le scanner USB identifie ce qui est branché et le classe :
- **Supportée** : VID:PID connu (`0x03EB:0x160B`) → fonctionne direct
- **Candidate** : puce Atmel (VID 0x03EB) ou classe vendor-specific avec
  endpoints bulk 0x81/0x02 identiques à la wing connue
- **Test de handshake** : envoie le HELLO MATRIX_USB au périphérique et
  compare sa réponse (préfixe attendu `0x0191`). Même réponse = même PCB
  = compatible. Réponse différente = copier le rapport (JSON avec descripteurs
  + réponse hex) pour ajouter le support.

Base des modèles connus : `KNOWN_DEVICES` dans `wing_detect.py` — à enrichir
au fil des rapports.

Comment savoir si deux wings ont la même puce ? Leur VID:PID et leurs
descripteurs USB le révèlent. Beaucoup de modèles compatibles sortent des mêmes
usines avec le même PCB, mais seul le branchement (ou l'ouverture du boîtier)
le confirme. Une wing avec un VID:PID différent = puce différente = il faudra
capturer son protocole (Wireshark USB) comme on l'a fait pour celle-ci.

---

## Mapping boutons (wing_bridge.py)

### Touches → buffer de commande (CMD_BUF_TOKENS)
`0-9`, `.`, `+`, `-`, `Thru`, `At`, `If`  
`Sequence`, `Cue`, `Executor`, `Fixture`, `Group`, `Preset`, `Macro`, `Effect`  
`Delete`, `Copy`, `Move`, `Assign`, `Label`, `Store`, `Update`

### Logique buffer
- Chiffres consécutifs : collés (`1`+`0`+`1` → `"101"`)
- Mots-clés : séparés par espace (`Store`+`Cue`+`1` → `"Store Cue 1"`)
- `Please` → exécute le buffer (ou envoie `Please` si buffer vide)
- `Clear` → vide le buffer (ou envoie `Clear` si buffer vide)

### Note

`0x05` (Backup) n'a **pas de commande OSC équivalente** dans MA3 : il est mappé
sur `Menu` (F12) par défaut plutôt que laissé sans effet. Les push des roues
(`0x48`–`0x4b`) portent `__ENCn_PUSH__`, câblé sur la bascule de groupe
d'attributs 5-8 (voir `KEYBOARD_MAPPING.md`).

---

# 📒 La liaison USB : ce qui a été mesuré, et ce qu'il ne faut plus retenter

> Accueille les pavés de commentaire qui vivaient dans `src/wing_ui.py`. Le code
> garde la règle **et ses chiffres** — c'est la mesure qui rend une règle
> non-inversible, pas sa formulation.

## Cadence de boucle à deux états : 30 Hz ou 2,7 Hz, une fois sur deux

Mesuré de façon reproductible :

| Situation | Temps de lecture |
|---|---|
| app ARRÊTÉE, mesure directe sur la wing | < 1 ms (médiane 0,4 ms sur 60 essais) |
| DANS l'app | soit ~0,4 ms (30 Hz), soit ~320-337 ms (2,7 Hz) |

Les deux états **alternaient parfaitement** d'un démarrage à l'autre —
30 / 2,7 / 30 / 2,7… vérifié sur 8 redémarrages consécutifs. Le chemin
d'initialisation est identique dans les deux cas (journal), durée identique
(~2 s), aucun message de différence.

### ❌ Essayé sans succès — NE PAS REFAIRE

- **purger le canal de lecture à la connexion** (drain 40 × 5 ms) : sans effet ;
- **réinitialiser la wing quand la boucle est lente** : sans effet sur la
  cadence, et le drapeau « une seule fois » était remis à zéro par
  `_release_device()` → réinitialisation en boucle. Correctif retiré ;
- **réduire le délai du drain** : effondre la cadence (voir ci-dessous).

### ✅ Ce qui a réglé le problème

Supprimer la source : `full_init` retente avec une poignée neuve avant de
conclure « muette », donc plus de rechargement de firmware, donc plus de reboot,
donc plus de retour lent. Les remèdes plus légers (voir plus bas) restent en
place comme filets.

🔬 **Où semble être l'état fautif** : sur un comptage de 9 épisodes, `clear_halt`
a suffi **8 fois sur 9**, la réouverture de liaison 1 fois, le reset de port
0 fois. Sur cet échantillon, l'état fautif penche **du côté de la wing** plutôt
que de la pile USB de macOS — à confirmer sur plus d'épisodes avant de l'écrire
comme acquis. Le *pourquoi* reste inconnu.

## Redémarrage du moteur : `os.execv`, et pourquoi l'inverse a été essayé

⚠️ **Cette règle a DÉJÀ été inversée une fois.** Elle disait « ne JAMAIS revenir
à `execv`, un process neuf toujours », au motif que `execv` garde le même PID
donc la même réservation d'interface USB. **Hypothèse RÉFUTÉE par la mesure** :
`claim: ok` pendant la panne. L'interface était parfaitement réservée.

Ce qui a tranché, c'est un comptage dans le journal de l'utilisateur :

| Mécanisme | Sessions | Wing absente au démarrage |
|---|---|---|
| `execv` (même PID) | 24 | **0** |
| process neuf | 15 | **11** |

Un process qui **meurt** fait fermer la liaison par le système, et la wing
**re-énumère** — une fois sur deux elle revient à ~670 ms par lecture au lieu de
0,4. Avec `execv` le process ne meurt pas, la wing ne re-énumère pas.

🔑 **C'est le cas d'école du projet** : une règle courte, confiante et plausible
peut être à l'envers. Ce sont les chiffres qui l'ont redressée — c'est pourquoi
ils restent dans le code et pas seulement ici.

📌 Reste à démêler : la re-énumération vient-elle de la MORT du process, ou du
`release_interface()` ajouté en même temps ?

## Valeurs fantômes après une reconnexion

À chaque reconnexion, `prev_faders` / `prev_encs` gardaient l'état d'AVANT la
coupure, et le premier paquet du retour était comparé à cet état périmé → MA3
recevait des ordres que personne n'avait donnés (`Master 1.1 At 0`,
l'intensité de la séquence sélectionnée tombant à zéro toute seule).

Le garde-fou existait (`startup_skip`) mais n'était réarmé que sur un changement
de **mode**, que la boucle ne voit jamais lors d'une reconnexion : pendant la
coupure elle sort par la branche « dev is None », qui `continue` avant la
lecture du mode. On se raccroche donc à la **poignée USB**.

**Vérifié au câble** : de 9 commandes parasites avant le correctif à **0 après**,
sur deux débranchements réels. Contrôle `test_reconnexion_sans_fantomes`.

---

## Comparaison avec MA2 onPC — l'init, paquet par paquet

Faite à `tshark` sur les 13 cycles de connexion réussie disponibles (`d.pcapng`
+ `Phase 2/` + `phase 3/`). Objectif : trouver un écart entre **notre** séquence
d'init et celle de la seule implémentation connue qui marche.

⚠️ **Une capture NOMINALE ne peut pas dire ce qui se passe quand ça rate.** Elle
dit ce que fait la référence ; tout écart trouvé est une **piste**, jamais une
cause.

### Ce qui est identique, 13/13 — ne pas y revenir

| Piste | Verdict |
|---|---|
| Poignée de main post-reboot | **identique au bit près** : `HELLO2_PKT` → `CONFIG2_PKT` → `POLL_PKT`, nos constantes |
| Taille / découpage du firmware | identique : 67 × 512 o + 320 o = **34 624 o** |
| Paquets de longueur nulle (ZLP) après chaque morceau | **n'existent pas** : les « 0 o » sont les enregistrements de COMPLÉTION d'URB de USBPcap |
| Transferts de CONTRÔLE « en plus » | c'est **l'énumération de Windows** (GET_DESCRIPTOR ×3, GET_STATUS, SET_CONFIGURATION), pas MA2 onPC |
| Paquets OUT « en plus » chez nous | **aucun** : `wing_init.py` n'ajoute rien d'absent chez MA2 onPC pendant l'init |

### Le seul écart : `CMD_264` au bootloader — occasionnel

MA2 onPC envoie parfois `CMD_264` (la carte des LEDs, 264 o) **au bootloader**,
~6,6 ms après `FW_CFG_PKT` et avant le reboot. **Occasionnel : 2 cycles sur
13**, pas systématique — probablement un tour de son cycle normal plutôt qu'une
étape de démarrage.

L'ajouter à notre séquence a été tenté (`ENVOYER_CARTE_LED`) et s'est révélé
**intestable** : `FW_CFG_PKT` lui-même ne partait pas sur ces essais, donc le
code d'envoi de `CMD_264` ne s'exécutait jamais. `ENVOYER_CARTE_LED = False` ;
le code reste en place, prêt à resservir si l'endpoint de sortie cesse un jour
de se bloquer avant `CMD_264`.

## La fenêtre après FW_CFG_PKT

Après `FW_CFG_PKT` — l'ordre de démarrer — la wing parle encore un court instant
avant de rebooter. C'était le seul candidat sérieux pour **séparer un démarrage
réussi d'un refus**.

**Ce que fait la référence** (mesuré sur 6 connexions réussies) :

| Repère | Valeur |
|---|---|
| `FW_END` → `FW_CFG` | toujours **< 0,5 ms** |
| Rafale de paquets d'état du bootloader (`0400079101000100`, 1024 o) juste après `FW_CFG` | **non vide** — 4 à 8 paquets, 3 à 9 ms (une capture isolée montait à 17 paquets / 25 ms : un cas particulier, pas un seuil) |
| Silence ensuite | ~1,29 s |
| Ré-énumération applicative | ~1,3 s après `FW_END` |

**Ce que faisait Wing Bridge**, mesuré : `FW_CFG_PKT` **ne partait jamais** —
l'endpoint de sortie se bloquait dans le premier ms après `FW_END_PKT`, et
l'erreur était **avalée par un `except Exception: pass`**. La séquence « Hello →
68 morceaux → `FW_END` → `FW_CFG` → drain » était donc fausse dans sa dernière
étape, **y compris pour les branchements qui réussissent** : le firmware démarre
parfois SANS `FW_CFG_PKT`.

Aucune mesure côté hôte ne distinguait un succès d'un échec : signature
identique au bruit près (fenêtre muette des deux côtés, sortie du bus à +0,2 ms,
`FW_CFG` refusé à l'E/S). La décision se prenait **dans la wing**, pendant son
reboot — ce qui a fermé la piste « il manque un paquet à notre séquence ».

### Pièges d'instrumentation, tous corrigés

| Piège | Pourquoi c'est grave |
|---|---|
| `USBError` non départagé | même classe d'exception pour un device **parti** et pour un **délai dépassé** — a produit une conclusion non fondée (« la wing avait déjà quitté le bus »). Ne jamais conclure d'un texte d'exception ambigu |
| `depart_s` présenté comme une mesure | il démarre après un `sleep(0.5)` et scrute à 0,1 s : il vaut 0,5 s dès que la wing part vite, c'est-à-dire toujours. Un **plancher**, pas une mesure — le chiffre qui date la sortie du bus est `partie_ms` |
| `usb.util.clear_halt(dev, ep)` | **n'existe pas** : c'est `dev.clear_halt(ep)` (méthode de `Device`). `AttributeError` sinon |
| mesure prise seulement sur les échecs | dix relevés de panne et zéro témoin ne se comparent à rien. La ligne `⏱️` part aussi sur un succès |
| `time.sleep(6,6 ms)` avant `CMD_264` | on dormait pendant le premier quart de la fenêtre. Remplacé par `_attendre_en_lisant()` : aucun paquet sortant ajouté, uniquement des lectures |

⚠️ **Ne pas raccourcir aveuglément le délai de réapparition.**
`attendre_reapparition` enregistre le **trajet** — chaque changement d'état,
horodaté — et la trace le rapporte. Verdict anticipé à ~5 s sur un état figé (au
lieu de 15), avec de la marge : un réveil spontané ~25 s plus tard a été
consigné une fois. Si une wing se réveillait tard, la trace le montrerait au
lieu qu'on le suppose.

🔒 Contrôle `test_fenetre_apres_fw_cfg`.

## Chantier 1 — clos : un câble USB défectueux

Toute la mesure ci-dessus documente un phénomène — « le renvoi de firmware
échoue une fois sur deux » — dont la cause était **en amont de tout ce que ces
mesures pouvaient voir** : un **câble USB défectueux, partie données**.

Test croisé : ancien câble, **7 échecs sur 10** essais réels ; câble neuf,
**0 échec sur 10**.

Ça explique mécaniquement pourquoi rien, côté hôte, ne distinguait jamais un
succès d'un échec : un défaut sur la paire de données se joue au niveau
électrique, avant que le protocole applicatif n'ait quoi que ce soit à en dire.
Rien de ce qui est mesuré plus haut n'est faux — les invariants du protocole
restent bons. **Ne pas rouvrir cette section pour y chercher une explication
logicielle sans nouvelle preuve.**

## Ce qui met la wing en bootloader : ⏻ Quitter

| Sortie | État trouvé au lancement suivant | Occurrences |
|---|---|---|
| **⏻ Quitter** (`os._exit(0)`) | **bootloader** → renvoi de firmware obligatoire | 4 / 4 |
| **🔄 Réinitialiser** (`os.execv`, même PID) | **opérationnelle**, aucun firmware envoyé | 2 / 2 |

**Un process qui meurt fait fermer la liaison USB par le système, la wing
re-énumère et perd son firmware (qui vit en RAM) : elle revient en bootloader.**
`🔄` y échappe parce qu'`os.execv` ne tue pas le process.

### Ce n'est PAS réparable en changeant la sortie

`restart_self()` appelle le **même** `arreter_usb()` (`release_interface` +
`dispose_resources`) que `⏻ Quitter`, et la wing survit. Un banc de test a
croisé quatre stratégies de sortie (rendre l'interface ou non ; mourir par
`os._exit` ou passer la main par `os.execv` vers `/usr/bin/true`) : **toutes**
perdent la wing. Ce qui compte n'est pas *comment* on sort, c'est de **rester en
vie**.

⚠️ **libusb n'est pas sûr après un `os.fork()`** — un banc qui forkait mesurait
un contexte libusb dans un état indéfini. Process NEUF (`subprocess`)
obligatoire.

### La wing tombe même sans qu'on l'ait ouverte

Mesuré : un process qui démarre Python et meurt **sans jamais toucher à l'USB**
perd quand même la wing, ~3 s après l'arrêt du flux de lecture.

> 🎯 **Hypothèse de travail — la wing a un CHIEN DE GARDE.** Tant qu'on la
> sollicite, elle reste en firmware ; dès que le silence dure, elle se remet en
> bootloader. Cohérent avec Windows, où « ~1 s après le relâchement de la
> poignée USB, la wing reboote en bootloader » (`WINDOWS.md`).

Reste à départager proprement : est-ce le **silence** ou la **poignée rendue** ?
Un banc doit refaire *exactement* ce que fait l'app (ouvrir UNE fois, garder la
poignée, lire — jamais scruter le bus en boucle : **un instrument qui figure
parmi les causes possibles ne mesure rien**). Un close→reopen déclenche par
ailleurs l'état LENT (raison du retrait de « ⏏ Déconnecter »).

**Conséquence probable** : repartir du bootloader à chaque démarrage à froid est
sans doute **le comportement normal**, pas un défaut. ⚠️ Le bouton **⏻ Quitter**
promet donc quelque chose de faux — « quitte en rendant la wing, rien à faire
avant » : il la laisse dans son bootloader.
