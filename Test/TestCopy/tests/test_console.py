from terminalist.input.win32 import KeyEvent

from Test.TestCopy.console import translate_key


def test_translate_arrow_key():
    record = KeyEvent(None, 0x25, 0, 1)
    assert translate_key(record) == ("key", "left")


def test_translate_copy_mode_key():
    record = KeyEvent("[", ord("["), 0, 1)
    assert translate_key(record) == ("key", "copy_mode")


def test_translate_search_key():
    record = KeyEvent("/", ord("/"), 0, 1)
    assert translate_key(record) == ("key", "search")


def test_translate_printable_text():
    record = KeyEvent("x", ord("x"), 0, 1)
    assert translate_key(record) == ("text", "x")
