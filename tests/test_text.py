from deepseek_survey.text import sanitize_json_strings, sanitize_unicode


def test_lone_surrogate_is_replaced_for_utf8_transport() -> None:
    unsafe = "math symbol: \ud835"
    safe = sanitize_unicode(unsafe)
    assert safe == "math symbol: ?"
    assert safe.encode("utf-8")


def test_nested_json_strings_are_sanitized() -> None:
    value = {"text": ["valid", "broken \ud835"]}
    sanitized = sanitize_json_strings(value)
    assert sanitized == {"text": ["valid", "broken ?"]}
