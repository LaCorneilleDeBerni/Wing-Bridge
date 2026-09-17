<#
.SYNOPSIS
  Helper ÉLEVÉ UNIQUE pour la capture intégrée du firmware (USBPcap).

.DESCRIPTION
  Ce script est lancé UNE SEULE FOIS, élevé (ShellExecuteW verb=runas, depuis
  wing_firmware_capture.py), et enchaîne SEUL tout ce qui exige des droits
  admin : installer USBPcap si absent, lancer la capture sur CHAQUE root hub
  USBPcap (on ne sait pas d'avance lequel porte la wing — cf. le commentaire
  « à défaut, tous les filtres » dans wing_firmware_capture.py), attendre,
  puis DÉSINSTALLER si c'est lui qui a installé. Une seule invite UAC pour
  tout l'enchaînement — USBPcapCMD.exe hérite l'élévation du process PowerShell
  parent (vérifié dans le source amont, USBPcapCMD/cmd.c : IsElevated() est
  vrai dès qu'il tourne DANS un process déjà élevé, sinon il se relance lui-même
  élevé — ce qui redemanderait une 2e invite. Le lancer d'ici l'évite).

  wing_firmware_capture.py (non élevé, process serveur normal) NE PARTICIPE
  PAS à l'installation/désinstallation — il pilote ce script via ses
  PARAMÈTRES et lit sa PROGRESSION en pollant `$StatusFile` (JSON réécrit à
  chaque étape, écriture atomique via fichier .tmp + Move-Item). C'est LUI qui
  fait l'extraction (wing_firmware_extract.py, pur Python) : ce script se
  contente d'écrire des .pcap classiques, lisibles pendant leur écriture par
  un process tiers non élevé (permissions fichier normales).

.PARAMETER DejaPresent
  "1" si wing_firmware_capture.usbpcap_present() a détecté USBPcap AVANT
  d'élever — dans ce cas ce script n'installe ni ne désinstalle RIEN (on ne
  touche jamais à ce qu'on n'a pas posé soi-même).

.PARAMETER TimeoutS
  Durée de capture, secondes. Ce script s'arrête de lui-même à l'échéance, ou
  plus tôt si `$StopFlag` apparaît (posé par Python dès qu'un blob valide est
  extrait — inutile de continuer à capturer).

.PARAMETER InstallerPath / InstallDir
  Chemin de l'installeur vendoré. 🔒 Depuis l'audit du 25/09/2026, ce n'est
  PLUS l'original (dossier de l'app, modifiable par l'utilisateur) : ce script
  lui-même et l'installeur sont COPIÉS par l'amorce élevée
  (wing_firmware_capture._amorce_verifiee) dans un dossier %ProgramData%
  réservé aux administrateurs, leurs empreintes SHA-256 y sont vérifiées, et
  c'est CETTE copie qui s'exécute. Vérifier l'original côté Python, puis
  l'exécuter élevé, laissait une fenêtre où le remplacer.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$DejaPresent,
    [Parameter(Mandatory=$true)][int]$TimeoutS,
    [Parameter(Mandatory=$true)][string]$InstallerPath,
    [Parameter(Mandatory=$true)][string]$StatusFile,
    [Parameter(Mandatory=$true)][string]$StopFlag,
    [Parameter(Mandatory=$true)][string]$WorkDir,
    # Feu vert de Python pour retirer USBPcap : posé SEULEMENT une fois grandMA2
    # onPC fermé ET la wing débranchée (bus au calme) — c'est la condition pour
    # que le remontage des root hubs décharge réellement USBPcap.sys sans
    # laisser le service bloqué (DeleteFlag=1) jusqu'au reboot.
    [Parameter(Mandatory=$false)][string]$CleanupFlag = ""
)

$ErrorActionPreference = 'Stop'

