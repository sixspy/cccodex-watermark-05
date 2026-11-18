import threading

import pytest

from app.db import init_db
from app.services import (
    get_batch,
    list_void_snapshots,
    run_gap_report,
    stamp_batch,
    trace_downstream,
    void_batch,
)
from app.services.errors import ServiceError


def _stamped_batch_id(db_path):
    """种子里 ord-20261113-01 已是「已盖印」，水印 WM-ORD-131。"""
    from app.services import list_batches

    rows = list_batches(db_path=db_path)
    return next(b for b in rows if b["status"] == "已盖印")


def test_void_clears_watermark_and_returns_to_pending(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    b = _stamped_batch_id(db)
    assert b["watermark_value"] == "WM-ORD-131"

    out = void_batch(b["id"], operator="admin", db_path=db)

    # 同口径：状态回到待盖印，且库内水印真的被清空（不是仅展示变化）。
    assert out["status"] == "待盖印"
    assert out["watermark_value"] is None
    assert out["stamped_at"] is None

    again = get_batch(b["id"], db_path=db)
    assert again["status"] == "待盖印"
    assert again["watermark_value"] is None


def test_void_writes_snapshot_with_old_watermark(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    b = _stamped_batch_id(db)

    void_batch(b["id"], operator="admin", db_path=db)
    snaps = list_void_snapshots(b["id"], db_path=db)

    assert len(snaps) == 1
    snap = snaps[0]
    assert snap["watermark_snapshot"] == "WM-ORD-131"
    assert snap["cleared"] == 1
    assert snap["operator"] == "admin"
    # 快照里留痕的旧印，绝不能回写到 run_batches。
    live = get_batch(b["id"], db_path=db)
    assert live["watermark_value"] is None


def test_trace_touches_empty_after_void(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    b = _stamped_batch_id(db)

    before = trace_downstream("WM-ORD-131", db_path=db)
    assert before["sources"], "作废前应能摸到活印"

    void_batch(b["id"], operator="admin", db_path=db)

    # 硬验收：追索再摸必须摸空——sources/downstream 都不再含脏印。
    after = trace_downstream("WM-ORD-131", db_path=db)
    assert after["voided"] is True
    assert after["sources"] == []
    assert after["downstream"] == []
    assert after["void_snapshots"], "应返回作废快照摘要"
    assert "已作废清空" in after["void_summary"]


def test_double_void_second_rejected(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    b = _stamped_batch_id(db)

    void_batch(b["id"], db_path=db)
    with pytest.raises(ServiceError) as exc:
        void_batch(b["id"], db_path=db)
    assert exc.value.status_code == 409
    # 中文错误，不抛裸异常。
    assert exc.value.message


def test_void_only_allows_stamped(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    from app.services import list_batches

    pending = next(b for b in list_batches(db_path=db) if b["status"] == "待盖印")
    with pytest.raises(ServiceError) as exc:
        void_batch(pending["id"], db_path=db)
    assert exc.value.status_code == 409


def test_concurrent_double_void_only_one_succeeds(tmp_path):
    """两名调度齐点作废：无应用层锁，靠原子条件 UPDATE 保证只成一个。"""
    db = str(tmp_path / "t.db")
    init_db(db)
    b = _stamped_batch_id(db)
    results = []

    def worker():
        try:
            void_batch(b["id"], operator="scheduler", db_path=db)
            results.append("ok")
        except ServiceError as exc:
            results.append(f"err:{exc.status_code}")

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert sorted(results) == ["err:409", "ok"]
    live = get_batch(b["id"], db_path=db)
    assert live["status"] == "待盖印"
    assert live["watermark_value"] is None
    # 只有一条作废快照，没有重复/脏印。
    assert len(list_void_snapshots(b["id"], db_path=db)) == 1


def test_gap_report_counts_voided_as_pending(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    b = _stamped_batch_id(db)

    before = run_gap_report("2026-11-16", db_path=db)
    void_batch(b["id"], db_path=db)
    after = run_gap_report("2026-11-16", db_path=db)

    # 作废后回到待盖印：应盖印不变、已盖印减 1、缺口增 1（缺口不再跟着脏印漂）。
    assert after["expected_count"] == before["expected_count"]
    assert after["stamped_count"] == before["stamped_count"] - 1
    assert after["gap_count"] == before["gap_count"] + 1


def test_restamp_after_void_works(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    b = _stamped_batch_id(db)
    void_batch(b["id"], db_path=db)

    re = stamp_batch(b["id"], "WM-NEW-999", db_path=db)
    assert re["status"] == "已盖印"
    assert re["watermark_value"] == "WM-NEW-999"

    # 新印可追索，旧印依旧摸空。
    new_trace = trace_downstream("WM-NEW-999", db_path=db)
    assert new_trace["sources"]
    old_trace = trace_downstream("WM-ORD-131", db_path=db)
    assert old_trace["voided"] is True
    assert old_trace["sources"] == []
