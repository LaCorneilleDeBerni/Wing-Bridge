# WINDOWS — spécificités de l'exécution sous Windows x64

> 🇫🇷 This reference document is in French. Translation contributions are
> welcome — see `CONTRIBUTING.md`.

**Ce fichier = ce qui diffère quand Wing Bridge tourne sous Windows x64.** Le
protocole USB de la wing (paquets, bootloader, LEDs, DMX) est le même sur les
deux OS et reste dans `HARDWARE.md` ; ici, seulement ce qui est propre à
Windows.

🚫 **macOS reste la cible de référence.** Windows x64 est supporté ; Windows ARM
ne l'est pas (voir plus bas).

> 🧭 **Index de toute la doc technique** : [`README.md`](README.md) (quelle
> question → quel fichier). Avant de toucher au code : [`CONTRIBUTING.md`](../CONTRIBUTING.md)
> à la racine (méthode, règles de modification, pièges).

---

## État du portage

| Domaine | Windows x64 |
|---|---|
| Énumération USB de la wing | ✅ `pyusb` + backend `libusb` (voir plus bas) |
| Upload du firmware, boucle `usb_loop`, DMX, LEDs | ✅ code partagé avec macOS, non modifié |
| Démarrage du firmware (bootloader → applicatif) | ✅ fiable **en branchement USB direct** ; échoue à travers un adaptateur USB-C générique (voir « USB : brancher la wing ») |
| Assistant clavier (mode console) | ✅ `wing_keyboard_windows.py` — `SendInput` + vol de focus minimal |
| Détection de grandMA3 | ✅ `wing_ma3.py`, branches Windows |
| Capture du firmware intégrée | ✅ Windows x64 **uniquement** (USBPcap vendoré) |
| `vm_active()` (détection de VM, purement informatif) | ❌ non porté — renvoie toujours `False`, le champ `vm` du diagnostic est inerte |
| Windows **ARM** | ❌ non supporté : USBPcap n'a pas de pilote ARM64 signé, grandMA2 onPC n'existe qu'en x64 |

Le moteur figé (`build_windows.ps1`) produit un dossier `dist-windows\` (moteur +
assistant clavier) équivalent en fonctions au `.app` macOS. Il est buildé
`--noconsole` : au double-clic, aucune fenêtre de terminal, le navigateur s'ouvre
seul sur `http://127.0.0.1:8765`. La seule sortie propre est **⏻ Quitter** (plus
de `Ctrl+C`).

✅ **Build #250 buildé et testé en conditions réelles le 26/09/2026** (wing +
grandMA3 onPC + navigateur, machine Windows 11 dédiée) — voir le détail dans le
bloc `📍 OÙ ON EN EST` de `ETAT_PROJET.md`. Premier build Windows jamais buildé
ET testé avec du matériel réel.

### Packaging : `build_zip_windows.ps1`

