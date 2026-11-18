import pytest


@pytest.mark.asyncio
async def test_void_endpoint_clears_live_watermark(authed):
    items = (await (await authed.get("/api/batches")).json())["items"]
    target = next(b for b in items if b["status"] == "已盖印")
    old_wm = target["watermark_value"]

    r = await authed.post(f"/api/batches/{target['id']}/void")
    assert r.status == 200
    body = await r.json()
    assert body["ok"] is True
    assert body["batch"]["status"] == "待盖印"
    assert body["batch"]["watermark_value"] is None
    assert body["void_snapshots"][0]["watermark_snapshot"] == old_wm

    # 批次列表里库内水印确为空（不是只改了芯片）。
    after_items = (await (await authed.get("/api/batches")).json())["items"]
    after = next(b for b in after_items if b["id"] == target["id"])
    assert after["watermark_value"] is None
    assert after["status"] == "待盖印"


@pytest.mark.asyncio
async def test_void_detail_carries_cleared_chip_data(authed):
    items = (await (await authed.get("/api/batches")).json())["items"]
    target = next(b for b in items if b["status"] == "已盖印")
    await authed.post(f"/api/batches/{target['id']}/void")

    detail = await (await authed.get(f"/api/batches/{target['id']}")).json()
    assert detail["batch"]["ever_voided"] is True
    snap = detail["void_snapshots"][0]
    assert snap["cleared"] == 1
    assert snap["watermark_snapshot"]

    listing = await (await authed.get("/api/void-snapshots")).json()
    assert any(s["batch_id"] == target["id"] for s in listing["items"])


@pytest.mark.asyncio
async def test_double_void_returns_chinese_conflict(authed):
    items = (await (await authed.get("/api/batches")).json())["items"]
    target = next(b for b in items if b["status"] == "已盖印")

    first = await authed.post(f"/api/batches/{target['id']}/void")
    assert first.status == 200
    second = await authed.post(f"/api/batches/{target['id']}/void")
    assert second.status == 409
    body = await second.json()
    assert body["ok"] is False
    # 出错回中文。
    assert body["error"] and all(ord(c) > 127 for c in body["error"])


@pytest.mark.asyncio
async def test_trace_returns_snapshot_summary_after_void(authed):
    items = (await (await authed.get("/api/batches")).json())["items"]
    target = next(b for b in items if b["status"] == "已盖印")
    old_wm = target["watermark_value"]
    await authed.post(f"/api/batches/{target['id']}/void")

    r = await authed.post("/api/trace", json={"watermark_value": old_wm})
    assert r.status == 200
    body = await r.json()
    assert body["voided"] is True
    assert body["sources"] == []
    assert body["downstream"] == []
    assert body["void_snapshots"]
    assert old_wm in body["void_summary"]


@pytest.mark.asyncio
async def test_void_requires_auth(client):
    r = await client.post("/api/batches/1/void")
    assert r.status == 401
