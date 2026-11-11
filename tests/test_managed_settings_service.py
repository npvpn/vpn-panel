import pytest

from app.models.settings import DEFAULT_CLIENT_APPS
from app.services.managed_settings import validate_managed_payload


def test_client_apps_is_not_a_managed_key():
    with pytest.raises(KeyError):
        validate_managed_payload("client_apps", DEFAULT_CLIENT_APPS)


def test_validate_unknown_key_raises():
    with pytest.raises(KeyError):
        validate_managed_payload("nope", {})


def test_push_request_defaults():
    from app.models.managed import ManagedPushRequest

    req = ManagedPushRequest.model_validate({"data": {"a": 1}, "version": "abc", "source": "admin"})
    assert req.data == {"a": 1}
    assert req.version == "abc"

    empty = ManagedPushRequest.model_validate({})
    assert empty.data == {} and empty.version == ""