Pendant Windows de `build_zip_macos.sh` — à lancer **après** `build_windows.ps1`.
Ne build rien : empaquette `dist-windows\` en zip (`wing_server\` et
`Wing Keyboard\` directement à la racine de l'archive, pas de dossier parent —
c'est la structure déjà publiée), puis vérifie un **round-trip complet** sur la
copie EXTRAITE (comme côté macOS, pour prouver ce que l'utilisateur final aura
réellement) :

1. `wing_server.exe` présent
2. `Wing Keyboard.exe` présent
3. `wing_firmware.bin` **absent** (propriété MA Lighting, jamais embarqué en
   build OSS)
4. aucune fuite de nom personnel

Le zip est **refusé** (script en échec, zip laissé en place pour inspection) si
un seul de ces contrôles échoue.

```powershell
cd src
.\build_zip_windows.ps1                 # dist-windows\ -> ..\WingBridge-Windows-x64.zip
.\build_zip_windows.ps1 -DistPath ... -ZipPath ...   # chemins explicites
```

🚫 **Pas de contrôle de signature** — contrairement au `.app` macOS (ad-hoc
signé), l'exécutable Windows n'est **pas signé** : SmartScreen avertit
l'utilisateur (« More info → Run anyway »), c'est le comportement attendu et
documenté dans le `README.md` (« First launch »). Rien à vérifier de ce côté,
volontairement omis.

⚠️ **Contrôle anti-fuite de nom personnel — même principe que
`WING_NOMS_PRIVES` côté macOS** (voir `build_zip_macos.sh`) : les motifs à
chercher ne sont **jamais écrits en clair** dans le script (un script suivi par
le dépôt public qui épèle le nom qu'il protège serait lui-même la fuite). Ils
viennent de `$env:WING_NOMS_PRIVES` (une regex, ex. `'Prenom|Nom'`), définie
**localement** sur la machine de build, jamais dans le dépôt. Sans elle, le
contrôle est **sauté proprement** (avertissement affiché), pas un échec
silencieux — il faut la définir pour qu'il s'exécute réellement avant une
publication. Différence assumée avec le script macOS : ce contrôle-ci scanne
**tous** les fichiers du zip, `.exe`/`.dll`/`.pyd` compris (pas de filtre
« fichier binaire » à la `grep -I`) — un chemin de build absolu
(`C:\Users\<compte>\...`) peut se retrouver embarqué dans un binaire figé par
PyInstaller sans passer par une seule ligne de texte source.

⚠️ **Encodage du script** : comme `build_windows.ps1`, ce fichier `.ps1`
contient du texte accentué et doit être enregistré en **UTF-8 AVEC BOM** — sans
BOM, PowerShell 5.1 le relit dans la page de code système (cp1252 en FR) et les
caractères multi-octets (tirets cadratins, points de suspension…) cassent le
tokenizer en plein milieu d'une chaîne (vu une fois en écrivant ce script :
`Le terme «voir» n'est pas reconnu comme nom d'applet de commande…`). Voir
« Pièges de build PowerShell » plus bas — même piège que `wing_version.py` côté
Python, dans l'autre sens (celui-ci veut une BOM, celui-là la refuse).

---

## USB : brancher la wing

### Backend libusb

`pyusb` n'embarque aucune DLL libusb. Le backend est fourni par un fichier
`libusb-1.0.dll` (backend WinUSB, ~166 Ko) **posé dans `src/`** — c'est un
mécanisme déjà prévu par `wing_init._backend()`, qui cherche la DLL à côté des
scripts avant tout repli. Aucune DLL dans `System32`, aucun pilote modifié : le
pilote **WinUSB** déjà associé à la wing par Windows est justement celui avec
lequel libusb-1.0 sait dialoguer.

`build_windows.ps1` refuse de builder si `src\libusb-1.0.dll` est absente.

### 🟢 Brancher la wing DIRECTEMENT, jamais via l'adaptateur USB-C générique

La wing démarre **de façon fiable quand elle est branchée directement** sur un
port USB-A natif (racine → contrôleur xHCI). Elle **ne démarre pas** à travers un
adaptateur / hub USB-C générique à puce `VID_1A86&PID_809D` :

| Chemin | Taux de démarrage du firmware |
|---|---|
| **Direct** sur Root Hub 3.0 (aucun hub intermédiaire) | ~100 % (des dizaines de branchements, 0 échec) |
| **Via l'adaptateur** `VID_1A86&PID_809D` | **0 %** — retour bootloader systématique |

Preuve symétrique (même wing, même câble, même session, back-to-back à froid,
seule différence l'adaptateur dans la chaîne) : **6/6 échecs** via l'adaptateur,
**6/6 succès** en direct. Le `DevicePath` de l'instance USB départage les deux
cas sans ambiguïté (le parent immédiat de la wing est soit le concentrateur
générique, soit directement le Root Hub 3.0).

⚠️ **Ce qui est prouvé, c'est CE hub précis**, pas « les hubs en général ».
D'autres adaptateurs / hubs n'ont pas été testés.

**Rien à corriger côté code** : la séquence de `wing_init.py` marche telle quelle
en branchement direct.

### Comment la cause a été isolée

Avant de trouver l'adaptateur, toutes les explications logicielles ont été
épuisées et écartées, chacune indépendamment :

- **Ce n'est pas libusb.** La séquence firmware + `FW_CFG` réécrite en appelant
  `winusb.dll` directement (ctypes, sans libusb) reproduit l'échec à l'identique.
- **Ce n'est pas une policy de pipe.** Matrice `RAW_IO` / `SHORT_PACKET_TERMINATE`
  / `IGNORE_SHORT_PACKETS` / `PIPE_TRANSFER_TIMEOUT` : aucune ne fait booter en
  applicatif. `SHORT_PACKET_TERMINATE` change seulement le **code d'erreur** de
  `FW_CFG` (write accepté au lieu d'un stall), jamais l'issue — le stall était un
  symptôme, pas la cause.
- **Ce n'est pas un paquet manquant.** Le firmware envoyé est md5-identique à
  celui de grandMA2 onPC ; Hello / `FW_END` / `FW_CFG` identiques ; reboot et
  descripteurs identiques. Renvoyer `FW_CFG` une 2ᵉ fois après ré-énumération est
  **réfuté 3/3** (la wing accepte, reboote, retombe en bootloader — voir
  `HARDWARE.md`).
- **Ce n'est pas la veille sélective USB.** Registre : aucun opt-in
  (`DeviceIdleEnabled`, `SelectiveSuspendEnabled`) sur le chemin de la wing.
  Coupée au niveau système (`powercfg`), 5/5 essais échouent à l'identique.

Toutes ces captures / mesures **passaient par l'adaptateur** : elles ont servi à
éliminer une à une les causes logicielles et à forcer à remonter la chaîne USB
physique. Même schéma que côté macOS, où la cause d'un symptôme identique était
un **câble de données défectueux** (`HARDWARE.md`, section « Chantier 1 —
clos »).

### Signatures d'échec (pour mémoire — cause = l'adaptateur)

Deux signatures observées, deux noms du **même** fait :

- **Mode A** — `FW_CFG` écrit OK, la wing reste ~0,2 ms sur le bus, la lecture
  suivante ne rend que des zéros.
- **Mode B** — le write de `FW_CFG` stalle (`pipe (stall)` / `device parti`), la
  wing quitte le bus avant toute lecture. Dominant.

Vérifié au niveau bus (USBPcap) : **aucun STALL_PID** nulle part ; la complétion
de `FW_CFG` porte `USBD_STATUS_INVALID_PARAMETER` (rejet côté pile hôte), pas un
STALL, pas un « device gone ». Le device ne quitte pas le bus à +0,2 ms — il
ré-énumère ~1,3 s plus tard (le vrai reboot). Les étiquettes du code
(« stall », « device parti », « +0,2 ms ») **ne sont pas fiables** et varient
d'un run à l'autre sur le même échec : **toujours se fier au bus, jamais à
l'étiquette**.

### Piloter une wing déjà démarrée par grandMA2 onPC (« cas 1 »)

Si grandMA2 onPC démarre la wing en applicatif puis est fermé, Wing Bridge sait
reprendre la main — `full_init()` lit la vitesse de lien (speed 2 = applicatif),
exige `repond_au_poll`, et rend le device **sans jamais renvoyer le firmware**.
Deux conditions, toutes deux nécessaires (mesuré 3/3) :

1. **Rattraper la wing dans la fenêtre** après la fermeture de grandMA2 onPC.
2. **Ne jamais lâcher la poignée USB.** ~1 s après le relâchement de la poignée
   (bridge fermé ou planté), la wing reboote en bootloader. Le reset n'est pas dû
   à la fermeture de grandMA2 onPC en soi, mais à l'absence d'un hôte tenant la
   poignée.

⚠️ Tant que `gma2onpc.exe` tourne, son pilote (`OnPCWingDeviceClass`) **tient la
wing** — Wing Bridge (WinUSB) ne peut pas la reprendre (elle apparaît
« opérationnelle 12 Mb/s » mais muette). Fermer grandMA2 onPC → la wing repart.

---

## Auto-démarrage tardif de la wing

Après un upload firmware suivi d'un `FW_CFG` refusé, la wing reboote en
bootloader **mais le firmware est resté en RAM** : elle finit parfois son boot
toute seule et repasse de 480 Mb/s à 12 Mb/s **sans quitter le bus**, à un délai
variable (mesuré ~7 s à ~25 s).

L'ancienne logique ratait toujours ce cas : le verrou `attend_rebranchement` ne
se lève que sur un **départ réel du bus**, jamais sur un simple changement de
vitesse.

**Correctif** (`wing_connexion.py`, boucle `usb_loop`, branche
`attend_rebranchement`) : on surveille aussi la **vitesse USB**. Wing présente ET
applicative → on lève le verrou, la reprise se fait au tour suivant en **cas 1**
(aucun renvoi de firmware). Purement une lecture (`_trouver` + `dev.speed`),
aucune poignée ouverte, non bloquant.

⚠️ **Code partagé avec macOS** — le correctif peut y bénéficier aussi, mais n'y a
pas été revalidé. Depuis les correctifs de branchement direct, la wing boote
systématiquement sous Windows : ce chemin est **dormant** (jamais emprunté en
pratique), donc ni « sain » ni « à vérifier » — code en place, inoffensif.

---

## Reconnexion après un décrochage à chaud

Après un débranchement/rebranchement à chaud **pendant que l'app tourne** — ou
après un décrochage logiciel du Bridge (même exception `WingUnplugged`) — la wing
revient énumérée « opérationnelle » (12 Mb/s) mais **muette** au poll (écritures
acceptées, lectures vides 10/10 sur les deux poignées). `full_init` cas 1 rendait
alors « muette » → `return None`, sans fin : seul un redémarrage de l'app la
retrouvait.

**Solution — reconnexion complète automatique.** Le cas 1 fait déjà un test
exhaustif (10 polls × 2 poignées neuves, jamais de succès partiel) : un seul
verdict « muette » suffit comme preuve.

- Au 1ᵉʳ « muette » dans un épisode `WingUnplugged`, `full_init` arme
  `RECO_MUETTE["force_demande"]`.
- La **boucle USB** (seule propriétaire du device) le consomme au tour suivant et
  appelle `connect_wing(force_operateur=True)` → `full_init(force_operateur=True)`
  saute le cas 1 → cas 2 → `upload_firmware(force_operateur=True)`, qui contourne
  les deux refus « wing speed 2 » et renvoie le firmware.
- On ne touche jamais l'USB depuis le thread HTTP.

**Garde-fou firmware intact** : `force_operateur` vaut `False` par défaut. Le
seul `force_operateur=True` runtime est dans `usb_loop`, gardé par
`force_demande`. Le contrôle smoke « aucun firmware à une wing déjà
opérationnelle » reste vert.

Perte → récupération ≈ 19 s (dont ~7 s de rebranchement physique) ; récupération
logicielle pure ≈ 12 s, sans redémarrage, sans clic.

⚠️ Risque assumé : si l'upload Mode-B cale, la wing peut rester en bootloader (un
vrai débranchement la relance).

---

## Détection de grandMA3

`ma3_reachable()`, `ma3_sockets()` et `_port_ecoute()` reposaient sur des outils
Unix uniquement — leurs échecs étaient **avalés en silence** par un `try/except`
prévu pour les pannes transitoires, ce qui masquait l'incompatibilité de
plateforme (le panneau de santé restait « MA3 absent » alors que grandMA3
tournait).

| Fonction | macOS | Windows |
|---|---|---|
| `ma3_reachable()` — process vivant ? | `pgrep -i gma3` | `wing_keyboard_windows.find_ma3_pid()` — fenêtre GLFW30 de `app_gma3.exe`, **ré-énumérée à chaque appel**, aucun cache de PID (même principe « à chaud » que `pgrep`) |
| `_port_ecoute()` — port UDP écouté ? | `netstat -an -p udp`, format BSD (`127.0.0.1.8000`, séparateur `.`) | `netstat`, format Windows (`0.0.0.0:8000`, séparateur `:` ; `endswith(":8000")` évite qu'un port `48000` matche) |
| `ma3_sockets()` — compte de sockets | `pgrep` + `lsof -i` | PID via `find_ma3_windows()` puis `netstat -ano` compte les lignes du PID |

**`psutil` volontairement écarté** : non installé, et l'ajouter romprait la
contrainte « distribuable sans l'environnement de build ». `netstat` est déjà
présent partout.

⚠️ **Décodage `netstat`** : `subprocess.run(..., text=True)` décode avec la
codepage locale (cp1252 en FR), qui bute sur certains octets → `UnicodeDecodeError`
avalé → port signalé « muet » à tort. Les appels `netstat` passent
`errors="replace"` (on ne matche que de l'ASCII : « UDP », « :8000 », le PID).

⚠️ **`CREATE_NO_WINDOW`** sur les appels `netstat` : sinon une fenêtre console
clignote en boucle dans le build `--noconsole`.

---

## Assistant clavier Windows

`wing_keyboard.py` est un simple sélecteur (`sys.platform`) : `wing_keyboard_macos.py`
(CGEvent, inchangé) ou **`wing_keyboard_windows.py`** (`SendInput` + vol de
focus).

### Pourquoi `PostMessage` ne suffit pas

Le mode réellement utilisé par la wing exige **ShCuts activé** dans MA3. Mesuré :

| Mode MA3 | `PostMessage` (arrière-plan) | `SendInput` + focus |
|---|---|---|
| ShCuts OFF (texte) | ✅ | ✅ |
| **ShCuts ON** (le mode réel) | ❌ **rien**, même sur une touche simple, même avec `AttachThreadInput` | ✅ **seulement si MA3 a le focus** |

En ShCuts ON, MA3 ne consomme que les **vrais événements clavier** et seulement
quand il a le focus. Contrairement à macOS (`CGEventPostToPid` sans premier
plan), Windows n'offre aucune voie « arrière-plan » qui marche.

### Le mécanisme — vol de focus minimal

- Si MA3 est **déjà** au premier plan → on injecte, on ne touche à rien.
- Sinon : mémoriser le HWND courant, `SetForegroundWindow(MA3)` (fiabilisé par
  `AttachThreadInput`), injecter en `SendInput`, **restaurer immédiatement** le
  focus précédent.
- `SetForegroundWindow` refusé (restriction anti focus-stealing) → on
  **journalise** et on n'envoie pas. Jamais d'échec muet.
- Imprimables → **événement TOUCHE VK** (pas `WM_CHAR`, pas `KEYEVENTF_UNICODE`) :
  en ShCuts ON, un événement caractère unicode ne déclenche pas les raccourcis.

**Compromis assumé : fiabilité > confort visuel.** Le vol de focus est visible
(MA3 passe devant ~¼ s) et coûte **≈ 250 ms par frappe** — c'est le seul moyen
mesuré de faire arriver une frappe en ShCuts ON.

### AZERTY — chiffres en position US

Sur AZERTY, `VkKeyScanW('8')` réclame **Shift** ; or en ShCuts, « Shift = touche
MA », donc MA3 lit « MA+8 ». MA3 lit la **position** de touche, pas le caractère
produit — même règle « position US » que le projet applique déjà aux raccourcis à
modificateur (`KEYBOARD_MAPPING.md`). `type_char` envoie donc les chiffres en
position US nue (`0x30`–`0x39`). Les lettres partagent leur VK AZERTY/QWERTY
(`s` → `0x53`), `VkKeyScan` suffit.

### Limites connues, non résolues

- **Appui long (hold)** : le focus est rendu **entre** `hold_down` et `hold_up`.
  Le maintien natif MA3 (Clear maintenu = ClearAll…) n'est pas fiable par ce
  chemin.
- **Caractères accentués / symboles** au-delà des chiffres : repli
  `KEYEVENTF_UNICODE`, qui ne déclenche pas les raccourcis ShCuts. Rare pour la
  wing (mots-clés en minuscules), assumé.

Piste future notée, non engagée : driver HID virtuel pour injecter sans vol de
focus.

---

## Capture du firmware intégrée (USBPcap)

**Windows x64 uniquement.** La distribution ne contient pas `wing_firmware.bin` :
l'utilisateur en extrait une copie depuis une capture de grandMA2 onPC poussant
le firmware à sa wing. Sur Windows x64, Wing Bridge peut faire toute la capture
lui-même — l'exigence étant que **rien ne reste installé** au-delà de la capture.

### Windows x64 uniquement — pas Windows ARM

Deux briques n'existent qu'en x64 : USBPcap (pilote-filtre noyau, aucun `.sys`
ARM64 signé) et grandMA2 onPC (la source du firmware). `capture_supportee()` lit
l'architecture **réelle** de l'OS (`PROCESSOR_ARCHITEW6432` / `PROCESSOR_ARCHITECTURE`,
pas celle du process qui peut être émulé) ; sur ARM, `_capture_statut()` renvoie
`null` et l'UI masque entièrement la carte. Repli : capturer sur un PC x64,
exporter le `.bin`, l'importer sur la machine ARM.

### Le spike ETW — refusé

Remplacer USBPcap par de l'ETW natif (`logman` / `tracerpt`, admin, zéro pilote)
a été testé et **refusé** : les événements USB de `FullDataBusTrace` ne portent
que la structure de l'URB (adresses, tailles, statuts), **jamais les octets
transportés** — vérifié en Start et Stop, de 3 o à 65 536 o, avec et sans `-lr`.
USBPcap reste la seule voie mesurée pour obtenir la charge utile.

### La forme CLI de USBPcapCMD

`USBPcapCMD.exe` sait parler le protocole *extcap* de Wireshark, mais la forme
CLI simple suffit et a été vérifiée en réel :

```
USBPcapCMD.exe -d \\.\USBPcapN -o sortie.pcap -A --capture-from-new-devices -b 134217728
```

- `-A` capture ce qui est **déjà branché** ; `--capture-from-new-devices` ce qui
  se branche **pendant** — deux drapeaux distincts, **les deux nécessaires** pour
  le cas « débranche puis rebranche ».
- Sortie : un `.pcap` **classique** (pas pcapng), que `wing_firmware_extract.py`
  lit déjà.

⚠️ **`USBPcapCMD.exe` casse la capture de sa sortie sous PowerShell.**
`& USBPcapCMD.exe ...` par variable ou `> fichier` rendent une sortie **vide**,
sans erreur : l'exe fait sa propre gestion de console (`AttachConsole` +
`freopen CONOUT$`) qui ne reconnaît pas la redirection PowerShell. **Seul**
`Start-Process -RedirectStandardOutput <fichier>` fonctionne.

### Capturer sur TOUS les root hubs

`USBPcapCMD.exe --extcap-interface=... --extcap-config` n'imprime **jamais** le
VID/PID par device (seulement `CM_DRP_DEVICEDESC`, une chaîne du Gestionnaire de
périphériques). Filtrer là-dessus serait un mirage. On capture donc en parallèle
sur **chaque** interface `USBPcapN`, chacune vers son propre `.pcap`, et Python
tente l'extraction sur chacun. Coût négligeable (~quelques process).

### Une seule élévation

`ShellExecuteExW(lpVerb="runas")` lance **un seul** `powershell.exe`
(chemin absolu sous `System32`), qui exécute le script
`wing_firmware_capture_eleve.ps1`. Celui-ci enchaîne install → capture → désinstall
lui-même, déjà élevé. `USBPcapCMD.exe` hérite l'élévation. Python (non élevé)
poll un fichier de statut JSON (écriture atomique `.tmp` + `Move-Item`) et fait
l'extraction (pur Python, lit les `.pcap` en cours d'écriture — le parseur tolère
un enregistrement final tronqué).

🔒 **Amorce vérifiée — audit du 25/09/2026 (I3).** Avant, la commande élevée
était `-File <chemin>` : le script et l'installeur USBPcap étaient lus **après**
le clic UAC, depuis des emplacements qu'un programme non élevé pouvait
réécrire entre-temps — il obtenait alors une exécution administrateur. Désormais
Python passe une **amorce** en `-EncodedCommand` (`_AMORCE`,
`_commande_eleve` dans `wing_firmware_capture.py`). Déjà élevée, elle :
1. crée `%ProgramData%\WingBridge-<guid>` **avec son ACL dès la création**
   (`Directory.CreateDirectory(chemin, DirectorySecurity)` : Administrateurs +
   SYSTEM, sans héritage) — aucun instant où le dossier est inscriptible par
   l'utilisateur ;
2. y copie le script et l'installeur, puis calcule `Get-FileHash` **sur la
   copie** et la compare aux empreintes figées dans le code Python
   (`SCRIPT_CAPTURE_SHA256`, `SCRIPT_RETIRER_SHA256`, `USBPCAP_SHA256`) ;
3. n'exécute que la copie vérifiée, et refuse tout le reste.

Le script de retrait (`wing_firmware_retirer_eleve.ps1`) passe par la même
amorce. ⚠️ **Modifier un `.ps1` change son empreinte** : il faut mettre à jour
la constante correspondante, sinon le contrôle `test_amorce_elevee_verifiee`
échoue (et, sous Windows, l'amorce refuserait le script). Piège rencontré en
écrivant l'amorce : PowerShell aplatit `@(@(a, b, c))` quand il n'y a qu'un
élément — la liste des copies est donc construite par `ArrayList.Add`.

✅ **Exécuté pour de vrai sous Windows le 26/09/2026** (harnais direct appelant
`_lancer_eleve` hors de tout le wizard, sur le script de retrait — sans danger,
USBPcap n'étant pas installé sur cette machine) :
- **Chemin normal** : vraie invite UAC, acceptée → statut final
  `uninstall_ok: true`, `termine: true`.
- **Chemin sabotage** : copie du script légitime + une ligne ajoutée, passée
  avec l'empreinte FIGÉE réelle (donc désormais fausse pour ce fichier modifié)
  → l'amorce refuse : `"erreur": "empreinte inattendue pour script.ps1 : …"`,
  `uninstall_ok: false`. La copie sabotée n'a jamais été exécutée.
- **Refus UAC** (clic accidentel sur « Non » pendant le premier essai) :
  `ok_lance=False`, `err="invite d'élévation refusée"` (`ERROR_CANCELLED`,
  1223) — bien distingué d'un échec technique.

🐛 **Deux bugs réels trouvés par cette exécution, corrigés le jour même :**

1. **Fichier de statut illisible par l'appelant (les deux scripts).** Le
   process ÉLEVÉ écrit `$StatusFile` dans un dossier créé par Python NON
   élevé (`tempfile.mkdtemp`) — le fichier hérite d'un ACL qui refuse la
   LECTURE au process non élevé qui doit le relire (`PermissionError`
   systématique, mesuré : `status.json` bien écrit, 78 octets, mais
   « Permission denied » en le relisant). Le script de capture avait déjà un
   correctif icacls, mais ciblant `$WorkDir` — le script de RETRAIT n'en avait
   aucun. **Impact réel** : le bouton de secours « Retirer le composant de
   capture » aurait toujours rapporté un échec/timeout, même en cas de retrait
   réussi. Correctif immédiat : même icacls ajouté dans
   `wing_firmware_retirer_eleve.ps1` (empreinte recalculée,
   `SCRIPT_RETIRER_SHA256` mis à jour).
2. **Le correctif ci-dessus ne suffisait pas : la faille était plus profonde.**
   Rejouer le chemin sabotage (empreinte inattendue) montrait le MÊME trou :
   60 s de timeout, aucun statut lu, alors que l'amorce avait bien tourné et
   refusé. Cause : `Stop-Amorce` (appelée par l'amorce PARTAGÉE, avant même de
   lancer l'un des deux scripts) écrit aussi dans `$statut` — et ni le
   correctif du script de capture ni celui, tout neuf, du script de retrait ne
   s'étaient encore exécutés à ce stade. **Corrigé à la racine** : le
   rehaussement de droits (icacls, lecture accordée au propriétaire du dossier
   de `$statut`) déplacé dans `_AMORCE` elle-même (`wing_firmware_capture.py`),
   en toute première action, avant la création du dossier `%ProgramData%`.
   Couvre désormais les deux scripts ET l'échec de l'amorce elle-même. Rejoué
   après correctif : le message d'erreur devient lisible (voir « chemin
   sabotage » ci-dessus).

Preuve indirecte supplémentaire, sans rapport avec l'amorce : le smoke test a
aussi trouvé et fait corriger, sur cette même machine, une course Windows dans
`os.replace()` — voir plus bas, section « Bug Windows trouvé par le smoke
test ».

⚠️ **Ce qui n'a PAS été rejoué** : le cycle complet
install→capture→désinstallation réelle de USBPcap (I4). Décision du 26/09/2026
: le correctif I4 est une SUPPRESSION pure (le bloc `PendingFileRenameOperations`
n'existe plus, dans aucun des deux scripts) — pas une nouvelle logique à risque
de régression. Confirmé par lecture des deux scripts, et indirectement par les
deux exécutions réelles ci-dessus (chemin retrait, USBPcap absent à chaque
fois) : aucune trace de ce bloc n'est apparue. Juger le gain de certitude d'un
cycle d'installation réelle (avec son ~1-3 s de coupure USB pendant que la wing
et MA3 tournaient) trop marginal pour le risque, sur cette machine en usage
réel.

⚠️ **`$WorkDir` est créé par Python (non élevé)** ; chaque fichier que le script
**élevé** y écrit héritait d'un ACL refusant la lecture au process non élevé. Le
script élevé pose donc, tout au début, un `icacls $WorkDir /grant "*<SID>:(OI)(CI)RX" /T`.
Depuis le 25/09/2026, le SID est celui du **propriétaire de `$WorkDir`**
(`GetOwner`) — l'utilisateur qui a lancé l'app, même si l'élévation s'est faite
avec un AUTRE compte administrateur ; repli sur l'identité courante si le
propriétaire est illisible. Avant, c'était toujours l'identité courante (celle
de l'admin qui a validé l'UAC). Même correctif : la variable `$args` du script,
qui masquait la variable automatique de PowerShell, s'appelle `$argsUsbpcap`.

✅ **Testé pour de vrai le 26/09/2026** — et incomplet : ce correctif ne
couvrait que `$WorkDir` (script de capture), pas `$StatusFile` du script de
RETRAIT (qui n'a pas de `$WorkDir`), ni l'échec de l'amorce elle-même AVANT
qu'aucun des deux scripts n'ait tourné. Les deux trous, trouvés par exécution
réelle, sont corrigés : icacls ajouté dans `wing_firmware_retirer_eleve.ps1`
(ciblant le dossier de `$StatusFile`) ET dans `_AMORCE` elle-même (voir
ci-dessus, « Une seule élévation »). Détail des deux bugs et de leur preuve
dans le paragraphe précédent.

### Un pilote-filtre de root hub ne se décharge pas à chaud

`Uninstall.exe /S` rend le code 0 et vide le dossier, mais :

- le **service** reste `RUNNING` avec `DeleteFlag=1` au registre ;
- `USBPcap.sys` reste **chargé** jusqu'au prochain redémarrage de Windows.

C'est le comportement standard d'un pilote-filtre actif sur un root hub. Donc
`usbpcap_present()` ne regarde **que** le dossier `USBPcapCMD.exe` (ce qu'on peut
effectivement exécuter), jamais `sc query`. Et les messages d'échec ne renvoient
**pas** vers « Panneau de configuration → Programmes » (USBPcap n'y apparaît pas,
ce n'est pas un « Programme »).

⚠️ **Réinstaller PENDANT la fenêtre `DeleteFlag=1`** déclenche une **MessageBox
NSIS bloquante** (« Reboot is required before installation »), que `/S` et
`-WindowStyle Hidden` **n'empêchent pas**. Deux défenses :
`Test-DesinstallationEnAttente` lit `DeleteFlag` avant l'installeur et refuse
proprement ; `Start-ProcessAvecTimeout` (30 s) enveloppe tous les
install/désinstall et tue le process si la boîte apparaît.

### Attache À CHAUD du filtre — pas de redémarrage au 1ᵉʳ install

`USBPcap.inf` : `DriverPackageType = ClassFilter`, `ClassGuid = {36FC9E60-…}`.
L'installeur NSIS fait **une seule chose côté pilote** : ajouter `USBPcap` à
`HKLM:\SYSTEM\CurrentControlSet\Control\Class\{36FC9E60-…}\UpperFilters` (filtre
de **classe**, pas un `UpperFilters` par-périphérique — c'est là que les
premières enquêtes regardaient au mauvais endroit).

**Un filtre de classe ne s'insère dans la pile d'un périphérique qu'au
(re)montage de cette pile.** Celle des root hubs est montée au **boot** → après
un install frais, `--extcap-interfaces` rend **0** (service tourne, `.sys`
chargé, filtre dans aucune pile) → d'où le reboot historiquement demandé.

**Forcer le remontage** (`pnputil /restart-device` sur chaque `USB\ROOT_HUB*`,
repli `Disable-PnpDevice` / `Enable-PnpDevice` dans un `finally`) **insère le
filtre à chaud, sans redémarrage** — vérifié : retirer `USBPcap` de
`UpperFilters` + restart → 0 interface ; remettre + restart → 2 interfaces + une
capture `.pcap` valide.

`wing_firmware_capture_eleve.ps1` tente donc `Enable-UsbpcapFilter` dès que
`--extcap-interfaces` = 0, avant de renoncer. Le message « redémarre Windows »
n'est plus qu'un **repli non bloquant** (« fais-le quand tu veux, puis reclique »)
appuyé par le nettoyage différé.

⚠️ **Coût** : `pnputil /restart-device` sur un root hub coupe tout l'USB de ce
contrôleur ~1-3 s (atomique, auto-rétabli). Invisible sur un portable à clavier
interne ; blip d'entrée sur un poste à clavier USB, au 1ᵉʳ install seulement.

### Le retrait de USBPcap ne se fait qu'À BUS CALME

Si le `finally` du script élevé retire USBPcap **pendant** que grandMA2 onPC
tourne et que la wing est branchée, `Restart-RootHubs` ne décharge pas
`USBPcap.sys` (root hub occupé) → service bloqué `DeleteFlag=1` jusqu'au reboot,
**et** le filtre reste coincé dans la pile de la wing (qui a énuméré sur un hub
filtré pendant la capture) → **wing muette, boutons éteints** une fois la capture
finie.

**Séquence de retrait** : détacher le filtre de classe (`Remove-UsbpcapClassFilter`
retire `USBPcap` de `UpperFilters` + `Restart-RootHubs`) **AVANT** `Uninstall.exe`.
Le script élevé écrit `capture_finie` puis **attend `cleanup.flag`**, que Python
ne pose qu'après « grandMA2 onPC fermé » ET « wing débranchée ». Bus au calme →
`restart-device` décharge réellement `USBPcap.sys` → `Uninstall.exe` retire tout
le service, **sans reboot**. Balayage final : `Remove-Item` du dossier vide + de
`USBPcap.sys`, en attendant la fin de l'auto-désinstalleur NSIS `Un_A.exe`.

⛔ **`PendingFileRenameOperations` n'est plus touché** (audit du 25/09/2026,
I4 — retiré des DEUX scripts, le script de retrait l'avait aussi). Ce balayage
réécrivait une valeur système lue par Windows au démarrage pour en retirer les
paires USBPcap, qui ne font pourtant que « supprimer un chemin déjà absent » au
prochain boot : gain nul. Le risque ne l'était pas : si PowerShell écartait les
chaînes vides du `REG_MULTI_SZ` (hypothèse jamais vérifiée), les paires
[source, cible] se décalaient, et une suppression différée d'un AUTRE logiciel
devenait un renommage vers un mauvais chemin. Ne pas le remettre sans l'avoir
mesuré sur une vraie machine Windows.

### Nettoyage différé

Si le flag persistant `usbpcap_installe_par_nous` était vrai **avant** un run
(USBPcap laissé par une tentative antérieure) et que la capture **réussit** cette
fois, `retirer_composant_capture()` est appelé en fin de fonction — pour ne pas
laisser USBPcap installé indéfiniment simplement parce que le run qui a réussi
n'était pas celui qui l'avait posé.

### L'assistant 7 étapes

La capture est un assistant numéroté (barre `1/7 … 7/7`), chaque étape débloquée
par une détection — pas de sous-endpoints, une machine à états dans
`capturer_firmware()`. `CAPTURE_STATE` porte `phase`, `phase_total`,
`phase_titre`, `chemin`, lus par `/api/status`.

| # | Consigne | Débloqué par |
|---|---|---|
| 1 | Lance grandMA2 onPC sur ce PC | `gma2onpc.exe` présent (`tasklist /FI`, ré-interrogé à chaque sondage — même principe que `pgrep`) |
| 2 | Débranche ta wing | `wing_init._trouver()` → `None` (le primitif exact d'`usb_loop` ; wing déjà débranchée → étape sautée) |
| 3 | Préparation (UAC + install USBPcap + attache à chaud) | script élevé |
| 4 | Branche ta wing — puis ne la débranche plus | blob Hello valide extrait du `.pcap` (le firmware est **sauvegardé dès ici** ; une étape 5-7 qui expire ne perd rien) |
| 5 | Ferme grandMA2 onPC | `gma2onpc.exe` **absent** (son pilote tient la wing) |
| 6 | Débranche ta wing → l'assistant retire USBPcap | wing absente + `cleanup.flag` posé (bus au calme) |
| 7 | Rebranche ta wing → Wing connectée | `etat.E.STATE["wing"]` (nudge `connect_wing(force=True)`) |

`usb_loop` se retire du bus pendant les phases 3-4 + nettoyage (drapeau dédié
`CAPTURE_STATE["usb_exclusif"]`, **jamais** `actif` qui couvre aussi les pré-vols
1-2 et la reprise 5-7 où `usb_loop` doit au contraire tourner). Fenêtre de
capture 150 s + `GRACE_APRES_WING_S` (60 s après le retour de la wing).

### Repli manuel (Wireshark)

Toujours conservé : installer Wireshark (qui propose USBPcap), capturer
l'interface `USBPcapN` du hub où l'on branche la wing pendant que grandMA2 onPC
pousse le firmware, enregistrer en `.pcapng`, puis **Paramètres → Configurer le
firmware → Importer une capture**.

### Licences

USBPcapDriver = **GPLv2**, USBPcapCMD = **BSD 2-Clause** (deux licences
distinctes, ni l'une ni l'autre GPLv3). Détail dans `THIRD_PARTY.md` et
`src/vendor/usbpcap/README.md`.

---

## Bug Windows trouvé par le smoke test : `os.replace()` n'est pas `rename(2)`

🐛 **Trouvé le 26/09/2026**, contrôle 77 (`test_part_unique`, sauvegardes
concurrentes d'un même profil) : 3 fils × 150 sauvegardes du MÊME profil
(motif temp-file unique par fil + `os.replace()` vers la destination commune,
voulu pour supporter bouton + sauvegarde auto + plusieurs onglets en même
temps) → `PermissionError: [WinError 5] Accès refusé` sur ~78/450 tentatives,
jamais vu sur macOS.

**Cause** : `rename(2)` POSIX garantit l'atomicité même sous deux renommages
concurrents vers la MÊME destination — aucune erreur, le dernier gagne.
`os.replace()` sous Windows (`MoveFileEx`) n'offre pas cette garantie : deux
remplacements concurrents de la même destination peuvent se faire concurrence
et lever un accès refusé intermittent. Le nom du fichier temporaire était déjà
unique par fil (ça, ce n'était pas la faille) — c'est le remplacement FINAL,
vers la destination partagée, qui se marchait dessus.

**Correctif** : un verrou (`threading.Lock`) qui sérialise uniquement l'appel
`os.replace()` — l'écriture du temporaire reste hors verrou, en parallèle.
Ajouté dans les deux endroits qui partagent exactement ce motif
(temp-file-unique-par-fil + destination commune) :
- `wing_mapper.save_profile()` → `_SAVE_PROFILE_LOCK`
- `wing_reglages.save_settings()` → `_SAVE_SETTINGS_LOCK`

Les autres écritures atomiques du projet (`wing_profils.py`,
`wing_etat_materiel.py`, `wing_firmware.py`, `wing_jeton.py`,
`wing_raccourcis.py`) utilisent un nom de temporaire FIXE (pas pid+fil) : elles
n'ont qu'un seul écrivain possible, donc pas concernées par cette course.

**Preuve** : smoke test §77 rouge avant correctif (mesuré sur cette machine),
82/82 vert après.

---

## Pièges de build PowerShell

Tous vécus, tous corrigés. À connaître avant de toucher aux `.ps1`.

| Piège | Remède |
|---|---|
| **`Set-Content -Encoding UTF8` pose TOUJOURS un BOM** (PowerShell 5.1) ; Python décode en `utf-8` strict → `JSONDecodeError: Unexpected UTF-8 BOM` / `ast.parse` échoue sur `U+FEFF`. **Piège récurrent** — vu au moins deux fois (`wing_version.py`, puis le statut de capture) | `[System.IO.File]::WriteAllText($path, $txt, [System.Text.UTF8Encoding]::new($false))` partout où le fichier est relu par Python |
| **Toute ligne sur stderr = erreur TERMINANTE** avec `$ErrorActionPreference = 'Stop'` (PS 5.1 ; pas pwsh 7) : les logs INFO de PyInstaller avortent le build avant le contrôle de `$LASTEXITCODE` | helper `Invoke-Native` : exécute smoke + PyInstaller avec la préférence relâchée, verdict = `$LASTEXITCODE` |
| **Crash au 1ᵉʳ `print()` sur console cp1252** : `UnicodeEncodeError` sur « → » et les nombreux caractères non-ASCII des messages. Masqué depuis les sources par `PYTHONIOENCODING=utf-8`, découvert au lancement du build figé | `main()` (`wing_ui.py`) bascule `stdout`/`stderr` en `reconfigure(errors="replace")` avant tout affichage |
| **`USBPcapCMD.exe` : sortie vide** sous `& ... > fichier` ou par variable | `Start-Process -RedirectStandardOutput` uniquement (voir « Capture du firmware ») |
| **L'assistant clavier figé verrouille ses DLL** (`libcrypto-3.dll`) : un rebuild échoue au nettoyage de `dist-windows\` tant qu'il tourne | le tuer (avec le serveur) avant de rebuilder |
| **Shell ÉLEVÉ ≠ comportement réel** : lancer le moteur depuis un shell déjà administrateur fait que `ShellExecuteExW(verb=runas)` élève **silencieusement**, sans invite UAC | toujours tester depuis une session utilisateur **normale** (double-clic dans l'Explorateur) |
| **Plusieurs serveurs Wing partagent le port 8765** (`SO_REUSEADDR`) : `curl` tombe sur un ancien serveur de façon non déterministe | tuer tous les serveurs et vérifier l'unique détenteur de 8765 (`netstat -ano | findstr :8765`) avant de conclure d'un `/api/status` |
| **Un `.ps1` accentué SANS BOM casse le tokenizer PowerShell 5.1** (piège inverse du premier : ici c'est le script LUI-MÊME, pas un fichier qu'il écrit) — lu en cp1252 (FR), un tiret cadratin ou des points de suspension UTF-8 se changent en octets qui terminent une chaîne en plein milieu, ex. `Le terme «voir» n'est pas reconnu…` (vu en écrivant `build_zip_windows.ps1`) | enregistrer le `.ps1` en **UTF-8 AVEC BOM** (`[System.IO.File]::WriteAllText($path, $txt, [System.Text.UTF8Encoding]::new($true))`) — tous les `.ps1` du projet (`build_windows.ps1` compris) le sont déjà |

---

## Désinstallation — deux dossiers de données

Sous Windows, l'assistant clavier écrit `wing_keyboard.log` dans
`%LOCALAPPDATA%\Wing Bridge`, **hors** de `%APPDATA%\Wing Bridge` où le moteur
écrit ses profils et son journal. `_desinstall_dir_local()` renvoie ce second
dossier (et `None` sur macOS) ; `_desinstall_plan` le balaie comme une seconde
racine, `_menage` le retire s'il ne reste rien d'utile. Le journal clavier suit
donc la case « journal » comme les autres `*.log`.

`_menage` coupe l'écriture disque du journal (`wing_reglages._arret_en_cours`)
**avant** le `rmtree` et le réessaie quelques fois — sinon un fil de fond
recrée `LOG_FILE.parent` par `mkdir` juste après et laisse une coquille vide.

**Résidu manuel** (`_desinstall_residu`) : retrait du pilote WinUSB via le
Gestionnaire de périphériques + corbeille de `dist-windows\`, plus le retrait du
plugin du pool grandMA3.
