from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from animetta.services.bilibili.api import fetch_comments


@pytest.mark.asyncio
async def test_fetch_comments_resolves_bvid_to_numeric_aid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeVideo:
        def __init__(self, *, bvid: str) -> None:
            assert bvid == "BV1test"

        def get_aid(self) -> int:
            return 12345

    def get_comments(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        assert kwargs["oid"] == 12345
        return {
            "replies": [
                {
                    "content": {"message": "useful comment"},
                    "like": 7,
                    "rcount": 2,
                    "ctime": 123,
                }
            ]
        }

    fake_comment = SimpleNamespace(
        CommentResourceType=SimpleNamespace(VIDEO="video"),
        OrderType=SimpleNamespace(LIKE="like"),
        get_comments=get_comments,
    )
    fake_bilibili_api = SimpleNamespace(
        video=SimpleNamespace(Video=FakeVideo),
        comment=fake_comment,
        sync=lambda value: value,
    )
    monkeypatch.setitem(sys.modules, "bilibili_api", fake_bilibili_api)

    comments = await fetch_comments("BV1test", max_count=5, min_likes=2)

    assert captured["oid"] == 12345
    assert comments == [
        {
            "content": "useful comment",
            "likes": 7,
            "replies": 2,
            "publish_time": "123",
        }
    ]
