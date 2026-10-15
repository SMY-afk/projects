"""Download proven public CDN assets through a guarded browser with an intact CDN transport."""
import json
from datetime import UTC, datetime
from pathlib import Path

from scripts.affiliate_avatar_images import download_avatars


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value))
    temporary.replace(path)


async def download_pending(context, root: Path, *, batch_size=500):
    pending = []
    downloads = root / "downloads"
    saved = {}
    for state_path in root.glob("*/state.json"):
        label = state_path.parent.name
        if label != "local":
            continue
        state = json.loads(state_path.read_text())
        output = downloads / (label + ".json")
        images = json.loads(output.read_text()) if output.exists() else {}
        saved[label] = images
        for name, record in state["sources"].items():
            if name not in images and name not in state["images"]:
                pending.append(dict(record, sourceLabel=label))
    chosen = pending[:batch_size]
    if not chosen:
        return 0
    records = {r["name"]: r for r in chosen}
    completed = 0
    def on_image(name, image):
        nonlocal completed
        record = records[name]
        path = downloads / (record["sourceLabel"] + ".json")
        images = saved[record["sourceLabel"]]
        images[name] = dict(image, username=name, sourceIdentity=record["sourceIdentity"],
                            observedAt=record["observedAt"], storedAt=datetime.now(UTC).isoformat())
        completed += 1
        if completed % 12 == 0:
            write(path, images)
    failures = await download_avatars(context, chosen, root / "images", on_image)
    for label, images in saved.items():
        write(downloads / (label + ".json"), images)
    print(f"PUBLIC_AVATAR_POOL stored={len(chosen)-len(failures)} failures={len(failures)} pending={len(pending)-len(chosen)}", flush=True)
    return len(chosen) - len(failures)
