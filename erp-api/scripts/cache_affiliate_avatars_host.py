"""Cache fresh public official avatars; run on the static web host with Pillow."""
import hashlib
import http.client
import io
import json
import os
import subprocess
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image

ROOT = Path("/opt/erp/affiliate-avatar-cache")
BASE = "https://example.invalid/configure-resource"
WEB = Path("/var/www/erp/assets/creator-avatars")
TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}
FORMATS = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP", "image/gif": "GIF"}


def allowed(url):
    parsed = urlsplit(url)
    try:
        return (parsed.scheme == "https" and not parsed.username and not parsed.password
                and parsed.port in (None, 443) and (parsed.hostname or "").endswith(
                    (".tiktokcdn-us.com", ".tiktokcdn.com", ".tiktokcdn-eu.com")))
    except ValueError:
        return False


class OfficialRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed(newurl):
            raise ValueError("untrusted_avatar_redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def decode_image(body, content_type):
    if content_type not in TYPES or not 32 < len(body) <= 2_000_000:
        raise ValueError("invalid_avatar_type_or_size")
    with Image.open(io.BytesIO(body)) as image:
        if image.format != FORMATS[content_type] or max(image.size) > 4096:
            raise ValueError("invalid_avatar_format_or_dimensions")
        image.verify()
    digest = hashlib.sha256(body).hexdigest()
    return digest + "." + TYPES[content_type], digest


def cache(record):
    try:
        if not allowed(record["url"]):
            raise ValueError("untrusted_avatar_origin")
        opener = urllib.request.build_opener(OfficialRedirects())
        with opener.open(record["url"], timeout=8) as response:
            if response.status != 200 or not allowed(response.url):
                raise ValueError("invalid_avatar_response")
            body, kind = response.read(2_000_001), response.headers.get_content_type()
        filename, digest = decode_image(body, kind)
        target = WEB / filename
        if target.exists():
            assert hashlib.sha256(target.read_bytes()).hexdigest() == digest
        else:
            temporary = WEB / (filename + f".{os.getpid()}.{threading.get_ident()}.tmp")
            temporary.write_bytes(body)
            temporary.chmod(0o644)
            try:
                temporary.replace(target)
            except (FileExistsError, PermissionError):
                if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                    raise
            finally:
                temporary.unlink(missing_ok=True)
        with urllib.request.urlopen(BASE + filename, timeout=10) as public:
            assert public.status == 200 and public.headers.get_content_type() == kind
            assert hashlib.sha256(public.read()).hexdigest() == digest
        return dict(record, file=filename, sha256=digest, bytes=len(body), contentType=kind), None
    except (OSError, ValueError, AssertionError, http.client.HTTPException, Image.DecompressionBombError) as error:
        return None, type(error).__name__


def run(*args):
    result = subprocess.run(args, capture_output=True, timeout=180, check=False)
    if result.returncode:
        raise RuntimeError("avatar_cache_child_failed")
    return result.stdout


def main():
    WEB.mkdir(parents=True, exist_ok=True)
    run("docker", "cp", str(ROOT / "export_uncached_affiliate_avatars.py"),
        "erp-ecs-api-1:/tmp/export_uncached_affiliate_avatars.py")
    records = json.loads(run("docker", "exec", "erp-ecs-api-1", "/opt/venv/bin/python",
                             "/tmp/export_uncached_affiliate_avatars.py"))
    if not records:
        summary = {"cached": 0, "failed": 0, "noFreshUncachedAvatars": True,
                   "checkedAt": datetime.now(UTC).isoformat()}
        (ROOT / "last-run.json").write_text(json.dumps(summary))
        print(json.dumps(summary), flush=True)
        return
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(cache, records))
    verified = [image for image, error in results if image]
    summary = {"cached": len(verified), "failed": len(records) - len(verified)}
    if verified:
        batch_id = hashlib.sha256(json.dumps(verified, sort_keys=True).encode()).hexdigest()[:16]
        folder = ROOT / "batches" / batch_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "batch.json").write_text(json.dumps({"batchId": batch_id, "imagesValidated": True, "records": verified}))
        (folder / "batch.json").chmod(0o600)
        (folder / "assets-receipt.json").write_text(json.dumps({"batchId": batch_id,
            "images": len({r["file"] for r in verified}), "publicHttpsVerified": True}))
        path = "/tmp/affiliate-avatar-cache-" + batch_id
        run("docker", "exec", "erp-ecs-api-1", "mkdir", "-p", path)
        for source in [folder / "batch.json", folder / "assets-receipt.json", ROOT / "publish_batch.py"]:
            run("docker", "cp", str(source), "erp-ecs-api-1:" + path + "/" + source.name)
        run("docker", "exec", "erp-ecs-api-1", "/opt/venv/bin/python", path + "/publish_batch.py")
        receipt = json.loads(run("docker", "exec", "erp-ecs-api-1", "/opt/venv/bin/python", path + "/publish_batch.py", "--apply"))
        for source, target in [("avatar-backup-" + batch_id + ".json", "avatar-backup.json"),
                               ("receipt-" + batch_id + ".json", "receipt.json")]:
            run("docker", "cp", "erp-ecs-api-1:" + path + "/" + source, str(folder / target))
            (folder / target).chmod(0o600)
        summary.update(updated=receipt["updated"], concurrentChanges=receipt["concurrentChanges"], batchId=batch_id)
    summary["checkedAt"] = datetime.now(UTC).isoformat()
    (ROOT / "last-run.json").write_text(json.dumps(summary))
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
