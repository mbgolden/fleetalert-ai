from fleetalert.whitelist import ALLOWED_FIX_TYPES, is_whitelisted


def test_known_fix_types_are_whitelisted() -> None:
    for fix_type in ALLOWED_FIX_TYPES:
        assert is_whitelisted(fix_type)


def test_unknown_fix_type_is_rejected() -> None:
    assert not is_whitelisted("delete_machine")
    assert not is_whitelisted("")