# ⚠️ DÉCOUVERT EN RÉEL : c'était la VRAIE cause
# de « rien ne s'affiche pendant la capture ». $WorkDir est créé par Python, NON
# élevé (tempfile.mkdtemp) — mais chaque fichier que CE script (élevé) écrit
# dedans (status.json, cap_N.pcap, interfaces.txt) hérite d'un ACL qui refuse la
# LECTURE au process non élevé qui l'a pourtant créé et qui doit le relire
# (`_lire_status` → PermissionError, systématique, tracé sur 50/50 sondages
# consécutifs sur une capture entière). Conséquence : la progression ne
# s'affichait JAMAIS (etape figée sur « invite Windows… ») ET un firmware
# réellement capturé aurait pu être invisible lui aussi (même lecture refusée
# sur les .pcap). Remède : redonner explicitement le droit de lecture à
# l'utilisateur courant sur TOUT le dossier de travail, AVANT d'y écrire quoi
# que ce soit — avec héritage (OI)(CI) pour couvrir les fichiers créés après
# coup (cap_N.pcap créés à l'étape 3, après ce point).
#
# 🔧 CIBLE DU DROIT CORRIGÉE (audit du 25/09/2026). Le droit était accordé à
# l'identité de CE process — le compte ÉLEVÉ. C'est le même compte quand
# l'utilisateur est lui-même administrateur (jeton scindé), mais PAS quand un
# compte standard s'élève avec les identifiants d'un AUTRE compte admin : le
# process Python, lui, tourne sous le compte standard, et ne pouvait toujours
# pas relire. Le bon destinataire est le PROPRIÉTAIRE de $WorkDir : c'est le
# process Python non élevé qui l'a créé (tempfile.mkdtemp). Repli sur
# l'identité courante si le propriétaire est illisible.
try {
    $lecteur = $null
    try {
        $lecteur = (Get-Acl -LiteralPath $WorkDir).GetOwner(
            [System.Security.Principal.SecurityIdentifier]).Value
    } catch { }
    if (-not $lecteur) {
        $lecteur = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    }
    # icacls exige le préfixe « * » pour reconnaître un SID brut (sinon il
    # tente de le résoudre comme un nom de compte et échoue).
    icacls $WorkDir /grant "*${lecteur}:(OI)(CI)RX" /T | Out-Null
} catch { }

# ⚠️ L'installeur NSIS peut poser USBPcap sous Program Files OU Program Files
# (x86) selon la bitness — jamais vérifié en réel avant ce chantier. On essaie
# les deux plutôt que de figer un chemin, et on résout à CHAQUE usage (avant
# ET après l'install) au lieu de figer une seule fois.
function Find-UsbpcapDir {
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if (-not $base) { continue }
        $cand = Join-Path $base 'USBPcap'
        if (Test-Path (Join-Path $cand 'USBPcapCMD.exe')) { return $cand }
    }
    return $null
}

# ⚠️ DÉCOUVERT EN RÉEL, PAS SUPPOSÉ. Un pilote-filtre de root hub
# NE PEUT PAS se décharger à chaud (il est actif sur des hubs en service en
# permanence). Une désinstallation « réussie » (code 0) pose donc juste
# `DeleteFlag=1` sur la clé de service et ATTEND le prochain redémarrage — le
# fichier USBPcap.sys reste chargé (cf. docs/WINDOWS.md, « Capture
# firmware intégrée »). Si on tente d'INSTALLER par-dessus cet état, le setup
# NSIS affiche une MessageBox bloquante — « USBPcap driver service is
# removal. Reboot is required before installation. » — need d'un clic OK
# humain. Sous `/S` (silencieux, censé n'afficher AUCUNE fenêtre) et
# `-WindowStyle Hidden`, cette boîte reste quand même AFFICHÉE et bloque tout
# — testé en réel, 3 boîtes identiques avant que l'installeur rende le code 2
# (échec). Un flux automatisé qui tomberait là-dessus SANS personne devant
# l'écran resterait bloqué indéfiniment. On détecte donc ce cas AVANT de
# lancer l'installeur, et on échoue proprement avec un message actionnable —
# plutôt que d'attendre un clic qui ne viendra peut-être jamais.
function Test-DesinstallationEnAttente {
    try {
        $v = Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\USBPcap' `
            -Name 'DeleteFlag' -ErrorAction SilentlyContinue
        return ($v -and $v.DeleteFlag -eq 1)
    } catch { return $false }
}

