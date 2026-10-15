"""Cache verified official avatar bytes through the already authenticated shop browser."""
import base64
import hashlib
import os
import threading
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}
SUFFIXES = (".tiktokcdn-us.com", ".tiktokcdn.com", ".tiktokcdn-eu.com")
FETCH = """async (items) => Promise.all(items.map(async item => {
  try {
    const response = await fetch(item.url, {credentials:'omit', signal:AbortSignal.timeout(8000)});
    const type = (response.headers.get('content-type') || '').split(';')[0];
    if(response.status!==200) return {name:item.name,error:'http_'+response.status};
    const buffer = await response.arrayBuffer();
    if(buffer.byteLength < 32 || buffer.byteLength > 2000000) return {name:item.name,error:'size'};
    const bytes = new Uint8Array(buffer);
    let value='';
    for(let i=0;i<bytes.length;i+=8192) value+=String.fromCharCode(...bytes.subarray(i,i+8192));
    return {name:item.name,type,url:response.url,data:btoa(value)};
  } catch (_) { return {name:item.name,error:'request_failed'}; }
}))"""


def official_avatar_url(url):
    parsed = urlsplit(url)
    return (parsed.scheme == "https" and not parsed.username and not parsed.password
            and parsed.port in (None, 443) and (parsed.hostname or "").endswith(SUFFIXES))


def store_image(folder: Path, body: bytes, content_type: str):
    if content_type not in TYPES or not 32 < len(body) <= 2_000_000:
        raise ValueError("Avatar image type or size is invalid")
    signatures = {"image/jpeg": body.startswith(b"\xff\xd8") and body.endswith(b"\xff\xd9"),
                  "image/png": body.startswith(b"\x89PNG\r\n\x1a\n"),
                  "image/webp": body.startswith(b"RIFF") and body[8:12] == b"WEBP",
                  "image/gif": body.startswith((b"GIF87a", b"GIF89a"))}
    if not signatures[content_type]:
        raise ValueError("Avatar bytes do not match the image type")
    digest = hashlib.sha256(body).hexdigest()
    filename = digest + "." + TYPES[content_type]
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / filename
    if not target.exists():
        temporary = folder / (filename + f".{os.getpid()}.{threading.get_ident()}.tmp")
        temporary.write_bytes(body)
        try:
            temporary.replace(target)
        except (FileExistsError, PermissionError):
            if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise
        finally:
            temporary.unlink(missing_ok=True)
    return {"file": filename, "sha256": digest, "bytes": len(body), "contentType": content_type}


async def download_avatars(context, records, folder, on_image):
    groups = defaultdict(list)
    for record in records:
        if official_avatar_url(record["url"]):
            groups[urlsplit(record["url"]).hostname].append(record)
    page = await context.new_page()
    failures = []
    redirect_hosts = set()
    try:
        for group in groups.values():
            response = await page.goto(group[0]["url"], wait_until="commit", timeout=15_000)
            if not response or response.status != 200:
                failures.extend({"name": r["name"], "error": "origin_unavailable"} for r in group)
                continue
            for offset in range(0, len(group), 12):
                results = await page.evaluate(FETCH, group[offset:offset + 12])
                for result in results:
                    if result.get("error"):
                        failures.append({"name": result["name"], "error": result["error"]})
                        continue
                    if not official_avatar_url(result["url"]):
                        host = urlsplit(result["url"]).hostname or "unknown"
                        if host not in redirect_hosts:
                            print(f"AVATAR_REDIRECT_SKIPPED host={host}", flush=True)
                            redirect_hosts.add(host)
                        failures.append({"name": result["name"], "error": "redirect_host"})
                        continue
                    try:
                        image = store_image(folder, base64.b64decode(result["data"], validate=True), result["type"])
                    except (ValueError, OSError):
                        failures.append({"name": result["name"], "error": "invalid_image"})
                        continue
                    on_image(result["name"], image)
    finally:
        await page.close()
    return failures
