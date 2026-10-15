"""Build isolated local ERP worker overrides for RDS, OSS and ECS Redis."""

import io
import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import dotenv_values


PRIVATE_RDS = "pgm-wz9bb45790nb73dc.pg.rds.aliyuncs.com"
PUBLIC_RDS = "pgm-wz9bb45790nb73dcso.pg.rds.aliyuncs.com"
CA = Path(__file__).resolve().parents[1] / "var/certs/ApsaraDB-CA-Chain.pem"
TUNNEL_PORT = 16379
STORAGE_KEYS = (
    "OBJECT_STORAGE_ENDPOINT_URL",
    "OBJECT_STORAGE_REGION",
    "OBJECT_STORAGE_ACCESS_KEY",
    "OBJECT_STORAGE_SECRET_KEY",
    "OBJECT_STORAGE_BUCKET",
    "OBJECT_STORAGE_KEY_PREFIX",
    "OBJECT_STORAGE_FORCE_PATH_STYLE",
)


def ecs_values() -> dict[str, str]:
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "erp-ecs", "grep -E '^([A-Z0-9_]+)=' /etc/erp/erp-api.env"],
        capture_output=True, check=True, timeout=15,
    )
    return dict(dotenv_values(stream=io.StringIO(result.stdout.decode())))


def replace_host_port(raw: str, host: str, port: int) -> str:
    parsed = urlsplit(raw)
    if not parsed.hostname or not parsed.path:
        raise ValueError("CUTOVER_URL_INVALID")
    userinfo = parsed.netloc.rsplit("@", 1)[0] + "@" if "@" in parsed.netloc else ""
    return urlunsplit(parsed._replace(netloc=f"{userinfo}{host}:{port}"))


def build_environment() -> dict[str, str]:
    values = ecs_values()
    database = urlsplit(values.get("DATABASE_URL", ""))
    redis_url = urlsplit(values.get("REDIS_URL", ""))
    if (
        database.hostname != PRIVATE_RDS
        or database.path != "/wj_erp"
        or redis_url.hostname != "127.0.0.1"
        or redis_url.port != 6379
        or values.get("OBJECT_STORAGE_BUCKET") != "wjvedio"
        or values.get("OBJECT_STORAGE_KEY_PREFIX") != "erp/"
        or not CA.is_file()
    ):
        raise ValueError("CUTOVER_TARGET_IDENTITY_MISMATCH")
    if any(not values.get(key) for key in STORAGE_KEYS):
        raise ValueError("CUTOVER_STORAGE_CONFIG_INCOMPLETE")
    env = os.environ.copy()
    env["DATABASE_URL"] = replace_host_port(values["DATABASE_URL"], PUBLIC_RDS, 5432)
    env["REDIS_URL"] = replace_host_port(values["REDIS_URL"], "127.0.0.1", TUNNEL_PORT)
    env.update({key: values[key] for key in STORAGE_KEYS})
    env["PGSSLMODE"] = "verify-full"
    env["PGSSLROOTCERT"] = str(CA)
    return env
