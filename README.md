# Wing Bridge — use a grandMA2 command wing with grandMA3 onPC

### [⬇ Download for macOS](https://github.com/LaCorneilleDeBerni/Wing-Bridge/releases/latest/download/WingBridge-macOS-universal.zip) · [⬇ Download for Windows](https://github.com/LaCorneilleDeBerni/Wing-Bridge/releases/latest/download/WingBridge-Windows-x64.zip)

Unzip, launch — nothing to build. The app is **ad-hoc signed, not notarised**
(no paid Apple account), so the first launch needs one manual step: on macOS,
**System Settings → Privacy & Security → “Open Anyway”**; on Windows, **More
info → Run anyway**. Details in [“First launch”](#first-launch) below.

**Wing Bridge makes a grandMA2 onPC command wing** (VID `0x03EB` / PID `0x160B`,
USB) **work with grandMA3 onPC.** The wing's keys, faders and encoder wheels
drive grandMA3 over OSC; the wing's two XLR ports output two DMX universes; the
button LEDs are driven. One mapping profile per wing, editable in the interface,
without touching the code.

Whether your wing is genuine MA hardware or a compatible model from another
manufacturer, it works the same way: the USB protocol is identical, and it has
been fully reverse-engineered (firmware, handshake, inputs, LEDs).

**The motivation**: don't throw away hardware that still works. What we're
working around is planned obsolescence, not a technical shortcoming.

---

## How this was built — please read

Wing Bridge was built by one person — a lighting professional, not a software
engineer — directing AI coding assistants. Every change was reviewed and
tested by the author, but most of the code was not hand-written.

In practice:

- There is an 82-check test suite, and every feature was verified against a
  real wing and a real grandMA3 onPC before release.
- The USB protocol was reverse-engineered and checked byte-for-byte against
  packet captures.
- But: the code has had no independent review, the project is young, and cases
  on hardware the author doesn't own (Intel Mac, some wing variants) are
  untested.

Treat it as what it is: a working tool made to keep usable hardware out of the
bin. Report anything that breaks — contributions and scrutiny are very welcome.

---

## Download

Direct links, always the latest build:

- **macOS** — [`WingBridge-macOS-universal.zip`](https://github.com/LaCorneilleDeBerni/Wing-Bridge/releases/latest/download/WingBridge-macOS-universal.zip)
  — universal build (Intel + Apple Silicon, macOS 11+). Ad-hoc signed, not
  notarised: first launch needs **System Settings → Privacy & Security → “Open
  Anyway”** (see [“First launch”](#first-launch)).
- **Windows x64** — [`WingBridge-Windows-x64.zip`](https://github.com/LaCorneilleDeBerni/Wing-Bridge/releases/latest/download/WingBridge-Windows-x64.zip)
  — unsigned app: SmartScreen shows a warning, **More info → Run anyway**.

Unzip, launch. Nothing to build. The full list of builds is on the
[releases page](../../releases).

### First launch

The macOS app is **ad-hoc signed but not notarised** — signing it properly would
need a paid Apple Developer account, which this project deliberately avoids.
So the first launch takes one manual step:

1. Unzip and move **Wing Bridge.app** to `/Applications` (or wherever you keep
   it).
2. Double-click it. macOS refuses: *“Apple could not verify …”* or *“… cannot be
   opened”*. Click **Done** / **Cancel**.
3. Open **System Settings → Privacy & Security**, scroll down to the security
   section: a line mentions *Wing Bridge* was blocked. Click **Open Anyway**,
   confirm with your password / Touch ID.
4. Launch the app again — this time choose **Open**. It starts, and you won't be
   asked again.

If macOS instead says the app is **“damaged and can't be opened”** (this happens
when the download kept a quarantine flag), open **Terminal** and run — type
`xattr -cr ` (with the trailing space), then drag **Wing Bridge.app** onto the
Terminal window so its path is filled in, and press **Return**. Then launch the
app normally.

**Windows**: SmartScreen shows *“Windows protected your PC”* — click **More
info → Run anyway**. One time only.

---

## ⚠️ The wing's firmware is not included

> **Wing Bridge does not include the wing's application firmware** — it belongs
> to MA Lighting. A command wing (genuine or compatible) only contains a
> bootloader: it waits for MA's software to push its firmware into RAM **on
> every plug-in**. Wing Bridge does exactly the same thing, with the same bytes.
>
> **On first launch, the app helps you extract your own copy of the firmware**
> from a **grandMA2 onPC** installation (free download from MA Lighting). Import
> a `.pcapng` capture or a `.bin`, sha256 fingerprint verified before caching.
> Nothing is unlocked, nothing is modified inside the wing: it stays 100 %
> usable with grandMA2 onPC.

---

## What you need

| To… | Requirements |
|---|---|
| Run Wing Bridge | a **Mac** (Apple Silicon or Intel) or a **Windows x64 PC**, **grandMA3 onPC** on that same machine (versions **2.4.x and 2.5.x** verified), the **wing plugged in over USB** — a direct connection is the most reliable; some hubs or adapters can prevent startup (seen on Windows with one adapter) |
| Extract the firmware, **once only** | a **Windows x64 PC** with **grandMA2 onPC** (free) and the wing; or a `.bin` you already own |
| Console state feedback | the **MA3 plugin** (`src/plugin_ma3/`) installed in grandMA3 — a **mandatory setup step**, on the same footing as the firmware (see [“MA3 plugin”](#ma3-plugin--the-consoles-state-feedback)) |

> Capturing the firmware is done on a **Windows x64 PC only**: the capture tool
> (USBPcap) and grandMA2 onPC don't exist anywhere else. Once the copy is
> extracted, export it as a `.bin` and import it into Wing Bridge on your Mac —
> everything else happens there.

---

## Quick start

1. **[Download the app](#download)** and unzip it.
2. **Plug in the wing** over USB (a direct connection is the most reliable).
3. **Launch the app you downloaded.** First launch, ad-hoc-signed app: on macOS
   go to *System Settings → Privacy & Security → “Open Anyway”*, then reopen
   (full steps under [“First launch”](#first-launch)); on Windows *More info →
   Run anyway* (SmartScreen) — once only. No admin rights needed.
4. The interface opens in the browser at `http://127.0.0.1:8765`. Relaunching
   the app while that tab is open does nothing — it reuses the existing tab.
   **Closing the window shuts Wing Bridge down** (no server left running in the
   background); the wing then goes back to its bootloader, exactly as with the
   **⏻ Quit** button.
5. **Configure the firmware.** Without firmware, the **Bridge** tab shows a
   “Firmware not configured” banner; the button points to **Settings → 🧩 Wing
   firmware** (see below).
6. **Configure grandMA3.** The full instructions are in the **Bridge** tab
   (“Check the configuration” button): `Menu → In & Out → OSC`, port 8000,
   `Enable Input` on, `Interface` ≠ `<None>`, `Receive Command` = `Yes`.
7. **Install the MA3 plugin.** A mandatory step, on the same footing as the
   firmware: without it, Wing Bridge sends OSC **blind** — no executor LED
   feedback, no fader pickup, no page awareness. With grandMA3 running, the
   **“🧩 Install automatically”** button (Settings → 🧩 Wing firmware) does
   everything; otherwise, the manual procedure is in **Settings → 🎛️ grandMA3**
   (and [“MA3 plugin”](#ma3-plugin--the-consoles-state-feedback) below).
8. **Open grandMA3 onPC**, then the **Bridge → Start** tab.

Mapping profiles are stored per machine — `~/Library/Application Support/Wing
Bridge/` on macOS, `%APPDATA%\Wing Bridge\` on Windows.

### Configuring the firmware

In **Settings → 🧩 Wing firmware**, two ways to provide it:

- **a `.pcapng` capture** of a grandMA2 onPC session (the app reconstructs the
  firmware on its own, pure Python);
- **a `.bin` file** you already own.

In both cases, the app **verifies the sha256 fingerprint** before caching. A
file that isn't the right firmware is rejected with a clear message. Without
firmware, connecting to the wing is blocked **cleanly** (never a crash).

On a **Windows x64 PC**, the app additionally offers an **integrated capture**:
it temporarily installs the capture tool, reads the firmware while grandMA2 onPC
pushes it to the wing, then **uninstalls it** (unless it was already present).
Details in the **Help** tab and in [`docs/HARDWARE.md`](docs/HARDWARE.md).

### The interface tabs

| Tab | Role |
|--------|------|
| **Bridge** | Start/stop the bridge, check the MA3 config, live log, link health |
| **Keys** | Learn mode: assign each key to an MA3 command or to a keystroke (console mode) |
| **Faders** | Type and target of the 8 faders (executor, crossfade, GrandMaster, Speed Master…), pickup |
| **Encoders** | Attribute groups for the 4 wheels, directory of MA3's attributes |
| **Profiles** | Save/load mappings by name — one profile per wing |
| **Settings** | 7 cards: **🎛️ grandMA3** (OSC target + plugin), **🔌 DMX output** (XLR A/B), button **💡 LEDs**, **🔍 USB detection**, **🧩 Firmware**, **⌨️ Keyboard test**, uninstall |
| **Help** | All of the app's help, organised by tab — including installing the MA3 plugin |

### MA3 plugin — the console's state feedback

A small plugin (`src/plugin_ma3/`) that runs **inside** grandMA3 and makes it
report its state: button LEDs matching the console's real state, current page,
fader pickup, a warning if a fader's function doesn't match. It is the **only
feedback channel** — OSC only goes one way.

**Installing it is a mandatory setup step**, on the same footing as the
firmware. Without it, Wing Bridge is not broken but runs **degraded**: it sends
OSC blind, with no LED feedback and no fader pickup. As long as grandMA3 is
reachable and the console doesn't see the plugin, the activity bar at the top of
the interface scrolls **“grandMA3 plugin not installed”**.

**The simplest way**: with grandMA3 running, go to **Settings → 🧩 Wing firmware
→ “🧩 Install automatically”**. The app copies the files into MA3's pool, sends
the import + `SaveShow`, and checks that the probe answers. On failure, it falls
back to the manual procedure.

**By hand** (`src/plugin_ma3/installer.sh` on macOS copies the files into MA3's
plugin pool), then in MA3's command line (`3` is the plugin's **location**
in MA3's Plugins pool — **configurable**, Settings → 🎛️ grandMA3, default `3`;
change it if that slot is already taken by another plugin on your machine):

```
Import Plugin Library "wingloader.xml" At 3
Set Plugin 3.1 Property "Installed" "Yes"
Plugin 3
```

…and **save the show**. These commands also work over OSC. The full procedure
(Windows included) is in **Settings → 🎛️ grandMA3** and in the **Help → Install
the MA3 plugin** tab.

> 🔁 **`Plugin 3` must be re-typed in MA3 after EVERY launch of grandMA3.**
> The probe does not survive an MA3 restart, and MA3 has no automatic plugin
> startup. Until it's done, the “MA3 probe” indicator on the Bridge tab flags
> it.

---

## What it does — and what it doesn't

**It does:**

- relay the wing's keys, faders and wheels to grandMA3 onPC over OSC;
- inject keystrokes into MA3's real command line (“console mode”), through a
  keyboard helper;
- output 2 DMX universes on the wing's XLR ports, fed by grandMA3's sACN /
  Art-Net (the wing becomes a 2-universe node);
- drive the button LEDs (backlight and press feedback);
- reflect the console's real state — executor LEDs, current page, fader pickup
  — **through the MA3 plugin** (a setup step);
- manage one mapping profile per wing, fully editable in the interface.

**It doesn't:**

- target a **real** grandMA3 console: the target is **grandMA3 onPC only**, on
  the same machine as the app;
- use the wing's DMX in, MIDI in or LTC in (protocol not captured);
- “unlock” anything in MA3. If grandMA3 onPC limits sACN output without MA
  hardware, that's an MA Lighting limitation — Wing Bridge adds no restriction
  and lifts none. OSC control (keys, faders, wheels) works in every case.

---

## Scope and intended use

Wing Bridge is a personal project, built to keep an otherwise-idle piece of
hardware useful — not a professional tool. It is **not recommended for
professional or commercial productions**: no independent review, no support
commitment, no guarantee of reliability under show conditions.

It only uses what grandMA3 onPC already provides for free (OSC control). It
never unlocks, patches, or bypasses any MA Lighting license, dongle, or
paywall — DMX/sACN output included, which stays entirely governed by your own
grandMA3 onPC license, exactly as if Wing Bridge didn't exist.

This is provided as-is, for personal use. The author makes no claim about the
legality of any specific use in your jurisdiction or under any third-party
license — you are responsible for complying with the terms of any software or
hardware you use alongside Wing Bridge.

---

## Known limitations

- **DMX chain never validated end to end.** Getting a DMX universe out of
  grandMA3 onPC requires an **official grandMA license / dongle**. Without it,
  MA3 onPC unlocks no sACN/Art-Net output: the “MA3 → network” part of the chain
  can't be fed, so there's nothing to check downstream (wing, XLR). The sACN →
  buffer → USB packet decoding is tested in isolation; only the **LEDs** are
  confirmed as real output from the wing.
- **Intel Mac: never validated on real hardware.** The app is built universal
  (Intel + Apple Silicon, macOS 11+) and the x86_64 code has been checked under
  Rosetta, but no Intel machine could be tested, wing included.
- **Firmware capture: Windows x64 only.** Elsewhere, import a `.pcapng` capture
  made on a Windows PC, or a `.bin`.
- **Encoder wheels**: configured per profile. Partial detection of grandMA3's
  current selection works, but full automatic following is not there yet.
- **Not notarised (no paid Apple account).** The macOS app is ad-hoc signed;
  first launch needs *System Settings → Privacy & Security → “Open Anyway”*
  (Windows: *More info → Run anyway*). See [“First launch”](#first-launch).
- **grandMA3: tested with versions 2.4.x and 2.5.x** (2.5.0.3 included). The Lua
  probe runs under Lua 5.5. A newer version may rename a keyword or an
  attribute: Wing Bridge then reads the list from the installed manual and flags
  it in the interface rather than failing silently.
- Only the wing with VID `0x03EB` / PID `0x160B` is supported. Another model?
  **Settings → Detection → Test the handshake**: if the response differs, its
  protocol will need to be captured (see [`docs/HARDWARE.md`](docs/HARDWARE.md)).

---

## Wing safety

The firmware is uploaded **into RAM on every plug-in** — exactly the same
process, and the same bytes, as grandMA2 onPC. The 68 reassembled packets from
the original capture yield 34,624 bytes, sha256 fingerprint identical to that of
the expected firmware. Nothing is ever written permanently into the wing: it
stays 100 % usable with grandMA2 onPC.

**Why the firmware comes not from the wing but from grandMA2 onPC** — three
facts established from the capture:

- it is **re-sent on every plug-in**: if it lived in the wing, that would be
  pointless;
- the wing **enumerates in bootloader (480 Mb/s) on every power-up**: that's its
  factory state, it has no application to start on its own;
- in the init capture, the 34,624 bytes go **`host → wing`**, one way only. The
  PC already had them.

It is to stay on the right side of things that the distribution does **not**
contain MA Lighting's `.bin` — only its fingerprint (to verify an import) and
the code that reconstructs the firmware from your own capture.

> ⚠️ This is not legal advice — it's the choice to be on the right side by
> construction: not redistributing an MA Lighting file.

---

## Repository layout

```
Wing 2 vers 3/
├── src/                ← the code, nothing but the code
│   ├── wing_ui.py          shared state + entry point — the conductor
│   ├── wing_ui.html        the interface: markup only, no JavaScript
│   ├── ui/                 the JavaScript, one file per tab
│   │                       (core · i18n · aides · bridge · touches · faders_encodeurs ·
│   │                        profils · parametres · init — imposed load order)
│   ├── locales/            language catalogues fr.json / en.json (bilingual FR/EN)
│   ├── wing_init.py        USB connection: bootloader, firmware, handshake
│   ├── wing_*.py           the engine's modules (see docs/ARCHITECTURE.md)
│   ├── wing_firmware_extract.py  reconstructs the firmware from a capture (pure Python)
│   ├── wing_keyboard*.py   console-mode keyboard helper (macOS / Windows)
│   ├── smoke_test.py       82 checks, run before every build
│   ├── build_server.sh     rebuild of the engine only (the normal case)
│   ├── build_app.sh        full rebuild (keyboard helper included)
│   ├── build_zip_macos.sh  package the signed .app into the release .zip
│   ├── build_windows.ps1   Windows x64 build
│   ├── fixtures/           synthetic capture for the smoke test (never the real firmware)
│   ├── plugin_ma3/          Lua probe to install in grandMA3 (a setup step)
│   ├── profiles/           reference profiles shipped
│   └── vendor/             vendored third-party components (see THIRD_PARTY.md)
├── docs/               ← 📚 the technical docs, one file per subsystem
│   ├── README.md           index: which question → which file
│   ├── ARCHITECTURE.md     how the pieces fit together ← start here
│   ├── HARDWARE.md         the wing over USB: packets, bootloader, LEDs, DMX
│   ├── KEYBOARD_MAPPING.md keys (discrete inputs) + console mode
│   ├── FADERS_ENCODERS.md  faders and wheels (continuous inputs)
│   ├── GRANDMA3_SYNC.md    OSC, Lua probe, console feedback
│   ├── I18N.md             bilingual FR/EN: engine, catalogue, conventions
│   └── WINDOWS.md          specifics of running under Windows x64
├── Wing Bridge Officiel/   ← the app, once built (outside the repo)
├── CHANGELOG.md        ← notable changes
├── CONTRIBUTING.md     ← method, editing rules, pitfalls, build
├── LICENSE             ← GNU GPL-3.0
├── THIRD_PARTY.md      ← third-party components and their licenses
└── README.md
```

---

## Building from source

The normal route is to [download the app](#download) — the repository contains
the **sources**, not the pre-built app. To build it yourself, on the build Mac,
once:

```bash
python3 -m venv ~/wing-env
~/wing-env/bin/pip install pyusb python-osc pyobjc pyinstaller
brew install libusb

cd src
./build_app.sh          # full build — drops Wing Bridge.app into “Wing Bridge Officiel/”
```

After that, `./build_server.sh` is enough to rebuild the engine only (see
[“For developers”](#for-developers)). Details and method in
[`CONTRIBUTING.md`](CONTRIBUTING.md).

📍 The app lives in `Wing Bridge Officiel/`, next to the sources. Its keyboard
helper is what holds macOS's Accessibility permission: it's tied to the binary
(a copy recreated afterwards would not be authorised), but **moving the project
folder breaks nothing** — the build scripts target the app by a relative path.

⚠️ Keep **only one** copy: a stale bundle alongside would capture builds
launched without an argument, and the real app would fall behind with nothing to
flag it.

---

## For developers

A rebuild is needed after modifying the `.py` files (the app embeds its own copy
of the code). On the build Mac, after the `python3 -m venv` from
[“Building from source”](#building-from-source):

```bash
cd src
~/wing-env/bin/python3 smoke_test.py   # ~82 checks, ~35 s, no hardware
./build_server.sh                      # rebuild of the ENGINE only — the normal case (95 %)
```

⚠️ **`build_server.sh` in 95 % of cases.** It rebuilds only the engine and
**preserves the keyboard helper's Accessibility permission**. `build_app.sh`
also rebuilds the helper — so the permission drops and has to be re-granted.
Reserve it for changes to `wing_keyboard*.py`.

Both scripts run `smoke_test.py` first and **cancel the build if it fails**.
Before contributing: [`CONTRIBUTING.md`](CONTRIBUTING.md) (working method,
editing rules, pitfalls, build details). The full technical documentation is in
[`docs/`](docs/) — start with [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## License

Wing Bridge is distributed under the **GNU General Public License v3.0** — full
text in [`LICENSE`](LICENSE).

It embeds third-party components that keep **their own license** (they are not
re-licensed under GPL-3.0): the **USBPcap** installer is aggregated **unmodified**
(driver under GPLv2, command-line tool under BSD 2-Clause), **libusb** is under
LGPL-2.1, and the Python dependencies (pyusb, python-osc, pyobjc) keep their
respective licenses. PyInstaller, the build tool, carries an **explicit
exception** that means the executables it produces are **not** forced to GPL.
The details, version by version, are in [`THIRD_PARTY.md`](THIRD_PARTY.md).

The wing's firmware is **not** covered by this license and is **not
distributed**: it belongs to MA Lighting, and each user imports their own copy.
