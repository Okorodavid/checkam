# CheckAm

**Forward a suspicious message to CheckAm and it tells you if it's a scam, and exactly why.**

"Check am" is Nigerian Pidgin for "check it". My mum got a text: *"Your OPay loan of ₦150,000 is approved. Pay a processing fee of ₦5,000 to unlock it."* She almost paid. Millions of Nigerians get messages like this every week: fake loans, fake jobs, Ponzi "investments", fake bank alerts, phishing links. Most of them have no one to ask.

CheckAm is that someone to ask. Forward it a message, a link or an account number on Telegram, WhatsApp or Discord. It investigates across independent sources, connects what it finds, and answers with a verdict where every reason points to its evidence:

```
🔴 This is a scam.

Why:
1. It asks you to pay ₦5,000 before you can receive the loan. That is the classic advance-fee scam. [1]
2. opay-loans.xyz uses OPay's name but isn't OPay's website (opayweb.com). [2]
3. The website was created 5 days ago. [3]
4. 2 other people sent me this same account number this week. [4]

Don't pay, don't click, and don't share any code or PIN. Block the sender.

Sources:
[1] Message check
[2] Official accounts list: https://opayweb.com
[3] Domain record (RDAP): https://lookup.icann.org/en/lookup?name=opay-loans.xyz
[4] Other CheckAm users
```

It replies in the language you wrote in, including Pidgin. It's built for everyone: anyone can message it privately, and in family or community groups it speaks up only when a message looks like a scam.

## How it investigates

Every message goes through the same steps. Each source looks at one thing and reports what it found. None of them decides alone.

| Source | What it checks | Needs |
|---|---|---|
| **Message check** | Known Nigerian scam patterns: pay-to-unlock, "send your OTP", guaranteed returns, pay-to-apply jobs and grants, fake credit alerts, threats, fake customer care | nothing |
| **Link safety** | 153,000+ known phishing sites (Phishing Army) and live phishing URLs (OpenPhish); link tricks: brand names bolted onto other sites, look-alike letters, bare IP addresses, `.apk` downloads, short links (expanded to see where they really go), free page hosts | nothing; Google Safe Browsing and URLhaus optional |
| **Official accounts list** (Zetaris) | 37 Nigerian banks, fintechs, telecoms and agencies with their real websites and X accounts. Catches `opay-loans.xyz`, `gtbamk.com` and `@gtbank_care` | nothing |
| **Domain record (RDAP)** | When the website was registered. Scam sites are usually days old | nothing |
| **Regulators** (Zetaris) | SEC Nigeria's published "Illegal Operator" warnings (CBEX, ZugaCoin, MMM, AfriQuantumX and more, pulled live from sec.gov.ng), plus SEC and FCCPC rules on investments and loan apps | nothing |
| **CheckAm memory (Meterless H-MEM)** | Has anyone else sent the same account number, phone, website or handle? One person's check warns the next, across sessions | nothing |
| **Web and X search** | What news sites and posts on X say about the company or site | Tavily key (free tier) |

Then the agent decides:

- **Nemotron drafts the verdict through Meterless Nightshift**, the primary AI provider. CheckAm picks a Nemotron-backed route from Nightshift's model list. Fallbacks: NVIDIA's API directly (`nvidia/nemotron-3-ultra-550b-a55b`), then Gemini, then built-in rules.
- **An evaluator checks the draft.** Is it valid? Does every reason cite real finding ids? Does it clash with decisive evidence? If not, the problems go back to the model for one revision. Reasons that still cite nothing are dropped, so the model can connect findings but can't invent them.
- **A safety floor.** A blocklisted link or a named SEC warning can never come back as "looks safe", whatever the model says.
- **A trace** logs where the data came from, which model handled each request and what the evaluator decided. `check` prints it; `check --json` includes it.
- Verdicts: 🔴 scam, 🟠 likely scam, 🟡 not sure (with what to check), 🟢 looks genuine.

## Sponsor stack

| Layer | What CheckAm uses it for | Code |
|---|---|---|
| **Zetaris** (data layer) | The official accounts, regulator warnings and rules, and SEC operator names are Lightning REST tables and views in Zetaris (`checkam.official_accounts`, `checkam.regulator_warnings`, `checkam.regulator_rules`, `checkam.sec_notices`), loaded with SQL over its REST API | `checkam/zetaris.py`, `checkam/data/zetaris_setup.sql` |
| **Meterless Nightshift** (AI provider) | Every verdict request goes to Nightshift's OpenAI-compatible Runtime, which serves a Nemotron lane | `ask_meterless` in `checkam/reasoner.py` |
| **Meterless H-MEM** (engine) | Memory across sessions and users of the account numbers, phones, sites and handles scammers reuse | `checkam/hmem.py`, `checkam/sources/memory.py`, [docs/HMEM.md](docs/HMEM.md) |
| **NVIDIA Nemotron** | Connects the findings and writes the explanation, in English or Pidgin | via Nightshift, or NVIDIA's API as fallback |

Without Zetaris or Nightshift, CheckAm runs in sample mode: the same data from the bundled JSON files, and NVIDIA's API, Gemini or offline rules for the verdict. The trace says which was used.

## Run it

Python 3.10+.

```bash
pip install -r requirements.txt
cp .env.example .env            # add whatever keys you have; all optional
python -m checkam refresh       # download blocklists + SEC warnings (run daily)
python -m checkam zetaris       # optional: register the data in Zetaris and check it loads
python -m checkam check "Pay N5,000 to unlock your OPay loan: opay-loans.xyz"
python -m checkam run           # start Telegram / Discord / WhatsApp, whichever have tokens
```

`check --json` prints the verdict and every finding as JSON, for other tools and agents.

### Chat apps

- **Telegram:** make a bot with @BotFather and put the token in `TELEGRAM_BOT_TOKEN`. Private chats check everything. In groups it checks when tagged, on `/check` (also as a reply to someone's message), and flags likely scams by itself.
- **Discord:** create an app, add a bot, turn on *Message Content Intent*, put the token in `DISCORD_BOT_TOKEN`. Same behaviour: DMs, mentions, and quiet scam flags in channels.
- **WhatsApp:** uses Meta's official Cloud API. Create an app at developers.facebook.com, add WhatsApp, and use the free test number. Set `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` and a `WHATSAPP_VERIFY_TOKEN` of your choice. Expose port 8080 (for example `cloudflared tunnel --url http://localhost:8080`), and set the webhook to `https://<tunnel>/webhook` with the same verify token, subscribed to `messages`. Unofficial WhatsApp bot libraries break WhatsApp's terms, so CheckAm doesn't use them.

## Privacy and safety for a public bot

- Message text is never stored. Only the things scammers reuse are kept: account numbers, phone numbers, websites and handles. They're kept so repeat scams can be spotted.
- Users are stored only as salted hashes.
- CheckAm never asks for PINs, OTPs or passwords, and says so.
- It never fetches links that point into private networks.
- Each person gets a fair-use limit, and there's a daily cap, so one spammer can't run up the bill.

## Honest limits

- X is read through web search, which can lag behind new posts. CheckAm doesn't scrape X.
- Screenshots and voice notes aren't read yet; forward the text.
- The official X handle list only includes handles we're confident of. An unknown handle is reported as "not on our list", never as "fake".
- The regulator data covers SEC Nigeria warnings and the main SEC and FCCPC rules. The full FCCPC loan-app register isn't wired in yet.

## Tests

```bash
python -m pytest -q     # 51 tests, all offline
```

MIT licence.
