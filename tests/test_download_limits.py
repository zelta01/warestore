import io

import pytest

from warestore.infrastructure.persistence.download import (
    DownloadTooLargeError,
    download_limited,
    read_limited,
)


class _Response(io.BytesIO):
    def __init__(self, data: bytes, content_length: str | None = None):
        super().__init__(data)
        self.headers = {}
        if content_length is not None:
            self.headers["Content-Length"] = content_length


def test_read_limited_rejects_stream_larger_than_limit():
    with pytest.raises(DownloadTooLargeError):
        read_limited(_Response(b"12345"), 4)


def test_download_refuses_to_overwrite_existing_partial(tmp_path):
    destination = tmp_path / "download.part"
    destination.write_bytes(b"keep")

    with pytest.raises(FileExistsError):
        download_limited(
            "https://example.test/file",
            str(destination),
            timeout=1,
            max_bytes=100,
            opener=lambda _url, timeout: _Response(b"replacement", "11"),
        )

    assert destination.read_bytes() == b"keep"
