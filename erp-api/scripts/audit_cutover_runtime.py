"""Read-only ERP target and ARQ queue audit without revealing credentials or args."""

import argparse
import hashlib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import redis
from arq.jobs import deserialize_job

from erp_api.core.config import Settings, get_settings


QUEUES = ("arq:queue", "arq:sample", "arq:daily-valid-creators")


def identity(raw: str) -> str:
    parsed = urlsplit(raw)
    return f"{parsed.hostname}:{parsed.port or ''}{parsed.path}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ecs-env", type=Path)
    args = parser.parse_args()
    settings = Settings(_env_file=args.ecs_env) if args.ecs_env else get_settings()
    print(f"DATABASE_TARGET={identity(settings.database_url)}")
    print(f"REDIS_TARGET={identity(settings.redis_url)}")
    print(
        f"OBJECT_TARGET={settings.object_storage_endpoint_url} "
        f"BUCKET={settings.object_storage_bucket} "
        f"PREFIX={settings.object_storage_key_prefix}"
    )
    client = redis.Redis.from_url(settings.redis_url, socket_timeout=5)
    client.ping()
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    for queue in QUEUES:
        members = client.zrange(queue, 0, -1, withscores=True)
        functions = Counter()
        missing = 0
        due = 0
        records = []
        for job_id, score in members:
            job_data = client.get(b"arq:job:" + job_id)
            if job_data is None:
                missing += 1
                continue
            job = deserialize_job(job_data)
            functions[job.function] += 1
            due += score <= now_ms
            records.append(
                (
                    hashlib.sha256(job_id).hexdigest()[:16],
                    job.function,
                    job.enqueue_time.isoformat(),
                    int(score),
                    str(job.args[1]) if job.function == "sync_sample_applications_job" and len(job.args) > 1 else "-",
                    str(job.args[2]) if job.function == "sync_sample_applications_job" and len(job.args) > 2 else "-",
                )
            )
        print(
            f"QUEUE={queue} COUNT={len(members)} DUE={due} "
            f"MISSING_PAYLOAD={missing} FUNCTIONS={dict(sorted(functions.items()))}"
        )
        for digest, function, queued_at, score, shop, mode in records:
            print(
                f"JOB_HASH={digest} FUNCTION={function} ENQUEUED={queued_at} "
                f"SCORE={score} SAMPLE_SHOP={shop} SAMPLE_MODE={mode}"
            )
    in_progress_keys = list(client.scan_iter(match="arq:in-progress:*"))
    print(f"IN_PROGRESS_KEYS={len(in_progress_keys)}")
    for key in in_progress_keys:
        job_id = key.removeprefix(b"arq:in-progress:")
        payload = client.get(b"arq:job:" + job_id)
        function = deserialize_job(payload).function if payload else "no_payload"
        print(
            f"IN_PROGRESS_JOB_HASH={hashlib.sha256(job_id).hexdigest()[:16]} "
            f"FUNCTION={function} TTL_SECONDS={client.ttl(key)}"
        )
    client.close()


if __name__ == "__main__":
    main()
