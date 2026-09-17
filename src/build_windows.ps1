<#
.SYNOPSIS
  Build Windows de Wing Bridge — ÉBAUCHE (premier jet, à revoir).

.DESCRIPTION
  Équivalent Windows de build_app.sh : produit un exécutable autonome
  (PyInstaller, --onedir) qui tourne sans Python ni venv installé. C'est le
  pendant du build macOS, adapté aux différences de la plateforme.

  ⚠️ CE N'EST PAS ENCORE LE BUILD FINAL. Différences ASSUMÉES vs macOS,
  listées ici pour être tranchées ensemble :

    • Assistant clavier : second exécutable, mais DÉMARRÉ AUTOMATIQUEMENT par le
      serveur (wing_ui.restart_keyboard_helper) — pas un exe à lancer à la main.
      Pas d'Accessibilité à accorder sous Windows : pas de codesign, pas de
      LSUIElement, pas de bundle .app. Construit en --noconsole (aucune fenêtre
      visible) ; le serveur le relance s'il meurt et le tue à « ⏻ Quitter ».
    • Séparateur --add-data : « ; » sous Windows (« : » sous macOS).
    • libusb : on embarque src\libusb-1.0.dll (backend natif WinUSB).
      wing_init._backend() la cherche à la racine du bundle figé
      (sys._MEIPASS) — d'où « libusb-1.0.dll;. ».
    • profiles\ : embarqués À LA DEMANDE (mêmes __reference__.json /
      défauts.json que le dépôt). ⚠️ NOTE : le build macOS ne les embarque PAS,
      et l'app n'amorce PAS sa config depuis _MEIPASS/profiles : ensure_reference()
      seed depuis PROFILE_DIR (dossier utilisateur) ou les défauts EN CODE. Les
      embarquer reste donc inoffensif mais INERTE tant qu'un seeding « depuis le
      bundle » n'est pas câblé — à trancher ensemble (câbler, ou retirer ce
      --add-data). Le chemin des profils, lui, EST corrigé : depuis ce chantier
      _default_profile_dir() renvoie %APPDATA%\Wing Bridge\profiles sous Windows
      (plus le chemin ~/Library macOS en dur).

.PARAMETER SkipBump
  Ne pas incrémenter le numéro de build (wing_version.py laissé tel quel).
  Utile pour un build de test qui ne doit pas salir l'arbre git.

.PARAMETER WithFirmware
  EMBARQUER wing_firmware.bin dans le bundle (build PRIVÉ). Par défaut (build
  OSS), le firmware appartient à MA Lighting et n'est PAS embarqué : l'utilisateur
  importe le sien (Paramètres -> Configurer le firmware). Pendant du --with-firmware
  des scripts macOS.

.PARAMETER SkipKeyboard
  Ne pas construire l'assistant clavier (wing_keyboard_windows.py). Le moteur
  seul suffit pour vérifier que l'interface web est servie.

.PARAMETER DistPath
  Dossier de sortie. Défaut : <racine du dépôt>\dist-windows.

.NOTES
  Prérequis (machine de build) : wing-env-windows avec pyusb, python-osc,
  pyinstaller, et src\libusb-1.0.dll présent.
#>
[CmdletBinding()]
param(
    [switch]$SkipBump,
    [switch]$SkipKeyboard,
    [switch]$WithFirmware,
    [string]$DistPath
)

$ErrorActionPreference = 'Stop'

# ── Chemins ───────────────────────────────────────────────────────────────────
$SRC  = $PSScriptRoot                     # dossier des sources (src\)
$ROOT = Split-Path $SRC -Parent           # racine du dépôt (Wing-Bridge\)
$VENV = Join-Path $ROOT 'wing-env-windows'
$PY   = Join-Path $VENV 'Scripts\python.exe'
$PYI  = Join-Path $VENV 'Scripts\pyinstaller.exe'
if (-not $DistPath) { $DistPath = Join-Path $ROOT 'dist-windows' }

function Die($msg) { Write-Host "X $msg" -ForegroundColor Red; exit 1 }

# ── Appel d'un exécutable natif sous Windows PowerShell 5.1 ────────────────────
# ⚠️ Avec `$ErrorActionPreference = 'Stop'`, la MOINDRE ligne qu'un exe natif
# écrit sur stderr (PyInstaller y met TOUS ses logs INFO) devient une erreur
# TERMINANTE et avorte le build avant même le contrôle de `$LASTEXITCODE`. On
# exécute donc les natifs (smoke_test, PyInstaller) avec la préférence relâchée,
# puis on restaure : le vrai verdict reste `$LASTEXITCODE`, testé par l'appelant.
# (PS 5.1 uniquement ; pwsh 7 ne terminait pas là-dessus.)
function Invoke-Native([scriptblock]$Block) {
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Block } finally { $ErrorActionPreference = $old }
}