# Filet de sécurité générique : un Start-Process qui refuse de se terminer
# (boîte de dialogue imprévue, quelle qu'elle soit) ne doit JAMAIS bloquer ce
# script pour de bon — `-Wait` seul n'a pas de timeout. On tue et on échoue
# proprement plutôt que de pendre.
function Start-ProcessAvecTimeout {
    param([string]$FilePath, [string[]]$ArgumentList, [int]$TimeoutMs = 30000)
    $p = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -PassThru -WindowStyle Hidden
    if (-not $p.WaitForExit($TimeoutMs)) {
        try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch { }
        return $null
    }
    return $p
}

# ── Lister les root hubs USBPcap disponibles (--extcap-interfaces) ───────────
# ⚠️ NE PAS utiliser `& $CmdExe ... 2>$null` ni `> fichier` : USBPcapCMD.exe
# fait sa PROPRE gestion de rattachement de console (AttachConsole +
# freopen CONOUT$, vu dans USBPcapCMD/cmd.c) et les deux perdent SILENCIEUSEMENT
# sa sortie sous PowerShell — vérifié en réel. SEUL
# `Start-Process -RedirectStandardOutput` fonctionne.
function Get-UsbpcapInterfaces {
    param([string]$CmdExe, [string]$WorkDir)
    $ifaceTmp = Join-Path $WorkDir "interfaces.txt"
    Start-Process -FilePath $CmdExe -ArgumentList '--extcap-interfaces' `
        -RedirectStandardOutput $ifaceTmp -Wait -WindowStyle Hidden | Out-Null
    $out = @()
    if (Test-Path $ifaceTmp) {
        foreach ($line in Get-Content $ifaceTmp) {
            if ($line -match '^interface \{value=([^}]+)\}') { $out += $Matches[1] }
        }
    }
    return $out
}

# ── Activer le filtre de classe USBPcap SANS redémarrage de Windows ──────────
# USBPcap.inf déclare `DriverPackageType = ClassFilter` : le pilote s'ajoute à
# `Control\Class\{36FC9E60-...}\UpperFilters`. Un filtre de CLASSE ne s'insère
# dans la pile d'un périphérique QU'AU (re)montage de cette pile. La pile des
# root hubs USB est montée au démarrage de Windows et jamais défaite en marche
# → après un install FRAIS, `--extcap-interfaces` rend 0 tant que Windows n'a
# pas redémarré… OU qu'on force le remontage de la pile des root hubs.
# `pnputil /restart-device` sur chaque `USB\ROOT_HUB*` fait exactement ça, de
# façon ATOMIQUE (désactive+réactive d'un bloc — jamais de hub laissé mort).
# VÉRIFIÉ EN RÉEL : filtre retiré du registre + restart → 0
# interface ; filtre remis + restart → 2 interfaces + capture pcap valide.
# Voir docs/WINDOWS.md, « Enquête reboot USBPcap ».
# ⚠️ Coupe brièvement (~1-3 s) TOUT l'USB — entrées comprises si le clavier /
# la souris sont en USB. Sans effet sur un portable à clavier interne
# (I2C/PS2). Le repli Disable/Enable garde Enable dans un `finally` pour ne
# JAMAIS laisser un hub désactivé si le script est interrompu entre les deux.
$USBPCAP_CLASS_KEY = 'HKLM:\SYSTEM\CurrentControlSet\Control\Class\{36FC9E60-C465-11CF-8056-444553540000}'

function Restart-RootHubs {
    $ids = @()
    try {
        $ids = Get-PnpDevice -PresentOnly -Class USB -ErrorAction SilentlyContinue |
               Where-Object { $_.InstanceId -like 'USB\ROOT_HUB*' } |
               Select-Object -ExpandProperty InstanceId
    } catch { }
    foreach ($id in $ids) {
        $ok = $false
        try {
            & pnputil /restart-device "$id" 2>&1 | Out-Null
            $ok = ($LASTEXITCODE -eq 0)
        } catch { $ok = $false }
        if (-not $ok) {
            # `restart-device` échoue si le hub est « en attente de redémarrage
            # système » (constaté en réel après plusieurs cycles) — Disable puis
            # Enable, LUI, débloque même dans ce cas (vérifié). Enable dans
            # un `finally` : jamais de hub laissé mort.
            try {
                Disable-PnpDevice -InstanceId $id -Confirm:$false -ErrorAction Stop
            } catch {
            } finally {
                try { Enable-PnpDevice -InstanceId $id -Confirm:$false -ErrorAction SilentlyContinue } catch { }
            }
        }
    }
}

function Enable-UsbpcapFilter {
    # Le filtre est DÉJÀ dans `…\Class\{36FC9E60}\UpperFilters` (posé par
    # l'installeur) : il suffit de remonter la pile des root hubs pour qu'il s'y
    # insère.
    Restart-RootHubs
}

# ── Détacher USBPcap PROPREMENT avant Uninstall.exe ─────────────────────────
# ⚠️ DÉCOUVERT EN RÉEL. `Uninstall.exe /S` seul
# laisse le pilote-filtre de classe EN PLACE dans les piles de périphériques
# déjà montées (dont la wing, qui a énuméré sur un hub filtré pendant la
# capture) : USBPcap.sys reste chargé (`DeleteFlag=1`, service bloqué jusqu'au
# reboot) ET la wing devient MUETTE — le filtre reste dans son chemin de
# données mais ne « passe » plus une fois la capture finie (wing revient
# « opérationnelle 12 Mb/s » mais 0 réponse au poll ; l'utilisateur a dû
# rebrancher ~5 fois). Remède : retirer USBPcap de `UpperFilters` PUIS remonter
# la pile des root hubs (USBPcap.sys sort des piles et se décharge) AVANT
# `Uninstall.exe`. Vérifié en réel : après ça, `Uninstall.exe /S` retire
# complètement le service (plus de `DeleteFlag=1`), et la wing repart normale.
function Remove-UsbpcapClassFilter {
    try {
        $uf = (Get-ItemProperty -Path $USBPCAP_CLASS_KEY -Name UpperFilters -ErrorAction SilentlyContinue).UpperFilters
        if ($uf -contains 'USBPcap') {
            $n = @($uf | Where-Object { $_ -ne 'USBPcap' })
            if ($n.Count) { Set-ItemProperty -Path $USBPCAP_CLASS_KEY -Name UpperFilters -Value $n }
            else { Remove-ItemProperty -Path $USBPCAP_CLASS_KEY -Name UpperFilters }
        }
    } catch { }
    Restart-RootHubs
}

# ── Statut : écrit à CHAQUE étape, lu par Python toutes les ~1 s ──────────────
function Write-Status {
    param([string]$Etape, [hashtable]$Extra = @{})
    $o = @{ etape = $Etape; termine = $false }
    foreach ($k in $Extra.Keys) { $o[$k] = $Extra[$k] }
    try {
        # ⚠️ Même piège que build_windows.ps1 (wing_version.py,
        # cf. docs/WINDOWS.md) : `Set-Content -Encoding UTF8` pose TOUJOURS
        # un BOM sous PowerShell 5.1. Python lit avec `text.decode("utf-8")` (pas
        # `utf-8-sig`) → `JSONDecodeError: Unexpected UTF-8 BOM` à CHAQUE lecture,
        # tracé en réel (49/49 sondages sur une capture entière) une fois le
        # PermissionError du dessus corrigé. Remède identique : écrire sans BOM.
        $tmp = "$StatusFile.tmp"
        $json = $o | ConvertTo-Json -Compress -Depth 5
        [System.IO.File]::WriteAllText($tmp, $json, [System.Text.UTF8Encoding]::new($false))
        Move-Item -Force $tmp $StatusFile
    } catch { }
}

$installedByUs = $false
$uninstallOk   = $null
$uninstallErr  = $null
$pcapFiles     = @()
$pcapSizes     = @()
$procs         = @()
$needsReboot   = $false
$ifaceCount    = 0

try {
    # ── 1. Installation, seulement si absente AVANT ──────────────────────────
    $InstallDir = Find-UsbpcapDir
    if ($DejaPresent -eq '1') {
        Write-Status "USBPcap déjà présent — utilisation telle quelle"
        if (-not $InstallDir) {
            throw "usbpcap_present() dit « déjà présent » mais USBPcapCMD.exe introuvable (Program Files ou Program Files (x86))"
        }
    } else {
        if (Test-DesinstallationEnAttente) {
            throw "une désinstallation précédente de USBPcap attend un redémarrage de Windows pour se terminer — redémarre puis réessaie (le pilote ne peut pas se décharger à chaud, cf. docs/WINDOWS.md)"
        }
        Write-Status "installation de USBPcap…"
        $p = Start-ProcessAvecTimeout -FilePath $InstallerPath -ArgumentList @('/S') -TimeoutMs 30000
        if ($null -eq $p) {
            throw "l'installeur USBPcap ne s'est pas terminé en 30 s — bloqué sur une confirmation Windows non automatisable ? (ferme toute fenêtre USBPcap visible et réessaie)"
        }
        Start-Sleep -Seconds 2
        $InstallDir = Find-UsbpcapDir
        if (-not $InstallDir) {
            throw "USBPcap installé (code sortie $($p.ExitCode)) mais USBPcapCMD.exe introuvable après coup"
        }
        $installedByUs = $true
        Write-Status "USBPcap installé"
    }
    $CmdExe       = Join-Path $InstallDir 'USBPcapCMD.exe'
    $UninstallExe = Join-Path $InstallDir 'Uninstall.exe'

    # ── 2. Repérer les root hubs USBPcap disponibles ─────────────────────────
    Write-Status "recherche des interfaces USBPcap…"
    $interfaces = @(Get-UsbpcapInterfaces -CmdExe $CmdExe -WorkDir $WorkDir)

    if ($interfaces.Count -eq 0) {
        # 0 interface = le filtre de CLASSE USBPcap n'est pas encore inséré
        # dans la pile des root hubs (install frais, ou USBPcap présent mais
        # jamais rattaché depuis le dernier boot de Windows). Cause exacte :
        # un filtre de classe ne s'insère qu'au (re)montage de la pile du
        # périphérique, et la pile des root hubs est montée au boot. On force
        # ce remontage SANS redémarrer Windows — vérifié en réel
        # (cf. Enable-UsbpcapFilter et docs/WINDOWS.md, « Enquête
        # reboot USBPcap »).
        Write-Status "activation du composant de capture (redémarrage des hubs USB, ~2 s)…"
        Enable-UsbpcapFilter
        Start-Sleep -Seconds 2
        $interfaces = @(Get-UsbpcapInterfaces -CmdExe $CmdExe -WorkDir $WorkDir)
        Write-Status "interfaces après activation à chaud : $($interfaces.Count)" @{ iface_count = $interfaces.Count }
    }

    if ($interfaces.Count -eq 0) {
        # Le remontage forcé n'a pas suffi (rare — pilote de contrôleur qui
        # refuse le restart à chaud, etc.). Repli NON BLOQUANT : on garde
        # USBPcap installé (le flag persistant côté Python fera apparaître le
        # bouton « Retirer le composant de capture »), et on demande un
        # redémarrage « quand tu veux » — la prochaine tentative trouvera le
        # filtre attaché au boot et ira directement à la capture. Ne JAMAIS
        # forcer ni bloquer un redémarrage (exigence produit).
        $needsReboot = $true
        if ($installedByUs) { throw "USBPCAP_NEEDS_REBOOT" }
        throw "USBPCAP_NEEDS_REBOOT_DEJA_PRESENT"
    }

    # ── 3. Capturer sur TOUS les root hubs en parallèle ──────────────────────
    # On ne sait pas d'avance lequel porte la wing (elle peut être débranchée
    # au moment où ce script démarre) : capturer partout est le repli robuste,
    # moins cher que ça n'en a l'air (quelques root hubs, ~45 s, fichiers .pcap
    # classiques). -A couvre un device déjà branché, --capture-from-new-devices
    # couvre le rebranchement PENDANT la capture (notre cas réel) — cf.
    # USBPcapCMD/cmd.c, les deux drapeaux sont DISTINCTS.
    $i = 0
    foreach ($iface in $interfaces) {
        $out = Join-Path $WorkDir "cap_$i.pcap"
        $pcapFiles += $out
        # ⚠️ PAS `$args` : c'est une variable AUTOMATIQUE de PowerShell (les
        # arguments non liés du script). L'écraser marchait par chance ; un
        # appel de fonction entre deux l'aurait silencieusement remplacée.
        $argsUsbpcap = @('-d', $iface, '-o', $out, '-A', '--capture-from-new-devices', '-b', '134217728')
        $proc = Start-Process -FilePath $CmdExe -ArgumentList $argsUsbpcap -WindowStyle Hidden -PassThru
        $procs += $proc
        $i++
    }
    $ifaceCount = $interfaces.Count
    Write-Status "capture en cours sur $($interfaces.Count) interface(s)" @{
        pcap_files = $pcapFiles; iface_count = $ifaceCount
        installed_by_us = $installedByUs
    }

    # ── 4. Attendre : timeout, ou stop demandé par Python (blob déjà trouvé) ─
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $TimeoutS -and -not (Test-Path $StopFlag)) {
        Start-Sleep -Milliseconds 500
    }

    # ── 5. Arrêter TOUTES les captures (pas de handler propre côté USBPcapCMD
    #      pour un arrêt distant — cf. commentaire de wing_firmware_capture.py.
    #      Les .pcap classiques survivent à un kill : le dernier enregistrement
    #      peut être tronqué, l'extracteur Python le tolère déjà.) ────────────
    Write-Status "arrêt de la capture…"
    foreach ($proc in $procs) {
        try { if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } } catch { }
    }
    Start-Sleep -Milliseconds 400   # laisser les handles de fichier se libérer

    # Tailles des .pcap écrits — remontées à Python pour le journal : un .pcap
    # de quelques Ko = filtre actif mais device manqué ; ~0 o = filtre inerte ;
    # gros = plein, l'extraction dira si le Hello y est.
    $pcapSizes = @()
    foreach ($pf in $pcapFiles) {
        if (Test-Path $pf) {
            $pcapSizes += ('{0}={1}o' -f (Split-Path $pf -Leaf), (Get-Item $pf).Length)
        } else {
            $pcapSizes += ('{0}=absent' -f (Split-Path $pf -Leaf))
        }
    }

    # ── 5b. Attendre le feu vert de Python avant de retirer USBPcap ──────────
    # Python enchaîne d'abord SES étapes 5-6 (fermer grandMA2 onPC, débrancher
    # la wing). Tant que MA2 tourne ou que la wing est branchée, un root hub
    # est « occupé » et son remontage NE décharge PAS USBPcap.sys → service
    # bloqué DeleteFlag=1 jusqu'au reboot (constaté en réel). On
    # n'entre dans le `finally` (désinstallation) qu'une fois $CleanupFlag posé.
    if ($installedByUs -and -not $needsReboot -and $CleanupFlag) {
        Write-Status "firmware enregistré — en attente du bus au calme" @{
            pcap_files = $pcapFiles; installed_by_us = $true
            iface_count = $ifaceCount; capture_finie = $true
        }
        $waitSw = [System.Diagnostics.Stopwatch]::StartNew()
        $vu = $false
        while (-not $vu -and $waitSw.Elapsed.TotalSeconds -lt 360) {
            # ⚠️ $ErrorActionPreference = 'Stop' : Test-Path qui lèverait
            # (chemin, ACL…) tuerait la boucle ET le script d'un coup, laissant
            # USBPcap installé. On isole avec -ErrorAction SilentlyContinue.
            try { $vu = Test-Path $CleanupFlag -ErrorAction SilentlyContinue } catch { $vu = $false }
            if (-not $vu) { Start-Sleep -Milliseconds 500 }
        }
        Write-Status "feu vert reçu — retrait de USBPcap…" @{
            pcap_files = $pcapFiles; installed_by_us = $true; capture_finie = $true
        }
    }

} catch {
    if ($needsReboot) {
        # On a DÉJÀ tenté d'activer le filtre à chaud (Enable-UsbpcapFilter) et
        # ça n'a pas suffi sur cette machine — cas rare. Windows doit redémarrer
        # une fois pour finir d'attacher le filtre de classe. On NE force RIEN :
        # USBPcap reste installé, la prochaine tentative ira droit à la capture.
        $scriptErr = "Windows doit redémarrer une fois pour activer le composant de " +
            "capture (USBPcap) — l'activation à chaud n'a pas suffi sur cette machine. " +
            "Fais-le quand tu veux, puis relance Wing Bridge et reclique sur « Capturer » : " +
            "USBPcap reste installé exprès, la 2e tentative ira directement à la capture."
    } else {
        $scriptErr = "$($_.Exception.Message)"
    }
    Write-Status "erreur : $scriptErr" @{ erreur = $scriptErr }
} finally {
    # ── 6. Désinstaller — SEULEMENT si c'est CE script qui a installé, ET que ce
    #      n'est PAS le cas « redémarrage requis » ci-dessus (garder USBPcap en
    #      place exprès, sinon la 2e tentative repartirait pour rien de zéro).
    if ($installedByUs -and -not $needsReboot) {
        try {
            # Détacher le filtre de classe + remonter les root hubs AVANT
            # Uninstall.exe : sans ça, USBPcap.sys reste chargé (service bloqué
            # jusqu'au reboot) ET la wing reste MUETTE (filtre coincé dans son
            # chemin de données). Voir Remove-UsbpcapClassFilter.
            Write-Status "détachement du composant de capture (remontage des hubs USB, ~2 s)…"
            Remove-UsbpcapClassFilter
            Start-Sleep -Seconds 1
            Write-Status "retrait de USBPcap…" @{ pcap_files = $pcapFiles; installed_by_us = $true }
            if (Test-Path $UninstallExe) {
                $u = Start-ProcessAvecTimeout -FilePath $UninstallExe -ArgumentList @('/S') -TimeoutMs 30000
                if ($null -eq $u) {
                    $uninstallOk = $false
                    $uninstallErr = "Uninstall.exe ne s'est pas terminé en 30 s — bloqué sur une confirmation Windows non automatisable ?"
                } else {
                    Start-Sleep -Seconds 1
                    $uninstallOk = -not (Test-Path $CmdExe)
                    if (-not $uninstallOk) {
                        $uninstallErr = "USBPcapCMD.exe toujours présent après Uninstall.exe /S (code $($u.ExitCode))"
                    }
                }
            } else {
                $uninstallOk = $false
                $uninstallErr = "Uninstall.exe introuvable dans $InstallDir"
            }

            # ── Balayage final : `Uninstall.exe` (NSIS) laisse un dossier VIDE
            #    `Program Files\USBPcap\`, le fichier `USBPcap.sys` (0 référence,
            #    pilote déchargé) et des temporaires `~nsuA.tmp`, tous programmés
            #    pour suppression AU PROCHAIN REBOOT via PendingFileRenameOperations.
            #    Or on les VEUT partis MAINTENANT (exigence « rien ne reste »).
            #    Le pilote étant déchargé (Remove-UsbpcapClassFilter l'a fait), ils
            #    sont supprimables à chaud — vérifié en réel.
            try {
                # NSIS relance son désinstalleur depuis un `~nsu*.tmp\Un_A.exe`
                # qui finit de vider `Program Files\USBPcap\` APRÈS le retour de
                # `Uninstall.exe /S`. Attendre sa fin, sinon on balaye trop tôt
                # (dossier encore verrouillé → il survit jusqu'au reboot,
                # constaté en réel).
                $fin = (Get-Date).AddSeconds(20)
                while ((Get-Date) -lt $fin) {
                    $nsu = @(Get-CimInstance Win32_Process -Filter "Name='Un_A.exe'" -ErrorAction SilentlyContinue)
                    if ($nsu.Count -eq 0) { break }
                    Start-Sleep -Milliseconds 500
                }
                Start-Sleep -Seconds 1
                # 3 tentatives : le handle sur le dossier peut se libérer avec retard.
                foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
                    if (-not $base) { continue }
                    $d = Join-Path $base 'USBPcap'
                    for ($k = 0; $k -lt 3 -and (Test-Path $d); $k++) {
                        Remove-Item $d -Recurse -Force -ErrorAction SilentlyContinue
                        if (Test-Path $d) { Start-Sleep -Seconds 1 }
                    }
                }
                $sys = Join-Path $env:windir 'System32\drivers\USBPcap.sys'
                if (Test-Path $sys) { Remove-Item $sys -Force -ErrorAction SilentlyContinue }
                # ⛔ PendingFileRenameOperations : on N'Y TOUCHE PLUS (audit du 25/09/2026).
                # Ce bloc réécrivait cette valeur système, lue par Windows au démarrage, pour
                # en retirer les paires USBPcap — alors que ces entrées ne font plus que
                # « supprimer un chemin déjà absent » au prochain boot : gain nul. Le risque,
                # lui, ne l'était pas : si PowerShell écartait les chaînes vides du
                # REG_MULTI_SZ (hypothèse jamais vérifiée), les paires [source, cible] se
                # décalaient et une suppression différée d'un AUTRE logiciel devenait un
                # renommage vers le mauvais chemin. Retiré purement et simplement ; ne pas
                # le remettre sans l'avoir mesuré sur une vraie machine Windows.
            } catch { }
        } catch {
            $uninstallOk = $false
            $uninstallErr = "$($_.Exception.Message)"
        }
    }
    # ⚠️ Le message d'erreur de l'étape 1-5 (capturé dans le `catch` ci-dessus)
    # doit SURVIVRE jusqu'à cette dernière écriture — sinon Python ne voit que
    # « terminé » sans jamais savoir POURQUOI ça a échoué (la première version
    # écrasait le champ `erreur` en silence).
    Write-Status "terminé" @{
        termine            = $true
        pcap_files         = $pcapFiles
        pcap_sizes         = ($pcapSizes -join ', ')
        iface_count        = $ifaceCount
        installed_by_us    = $installedByUs
        uninstall_ok       = $uninstallOk
        uninstall_error    = $uninstallErr
        erreur             = $scriptErr
        besoin_redemarrage = $needsReboot
    }
}
