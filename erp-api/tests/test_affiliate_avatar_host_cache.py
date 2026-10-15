import io

import pytest
from PIL import Image

from scripts.cache_affiliate_avatars_host import (
    OfficialRedirects,
    allowed,
    decode_image,
)


@pytest.mark.parametrize("url", ["http://p16.tiktokcdn-us.com/a.png",
    "https://p16.tiktokcdn-us.com.evil.example/a.png", "https://user@p16.tiktokcdn-us.com/a.png",
    "https://p16.tiktokcdn-us.com:8443/a.png", "https://nginx-nc.ziniao.com/a.png"])
def test_rejects_untrusted_origins(url):
    assert not allowed(url)


def test_decodes_original_avatar_and_preserves_bytes_hash():
    import hashlib
    buffer = io.BytesIO()
    Image.new("RGB", (20, 20), "blue").save(buffer, format="PNG")
    body = buffer.getvalue()
    name, digest = decode_image(body, "image/png")
    assert digest == hashlib.sha256(body).hexdigest()
    assert name == digest + ".png"


def test_rejects_mislabeled_or_broken_image():
    with pytest.raises(ValueError):
        decode_image(b"not an image" * 10, "text/html")
    buffer = io.BytesIO()
    Image.new("RGB", (20, 20)).save(buffer, format="PNG")
    with pytest.raises(ValueError):
        decode_image(buffer.getvalue(), "image/jpeg")


def test_blocks_redirect_before_following_external_host():
    with pytest.raises(ValueError, match="untrusted_avatar_redirect"):
        OfficialRedirects().redirect_request(None, None, 302, "", {}, "https://example.com/avatar.png")


def test_simultaneous_identical_download_keeps_verified_existing_file(tmp_path, monkeypatch):
    from pathlib import Path

    from scripts.affiliate_avatar_images import store_image
    buffer = io.BytesIO()
    Image.new("RGB", (20, 20)).save(buffer, format="PNG")
    body = buffer.getvalue()

    def concurrent_write(source, target):
        target.write_bytes(body)
        raise PermissionError("Another thread published the identical file")

    monkeypatch.setattr(Path, "replace", concurrent_write)
    record = store_image(tmp_path, body, "image/png")
    assert (tmp_path / record["file"]).read_bytes() == body
    assert not list(tmp_path.glob("*.tmp"))