if (-not (Test-Path $PY))  { Die "Python introuvable : $PY (venv wing-env-windows ?)" }
if (-not (Test-Path $PYI)) { Die "PyInstaller absent du venv : $PYI  (pip install pyinstaller)" }

# ── libusb : le backend natif DOIT être là (sinon aucun accès USB dans l'app) ──
$LIBUSB = Join-Path $SRC 'libusb-1.0.dll'
if (-not (Test-Path $LIBUSB)) {
    Die "libusb-1.0.dll absente de src\ — c'est le backend natif WinUSB (166 Ko, cf. WINDOWS.md). Sans elle l'app démarre mais ne voit aucune wing."
}

# ── USBPcap vendoré : présent ET empreinte vérifiée AVANT d'embarquer ──────────
# Composant de capture intégrée du firmware (wing_firmware_capture.py) — voir
# docs/WINDOWS.md, « Capture firmware intégrée ». Un sha256 qui ne
# correspond plus (mise à jour manuelle de l'exe sans mise à jour de
# l'empreinte, ou fichier altéré) ne doit JAMAIS partir dans un build : c'est
# ce binaire qui obtient les droits admin d'installer un pilote noyau.
$USBPCAP_VERSION = '1.5.4.0'
$USBPCAP_SHA256  = '87a7edf9bbbcf07b5f4373d9a192a6770d2ff3add7aa1e276e82e38582ccb622'
$USBPCAP_DIR     = Join-Path $SRC 'vendor\usbpcap'
$USBPCAP_EXE     = Join-Path $USBPCAP_DIR "USBPcapSetup-$USBPCAP_VERSION.exe"
if (-not (Test-Path $USBPCAP_EXE)) {
    Die "installeur USBPcap absent : $USBPCAP_EXE (voir src\vendor\usbpcap\README.md)"
}
$hashReel = (Get-FileHash $USBPCAP_EXE -Algorithm SHA256).Hash.ToLower()
if ($hashReel -ne $USBPCAP_SHA256) {
    Die "empreinte sha256 de l'installeur USBPcap INATTENDUE`n  attendu : $USBPCAP_SHA256`n  obtenu  : $hashReel`nBUILD ANNULÉ — ne jamais embarquer un installeur non vérifié (voir src\vendor\usbpcap\README.md pour mettre à jour l'empreinte)."
}
$fwCaptureFiles = @('wing_firmware_capture.py', 'wing_firmware_capture_eleve.ps1', 'wing_firmware_retirer_eleve.ps1')
foreach ($f in $fwCaptureFiles) {
    if (-not (Test-Path (Join-Path $SRC $f))) { Die "$f absent de src\ (capture intégrée du firmware)." }
}
Write-Host "-> USBPcap vendoré vérifié (v$USBPCAP_VERSION, sha256 OK)."

# ── Garde-fou : un build ne part JAMAIS si le test de fumée échoue ─────────────
# Identique aux scripts macOS. Attrape les cassures silencieuses (JS mort =
# interface figée sans erreur en console).
Write-Host "-> Test de fumée..."
Invoke-Native { & $PY (Join-Path $SRC 'smoke_test.py') }
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Die "BUILD ANNULÉ : le test de fumée a échoué (rien n'a été construit)."
}
Write-Host ""

