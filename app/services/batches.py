from app.db import get_db
from app.services.errors import ServiceError


def list_batches(db_path: str | None = None, status: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM run_batches WHERE status=? ORDER BY id",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM run_batches ORDER BY id"
            ).fetchall()
        return [dict(r) for r in rows]


def get_batch(batch_id: int, db_path: str | None = None) -> dict | None:
    with get_db(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM run_batches WHERE id=?", (batch_id,)
        ).fetchone()
        return dict(row) if row else None


def stamp_batch(
    batch_id: int,
    watermark_value: str,
    db_path: str | None = None,
) -> dict:
    value = (watermark_value or "").strip()
    if not value:
        raise ServiceError("水印值不能为空")
    with get_db(db_path) as conn:
        batch = conn.execute(
            "SELECT * FROM run_batches WHERE id=?", (batch_id,)
        ).fetchone()
        if not batch:
            raise ServiceError("批次不存在", 404)
        if batch["status"] == "已盖印":
            raise ServiceError("批次已盖印", 409)
        if batch["status"] != "待盖印":
            raise ServiceError("仅待盖印批次可盖印", 409)
        tpl = conn.execute(
            "SELECT * FROM watermark_templates WHERE table_name=? AND status='现行'",
            (batch["table_name"],),
        ).fetchone()
        if not tpl:
            raise ServiceError("无现行水印模板", 409)
        conn.execute(
            "UPDATE run_batches SET status='已盖印', watermark_value=?, "
            "stamped_at=datetime('now') WHERE id=?",
            (value, batch_id),
        )
        row = conn.execute(
            "SELECT * FROM run_batches WHERE id=?", (batch_id,)
        ).fetchone()
        return dict(row)


def list_void_snapshots(
    batch_id: int | None = None,
    db_path: str | None = None,
) -> list[dict]:
    """作废快照（旧印留痕）。可按批次过滤。"""
    with get_db(db_path) as conn:
        if batch_id is None:
            rows = conn.execute(
                "SELECT * FROM void_snapshots ORDER BY id"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM void_snapshots WHERE batch_id=? ORDER BY id",
                (batch_id,),
            ).fetchall()
        return [dict(r) for r in rows]


def void_batch(
    batch_id: int,
    operator: str | None = None,
    db_path: str | None = None,
) -> dict:
    """
    作废一个已盖印批次（提交瞬间清空口径，全程同一事务）：
      1. 读出批次，校验存在且为「已盖印」；
      2. 原子条件 UPDATE：仅当仍为「已盖印」时，把状态改回「待盖印」，
         同时把 watermark_value、stamped_at 置空——状态与空值同口径落库；
      3. rowcount=0 说明已被并发作废/改态，抛 409，绝不留脏印；
      4. 旧水印先快照入 void_snapshots（留痕但不再是活印）。
    """
    with get_db(db_path) as conn:
        batch = conn.execute(
            "SELECT * FROM run_batches WHERE id=?", (batch_id,)
        ).fetchone()
        if not batch:
            raise ServiceError("批次不存在", 404)
        if batch["status"] == "待盖印":
            raise ServiceError("批次已是待盖印状态，无需作废", 409)
        if batch["status"] != "已盖印":
            raise ServiceError("仅已盖印批次可作废", 409)

        old_watermark = batch["watermark_value"]
        old_stamped_at = batch["stamped_at"]
        if not old_watermark:
            # 同口径护栏：已盖印却没有水印属于数据不一致，拒绝继续。
            raise ServiceError("该批次缺少水印值，状态与水印不一致，已拦截作废", 409)

        # 原子条件更新：并发双作废时只有一个事务 rowcount 为 1。
        cur = conn.execute(
            "UPDATE run_batches SET status='待盖印', watermark_value=NULL, "
            "stamped_at=NULL WHERE id=? AND status='已盖印'",
            (batch_id,),
        )
        if cur.rowcount != 1:
            raise ServiceError("该批次已被处理，请刷新后重试", 409)

        conn.execute(
            "INSERT INTO void_snapshots(batch_id, run_code, table_name, "
            "watermark_snapshot, stamped_at, operator, cleared) "
            "VALUES (?,?,?,?,?,?,1)",
            (
                batch_id,
                batch["run_code"],
                batch["table_name"],
                old_watermark,
                old_stamped_at,
                operator,
            ),
        )

        row = conn.execute(
            "SELECT * FROM run_batches WHERE id=?", (batch_id,)
        ).fetchone()
        result = dict(row)
        # 落库后同口径复核：作废态（回到待盖印）与水印空值必须一致。
        if result["status"] != "待盖印" or result["watermark_value"] is not None:
            raise ServiceError("作废后状态与水印空值不一致，已回滚", 500)
        return result
