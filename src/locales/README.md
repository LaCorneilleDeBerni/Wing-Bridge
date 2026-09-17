# Translation catalogues

This folder holds Wing Bridge's **language catalogues**, one flat JSON file per
language:

| File | Language | Role |
|---|---|---|
| `fr.json` | French | **the reference** — every key exists here first |
| `en.json` | English | translation, up to date (Phase 3 done) |

Keys carry a **namespace** prefix: `ui.*` (interface), `journal.*` (engine log),
`err.*` (errors shown to the user), `firmware.*` (capture wizard), `diag.*`
(diagnostic report, **always rendered in English**), `aide.*` (the `?` popups
and the Help tab). A translator treats them all the same; on the code side,
`docs/I18N.md` § "Server side" says which resolver handles what.

## For a translator

1. **Translate the values only**, on the right of the `:` — **never the keys**,
   on the left. The key `"ui.bridge.journal.titre"` stays
   `"ui.bridge.journal.titre"` in every language; only `"Journal"` gets
   translated.

   ```json
   "ui.bridge.journal.titre": "Journal"          →  "ui.bridge.journal.titre": "Log"
   ```

2. **Keep the `{name}` gaps intact.** `"Fader {n} rattrapé"` can become
   `"Fader {n} caught up"` — the `{n}` must stay, it is a placeholder the app
   fills. You may move it within the sentence, but not rename or remove it.

3. **Keep the emoji and meaningful punctuation** (`«  »`, `→`, `⚠️`, leading and
   trailing spaces): they are part of the rendered output.

4. **`fr.json` and `en.json` must have EXACTLY the same keys.** If you add one on
   one side, add it on the other. The smoke test (`smoke_test.py`, `test_i18n`
   check) fails the build otherwise.

## Adding a language

1. Copy `en.json` to `xx.json` (`xx` = ISO code: `de`, `es`, `it`…).
2. Translate the values.
3. Add `"xx"` to **`LANGUES_SUPPORTEES`** in `src/ui/i18n.js` (and a
   `REGLES_PLURIEL` rule in the same file if the language has more than two
   forms).
4. Add the `xx` rule to **`_REGLES_PLURIEL`** in `src/wing_i18n.py` — it also
   acts as the allow-list for `POST /api/lang` (server engine).
5. Add `"xx"` to **`LOCALES`** in `src/wing_ui.py` — without it, the
   `/locales/xx.json` route returns 404.
6. Add a flag button to the header in `src/wing_ui.html`.
7. Submit the change (pull request).

The **full list** of contact points and the "the interface tolerates ± 35 % text
length" constraint are in `docs/I18N.md`, section "Adding a language".

Architecture details, key naming conventions, known limitations:
**`docs/I18N.md`**.

## Testing

```bash
cd ../          # src/
~/wing-env/bin/python3 smoke_test.py    # includes the test_i18n check
```

Then, with the app running, the 🇫🇷 / 🇬🇧 selector in the header switches the
language live (the choice is remembered).
