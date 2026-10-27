# Demo video script (target 3:15, rules allow 1 to 4 minutes)

Record in two parts and join them: your phone screen (Android: swipe down > Screen record, microphone on) and your laptop screen (Windows: Win + Alt + R records the active window, or use OBS). Speak in your own voice. Show the product working in the first 20 seconds. The rules say the video must show how Zetaris and Meterless are integrated, so don't skip the laptop part.

Before recording:

1. Nightshift is open with the NVIDIA provider connected and a Nemotron lane active.
2. Zetaris isn't installed yet, so the trace says "sample mode". Show the Zetaris code instead (step below).
3. On the laptop: `python -m checkam run`. The log should say "Reasoning with: meterless". Keep it plugged in and awake.
4. For the group scene: in @BotFather send `/setprivacy`, pick the bot, choose **Disable**. Make a Telegram group with one other person, then add the bot. If it was already in the group, remove it and add it again.
5. Copy the messages below into your phone's notes.
6. Each check takes 10 to 30 seconds. The bot shows "🔎 Checking…" at once. Cut the wait when you edit.

| Time | Screen | You say |
|---|---|---|
| 0:00-0:15 | Phone: the fake OPay loan text | "My mum got this: her OPay loan is approved, she just has to pay five thousand naira to unlock it. She nearly paid. Millions of Nigerians get messages like this every week." |
| 0:15-0:40 | Phone: forward it to @checkamoutbot. "🔎 Checking…", then the verdict | "So I built CheckAm. You forward it any message you're not sure about. It investigates, and it tells you why." Point at reasons 1 and 2. |
| 0:40-0:55 | Phone: scroll to Sources | "Every reason is numbered to a source you can check yourself. This link uses OPay's name, but OPay's real website is opayweb.com." |
| 0:55-1:15 | Phone: send the CBEX message | "Investment schemes too. SEC Nigeria publicly warned about CBEX, and CheckAm cites the SEC's own notice." |
| 1:15-1:30 | Phone: the Pidgin NNPC message, then the Pidgin reply | "It answers in the language you write in. Pidgin in, Pidgin out." |
| 1:30-1:45 | Phone: the family group, someone posts a scam link, CheckAm warns | "In a family group it stays quiet, and only speaks up when something looks like a scam." |
| 1:45-2:10 | Laptop: open `checkam/data/zetaris_setup.sql` on GitHub, then `checkam/zetaris.py` | "The facts behind every answer, the real websites of 37 Nigerian banks and agencies and every operator the SEC has warned about, are set up as Zetaris tables and loaded with SQL. Tonight it's running in sample mode from the same files, because the Zetaris install didn't finish on my connection." |
| 2:10-2:35 | Laptop: Nightshift's lanes with the Nemotron model, then the terminal running `python -m checkam check "<OPay message>"` scrolled to the agent trace | "The reasoning runs on NVIDIA Nemotron through Meterless Nightshift. Here's the trace: Nemotron, through Nightshift, drafted the verdict, and an evaluator checked that every reason cites real evidence. If it doesn't, the evaluator sends it back for a fix." |
| 2:35-3:00 | Laptop: run `python -m checkam check "Send 5000 to 8123456789 to claim your grant"` and point at the "CheckAm memory (H-MEM)" finding | "CheckAm also remembers, using the Meterless H-MEM memory engine. My mum's message had this account number. Now anyone who gets a message with the same account is told someone already reported it. It stores the account number, never the message." |
| 3:00-3:15 | Phone: the red verdict again | "Check am before you pay." |

Messages to send (copy them to your phone notes first):

1. `Congratulations! Your OPay loan of N150,000 has been approved. Pay a processing fee of N5,000 to 8123456789 to unlock and receive your money within 24 hours. Visit opay-loans.xyz/claim`
2. `Join CBEX today! Guaranteed 40% monthly returns. Send your USDT to my wallet, the platform is paying fast`
3. `Abeg check am: dem say make I pay 3k registration fee for NNPC recruitment, link na nnpc-recruitment-portal.online`
4. For the group: a fresh phishing link. Run `python -c "import sqlite3;print(sqlite3.connect('checkam.db').execute(\"select url from threats where source='OpenPhish' limit 1\").fetchone()[0])"` just before recording. Don't open it yourself.

The H-MEM step works because the phone (Telegram) and the laptop (CLI) count as two different people, so the second check sees the first one's memory.
