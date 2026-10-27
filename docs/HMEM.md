# CheckAm memory (H-MEM)

CheckAm uses the Meterless **H-MEM** memory engine so one person's check can warn the next person, even after a restart.

## What it does

1. After every check, CheckAm writes one H-MEM memory for each thing scammers reuse: account number, phone number, website, @handle. Example: `Account number 8123456789 was in a message CheckAm judged scam (telegram)`.
   - entity: `account:8123456789`; tags: verdict, platform, kind and the salted user key; source: `checkam-check`.
   - The message text is never stored.
   - If the same person sends the same value with the same verdict again, the old memory is refreshed. No duplicate is added.
2. Before deciding, CheckAm asks H-MEM about the same values (hybrid ranked recall), keeps only exact entity matches, and drops the asker's own memories, so nobody can confirm their own report.
3. What's left becomes one finding per value, source `CheckAm memory (H-MEM)`:
   - 3 or more other people: `scam`, weight 3
   - 1 or 2 other people: `caution`, weight 2
   - only "looks safe" verdicts before: `info`, weight 0

This replaces the old `reports.py` source inside `Checker.check()`, so the same signal is never counted twice. `reports.py` and the `reports` table still exist, and `Store.record()` still runs for stats.

## Where the code is

| File | What |
|---|---|
| `checkam/hmem.py` | The engine, ported from `engines/hmem/reference/src`. Record model (source required), hybrid query, feedback deltas, append-only trust ledger, conflict scan + 0.70 auto-resolve gate, sleep preview/execute/restore, dreaming with approval, model-free mining. Injectable `clock` (ms). |
| `checkam/sources/memory.py` | `check()` (recall -> evidence) and `remember()` (write after the verdict). |
| `checkam/agent.py` | `Checker(..., hmem=None)` builds `HMEM(store.path)`; it calls `memory.check` with the other sources and `memory.remember` after the verdict. |

Storage: tables `hmem_memories` (working + long_term tiers), `hmem_ledger` and `hmem_meta` in the same SQLite file as CheckAm (`checkam.db`). short_term stays in memory. If another process writes to the file, the next query reloads the durable tiers (SQLite `data_version`).

## Tests

```
python -m pytest -q tests/test_hmem_conformance.py tests/test_hmem_feature.py
```

- `test_hmem_conformance.py`: all 13 checks from `conformance/runner.ts` against `tests/data/hmem_vectors.json`, plus persistence, sleep restore and mining tests. All pass.
- `test_hmem_feature.py`: two people check messages with the same account number in separate sessions (new `Store` and new `HMEM` on the same db file); the second gets the H-MEM finding. Also checks the 3-person scam signal, look-alike numbers, safe-only history, that message text is never stored, and the ledger.

## Not covered

- Sleep and dreaming are built and tested in the engine but not scheduled in CheckAm. Sleep synthesis would merge near-identical memories from different people, which would break the per-person count, so leave it off for CheckAm data.
- No time window: memories rank lower as they age (14-day recency decay) but still count. The old source used a 30-day window.
- Feedback (`helpful` / `wrong`) is in the engine, but no chat command uses it yet.
- Conflict detection is not run on CheckAm memories (they are observations, not claims that contradict each other).
- Mining only has the model-free path. There is no model hook.
- A website that showed up in a scam message (for example a real bank site quoted by the scammer) is remembered with that verdict, the same as the old source did.
