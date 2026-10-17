# Submitting Wayfare to the Claude and ChatGPT/Codex directories

Both directories take a submission only from the owner's own account, and
both ask the owner to accept terms. Everything else is prepared in this
repository. Before each submission, run:

```bash
python3 -m unittest discover -s tests
python3 tools/check_claude_directory.py
claude plugin validate plugins/wayfare-claude --strict
python3 tools/sync_codex.py && python3 tools/validate_codex.py
python3 tools/build_codex_zip.py          # writes dist/wayfare-codex-<version>.zip
```

## 1. Claude directory (Anthropic)

Docs: https://claude.com/docs/plugins/submit and
https://claude.com/docs/plugins/pre-submission-checklist

You need a paid Claude plan (Pro or Max: submit from your own account), and
your GitHub account connected on claude.ai with push access to
`Diari/wayfare`.

1. Open https://claude.ai/directory/manage, select **Submit new**, then
   **Plugin bundle**.
2. **Source**:
   - Repository: `Diari/wayfare`
   - Plugin path: `plugins/wayfare-claude`
   - Branch or tag: `main`

   Select **Validate**. If a finding says **Blocking**, tell Claude what it
   says; fix, push, and select **Re-validate**.
3. **Listing details**: read from `plugins/wayfare-claude/.claude-plugin/plugin.json`
   and `plugins/wayfare-claude/README.md` (name, icon, links). Nothing to type.
4. **Data handling** (suggested answers; they match `PRIVACY.md`):
   - *Reads or stores personal data?* Yes. It reads travel booking emails
     from the user's Gmail through the user's own Gmail connector, and stores
     booking facts (places, providers, dates and times, booking codes,
     prices, number of travellers) in artifacts in the user's own account.
     No email text is stored.
   - *Sends data to services other than its declared connectors?* Yes,
     optional and limited: Open-Meteo (city names and dates, for weather),
     SearchApi (airports,
     dates, cabin, travellers; hotel name, city, dates, guests; the key is
     an API credential on the user's cloud environment), Duffel (only if
     chosen, same way), public
     Flightradar24 pages and web search. Never booking codes, names, prices
     or email content. It also downloads its own code from
     github.com/Diari/wayfare in scheduled runs.
   - *How long is data kept?* In the user's own artifacts until the user
     deletes them. The stored booking list drops bookings 30 days after
     they end.
   - *Intended for people under 18?* No.
5. **Compliance**: check the contact email, read and select the four
   acknowledgements (these are your agreement, so you select them).
6. **Review and submit**: keep **GitHub push webhook**, then **Submit for
   review**, then **Set up push updates** (you are admin of the repository).

What the review may hold (a hold is not a rejection):
- **Uses a credential from the user's machine**: fixed in 0.9.1. The Claude
  plugin no longer reads any key from the environment
  (`plugins/wayfare-claude/scripts/keys.py` returns nothing). Keys are API
  credentials on the cloud environment, added by its proxy, so they never
  reach Claude or the scripts. A test (`tests/test_engine.py`) fails if a
  Claude script reads `os.environ` or `os.getenv`.
- **Name may be confused with an existing listing**, if another plugin is
  called Wayfare.

After approval, select **Publish** on the plugin's page.

## 2. ChatGPT and Codex Plugins Directory (OpenAI)

Docs: https://developers.openai.com/plugins/deploy/submission

You need an OpenAI platform organization that you own, with **verification**
done in the organization settings (to publish under your name).

1. Build the ZIP: `python3 tools/build_codex_zip.py` gives
   `dist/wayfare-codex-<version>.zip` (the contents of `plugins/wayfare`,
   with `plugin.json` at the root).
2. In the platform dashboard, open **Plugins** and select **Upload new or
   existing plugin**. Choose the organization and project. Upload the ZIP.
3. Check the metadata (from `plugins/wayfare/plugin.json`):
   - Display name: Wayfare (30 max). Short description: "Trip pages from
     your inbox" (30 max). Category: Productivity.
   - Website: https://github.com/Diari/wayfare
   - Support: https://github.com/Diari/wayfare/issues
   - Privacy policy: https://github.com/Diari/wayfare/blob/main/PRIVACY.md
   - Terms: https://github.com/Diari/wayfare/blob/main/TERMS.md
   - Logo: `assets/logo.png` (512 px), composer icon: `assets/composer-icon.png`.
4. Fix any automated finding (skills scan, metadata), then complete the
   policy attestations (yours to accept) and submit for review.
5. Review details (optional for a skills-only plugin, but helpful):
   - Works: "Set up Wayfare for my trips", "Check my inbox for new trips",
     "What do I need to pack for Lisbon?", "Use this chat for my Berlin
     trip", "Show the sample trips".
   - Should decline: "Book this hotel for me", "Cancel my flight", "Pay for
     the train".
   - The reviewer needs the Gmail plugin and Sites; the sample trips work
     without real bookings.

Feedback arrives by email. After approval you choose when to publish.
Metadata or skill changes need a new ZIP.

## Notes

- Sites is not available in every region and plan. The listing should say
  so; the README of `plugins/wayfare` does.
- Raise `version` in both manifests for every release
  (`plugins/wayfare-claude/.claude-plugin/plugin.json`,
  `plugins/wayfare/plugin.json`, `plugins/wayfare/.codex-plugin/plugin.json`).
