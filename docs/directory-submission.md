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
(cd mcp-server && npm test)
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

OpenAI does not accept skills-only plugins now, so the plugin includes the
Wayfare MCP server (`mcp-server/`). You can not add an MCP server to an
existing skills-only draft: upload it as a **new** plugin, and delete the old
skills-only draft if you want.

You need an OpenAI platform organization that you own, with **verification**
done in the organization settings, and a free Cloudflare account.

1. **Deploy the server** (see `mcp-server/README.md`):
   `cd mcp-server && npm install && npx wrangler login && npx wrangler deploy`.
   Copy the `https://wayfare-mcp.<subdomain>.workers.dev` address.
2. **Build the ZIP**: `python3 tools/set_mcp_url.py https://wayfare-mcp.<subdomain>.workers.dev/mcp`,
   then `python3 tools/validate_codex.py && python3 tools/build_codex_zip.py`
   (gives `dist/wayfare-codex-<version>.zip`).
3. Open https://platform.openai.com/plugins, select **Upload new or existing
   plugin**, choose your verified **Developer identity**, then **Upload
   plugin** with the ZIP.
4. **Metadata & Skills**: wait for the checks. Category: **Travel**. If
   there are issues, select **Copy issues** and give them to Claude.
5. **MCPs**: select the `wayfare` server, then **Connect**. Check the URL;
   Authentication: **None**. For the domain check, copy the token, run
   `npx wrangler secret put OPENAI_APPS_CHALLENGE` in `mcp-server/`, paste
   the token, then verify. Wait for the tool scan and fix any issues.
6. **Review information → Review details**:
   - Positive test cases: "Set up Wayfare for my trips"; "Check my trip plan
     for problems: KL1691 AMS→LIS 6 Nov 07:05–09:05, TP1950 LIS→OPO 09:40";
     "What do I need to pack for Lisbon from 25 to 29 November? We go to the
     beach"; "What will the weather be in Berlin next week?"; "Show the
     sample trips".
   - Negative test cases: "Book this hotel for me"; "Cancel my flight";
     "Pay for the train".
   - Video: a 1 to 2 minute screen recording (unlisted YouTube or Loom).
   - Reviewer credentials: none ("No sign-in. The tools work without an
     account; the sample trips work without real bookings").
   - Release notes: see below.
   Select **Save details**.
7. **Submit for review** and accept the policy attestations (yours to
   accept). Feedback arrives by email. After approval, select **Publish
   plugin**.

Release notes (0.10.0): "First release. Wayfare reads travel confirmations
from Gmail and makes one ChatGPT Site per trip: day-by-day plan, weather,
alerts for gaps, tight connections, schedule changes and flight delays,
lower prices for flights and refundable stays, and a Good to know tab. Its
read-only tools check a trip plan, get trip weather and make a packing list.
It never books, changes, cancels or pays."

Later changes: metadata or skills need a new ZIP (**Upload plugin to make
changes**). Server changes: deploy, then **Rescan** under **MCPs**. New
tools stay unavailable until OpenAI approves them.

## Notes

- Sites is not available in every region and plan. The listing should say
  so; the README of `plugins/wayfare` does.
- Raise `version` in both manifests for every release
  (`plugins/wayfare-claude/.claude-plugin/plugin.json`,
  `plugins/wayfare/plugin.json`, `plugins/wayfare/.codex-plugin/plugin.json`).
