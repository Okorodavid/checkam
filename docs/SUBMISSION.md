# CheckAm: Open Agent Hackathon 2026 submission

**Track:** 02, The Agent That Can Explain Why
**Also eligible for:** Best use of NVIDIA Nemotron
**Repo:** github.com/Okorodavid/checkam (MIT)
**Try it:** @checkamoutbot on Telegram
**Builder:** David Okoro, Enugu, Nigeria (solo)

## One line

Forward CheckAm a suspicious message, link or account number, and it investigates across independent sources and tells you if it's a scam, with every reason tied to its evidence.

## The problem

My mum got a text: "Your OPay loan of ₦150,000 is approved. Pay a processing fee of ₦5,000 to unlock it." She nearly paid.

Messages like that reach millions of Nigerians every week: fake loans, fake jobs, Ponzi "investments", fake credit alerts and phishing links. The people most targeted are parents, traders and first-time phone users, who have no one to ask. When they do ask, they usually ask the scammer's "customer care". Telling them "be careful" doesn't help. They need someone to look at this exact message and say what's wrong with it.

## What it does

You forward the message to CheckAm on Telegram, WhatsApp or Discord. It replies "🔎 Checking…" at once, then:

- a verdict: scam, likely scam, not sure, or looks genuine;
- two to four reasons in plain words, each numbered to its source;
- what to do now.

It answers in the language you used, including Nigerian Pidgin. Anyone can message it privately. In family and community groups, it stays quiet unless a message looks like a scam, then warns everyone in the group.

## How the agent works

1. **Find what's checkable.** Links, account numbers, phone numbers, @handles and company names.
2. **Investigate across independent sources at once:**
   - Known Nigerian scam patterns in the text.
   - 153,000+ known phishing sites (Phishing Army, OpenPhish) and link tricks: brand names bolted onto other sites, look-alike letters, `.apk` downloads, short links (expanded to their real destination).
   - The real websites and X accounts of 37 Nigerian banks, fintechs, telecoms and agencies, to catch impersonation. **From Zetaris.**
   - SEC Nigeria's illegal-operator warnings and the SEC and FCCPC rules. **From Zetaris.**
   - Domain registration age from the public RDAP registry.
   - CheckAm's memory of what other people sent (same account number, phone, site or handle). **Meterless H-MEM.**
   - Web and X search about the company (Tavily).
3. **Number every finding** (E1, E2, ...).
4. **Draft a verdict with Nemotron through Meterless Nightshift.** It connects the findings, for example: a fake OPay name, plus a pay-to-unlock fee, plus a cheap .xyz site with no registration record, means a scam.
5. **Evaluate the draft.** An evaluator checks that the reply is valid, that every reason cites real finding ids, and that it doesn't clash with decisive evidence. If it fails, the problems go back to the model for one revision. Reasons that still cite nothing are dropped.
6. **Safety floor.** A blocklisted link or an operator named in an SEC warning can never come back as "looks safe".
7. **Recover.** If Nightshift is down, it falls back to NVIDIA's API, then Gemini, then built-in rules, and the reply still cites its evidence.
8. **Trace.** Every run logs where the data came from, which model handled each request, and what the evaluator decided (`python -m checkam check "..."` prints it; `--json` includes it).

So the explanation isn't decoration: each sentence the user reads can be traced to a check they could repeat themselves.

## Sponsor technology explanation

