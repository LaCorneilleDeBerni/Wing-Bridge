# Technical documentation — index

**This is an index, not a manual.** The user guide is the `README.md` at the
root of the project; the rules for contributing are in `CONTRIBUTING.md` (root).

> 🚫 **Do not turn this file into a second manual.** A duplicate `README.md` has
> already rotted this project: one of them survived for weeks claiming an admin
> password was required and that the app was Apple Silicon only — both false.
> **One fact, one place.**

> 🇫🇷 **The files below are in French.** They are the working documentation for
> the reverse-engineered protocol. Translation contributions are welcome — see
> `CONTRIBUTING.md`, section “Translations” (one document per PR, keep the
> filename). `I18N.md` is in English.

## By question

| Your question | The file |
|---|---|
| “How does all this fit together, again?” | **`ARCHITECTURE.md`** ← start here |
| “Which byte does what? The wing won't connect any more” | `HARDWARE.md` |
| “What does this key send? How does console mode work?” | `KEYBOARD_MAPPING.md` |
| “The fader doesn't follow / the wheel moves nothing” | `FADERS_ENCODERS.md` |
| “MA3 doesn't react / what does the console send back?” | `GRANDMA3_SYNC.md` |
| “How does the FR/EN bilingual mode work? Add a sentence / a language?” | `I18N.md` |
| “What changes under Windows?” | `WINDOWS.md` |
| “What can I break by touching this?” | `CONTRIBUTING.md` (root), “Editing rules” |
| “What changed recently?” | `CHANGELOG.md` (root) |

## By subsystem

The split follows **protocol boundaries**, not the code files:

```
   HARDWARE.md          KEYBOARD_MAPPING.md   FADERS_ENCODERS.md
   ┌──────────┐         ┌─────────────────┐   ┌────────────────┐
   │ raw USB  │         │ DISCRETE        │   │ CONTINUOUS     │
   │ packets  │────────►│ inputs          │   │ inputs         │
   │ bootloader         │ (keys)          │   │ (faders/wheels)│
   └──────────┘         └────────┬────────┘   └───────┬────────┘
                                 │                    │
                                 └────────┬───────────┘
                                          ▼
                                  GRANDMA3_SYNC.md
                                  ┌────────────────┐
                                  │ OSC · Lua probe│
                                  │ console feedbk │
                                  └────────────────┘

   WINDOWS.md — what differs when all this runs under Windows x64
```

**Why this split, and not another:**

- **`HARDWARE.md` ≠ `GRANDMA3_SYNC.md`**: these are two protocols with nothing
  in common (binary USB on one side, text OSC on the other). Mixing them makes
  debugging harder when only one of the two breaks — and that's the most common
  case.
- **`KEYBOARD_MAPPING.md` ≠ `FADERS_ENCODERS.md`**: discrete inputs versus
  continuous inputs. Two different mechanics (debounce and press/release on one
  side, anti-flood and pickup on the other), which evolve separately.
- **`WINDOWS.md` apart**: the wing's USB protocol is the same on both OSes and
  stays in `HARDWARE.md`; `WINDOWS.md` only keeps what is specific to running
  under Windows (USB backend, keyboard helper, firmware capture, PowerShell
  build pitfalls).

## The three rules for keeping this documentation

1. **One fact, one place.** Elsewhere, a link. Duplication always ends up
   diverging, and it's the stale copy that gets read.
2. **State what is established and what is not.** A coherent hypothesis remains a
   hypothesis; write it as such. Several of this project's mistakes came from
   plausible hypotheses presented as facts.
3. **A comment or a cross-reference that has aged is worse than nothing**: it
   makes people re-try what works, or trust what doesn't. When touching a
   section, check its cross-references still point somewhere — that is what the
   smoke test's `test_renvois_doc` check guards for the cross-references written
   in the code.
