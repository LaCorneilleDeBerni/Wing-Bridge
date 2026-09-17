# Changelog

All notable changes to Wing Bridge are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
the project aims for [semantic versioning](https://semver.org/).

## [Unreleased]

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
