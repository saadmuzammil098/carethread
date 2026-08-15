import pytest
import redis as redis_module
from botocore.session import Session
from src.cache import CacheClient, _generate_iam_auth_token
from src.care_flagger import CareFlag, FlagType


class FakeRedis:
    """In-memory double, just enough of redis.Redis's surface for CacheClient."""

    def __init__(self, *args, **kwargs):
        self._store: dict[str, str] = {}

    def get(self, key):
        return self._store.get(key)

    def set(self, key, value, ex=None):
        self._store[key] = value


class BrokenRedis:
    def __init__(self, *args, **kwargs):
        pass

    def get(self, key):
        raise redis_module.RedisError("boom")

    def set(self, key, value, ex=None):
        raise redis_module.RedisError("boom")


def _flags():
    return [
        CareFlag(
            patient_id="p1",
            flag_type=FlagType.OVERDUE_FOLLOW_UP,
            detail="Heart failure (disorder): overdue.",
            source="rule:x",
        )
    ]


def test_disabled_when_no_host_configured():
    client = CacheClient(host=None)
    assert client.enabled is False
    assert client.get("any-key") is None
    client.set("any-key", "value")  # must not raise


def test_cache_key_is_stable_for_identical_flags():
    key_a = CacheClient.cache_key("p1", _flags())
    key_b = CacheClient.cache_key("p1", _flags())
    assert key_a == key_b


def test_cache_key_differs_for_different_patients():
    key_a = CacheClient.cache_key("p1", _flags())
    key_b = CacheClient.cache_key("p2", _flags())
    assert key_a != key_b


def test_get_set_round_trip(monkeypatch):
    monkeypatch.setattr(redis_module, "Redis", FakeRedis)
    client = CacheClient(host="localhost", port=6379)
    key = CacheClient.cache_key("p1", _flags())
    assert client.get(key) is None
    client.set(key, "a narrative")
    assert client.get(key) == "a narrative"


def test_redis_errors_degrade_to_cache_miss_not_an_exception(monkeypatch):
    monkeypatch.setattr(redis_module, "Redis", BrokenRedis)
    client = CacheClient(host="localhost", port=6379)
    assert client.get("some-key") is None
    client.set("some-key", "value")  # must not raise


def test_iam_token_raises_without_credentials(monkeypatch):
    # Patched at the source (Session.get_credentials), not via clearing env
    # vars: a local ~/.aws/credentials or profile can still supply
    # credentials even with AWS_* env vars unset, this isolates the "no
    # credentials at all" case regardless of the machine running the test.
    monkeypatch.setattr(Session, "get_credentials", lambda self: None)
    with pytest.raises(RuntimeError):
        _generate_iam_auth_token("carethread-cache", "carethread-app", "us-east-1")


def test_iam_token_is_a_signed_connect_url(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "fake-access-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fake-secret-key")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)

    token = _generate_iam_auth_token("carethread-cache", "carethread-app", "us-east-1")

    assert token.startswith("carethread-cache/")
    assert "Action=connect" in token
    assert "User=carethread-app" in token
    assert "X-Amz-Signature=" in token
