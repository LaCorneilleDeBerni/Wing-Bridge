# Contributing to Wing Bridge

> 🇫🇷 The project is kept **in French**: code comments, commit messages, and the
> technical documentation in `docs/`. Please follow suit. (The entry-point docs
> — this file, `README.md`, `CHANGELOG.md`, `THIRD_PARTY.md`, `docs/README.md`,
> `docs/I18N.md` — are in English; see [Translations](#translations) below.)

This file gathers what you need to know **before touching the code**: the
expected working method, the editing rules, the pitfalls that each cost hours,
and how to build / test.

The full technical documentation is in `docs/` — start with
`docs/ARCHITECTURE.md` (how the pieces fit together), then the file for the
subsystem concerned (`docs/README.md` says which).

---

## The three constraints that decide everything

1. **Reliability comes before features.** A crash during a show costs more than
   ten missing functions.
2. **Distributable to someone who does not have the build environment.** Any
   value to be changed “in the code then rebuild” is a design bug — it must be
   adjustable in the interface.
3. **Free.** No solution that assumes a paid Apple developer account.

**Target: grandMA3 onPC only**, never a real console. MA3 therefore necessarily
runs on the same machine as the app.

## Every wing is different — customisation is a requirement

Nothing guarantees that two command wings have the same layout: the fader order
may differ, keys may be missing and have been replaced by others. **Never
remove, in the name of simplification, a setting the user must be able to adapt
to THEIR unit**: assignment of each key, type and label of each fader, keyboard
shortcut of each token, attribute groups of the wheels. They can be moved or
grouped, not removed.

## Expected working method

- **Verify, never assume.** Several of this project's mistakes came from
  plausible hypotheses presented as facts. When a claim matters, it is proven:
  log to back it up, isolated test, or official documentation.
- **State what is established and what is not.** A coherent hypothesis remains a
  hypothesis; write it as such.
- **A check never seen RED proves nothing.** Re-injecting the bug a smoke-test
  check watches for is part of the job — it has already happened that a check
  went green on faulty code.
- **Document in `docs/`**, in the file for the **subsystem concerned**
  (`docs/README.md` says which). An undocumented change is a lost change.

---

## Building and testing

```bash
# once only:
python3 -m venv ~/wing-env
~/wing-env/bin/pip install pyusb python-osc pyobjc pyinstaller
brew install libusb                       # macOS

cd src
~/wing-env/bin/python3 smoke_test.py      # ~82 checks, ~35 s, no hardware
```

| Script | When | Effect |
|---|---|---|
| `./build_server.sh` | **95 % of cases** — engine change | rebuild of the engine only, **preserves the keyboard helper's Accessibility permission** |
| `./build_app.sh` | only if `wing_keyboard.py` changes | full rebuild — **the Accessibility permission drops** and must be re-granted by hand |
| `.\build_windows.ps1` | Windows x64 build (PowerShell) | engine + keyboard helper frozen into `dist-windows\` |
| `./build_zip_macos.sh` | after a macOS build, to produce the release asset | zips `Wing Bridge.app` and **verifies the ad-hoc signature survives a compress/extract round-trip** (also checks: no `._*` files, no `wing_firmware.bin`, no personal-name leak, universal engine) |

⚠️ The build scripts **run `smoke_test.py` first and cancel the build if it
fails**. Do not bypass this. Both macOS build scripts also **ad-hoc sign the
whole `.app` bundle** (`codesign -s -`, no Apple account) as their last step and
**cancel the build if `codesign --verify --deep --strict` fails** — without a
signature on the shell-script-based bundle, macOS 15+ blocks it with no “Open
Anyway”. `build_server.sh` leaves `Wing Keyboard.app` untouched as long as its
signature is still valid, so its Accessibility permission is preserved.

`build_server.sh` / `build_app.sh` accept `--no-bump` (don't increment the build
number); `build_windows.ps1` has `-SkipBump` / `-SkipKeyboard`. The first
platform of a release bumps, the other passes `--no-bump` / `-SkipBump`.

To re-bundle the firmware into a **private** build: `--with-firmware`
(`build_*.sh`) or `-WithFirmware` (`build_windows.ps1`). The public distribution
never contains `wing_firmware.bin`.

### Interface: markup and JavaScript SEPARATE

- **The markup** lives in `src/wing_ui.html` — it contains **no JavaScript**.
- **The JavaScript** lives in `src/ui/`, **one file per tab**: `core`, `aides`,
  `bridge`, `touches`, `faders_encodeurs`, `profils`, `parametres`, `init`.
- ⚠️ **Global scope mandatory, never `type="module"`**: about forty inline
  handlers (`onclick=…`) in the markup depend on it and would all die silently.
- ⚠️ **Imposed load order**: `core` first (it declares the globals), `init` last
  (it calls everything else). The `<script defer>` tags in `wing_ui.html` are in
  that order on purpose.
- The entire `ui/` folder must stay in the `--add-data` of both build scripts: a
  missing file and the interface is **inert** (page served, no button responds).
  The build scripts refuse to finish if one is missing.

---

## Editing rules

Read before touching the code. Every line comes from a real failure. The common
thread: in this project, an error rarely shows up as an exception — it shows up
as **silence**.

| If you modify… | Then, mandatorily |
|---|---|
| **the markup** | edit `src/wing_ui.html` — it no longer contains JavaScript |
| **the JavaScript** | edit the `src/ui/` file matching the tab; global scope, never `type="module"`; keep the order `core` → … → `init` (see above) |
| **a field the JS reads in `/api/status`** | check it still exists server-side — a renamed field crashes `poll()` inside its `try` and makes the header disappear. Isolate any secondary display in its own `try/catch`. Check `test_encodeurs_ma3` |
| **the profile schema** (new key) | add it to `attendus` in `test_profil` (smoke) **and** guarantee it in `wing_mapper.migrate_profile` — the USB loop indexes 8 faders and 4 wheels without checking, a shorter profile kills the thread silently. Check `test_forme_profil` |
| **`wing_mapper.migrate_profile`** | keep the migration **idempotent** (verified by `test_profil`) and never overwrite a valid customisation — only complete it (`setdefault`) or fix a default **shown to be wrong** |
| **an MA3 command keyword** | verify it in the installed manual (`<version>/shared/language/HTML`, one `keyword_*.html` page per keyword). A wrong name, or wrongly capitalised, fails **silently** |
| **an encoder attribute name** | take it from MA3's `attribute_definitions.xml`, `<Attribute>` tags **only** — never the Encoder Bar label (`Pretty` field), never a `<FeatureGroup>`. Check `test_attributs` |
| **a COMPOUND command** (verb + targets) | read the manual's “Syntax” line, not just the keyword (`Copy [Object] [Source] At [Destination]` — the `At` is mandatory). Never classify a verb “by analogy” with another |
| **a command token** (button, helper, console table) | check it can REACH MA3: either all its words are keywords from the manual, or it has a keyboard shortcut. The name often comes from the physical key's **label**, not from the keyword (`Exec` → `Executor`, `SelFix` → `SelectFixtures`) |
| **what goes to MA3's command line** | NEVER type a word into it letter by letter. **It is not a text field**: each letter inserts a keyword. A compound command goes over **OSC**, never over the keyboard |
| **a console-table shortcut** | check no other key already has the same keystroke — two tokens on the same keystroke and one does the other's job. Check `test_raccourcis_uniques` (also compares against MA3's real table) |
| **a shortcut already saved in a profile** | only “fix” it if it is **shown to be wrong** (key observed broken, or doing another's job). A mere discrepancy with MA3's `KeyboardShortCuts.xml` is not enough: that file lists **one** binding, not the only one |
| **an executor button's behaviour** | handle **the press AND the release** in the same move — they live in two different functions (`handle_button_bridge` / `handle_button_release`) and have already diverged: an executor stayed stuck lit, silently. Check `test_executor_symetrie` |
| **the firmware upload** (`upload_firmware`, or a path leading to it) | check the wing is indeed **in bootloader (480 Mb/s)**. Sent to an application wing (12 Mb/s), the firmware goes into its command stream — and **that is what puts it into bootloader**. Check `test_poll_pkt` |
| **a USB handle or a resource held on an error path** | release it BEFORE exiting, even on a `return None`. In a process that never dies (`os.execv`), a forgotten handle is a **permanent lock** on the hardware, not a memory leak |
| **the engine restart** (`restart_self`) | go through `os.execv` (same PID). A process that **dies** makes the wing re-enumerate, and it comes back slow one time in two — measured: `execv`, 0 wing missing over 24 sessions; fresh process, 11 missing over 15. The fresh process is only a fallback |
| **an engine EXIT** (`/api/quit`) | go through `arreter_usb()` — which waits for an in-flight read to finish before releasing. Check `test_sorties_rendent_la_wing` |
| **a connection attempt** (wherever it comes from) | update `AUTO["last_try"]` — an attempt is an attempt whatever its origin; otherwise the loop sees a stale marker |
| **the USB link buttons** | there is only **one** (`wingBtn`), whose label follows the state, and **it's the server that decides** between connection and reset. Do not reintroduce “⏏ Disconnect”: its chaining with “Connect” is a close→reopen, the trigger of the SLOW state. Check `test_boutons_wing_uniques` |
| **an interface button** | check it has **actually done** what it announces, AT the moment of the click. A button that lies costs more than a missing button. Check `test_boutons_honnetes` |
| **a success message in a log** | check the target AT the moment of sending. A lying “✓ sent” costs hours |
| **a message that advises a physical action** (“unplug it”) | check the action would achieve something, and that the failure is **definitive** — not merely observed right now. Check `test_messages_actionnables` |
| **an `except: pass` around a system call** | ask what you are making invisible. If the failure is benign, write it in a comment; otherwise, log it |
| **a comment that describes a decision** | check it still describes the code below it. A false comment is worse than no comment — it makes people re-try what works, or trust what doesn't |
| **a field added to the Lua probe** | copy it into `wing_ma3.ma3_etat()` (`base.update(...)`) — otherwise the probe publishes it and it never reaches the app. Forgotten twice |
| **the lookup of MA3's PID** | go through `pgrep` (macOS) / window re-enumeration (Windows), **never** a list frozen in a process with no run loop — the keystrokes would go to a dead PID, silently |
| **`wing_keyboard.py`** | that's `build_app.sh` (full build) → the Accessibility permission drops |
| **anything at all** | `smoke_test.py` runs before every build and **cancels the build** if it fails — do not bypass it |

### The three USB link buttons

| Button | When | What it does |
|---|---|---|
| 🔌 Connect / ↻ Reconnect | the wing doesn't respond, or lags | re-establishes the USB link |
| 🔄 Reset | serious trouble, MA3 updated | restarts engine + keyboard helper (`os.execv`, same PID) |
| ⏻ Quit | end of session | releases the wing and kills the engine (leaves the wing in bootloader — see `docs/HARDWARE.md`) |

---

## The pitfalls that cost the most

| Topic | The rule |
|---|---|
| **Firmware upload** | NEVER to a wing that is already running — that is what puts it into bootloader. See `docs/HARDWARE.md`, “LE HELLO DIT QUI RÉPOND” |
| **MA3 keywords** | are verified in the installed manual. A wrong name, or wrongly capitalised, fails **silently** |
| **MA3 command line** | it is **not** a text field: each letter inserts a keyword. A compound command goes over OSC, never over the keyboard |
| **Executor buttons** | handle the press **and** the release together: they live in two different functions and have already diverged |
| **The markup** | edit `wing_ui.html` — it no longer contains JavaScript |
| **The JavaScript** | edit the `src/ui/` file matching the tab. Global scope mandatory, imposed load order (`core` → `init`) |
| **MA3 not reacting** | before touching the OSC config: **Menu → Network, is the button bottom-right GREEN?** MA3's global network off ⇒ no socket, OSC included. See `docs/GRANDMA3_SYNC.md` |
| **An interface button** | it must have **actually done** what it announces. A button that lies costs more than a missing button |

---

## Translations

The **entry-point documents** — `README.md`, `CONTRIBUTING.md`, `CHANGELOG.md`,
`THIRD_PARTY.md`, `docs/README.md`, `docs/I18N.md` — are in English: a GitHub
visitor lands on them first.

The **technical documents `docs/*.md`** (`ARCHITECTURE.md`, `HARDWARE.md`,
`GRANDMA3_SYNC.md`, `FADERS_ENCODERS.md`, `KEYBOARD_MAPPING.md`, `WINDOWS.md`)
are **in French**. A PR that translates one of them is welcome — **one document
per PR, keeping the same filename** (the file becomes English; no French version
is kept). Watch the cross-references: if you translate a section heading you
break the anchors that point at it, from the other docs and from the code
(`git grep "docs/" src/`); the smoke-test check `test_renvois_doc` guards this
and must stay green.

For the **app interface strings** (menus, buttons, log), that's a different job:
add a language in `src/locales/` — step-by-step guide in `src/locales/README.md`,
mechanics and conventions in `docs/I18N.md`.

---

## Commits

- Messages **in French**.
- End each commit message with the project trailers (see the recent `git log`
  for the exact form).
- On the default branch, branch first.
