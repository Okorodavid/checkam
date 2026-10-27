# Demo video script (target 2:30, hard limit 3:00)

Record your phone screen (Android: swipe down > Screen record, with microphone on). Speak in your own voice. Judges reject AI voice-overs at many events, and yours sounds real. Show the product working in the first 20 seconds.

Before recording:

1. On the laptop: `python -m checkam refresh`, then `python -m checkam run`. Keep it plugged in and awake.
2. For the group scene: in @BotFather send `/setprivacy`, pick the bot, choose **Disable** (otherwise bots can't see group messages). Make a Telegram group with one other person, then add the bot. If it was already in the group, remove it and add it again, or the change doesn't apply.
3. Copy the five messages below into your phone's notes.
4. Each check takes 10 to 30 seconds. The bot shows "🔎 Checking…" at once, then the verdict. Cut the wait when you edit.

| Time | Screen | You say |
|---|---|---|
| 0:00-0:15 | The fake OPay loan text on your phone | "My mum got this: her OPay loan is approved, she just has to pay five thousand naira to unlock it. She nearly paid. Millions of Nigerians get messages like this every week." |
| 0:15-0:40 | Long-press, forward it to CheckAm. "🔎 Checking…" appears, then the verdict (cut the wait) | "So I built CheckAm. You forward it any message you're not sure about. It investigates, and it tells you why." Read the red verdict and point at reasons 1 and 2. |
| 0:40-1:00 | Scroll to Sources, tap the opayweb.com link | "Every reason has a source you can check yourself. This link uses OPay's name, but OPay's real website is opayweb.com, and there's no public record of who registered this one." |
| 1:00-1:20 | Send: "Join CBEX, guaranteed 40% monthly returns" | "Investment schemes too. It knows the SEC publicly warned about CBEX in June 2025, because it reads the SEC's illegal-operator notices." |
| 1:20-1:40 | Send a phishing link from the blocklist, then a genuine `gtbank.com` message | "Links are checked against over 150,000 known phishing sites. And it's not paranoid: a real GTBank message comes back green." |
| 1:40-2:00 | Send the Pidgin NNPC recruitment message, show the Pidgin reply | "It answers in the language you write in. Pidgin in, Pidgin out." |
| 2:00-2:15 | A family WhatsApp or Telegram group where someone posts a scam and CheckAm warns the group | "Add it to your family group, and it only speaks up when something looks like a scam." |
| 2:15-2:30 | Laptop: `python -m checkam check ... ` showing every finding and "via nvidia/nemotron-3-ultra" | "Under the hood, seven sources run at once. NVIDIA Nemotron connects the findings, and every reason must cite real evidence or it gets thrown out. Check am before you pay." |

Messages to send (copy them to your phone notes first):

1. `Congratulations! Your OPay loan of N150,000 has been approved. Pay a processing fee of N5,000 to 8123456789 to unlock and receive your money within 24 hours. Visit opay-loans.xyz/claim`
2. `Join CBEX today! Guaranteed 40% monthly returns. Send your USDT to my wallet, the platform is paying fast`
3. A fresh phishing link: run `python -c "import sqlite3;print(sqlite3.connect('checkam.db').execute(\"select url from threats where source='OpenPhish' limit 1\").fetchone()[0])"` just before recording. Don't open it yourself.
4. `Dear customer, your GTBank statement for September is ready. Log in to the GTWorld app or visit gtbank.com`
5. `Abeg check am: dem say make I pay 3k registration fee for NNPC recruitment, link na nnpc-recruitment-portal.online`
