"""Copy pending ARQ jobs to ECS Redis without deleting the local queue."""

import argparse
import subprocess
from urllib.parse import unquote, urlsplit

import redis


def require(condition: bool, code: str) -> None:
    if not condition:
        raise SystemExit(code)


def target_client() -> redis.Redis:
    result = subprocess.run(
        [
            "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=8", "erp-ecs",
            "grep '^REDIS_URL=' /etc/erp/erp-api.env",
        ],
        capture_output=True,
        check=True,
        timeout=15,
    )
    line = result.stdout.decode().strip()
    require(line.startswith("REDIS_URL="), "STOP_TARGET_URL")
    parsed = urlsplit(line.split("=", 1)[1])
    require(parsed.hostname == "127.0.0.1" and parsed.port == 6379, "STOP_TARGET_HOST")
    return redis.Redis(
        host="127.0.0.1",
        port=16379,
        username=unquote(parsed.username) if parsed.username else None,
        password=unquote(parsed.password) if parsed.password else None,
        db=int(parsed.path.lstrip("/") or "0"),
        socket_connect_timeout=5,
        socket_timeout=5,
    )


def pending_jobs(source: redis.Redis) -> dict[bytes, list[tuple[bytes, float]]]:
    queues: dict[bytes, list[tuple[bytes, float]]] = {}
    for key in source.scan_iter(match="arq:*", count=500):
        if source.type(key) != b"zset":
            continue
        jobs = source.zrange(key, 0, -1, withscores=True)
        if jobs:
            queues[key] = jobs
    return queues


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    source = redis.Redis(host="127.0.0.1", port=6379, db=0, socket_timeout=5)
    target = target_client()
    try:
        require(source.ping() and target.ping(), "STOP_REDIS_PING")
        queues = pending_jobs(source)
        locks = list(source.scan_iter(match="arq:in-progress:*", count=500))
        total = sum(len(jobs) for jobs in queues.values())
        print(f"ARQ_PREFLIGHT QUEUES={len(queues)} JOBS={total} LOCKS={len(locks)}")
        require(not locks, "STOP_ARQ_IN_PROGRESS")
        copied = verified = 0
        for queue, jobs in sorted(queues.items()):
            require(target.type(queue) in (b"none", b"zset"), "STOP_TARGET_QUEUE_TYPE")
            for job_id, score in jobs:
                payload_key = b"arq:job:" + job_id
                payload = source.get(payload_key)
                ttl = source.pttl(payload_key)
                require(payload is not None and ttl > 0, "STOP_SOURCE_JOB_MISSING")
                existing = target.get(payload_key)
                target_score = target.zscore(queue, job_id)
                require(existing is None or existing == payload, "STOP_TARGET_JOB_CONFLICT")
                require(target_score is None or target_score == score, "STOP_TARGET_SCORE_CONFLICT")
                if args.apply:
                    if existing is None:
                        require(target.set(payload_key, payload, px=ttl, nx=True), "STOP_TARGET_SET")
                        copied += 1
                    target.zadd(queue, {job_id: score}, nx=True)
                    require(target.get(payload_key) == payload, "STOP_TARGET_READBACK")
                    require(target.zscore(queue, job_id) == score, "STOP_TARGET_QUEUE_READBACK")
                    verified += 1
        if args.apply:
            print(f"ARQ_COPY_OK COPIED={copied} VERIFIED={verified} SOURCE_UNCHANGED")
        else:
            print(f"ARQ_CHECK_OK JOBS={total} NO_REDIS_WRITES")
    finally:
        source.close()
        target.close()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as error:
        raise SystemExit(f"STOP_ARQ_COPY TYPE={type(error).__name__}") from None
