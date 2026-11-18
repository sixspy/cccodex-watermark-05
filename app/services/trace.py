from app.db import get_db
from app.services.errors import ServiceError


def trace_downstream(watermark_value: str, db_path: str | None = None) -> dict:
    value = (watermark_value or "").strip()
    if not value:
        raise ServiceError("水印值不能为空")
    with get_db(db_path) as conn:
        sources = conn.execute(
            "SELECT * FROM run_batches WHERE watermark_value=? ORDER BY id",
            (value,),
        ).fetchall()
        # 作废后旧印在 run_batches 必为空，这里只能摸到活印；摸不到再查作废快照。
        void_snapshots = conn.execute(
            "SELECT * FROM void_snapshots WHERE watermark_snapshot=? ORDER BY id",
            (value,),
        ).fetchall()

        if not sources:
            if void_snapshots:
                snaps = [dict(s) for s in void_snapshots]
                latest = snaps[-1]
                return {
                    "watermark_value": value,
                    "sources": [],
                    "edges": [],
                    "downstream": [],
                    "voided": True,
                    "void_snapshots": snaps,
                    "void_summary": (
                        f"旧水印 {value} 已作废清空，库内无活印；"
                        f"最近作废于 {latest['created_at']}（批次 {latest['run_code']}），"
                        "追索只命中作废快照，未返回任何盖印来源"
                    ),
                }
            raise ServiceError("未找到该水印值的盖印批次", 404)

        codes = [s["run_code"] for s in sources]
        placeholders = ",".join("?" for _ in codes)
        edges = conn.execute(
            f"SELECT * FROM lineage_edges WHERE upstream_run_code IN ({placeholders})",
            codes,
        ).fetchall()
        down_codes = sorted({e["downstream_run_code"] for e in edges})
        downstream = []
        if down_codes:
            ph2 = ",".join("?" for _ in down_codes)
            downstream = [
                dict(r)
                for r in conn.execute(
                    f"SELECT * FROM run_batches WHERE run_code IN ({ph2}) ORDER BY id",
                    down_codes,
                ).fetchall()
            ]
        return {
            "watermark_value": value,
            "sources": [dict(s) for s in sources],
            "edges": [dict(e) for e in edges],
            "downstream": downstream,
            "voided": False,
            "void_snapshots": [],
            "void_summary": None,
        }