# ── Numéro de build (port de bump_build.sh) — APRÈS le smoke, comme sur Mac ────
$VERF = Join-Path $SRC 'wing_version.py'
if ($SkipBump) {
    $cur = (Select-String -Path $VERF -Pattern '^BUILD = (\d+)').Matches.Groups[1].Value
    $BUILD = if ($cur) { $cur } else { '?' }
    Write-Host "-> Build #$BUILD (numéro NON incrémenté : -SkipBump)"
} else {
    $cur = 0
    $m = Select-String -Path $VERF -Pattern '^BUILD = (\d+)'
    if ($m) { $cur = [int]$m.Matches.Groups[1].Value }
    $BUILD = $cur + 1
    $date = Get-Date -Format 'dd/MM/yyyy HH:mm'
    $verTxt = @"
# ⚠️ GÉNÉRÉ AUTOMATIQUEMENT par build_windows.ps1 — NE PAS ÉDITER À LA MAIN.
# Numéro de build chronologique, incrémenté à chaque build (serveur ou complet).
# Le moteur et l'assistant clavier embarquent chacun le numéro du build qui les
# a produits : s'ils diffèrent dans l'interface, c'est qu'un build serveur seul
# a eu lieu depuis (normal), ou qu'un bundle a été mélangé (à surveiller).
BUILD = $BUILD
BUILD_DATE = "$date"
"@
    # ⚠️ UTF-8 SANS BOM (pas `Set-Content -Encoding utf8`, qui AJOUTE un BOM sous
    # PowerShell 5.1). Le BOM (U+FEFF) en tête casse le test de fumée : celui-ci
    # `ast.parse` chaque *.py de src\ (smoke_hardware.textes_affiches), et un
    # BOM lu en `utf-8` (pas `utf-8-sig`) lève « invalid non-printable character
    # U+FEFF ». Le prochain build échouerait alors dès le smoke.
    [System.IO.File]::WriteAllText(
        $VERF, ($verTxt -replace "`r`n", "`n") + "`n",
        (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "-> Build complet — build #$BUILD (moteur$(if(-not $SkipKeyboard){' + assistant clavier'}))..."
}

# ── Dossiers de travail (nettoyés en fin) ─────────────────────────────────────
$TMP  = Join-Path $env:TEMP ("wingbuild_" + [guid]::NewGuid().ToString('N'))
$WORK = Join-Path $TMP 'build'
$SPEC = Join-Path $TMP 'spec'
New-Item -ItemType Directory -Force -Path $WORK, $SPEC | Out-Null
if (Test-Path $DistPath) { Remove-Item -Recurse -Force $DistPath }

# ── Build du MOTEUR (wing_server, point d'entrée wing_ui.py) ───────────────────
# Mêmes données que le build macOS + profiles\ (demandé) + la DLL libusb.
# ⚠️ séparateur « ; » (Windows), pas « : ».
#
# --noconsole (GUI, aucune fenêtre de terminal) : au double-clic, l'app démarre
# comme sur Mac — pas de console noire, le navigateur s'ouvre seul sur
# http://127.0.0.1:8765 (wing_ui.main(open_browser=True), webbrowser.open). La
# SEULE sortie propre reste « ⏻ Quitter » dans l'interface (/api/quit), qui
# libère l'USB puis tue le serveur ET l'assistant clavier. ⚠️ Sans console, il
# n'y a plus de Ctrl+C possible — c'est justement le but : Ctrl+C tuait le
# process d'un coup, en pleine lecture USB, et laissait la wing dans un état
# incertain. wing_ui.main() met déjà stdout/stderr en UTF-8 tolérant, et le
# journalisation réelle passe par le fichier de log, pas par la console.
# Firmware embarqué UNIQUEMENT sur demande (-WithFirmware, build privé). Le
# build OSS par défaut ne l'inclut pas : l'utilisateur importe le sien
# (Paramètres -> Configurer le firmware).
$fwArgs = @()
if ($WithFirmware) {
    if (-not (Test-Path (Join-Path $SRC 'wing_firmware.bin'))) {
        Die "-WithFirmware demandé mais src\wing_firmware.bin est absent."
    }
    $fwArgs = @('--add-data', "$SRC\wing_firmware.bin;.")
    Write-Host "-> firmware EMBARQUÉ (build privé, -WithFirmware)"
} else {
    Write-Host "-> firmware NON embarqué (build OSS) — l'utilisateur importe le sien"
}
$engineArgs = @(
    '--noconfirm', '--onedir', '--noconsole', '--name', 'wing_server',
    '--icon', "$SRC\wing_icon.ico",
    '--distpath', $DistPath, '--workpath', $WORK, '--specpath', $SPEC
) + $fwArgs + @(
    '--add-data', "$SRC\wing_ui.html;.",
    '--add-data', "$SRC\ui;ui",
    '--add-data', "$SRC\locales;locales",
    '--add-data', "$SRC\plugin_ma3;plugin_ma3",
    '--add-data', "$SRC\profiles;profiles",
    '--add-binary', "$LIBUSB;.",
    # Capture intégrée du firmware (Windows) — l'installeur vendoré ET les
    # deux scripts élevés doivent voyager ENSEMBLE avec wing_firmware_capture.py
    # (wing_init._DIR / sys._MEIPASS le cherche à côté de lui, voir le module).
    '--add-data', "$USBPCAP_DIR;vendor\usbpcap",
    '--add-data', "$SRC\wing_firmware_capture_eleve.ps1;.",
    '--add-data', "$SRC\wing_firmware_retirer_eleve.ps1;.",
    "$SRC\wing_ui.py"
)
Invoke-Native { & $PYI @engineArgs }
if ($LASTEXITCODE -ne 0) { Die "Échec build moteur (voir la sortie PyInstaller ci-dessus)." }

# ── L'interface est faite de FICHIERS EMBARQUÉS : les vérifier un par un ───────
# Le JS vit dans ui\, un fichier par onglet. S'il en
# manque UN SEUL, l'app démarre, sert une page complète... et AUCUN bouton ne
# répond. Panne muette : ni erreur, ni journal. D'où ce garde-fou (comme sur Mac).
$engineDir = Join-Path $DistPath 'wing_server'
$needed = @(
    'wing_ui.html', 'ui\core.js', 'ui\i18n.js', 'ui\aides.js', 'ui\bridge.js', 'ui\touches.js',
    'ui\faders_encodeurs.js', 'ui\profils.js', 'ui\parametres.js', 'ui\init.js',
    'locales\fr.json', 'locales\en.json',
    'plugin_ma3\wingbridge.lua', 'plugin_ma3\wingbridge.xml',
    'plugin_ma3\wingloader.lua', 'plugin_ma3\wingloader.xml'
)
foreach ($f in $needed) {
    $leaf = Split-Path $f -Leaf
    $hit = Get-ChildItem -Path $engineDir -Recurse -Filter $leaf -ErrorAction SilentlyContinue |
           Where-Object { $_.FullName -like "*\$($f.Replace('/','\'))" }
    if (-not $hit) { Die "$f absent du bundle — l'interface serait inerte (ou, pour locales\, figée en français). Vérifie les --add-data de ce script." }
}
Write-Host "-> Interface complète dans le bundle (balisage + 9 JS + catalogues i18n)."

# ── Capture intégrée du firmware : mêmes vérifs, même raison ───────────────────
# Un module Python absent échouerait bruyamment (ImportError, visible dans le
# journal) — mais l'INSTALLEUR et les DEUX scripts PowerShell sont des fichiers
# de DONNÉES : leur absence serait aussi silencieuse que celle d'un JS.
$neededFw = @("vendor\usbpcap\USBPcapSetup-$USBPCAP_VERSION.exe",
             'wing_firmware_capture_eleve.ps1', 'wing_firmware_retirer_eleve.ps1')
foreach ($f in $neededFw) {
    $leaf = Split-Path $f -Leaf
    $hit = Get-ChildItem -Path $engineDir -Recurse -Filter $leaf -ErrorAction SilentlyContinue
    if (-not $hit) { Die "$f absent du bundle — la capture intégrée serait inerte. Vérifie les --add-data de ce script." }
}
Write-Host "-> Capture intégrée du firmware complète dans le bundle (installeur + 2 scripts élevés)."

# ── Sécurité libusb : écraser toute autre libusb collectée par la nôtre ────────
# PyInstaller peut aussi ramasser la DLL de libusb-package. On force la version
# de src\ pour ne charger qu'un seul backend connu (miroir du garde macOS).
Get-ChildItem -Path $engineDir -Recurse -Filter 'libusb*.dll' -ErrorAction SilentlyContinue |
    ForEach-Object { Copy-Item -Force $LIBUSB $_.FullName }

# ── Build de l'ASSISTANT CLAVIER (wing_keyboard_windows.py) ────────────────────
# On construit DIRECTEMENT le module Windows (pas le dispatcher wing_keyboard.py)
# pour ne PAS entraîner wing_keyboard_macos et ses imports Quartz/AppKit (macOS
# only). Aucun hidden-import nécessaire (ctypes/urllib sont dans la stdlib).
# Pas de codesign / LSUIElement / bundle .app : sans objet sous Windows.
#
# --noconsole (GUI, pas de fenêtre) : l'assistant est lancé AUTOMATIQUEMENT par
# le serveur (wing_ui.restart_keyboard_helper), en arrière-plan — un utilisateur
# final ne doit pas voir de fenêtre console « clavier » s'ouvrir. Le diagnostic
# n'en souffre pas : wing_keyboard_windows.py journalise déjà dans
# %LOCALAPPDATA%\Wing Bridge\wing_keyboard.log (flog()), et en dev on peut
# toujours lancer « Wing Keyboard.exe » ou le .py à la main pour voir la console.
if (-not $SkipKeyboard) {
    Write-Host "-> Build assistant clavier (wing_keyboard_windows.py, --noconsole)..."
    $kbdArgs = @(
        '--noconfirm', '--onedir', '--noconsole', '--name', 'Wing Keyboard',
        '--icon', "$SRC\wing_icon.ico",
        '--distpath', $DistPath, '--workpath', (Join-Path $TMP 'build2'), '--specpath', $SPEC,
        "$SRC\wing_keyboard_windows.py"
    )
    Invoke-Native { & $PYI @kbdArgs }
    if ($LASTEXITCODE -ne 0) { Die "Échec build assistant clavier." }
}

Remove-Item -Recurse -Force $TMP -ErrorAction SilentlyContinue

# ── Bilan ─────────────────────────────────────────────────────────────────────
$exe = Join-Path $engineDir 'wing_server.exe'
Write-Host ""
Write-Host "OK App Windows buildée (build #$BUILD)" -ForegroundColor Green
Write-Host "   Moteur   : $exe"
if (-not $SkipKeyboard) { Write-Host "   Clavier  : $(Join-Path $DistPath 'Wing Keyboard\Wing Keyboard.exe')" }
Write-Host "   Test     : & `"$exe`" --no-browser   puis  http://127.0.0.1:8765"
