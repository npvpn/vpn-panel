from app.xray.client_configs import parse_json_object, select_config


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


def test_selected_config_wins():
    configs = {1: {"from": "default"}, 2: {"from": "bs"}}
    assert select_config(configs, 1, 2) == {"from": "bs"}


def test_host_without_config_gets_default_document():
    assert select_config({1: {"from": "default"}}, 1, None) == {"from": "default"}


def test_empty_or_missing_body_falls_back_to_default_document():
    """Пустое тело выбранного конфига и ссылка на удалённый документ ведут одинаково."""
    assert select_config({1: {"from": "default"}}, 1, 2) == {"from": "default"}


def test_none_means_take_the_file_template():
    """None, а не сам шаблон: файловый рендер ленив и не должен трогаться на горячем пути."""
    assert select_config({}, None, None) is None
    assert select_config({}, 1, 1) is None