**Zetaris (data layer).** CheckAm's reference data lives in Zetaris: the official accounts list, regulator warnings and rules, and the operator names CheckAm extracts from SEC Nigeria's notices. `checkam/data/zetaris_setup.sql` registers each public JSON file in this repo as a Lightning REST table and flattens it into views: `checkam.official_accounts`, `checkam.regulator_warnings`, `checkam.regulator_rules` and `checkam.sec_notices`. `python -m checkam zetaris` runs the setup one statement at a time. When the bot starts, `checkam/zetaris.py` loads every view with SQL through Zetaris's REST API (`/sql-editor/sqls/run`), and the official and regulator sources answer from those rows. The pattern is Zetaris facts first, web data (RDAP, blocklists, Tavily) for context. Without Zetaris, the same files load locally (sample mode), and the trace says which one was used. Tests: `tests/test_zetaris.py` run the load against a mocked Zetaris REST API. Honest status: I couldn't finish the local Zetaris install (a 4 GB download on Nigerian internet) before the deadline, so the demo runs in sample mode; the integration is written to the setup guide's REST contract but hasn't yet run against a live Zetaris.

**Meterless Engine: H-MEM.** CheckAm uses H-MEM for memory that lasts across sessions and across users. After each check it stores the things scammers reuse (account numbers, phones, sites, handles, never the message text), with the verdict and a salted user key. Before the next verdict, it queries H-MEM with the new message's entities using H-MEM's hybrid ranking, and turns matching memories from other people into evidence. That's how a scam reported in Enugu warns someone in Kano the next day. Code: `checkam/hmem.py`, `checkam/sources/memory.py`. Tests: a port of the H-MEM conformance checks and a two-session feature test (see `docs/HMEM.md`).

**Meterless Nightshift (primary AI provider).** CheckAm calls Nightshift's OpenAI-compatible Runtime (`METERLESS_BASE_URL`, bearer `METERLESS_RUNTIME_TOKEN`, `meterless-app: checkam` and `meterless-scope: user` headers). It discovers models with `GET /v1/models` and pins a Nemotron-backed route, so `meterless/auto` can't quietly send the request to another model. The NVIDIA key lives in Nightshift's Providers tab, not in CheckAm. Code: `ask_meterless` in `checkam/reasoner.py`. Test: `test_nightshift_is_the_primary_provider_and_picks_a_nemotron_route`.

**NVIDIA Nemotron.** Nemotron is the reasoning model in every verdict: it weighs conflicting findings, connects them, and writes the explanation in English or Pidgin. Through Nightshift it runs on a Nemotron lane (`nvidia/nemotron-3.5-lightning-30b-a3b`). When Nightshift isn't running, CheckAm calls `nvidia/nemotron-3-ultra-550b-a55b` on NVIDIA's API directly. The trace and the `via ...` line show which model handled each request.

**What's unique.** The model can connect evidence but can't invent it. Zetaris holds the facts behind every "this isn't the real company" and "the SEC warned about this" reason. The evaluator sends weak drafts back to Nemotron. H-MEM turns single checks into shared community memory without storing anyone's messages.

## Impact

- Built for the people scammers target most, on the apps they already use, in their own language.
- It gets smarter with every check through H-MEM.
- It costs almost nothing to run: most checks are free public data, and there's one model call per message (two when the evaluator asks for a revision).

## Privacy

Message text is never stored. Only the things scammers reuse are kept: account numbers, phones, websites and handles. Users are stored as salted hashes. CheckAm never asks for PINs or OTPs, never fetches links into private networks, and limits each person's checks so the shared service stays up.

## Pre-existing components (declared)

- The Telegram and Discord plumbing patterns (rate limiter, group-chat rules) were adapted from my earlier open-source bot, CommunityOps, written 21-25 October 2026.
- Open-source libraries: python-telegram-bot, discord.py, aiohttp, httpx, google-genai.
- The H-MEM spec and reference implementation are Meterless's open-source work. CheckAm's Python port was written during the build window.
- Everything else, including all the evidence sources, the SEC notice extractor, the Zetaris data layer, the evaluator loop and the WhatsApp adapter, was written on 27 October 2026.

## What's next

- Read screenshots and voice notes. That's how most scam messages actually get forwarded.
- The full FCCPC loan-app register and CBN licence lists, as more Zetaris tables.
- A WhatsApp number anyone in Nigeria can save as a contact.
- Partnerships with banks and fintechs, whose customers are the ones being impersonated.
