(() => {
  const view = document.getElementById("view");
  const msgEl = document.getElementById("msg");
  let tab = "batches";
  let templates = [];
  let batches = [];
  let reports = [];
  let voidSnapshots = [];
  let selected = null;
  let stampValue = "";
  let traceValue = "WM-ORD-131";
  let traceResult = null;

  async function api(path, opts = {}) {
    const r = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    if (r.status === 401) {
      location.href = "/login";
      throw new Error("未登录");
    }
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
    return j;
  }

  function setMsg(t) {
    msgEl.textContent = t || "";
  }

  async function refresh() {
    const meta = await api("/api/meta");
    document.getElementById("lab-name").textContent = meta.lab_name || "血缘水印台";
    templates = (await api("/api/templates")).items || [];
    batches = (await api("/api/batches")).items || [];
    reports = (await api("/api/gap-reports")).items || [];
    voidSnapshots = (await api("/api/void-snapshots")).items || [];
  }

  function snapsOf(batchId) {
    return voidSnapshots
      .filter((s) => s.batch_id === batchId)
      .sort((a, b) => a.id - b.id);
  }

  function syncDock() {
    document.querySelectorAll(".dock [data-tab]").forEach((btn) => {
      btn.classList.toggle("on", btn.dataset.tab === tab);
    });
  }

  function renderTemplates() {
    return `
      <h2>水印模板</h2>
      <table>
        <thead><tr><th>表</th><th>列</th><th>版本</th><th>状态</th></tr></thead>
        <tbody>
          ${templates
            .map(
              (t) => `<tr>
            <td>${t.table_name}</td>
            <td>${t.column_name}</td>
            <td>${t.version_no}</td>
            <td><span class="chip">${t.status}</span></td>
          </tr>`
            )
            .join("")}
        </tbody>
      </table>`;
  }

  function renderBatches() {
    return `
      <h2>运行批次</h2>
      <p class="muted">主链：选批盖印 → 用水印追索下游 → 缺口对账；已盖印可作废，作废即清空库内水印并回到待盖印</p>
      <table>
        <thead><tr><th>编号</th><th>表</th><th>运行码</th><th>业务日</th><th>状态</th><th>水印</th><th></th></tr></thead>
        <tbody>
          ${batches
            .map((b) => {
              const snaps = snapsOf(b.id);
              const everVoided = snaps.length > 0;
              return `<tr>
            <td>${b.id}</td>
            <td>${b.table_name}</td>
            <td>${b.run_code}</td>
            <td>${b.biz_date}</td>
            <td>
              <span class="chip">${b.status}</span>
              ${everVoided ? `<span class="chip chip-void" title="该批次曾作废，旧印已清空">曾作废</span>` : ""}
            </td>
            <td>${b.watermark_value || "-"}</td>
            <td>${
              b.status === "待盖印"
                ? `<button type="button" class="ghost" data-pick="${b.id}">盖印</button>`
                : b.status === "已盖印"
                ? `<button type="button" class="danger" data-void="${b.id}">作废</button>`
                : ""
            }</td>
          </tr>`;
            })
            .join("")}
        </tbody>
      </table>
      ${renderVoidDetail()}
      ${
        selected
          ? `<div class="cardish">
        <h3>盖印</h3>
        <p>${selected.run_code} · ${selected.table_name}</p>
        <label>水印值<input id="stamp-input" value="${stampValue}" /></label>
        <button type="button" id="btn-stamp">写入盖印</button>
      </div>`
          : ""
      }`;
  }

  function renderVoidDetail() {
    if (!voidSnapshots.length) return "";
    const rows = [...voidSnapshots]
      .sort((a, b) => b.id - a.id)
      .map(
        (s) => `<tr>
          <td>${s.batch_id}</td>
          <td>${s.run_code}</td>
          <td><span class="chip chip-snapshot">${s.watermark_snapshot}</span></td>
          <td><span class="chip chip-cleared">已清空</span></td>
          <td>${s.operator || "-"}</td>
          <td>${s.created_at}</td>
        </tr>`
      )
      .join("");
    return `<div class="cardish void-detail">
      <h3>作废详情（旧印快照，库内活印已清空）</h3>
      <table>
        <thead><tr><th>批次</th><th>运行码</th><th>旧水印快照</th><th>库内水印</th><th>操作人</th><th>作废时间</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
  }

  function renderTrace() {
    const src = (traceResult && traceResult.sources) || [];
    const down = (traceResult && traceResult.downstream) || [];
    const voided = !!(traceResult && traceResult.voided);
    const voidSnaps = (traceResult && traceResult.void_snapshots) || [];
    return `
      <h2>下游追索</h2>
      <label>水印值<input id="trace-input" value="${traceValue}" placeholder="例如 WM-ORD-131" /></label>
      <div class="row"><button type="button" id="btn-trace">追索</button></div>
      ${
        traceResult && voided
          ? `<div class="cardish trace-void">
        <h3>追索进度</h3>
        <p><span class="chip chip-cleared">活印摸空</span></p>
        <p class="muted">${traceResult.void_summary || "该水印已作废清空，库内无活印。"}</p>
        <table>
          <thead><tr><th>运行码</th><th>表</th><th>旧水印快照</th><th>库内水印</th><th>作废时间</th></tr></thead>
          <tbody>
            ${voidSnaps
              .map(
                (s) => `<tr>
              <td>${s.run_code}</td>
              <td>${s.table_name}</td>
              <td><span class="chip chip-snapshot">${s.watermark_snapshot}</span></td>
              <td><span class="chip chip-cleared">已清空</span></td>
              <td>${s.created_at}</td>
            </tr>`
              )
              .join("")}
          </tbody>
        </table>
      </div>`
          : ""
      }
      ${
        traceResult && !voided
          ? `<div>
        <h3>源批次</h3>
        <ul>${src.map((s) => `<li>${s.run_code} · ${s.table_name}</li>`).join("")}</ul>
        <h3>下游</h3>
        <ul>${down
          .map(
            (d) =>
              `<li>${d.run_code} · ${d.status} · ${d.watermark_value || "未盖印"}</li>`
          )
          .join("")}</ul>
      </div>`
          : ""
      }`;
  }

  function renderGaps() {
    return `
      <h2>缺口对账</h2>
      <button type="button" id="btn-gap">生成对账</button>
      <table>
        <thead><tr><th>编号</th><th>截至</th><th>缺口</th><th>摘要</th></tr></thead>
        <tbody>
          ${reports
            .map(
              (r) => `<tr>
            <td>${r.id}</td>
            <td>${r.as_of_date}</td>
            <td>${r.gap_count}</td>
            <td>${r.summary}</td>
          </tr>`
            )
            .join("")}
        </tbody>
      </table>`;
  }

  function render() {
    if (tab === "templates") view.innerHTML = renderTemplates();
    else if (tab === "batches") view.innerHTML = renderBatches();
    else if (tab === "trace") view.innerHTML = renderTrace();
    else view.innerHTML = renderGaps();

    view.querySelectorAll("[data-pick]").forEach((btn) => {
      btn.onclick = () => {
        const id = Number(btn.dataset.pick);
        selected = batches.find((b) => b.id === id) || null;
        stampValue = selected ? "WM-" + selected.run_code.toUpperCase() : "";
        render();
      };
    });
    view.querySelectorAll("[data-void]").forEach((btn) => {
      btn.onclick = async () => {
        const id = Number(btn.dataset.void);
        const target = batches.find((b) => b.id === id);
        if (!target) return;
        if (!window.confirm(`确认作废 ${target.run_code}？将清空库内水印「${target.watermark_value || ""}」并回到待盖印。`)) {
          return;
        }
        setMsg("");
        try {
          const r = await api("/api/batches/" + id + "/void", { method: "POST" });
          selected = null;
          await refresh();
          const cleared = r.batch && r.batch.watermark_value === null;
          setMsg(
            cleared
              ? `作废完成：${target.run_code} 已清空水印并回到待盖印`
              : "作废返回异常，请核对库内水印"
          );
          render();
        } catch (e) {
          setMsg(e.message);
        }
      };
    });
    const stampInput = document.getElementById("stamp-input");
    if (stampInput) {
      stampInput.oninput = () => (stampValue = stampInput.value);
      document.getElementById("btn-stamp").onclick = async () => {
        setMsg("");
        try {
          await api("/api/batches/" + selected.id + "/stamp", {
            method: "POST",
            body: JSON.stringify({ watermark_value: stampValue }),
          });
          selected = null;
          await refresh();
          setMsg("盖印完成");
          render();
        } catch (e) {
          setMsg(e.message);
        }
      };
    }
    const traceInput = document.getElementById("trace-input");
    if (traceInput) {
      traceInput.oninput = () => (traceValue = traceInput.value);
      document.getElementById("btn-trace").onclick = async () => {
        setMsg("");
        try {
          traceResult = await api("/api/trace", {
            method: "POST",
            body: JSON.stringify({ watermark_value: traceValue }),
          });
          setMsg("追索完成");
          render();
        } catch (e) {
          setMsg(e.message);
        }
      };
    }
    const gapBtn = document.getElementById("btn-gap");
    if (gapBtn) {
      gapBtn.onclick = async () => {
        setMsg("");
        try {
          const r = await api("/api/gap-reports", {
            method: "POST",
            body: JSON.stringify({ as_of_date: "2026-11-16" }),
          });
          await refresh();
          setMsg(r.report.summary);
          render();
        } catch (e) {
          setMsg(e.message);
        }
      };
    }
  }

  document.querySelectorAll(".dock [data-tab]").forEach((btn) => {
    btn.onclick = () => {
      tab = btn.dataset.tab;
      syncDock();
      render();
    };
  });
  document.getElementById("btn-logout").onclick = () => {
    fetch("/api/logout", { method: "POST" }).then(() => (location.href = "/login"));
  };

  refresh()
    .then(() => {
      syncDock();
      render();
    })
    .catch((e) => setMsg(e.message));
})();
