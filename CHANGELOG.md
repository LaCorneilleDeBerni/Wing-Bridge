# Changelog

All notable changes to Wing Bridge are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the project aims for [semantic versioning](https://semver.org/).

## [Unreleased]

### Changed

- Help and diagnostic texts about grandMA3's OSC page no longer say just
  “`Interface` ≠ `<None>`”: `Interface` must be consistent with `Preferred IP`
  and the destination (local MA3: `lo0 (127.0.0.1)` + `127.0.0.0/8` +
  `127.0.0.1`), and an output line must not share port 8000. Seen on
  2026-11-12: `en0` + `127.0.0.0/8` opened no port at all, with no message.

### Fixed

- **Firmware capture, step 2 (“Unplug your wing”) could move on without an
  unplug**: a single “not on the bus” sample was taken as an unplug, while a
  wing re-enumerating (firmware pushed by grandMA2 onPC) or rebooting in
  bootloader drops off the bus by itself for a moment. The step now requires
  the wing to be absent for 5 s in a row (the same threshold the USB loop
  uses), and step 1 now says to unplug the wing **before** launching grandMA2
  onPC. Not yet tested on a Windows machine.
- Firmware capture log no longer says “no usable transfer — stopping the
  capture” right before a successful extraction; the “no transfer” failure
  message now names the likely cause first (wing not unplugged / transfer
  before the recording started), and “Wing in bootloader … unplug” now says
  the wing may still finish starting on its own (~30 s) before asking to
  unplug. Text only.
- The Bridge dot's “N DMX/LED write(s) refused by the wing” warning was never
  reset: after a firmware capture it kept showing `[Errno 19] No such device`
  while the wing was back and healthy, until the engine was restarted (known
  issue of 1.0.1). The counter and its last error are now cleared on every
  successful (re)connection, on the same path that logs “Wing connected”.
- **“Wing USB” indicator and Bridge banner lied when no firmware file was
  imported but the wing was running** (firmware kept in RAM by its power-only
  USB plug; seen on 2026-11-12 on Windows: 30 Hz loop, “operational … no
  reset”, yet “the wing can't start until a firmware is imported”). Both now
  look at the wing's real state: connected → “running on the firmware kept in
  its memory, import one before the next unplug or restart”; not connected →
  the “can't start” alert is kept. Display only, no change to the connection
  logic. Guarded by smoke check 23 (f), which runs the decision in node for
  both states.

## [1.0.1] — 2026-11-12

Maintenance release: same features as 1.0.0, 15 fixes from a full code audit,
known issues documented. Build **#253** on both platforms. Verified on
2026-11-12 on a Windows x64 PC with a real wing and grandMA3 onPC (USB loop,
faders, held executor across a page change, LED feedback, profiles, firmware
capture); the macOS build is the same source, checked by the 83-control smoke
test.

### Fixed

- **Executor held down while MA3 changes state** (page turned with the other
  hand, probe stale): the “Off” was recomputed on release and could be lost,
  leaving the executor **stuck on**. The Off is now decided at press time and
  replayed as is on release.
- Button LED could stay frozen if LED feedback or the chaser was toggled
  between press and release.
- *Save as…* with a reserved name (`__reference__`, `__autosave__`, the
  shipped fallback profile) silently overwrote the safe config; now refused
  (403) and reported in the interface.
- `/api/profile/favori` was not confined to the profiles folder.
- An invalid OSC target in `settings.json` made **all** other settings fall
  back to defaults on the next save; only the target does now.
- A failed profile save could let the auto-save delete the recovery file.
- A command-line verb expiring between two reads could send `None Executor N`.
- A faders-pickup reset from the UI during a USB loop iteration lost one tick.
- Uninstall dialog claimed success when the engine had not answered; six other
  buttons could leave a “working…” text forever after a failed request.

### Known issues

- **Integrated firmware capture can hang on some PCs** (seen on a Dell XPS
  7590, Windows 11 Pro: every attempt stalled at step 3 then failed with no
  interface detected). Cause not established. Workaround: manual Wireshark
  capture + *Import a capture*. See `README.md`, “Known limitations”.
- **Capture assistant, step 2 (“Unplug your wing”) can move on without an
  unplug** (seen once, 2026-11-12): a single “not on the bus” sample is taken
  as an unplug, while a wing in bootloader drops off the bus by itself for a
  few seconds. If grandMA2 onPC pushes the firmware before the recording
  starts, the capture fails with a misleading “check grandMA2 onPC is
  running” message. Workaround: **unplug the wing before launching grandMA2
  onPC**, then follow the steps; a second attempt succeeded.
- On a successful capture the log can still say “no usable transfer —
  stopping the capture” right before “valid firmware blob extracted”, and
  “Wing in bootloader … unplug then replug” right before “Late auto-start …
  resumed”. Read the last line, not the first.
- The Bridge dot's “N DMX/LED write(s) refused by the wing” warning is never
  reset; it stays until the engine is restarted even after a clean reconnect.
- The Wing USB dot can say the wing “cannot start until a firmware is
  imported” while the wing is actually running (firmware kept in RAM by its
  power-only USB socket): it checks the file, not the wing.
- **All status dots grey (“…”) with an empty log, on a PC that has not been
  truly restarted for weeks**: Windows had stopped recycling `TIME_WAIT`
  connections on port 8765 (16 058 of them, the whole dynamic port range) and
  even v1.0.0 could not listen. Fix: **Restart**, not *Shut down* — Fast
  Startup turns *Shut down* into a kernel hibernate that keeps the broken
  TCP state. See `docs/WINDOWS.md`, “Port 8765 saturé”.

## [1.0.0] — 2026-09-27

First public release. Wing Bridge makes a grandMA2 onPC command wing (VID
`0x03EB` / PID `0x160B`, genuine MA hardware or a compatible model) work with
grandMA3 onPC.

### Added

- **Wing USB protocol fully reverse-engineered**: bootloader, upload of the
  application firmware into RAM, handshake, state packet, LED map.
- **Keys → grandMA3**: each physical key is assignable to an MA3 command (OSC)
  or to a keystroke injected into the command line (“console mode”). Short press
  / long press relayed faithfully, double-press configurable per key.
- **Faders → grandMA3**: 8 faders, type configurable per fader (executor,
  crossfade, GrandMaster, Speed Master…), with pickup when the console has moved
  without the fader.
- **Encoder wheels → grandMA3**: 4 wheels, configurable attribute groups, option
  to follow the fixture selected in MA3.
- **2 DMX outputs** on the wing's XLR ports, fed by grandMA3's sACN / Art-Net
  (the wing becomes a 2-universe node).
- **Button LEDs driven**: backlight at rest + press feedback, and feedback of
  the executors' real state when the MA3 probe is installed.
- **MA3 Lua probe** (`src/plugin_ma3/`): a plugin to install in grandMA3, on the
  same footing as the firmware. It makes grandMA3 report its state (current
  page, executors, masters, shortcuts, OSC config) — the only feedback channel,
  OSC only goes one way. Without it, the app drives MA3 blind (no LED feedback,
  no fader pickup): it does not crash, but runs degraded.
- **Plugin state in 5 situations**: the “MA3 probe” indicator and the grandMA3
  card now distinguish plugin active / plugin inactive (restart with
  `Plugin 3`) / plugin not installed / plugin installed but grandMA3 off /
  plugin not installed and grandMA3 off — the app knows whether the files are in
  place even with the console closed. The setup step offers “Restart the plugin”
  when the files are already there, instead of a full reinstall.
- **Tested with grandMA3 onPC 2.4.x and 2.5.x** (up to 2.5.0.3, probe under
  Lua 5.5).
- **Named mapping profiles**: one profile per wing, reassignable in the
  interface, without touching the code.
- **Firmware acquired by the user**: the distribution does not contain
  `wing_firmware.bin` (MA Lighting's property). The app helps extract a copy
  from a grandMA2 onPC capture (`.pcapng` or `.bin` import, sha256 check); on
  Windows x64, integrated capture through vendored USBPcap, installed for the
  duration of the capture then removed.
- **Windows x64 port**: keyboard helper (`SendInput`), grandMA3 detection,
  integrated firmware capture. macOS (Apple Silicon and Intel) remains the
  reference target.
- **Built-in uninstaller** (Settings tab).
- **Bilingual French / English interface**: flag selector 🇫🇷 / 🇬🇧 in the
  header, in-house engine with no dependency (`src/ui/i18n.js`), flat catalogue
  (`src/locales/*.json`) served by a dedicated route. French by default and as
  fallback; the choice is remembered. All interface text is extracted into the
  catalogue. See `docs/I18N.md`. The `en.json` catalogue is translated (MA3
  vocabulary and literal MA3 keywords kept as-is).

- **macOS app ad-hoc signed.** The build scripts now sign the whole `.app`
  bundle inside-out with an ad-hoc signature (`codesign -s -`, no Apple account,
  no notarisation) and verify it with `codesign --verify --deep --strict`; the
  `.zip` is produced by `src/build_zip_macos.sh`, which checks the signature
  survives a compress/extract round-trip. Without this, macOS 15+ blocked the
  unsigned script-based bundle with no “Open Anyway” option. First launch still
  needs *System Settings → Privacy & Security → “Open Anyway”* (ad-hoc is not
  notarised).

### Known limitations

- **Not notarised.** The macOS app is ad-hoc signed only (no paid Apple
  Developer account); first launch requires *Privacy & Security → “Open
  Anyway”*. The Windows build is unsigned (SmartScreen: *More info → Run
  anyway*).
- The DMX chain has never been validated end to end: getting a universe out of
  grandMA3 onPC requires an official grandMA license / dongle. Only the LEDs are
  confirmed as output from the wing.
- Intel Mac: built universal and checked under Rosetta, but never tested on a
  real Intel machine with the wing.
- Integrated firmware capture is Windows x64 only (USBPcap and grandMA2 onPC
  don't exist elsewhere).
