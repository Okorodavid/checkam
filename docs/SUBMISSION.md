# CheckAm: Open Agent Hackathon 2026 submission

**Track:** 02, The Agent That Can Explain Why
**Also eligible for:** Best use of NVIDIA Nemotron
**Repo:** github.com/Okorodavid/checkam (MIT)
**Builder:** David Okoro, Enugu, Nigeria (solo)

## One line

Forward CheckAm a suspicious message, link or account number, and it investigates across seven sources and tells you if it's a scam, with every reason tied to its evidence.

## The problem

My mum got a text: "Your OPay loan of ₦150,000 is approved. Pay a processing fee of ₦5,000 to unlock it." She nearly paid.

Messages like that reach millions of Nigerians every week: fake loans, fake jobs, Ponzi "investments", fake credit alerts and phishing links. The people most targeted are parents, traders and first-time phone users, who have no one to ask. When they do ask, they usually ask the scammer's "customer care". Telling them "be careful" doesn't help. They need someone to look at this exact message and say what's wrong with it.

## What it does

You forward the message to CheckAm on Telegram, WhatsApp or Discord. Within seconds it replies with:

- a verdict: scam, likely scam, not sure, or looks genuine;
- two to four reasons in plain words, each numbered to its source;
- what to do now.

It answers in the language you used, including Nigerian Pidgin. Anyone can message it privately. In family and community groups, it stays quiet unless a message looks like a scam, then warns everyone in the group.

## How it explains why (the agent)

1. **Find what's checkable.** It pulls out links, account numbers, phone numbers, @handles and company names.
2. **Investigate across independent sources, all at once:**
   - Known Nigerian scam patterns in the text.
   - 153,000+ known phishing sites (Phishing Army, OpenPhish), and link tricks such as brand names bolted onto other sites, look-alike letters, `.apk` downloads, and short links (which it expands to find the real destination).
   - The real websites and X accounts of 37 Nigerian banks, fintechs, telecoms and agencies, to catch impersonation.
   - Domain registration age from the public RDAP registry.
   - SEC Nigeria's published illegal-operator warnings, pulled live from sec.gov.ng, plus SEC and FCCPC rules on investments and loan apps.
   - Reports from other CheckAm users of the same account number, phone, site or handle.
   - Web and X search about the company (Tavily).
3. **Number every finding** (E1, E2, ...).
4. **Reason with NVIDIA Nemotron** (`nemotron-3-ultra-550b-a55b`). It connects the findings into one verdict, for example: a fake OPay name, plus a pay-to-unlock fee, plus a cheap .xyz site with no registration record, means a scam.
5. **Verify the reasoning.** Every reason must cite real finding ids. Reasons that cite nothing, or an id that doesn't exist, are dropped. A safety floor means a blocklisted link or a named SEC warning can never be called safe. If the model is unreachable, built-in rules still give a cited verdict.

So the explanation isn't decoration: each sentence the user reads can be traced to a check they could repeat themselves.

## Sponsor technology

- **NVIDIA Nemotron** is the reasoning engine. It weighs conflicting findings, connects them, and writes the explanation in English or Pidgin, through NVIDIA's API on build.nvidia.com. The prompt marks strength-4 findings as decisive, and the output is validated against the evidence list.

## Impact

- Built for the people scammers target most, on the apps they already use, in their own language.
- It gets smarter with every check: a scam account number reported in Enugu warns someone in Kano the next day.
- It costs almost nothing to run. Most checks are free public data, and one model call is made per message.

## Privacy

Message text is never stored. Only the things scammers reuse are kept: account numbers, phones, websites and handles. Users are stored as salted hashes. CheckAm never asks for PINs or OTPs, never fetches links into private networks, and limits each person's checks so the shared service stays up.

## What I built in the hackathon window

All of CheckAm is new: the evidence sources, the SEC warning extractor, the blocklist matching, the cited-reasoning agent with its safety floor, and the Telegram, Discord and WhatsApp adapters, with 24 offline tests. I reused patterns from my earlier open-source support bot (CommunityOps) for the Telegram and Discord plumbing.

## What's next

- Read screenshots and voice notes. That's how most scam messages actually get forwarded.
- The full FCCPC loan-app register and CBN licence lists.
- A WhatsApp number anyone in Nigeria can save as a contact.
- Partnerships with banks and fintechs, whose customers are the ones being impersonated.
