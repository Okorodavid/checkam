"""CheckAm memory (H-MEM) as a working feature: one person's check warns the next, across restarts."""

import sqlite3

from checkam.agent import Checker
from checkam.evidence import CAUTION, INFO, SCAM, extract
from checkam.hmem import HMEM
from checkam.sources import memory
from checkam.store import Store

MSG = "Pay the N5,000 processing fee to 8123456789 today to unlock your loan."
LATER = "Na me be your agent. Send the registration money to 8123456789 make I process am."


def from_memory(report):
    return [e for e in report.evidence if e.source == memory.SOURCE]


async def test_a_second_person_in_a_new_session_gets_the_first_persons_check(checker, settings):
    first = await checker.check(MSG, "telegram", "ada")
    assert not from_memory(first)
    path = settings.db_path

    # a fresh process: new Store and a new H-MEM instance on the same db file
    later = Checker(settings, Store(path), checker.client)
    second = await later.check(LATER, "whatsapp", "bola")
    found = from_memory(second)
    assert len(found) == 1 and found[0].signal == CAUTION and found[0].weight == 2
    assert "1 other person" in found[0].finding and "8123456789" in found[0].finding
    assert found[0].id  # numbered like every other finding, so a verdict can cite it

    again = await Checker(settings, Store(path), checker.client).check(LATER, "telegram", "ada")
    assert len(from_memory(again)) == 1  # ada sees bola's check, never her own

    # message text is never stored, only the line about the account number
    rows = " ".join(r[0] for r in sqlite3.connect(path).execute("SELECT record FROM hmem_memories"))
    assert "8123456789" in rows and "processing fee" not in rows and "registration money" not in rows


def test_three_other_people_make_it_a_scam_signal(tmp_path):
    hmem = HMEM(tmp_path / "m.db")
    for who in ("a", "b", "c"):
        memory.remember(hmem, extract(MSG), "scam", "telegram", who)
    memory.remember(hmem, extract(MSG), "scam", "telegram", "c")  # repeats refresh, never add a person
    ev = memory.check(extract(LATER), HMEM(tmp_path / "m.db"), "d")
    assert ev[0].signal == SCAM and ev[0].weight == 3 and "3 other people" in ev[0].finding
    assert memory.check(extract(LATER), hmem, "a")[0].finding.startswith("2 other people")


def test_a_look_alike_number_and_safe_only_history(tmp_path):
    hmem = HMEM(tmp_path / "m.db")
    memory.remember(hmem, extract(MSG), "scam", "telegram", "a")
    assert memory.check(extract("Send it to 8123456780"), hmem, "b") == []  # one digit off is not a match
    memory.remember(hmem, extract("Download the app from opayweb.com"), "looks_safe", "cli", "a")
    ev = memory.check(extract("Is opayweb.com real?"), hmem, "b")
    assert ev[0].signal == INFO and ev[0].weight == 0


def test_every_memory_write_is_in_the_trust_ledger(tmp_path):
    hmem = HMEM(tmp_path / "m.db")
    m = memory.remember(hmem, extract(MSG), "scam", "telegram", "a")[0]
    memory.remember(hmem, extract(MSG), "scam", "telegram", "a")
    assert m.source == "checkam-check" and m.entities == ["account:8123456789"]
    assert [e.action for e in HMEM(tmp_path / "m.db").ledger.history(m.id)] == ["create", "update"]
