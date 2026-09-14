from app.xray.routing_profiles import parse_json_object, select_routing


def test_parse_json_object_treats_blank_as_unset():
    assert parse_json_object(None) is None
    assert parse_json_object("   ") is None
    assert parse_json_object('{"a": 1}') == {"a": 1}


def test_parse_json_object_rejects_non_object():
    for raw in ("[1]", '"s"', "{", "3"):
        try:
            parse_json_object(raw)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {raw!r}")


def test_select_routing_falls_back_to_template_routing():
    template = {"rules": ["from-template"]}
    assert select_routing(template, None, None, profile_assigned=False) == template
    assert select_routing(template, {"rules": ["from-profile"]}, None, profile_assigned=True) == {
        "rules": ["from-profile"]
    }


def test_select_routing_two_step_fallback_through_default_document():
    """Хост БЕЗ профиля: документ `default` → routing шаблона."""
    template = {"rules": ["from-template"]}
    default = {"rules": ["from-default"]}
    profile = {"rules": ["from-profile"]}
    # Хост без профиля (routing_profile_id IS NULL) — вторая ступень, а не шаблон.
    assert select_routing(template, None, default, profile_assigned=False) == default
    # Профиль хоста задан — он выигрывает у `default`.
    assert select_routing(template, profile, default, profile_assigned=True) == profile
    # Пустое тело `default` (его нет в карте профилей) — последняя ступень, шаблон.
    assert select_routing(template, None, None, profile_assigned=False) == template


def test_assigned_profile_with_empty_body_skips_default_document():
    """C1: назначенный, но пустой профиль уходит на routing ШАБЛОНА, минуя `default`.

    Так вело себя дореформенное select_routing(..., is_bs=True) с пустым
    sub_routing_json_bs: пустое тело у назначенного профиля — это «routing из
    шаблона», а не «как у всех остальных».
    """
    template = {"rules": ["from-template"]}
    default = {"rules": ["from-default"]}

    assert select_routing(template, None, default, profile_assigned=True) == template
