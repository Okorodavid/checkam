import hashlib
import hmac

from checkam.chat import RateLimiter, is_greeting, worth_checking_in_group
from checkam.whatsapp import incoming, valid_signature


def test_group_filter_stays_quiet_on_normal_chat():
    assert not worth_checking_in_group("Who is bringing the rice for Sunday?")
    assert worth_checking_in_group("Make una check this opay-bonus.top")
    assert worth_checking_in_group("Pay N2,000 registration fee to unlock your grant")
    assert worth_checking_in_group("Send to 0123456789")


def test_greetings():
    assert is_greeting("Hello") and is_greeting("good morning!") and is_greeting("How far")
    assert not is_greeting("hello, is this real? pay 5000 to unlock")


def test_rate_limiter_window():
    rl = RateLimiter(2, 60)
    assert rl.allow("u", 0) and rl.allow("u", 1) and not rl.allow("u", 2)
    assert rl.allow("u", 61)


def test_whatsapp_payload_and_signature():
    payload = {"entry": [{"changes": [{"value": {"messages": [
        {"from": "2348031234567", "id": "wamid.1", "type": "text", "text": {"body": "is this real?"}},
        {"from": "2348031234567", "id": "wamid.2", "type": "image", "image": {"caption": "pay to unlock"}},
        {"from": "2348031234567", "id": "wamid.3", "type": "sticker"},
    ]}}]}]}
    assert incoming(payload) == [("2348031234567", "wamid.1", "is this real?"), ("2348031234567", "wamid.2", "pay to unlock")]
    body = b'{"x":1}'
    sig = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert valid_signature("secret", body, sig) and not valid_signature("secret", body, "sha256=bad")
    assert valid_signature("", body, None)
