"""Redis cache for LLM narrative generations, with ElastiCache IAM auth.

Caches `narrative.generate_narrative`'s output keyed by a hash of the
patient's flags (not patient_id alone: two calls for the same patient
only hit the cache if the underlying flags are actually identical,
correct behavior for a follow-up visit that changes what's flagged).
TTL bounded (`CARETHREAD_CACHE_TTL_SECONDS`, default 1 hour) rather
than cached forever, a stale narrative describing yesterday's flags is
a correctness bug in a care-coordination note, worse than the
duplicate LLM call the cache exists to avoid.

## IAM auth, not a plain password

ElastiCache for Redis supports IAM authentication: a "user" is created
with `--authentication-mode Type=iam` (no password), and the connecting
client signs a throwaway request with its own IAM credentials, SigV4,
the same signature scheme every AWS API call uses, and passes the
resulting presigned URL as Redis's `AUTH` password. There's no SDK
helper for this the way `rds.generate_db_auth_token` exists for RDS,
`_generate_iam_auth_token` below builds it by hand from `botocore`'s
`RequestSigner`, following AWS's documented ElastiCache IAM-auth
approach: sign a fake `GET https://<replication-group-id>/?Action=
connect&User=<user>` request, never actually sent, whose signed query
string is exactly what Redis's `AUTH` accepts.

## Why this is unit-tested but not integration-tested against Floci

`aws elasticache create-replication-group` against Floci returns a real
`ConfigurationEndpoint` (verified: `localhost:6379`, `Status: available`
immediately) and genuinely provisions the control-plane resource this
module's Terraform declares. But nothing is actually listening on that
port, `redis.Redis(host="localhost", port=6379).ping()` against it
raises `ConnectionRefused`, confirmed by hand. Floci emulates
ElastiCache's control plane (the same category of gap Task 1's Lambda
`publish` versioning and Task 9's SSM parameter ARNs hit), not a real
Redis data plane. `CacheClient` is instead verified against a real
local Redis (`docker run -p 6379:6379 redis`, see task-2/README.md) for
actual cache hit/miss behavior, and `_generate_iam_auth_token` is
tested for producing a well-formed, correctly-signed presigned URL,
the part that's genuinely testable without a real IAM-auth-enabled
ElastiCache cluster, which only exists on real AWS.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from urllib.parse import urlencode

import redis
from botocore.awsrequest import AWSRequest
from botocore.session import Session

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 3600


def _generate_iam_auth_token(
    replication_group_id: str, user_id: str, region: str
) -> str:
    session = Session()
    credentials = session.get_credentials()
    if credentials is None:
        raise RuntimeError(
            "No AWS credentials available to sign an ElastiCache IAM auth token."
        )

    query = urlencode({"Action": "connect", "User": user_id})
    url = f"https://{replication_group_id}/?{query}"
    request = AWSRequest(method="GET", url=url)

    from botocore.auth import SigV4QueryAuth

    auth = SigV4QueryAuth(credentials, "elasticache", region, expires=900)
    auth.add_auth(request)

    # Redis's AUTH command takes the token without the scheme, matching
    # AWS's documented format for this exact mechanism.
    return request.url.removeprefix("https://")


class CacheClient:
    """Wraps a redis-py connection; every method degrades to a cache
    miss (never raises) if the cache is unreachable, so a Redis outage
    never blocks a `/flag` request, only makes it slower (a fresh LLM
    call instead of a cache hit)."""

    def __init__(
        self,
        host: str | None = None,
        port: int = 6379,
        iam_user: str | None = None,
        replication_group_id: str | None = None,
        region: str = "us-east-1",
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self.enabled = bool(host)
        self.ttl_seconds = ttl_seconds
        self._client: redis.Redis | None = None

        if not self.enabled:
            return

        auth_kwargs: dict = {}
        if iam_user and replication_group_id:
            try:
                token = _generate_iam_auth_token(
                    replication_group_id, iam_user, region
                )
                auth_kwargs = {"username": iam_user, "password": token}
            except Exception:
                logger.warning(
                    "Failed to generate ElastiCache IAM auth token, "
                    "connecting without AUTH.",
                    exc_info=True,
                )

        self._client = redis.Redis(
            host=host,
            port=port,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            **auth_kwargs,
        )

    @staticmethod
    def cache_key(patient_id: str, flags: list) -> str:
        flag_fingerprint = json.dumps(
            sorted((f.flag_type.value, f.detail) for f in flags)
        )
        digest = hashlib.sha256(flag_fingerprint.encode()).hexdigest()[:16]
        return f"carethread:narrative:{patient_id}:{digest}"

    def get(self, key: str) -> str | None:
        if not self.enabled or self._client is None:
            return None
        try:
            return self._client.get(key)
        except redis.RedisError:
            logger.warning("Cache GET failed, treating as a miss.", exc_info=True)
            return None

    def set(self, key: str, value: str) -> None:
        if not self.enabled or self._client is None:
            return
        try:
            self._client.set(key, value, ex=self.ttl_seconds)
        except redis.RedisError:
            logger.warning("Cache SET failed, continuing without caching.", exc_info=True)


def build_cache_client_from_env() -> CacheClient:
    return CacheClient(
        host=os.environ.get("CARETHREAD_REDIS_HOST"),
        port=int(os.environ.get("CARETHREAD_REDIS_PORT", "6379")),
        iam_user=os.environ.get("CARETHREAD_REDIS_IAM_USER"),
        replication_group_id=os.environ.get("CARETHREAD_REDIS_REPLICATION_GROUP_ID"),
        region=os.environ.get("AWS_REGION", "us-east-1"),
        ttl_seconds=int(
            os.environ.get("CARETHREAD_CACHE_TTL_SECONDS", str(DEFAULT_TTL_SECONDS))
        ),
    )
