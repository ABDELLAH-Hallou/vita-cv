from vita.commands.keys import _obfuscate


def test_mask_short_key() -> None:
    key = "12345678"
    assert _obfuscate(key) == "********"


def test_mask_long_key() -> None:
    key = "12345678901234567890"
    assert _obfuscate(key) == "1234************7890"
