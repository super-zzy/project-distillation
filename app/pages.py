from __future__ import annotations

from flask import Blueprint, Response

pages = Blueprint("pages", __name__)


@pages.get("/")
def home():
    html = """<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Project Distillation</title>
    <style>
      :root{
        --bg:#050711;
        --panel: rgba(255,255,255,.06);
        --stroke: rgba(255,255,255,.12);
        --text:#e7ecff;
        --muted:#9aa3c7;
        --accent:#7c5cff;
        --accent2:#22d3ee;
        --ok:#34d399;
        --warn:#fbbf24;
        --err:#fb7185;
      }
      body{
        margin:0;
        font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
        background:
          radial-gradient(1200px 700px at 20% 10%, rgba(124,92,255,.20), transparent 60%),
          radial-gradient(900px 600px at 80% 30%, rgba(34,211,238,.14), transparent 60%),
          radial-gradient(700px 500px at 50% 90%, rgba(52,211,153,.10), transparent 60%),
          var(--bg);
        color: var(--text);
      }
      .wrap{ max-width: 1100px; margin: 28px auto; padding: 0 18px; }
      .title{ display:flex; align-items:baseline; gap:10px; }
      .title h2{ margin:0; font-weight:700; letter-spacing:.3px; }
      .badge{ font-size:12px; color: var(--muted); border:1px solid var(--stroke); padding:4px 10px; border-radius:999px; background: rgba(255,255,255,.04);}
      .panel{
        margin-top: 14px;
        border: 1px solid var(--stroke);
        background: var(--panel);
        border-radius: 14px;
        padding: 14px;
        backdrop-filter: blur(10px);
        box-shadow: 0 10px 40px rgba(0,0,0,.35);
      }
      .row{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin: 10px 0; }
      .muted{ color: var(--muted); font-size: 12px; }
      input{
        flex: 1 1 680px;
        padding: 12px 12px;
        border-radius: 10px;
        border: 1px solid var(--stroke);
        background: rgba(0,0,0,.25);
        color: var(--text);
        outline: none;
      }
      input:focus{ border-color: rgba(124,92,255,.6); box-shadow: 0 0 0 3px rgba(124,92,255,.18); }
      button{
        padding: 11px 14px;
        border-radius: 10px;
        border: 1px solid var(--stroke);
        background: rgba(255,255,255,.06);
        color: var(--text);
        cursor:pointer;
        transition: transform .06s ease, background .15s ease, border-color .15s ease;
      }
      button:hover{ background: rgba(255,255,255,.10); border-color: rgba(255,255,255,.22); }
      button:active{ transform: translateY(1px); }
      button:disabled{ opacity:.45; cursor:not-allowed; }
      .btn-primary{ border-color: rgba(124,92,255,.55); background: rgba(124,92,255,.18); }
      .btn-primary:hover{ background: rgba(124,92,255,.24); }
      .statusbar{
        display:flex; flex-wrap:wrap; gap:10px; align-items:center;
        border: 1px solid var(--stroke);
        background: rgba(0,0,0,.22);
        border-radius: 12px;
        padding: 10px 12px;
      }
      .kv{ display:flex; gap:8px; align-items:baseline; }
      .k{ color: var(--muted); font-size: 12px; }
      .v{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace; font-size: 12px; }
      .pill{ padding: 3px 8px; border-radius:999px; border:1px solid var(--stroke); background: rgba(255,255,255,.04); }
      .pill.ok{ border-color: rgba(52,211,153,.45); }
      .pill.warn{ border-color: rgba(251,191,36,.45); }
      .pill.err{ border-color: rgba(251,113,133,.45); }
      pre{
        margin: 12px 0 0;
        background: rgba(0,0,0,.35);
        color: #d7e0ff;
        padding: 14px;
        border-radius: 14px;
        border: 1px solid rgba(255,255,255,.10);
        overflow: auto;
        min-height: 360px;
      }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="title">
        <h2>Project Distillation</h2>
        <span class="badge">Phase-1 • Multi-Agent • SSE</span>
      </div>
      <div class="panel">
        <div class="muted">输入本地 Git 项目路径（目录必须包含 `.git`）。不填则使用 `.env` 的 `PROJECT_PATH`。</div>
        <div class="row" style="margin-top:10px;">
          <input id="path" placeholder="D:/path/to/repo" />
          <button class="btn-primary" id="start">启动</button>
          <button id="pause" disabled>暂停</button>
          <button id="resume" disabled>恢复</button>
        </div>
        <div class="statusbar" style="margin-top:10px;">
          <div class="kv"><span class="k">task</span><span class="v" id="task">(none)</span></div>
          <div class="kv"><span class="k">status</span><span class="v pill" id="st">(unknown)</span></div>
          <div class="kv"><span class="k">phase</span><span class="v pill" id="ph">(unknown)</span></div>
          <div class="kv"><span class="k">operation</span><span class="v" id="op">(none)</span></div>
          <div class="kv"><span class="k">progress</span><span class="v" id="pg">0/0</span></div>
        </div>
        <pre id="log"></pre>
      </div>
    </div>
    <script>
      const logEl = document.getElementById('log');
      const taskEl = document.getElementById('task');
      const stEl = document.getElementById('st');
      const phEl = document.getElementById('ph');
      const opEl = document.getElementById('op');
      const pgEl = document.getElementById('pg');
      const startBtn = document.getElementById('start');
      const pauseBtn = document.getElementById('pause');
      const resumeBtn = document.getElementById('resume');
      let taskId = null;
      let lastId = 0;
      let es = null;

      function loadState() {
        try {
          taskId = localStorage.getItem('pd_task_id');
          const saved = localStorage.getItem('pd_last_id_' + taskId);
          lastId = saved ? parseInt(saved, 10) : 0;
        } catch (e) {}
      }

      function saveState() {
        try {
          if (taskId) localStorage.setItem('pd_task_id', taskId);
          if (taskId) localStorage.setItem('pd_last_id_' + taskId, String(lastId || 0));
        } catch (e) {}
      }

      function log(line) {
        logEl.textContent += line + "\\n";
        logEl.scrollTop = logEl.scrollHeight;
      }

      function setPill(el, text) {
        el.textContent = text || '(none)';
        el.classList.remove('ok','warn','err');
        const t = (text || '').toLowerCase();
        if (t.includes('running')) el.classList.add('ok');
        else if (t.includes('paused')) el.classList.add('warn');
        else if (t.includes('failed')) el.classList.add('err');
      }

      function updateStatus(t, lastMsg) {
        if (!t) return;
        setPill(stEl, t.status);
        setPill(phEl, t.phase);
        opEl.textContent = (t.message || lastMsg || '(none)');
        pgEl.textContent = `${t.progress.current}/${t.progress.total}`;
        pauseBtn.disabled = !(t.status === 'running' || t.status === 'queued');
        resumeBtn.disabled = !(t.status === 'paused');
      }

      function connect() {
        if (!taskId) return;
        if (es) es.close();
        saveState();
        es = new EventSource(`/api/progress/${taskId}?last_id=${lastId}`);
        es.addEventListener('event', (evt) => {
          const payload = JSON.parse(evt.data);
          lastId = payload.id || lastId;
          saveState();
          const t = payload.task;
          updateStatus(t, payload.message);
          log(`[${payload.level}] ${payload.message}`);
        });
        es.addEventListener('done', (evt) => {
          const payload = JSON.parse(evt.data);
          log(`DONE: status=${payload.status} error=${payload.error || ''}`);
          if (es) es.close();
          pauseBtn.disabled = true;
          resumeBtn.disabled = true;
        });
        es.onerror = () => {
          // auto-reconnect is built-in; keep log minimal
        };
      }

      async function attachMostRecent() {
        const resp = await fetch('/api/tasks/active');
        const data = await resp.json();
        if (!resp.ok) {
          log('ERROR: ' + JSON.stringify(data));
          return;
        }
        const tasks = data.tasks || [];
        if (!tasks.length) {
          log('No running task.');
          return;
        }
        // requirement: only one running task allowed; auto attach it if exists
        const running = tasks.find(t => t.status === 'running') || tasks[0];
        taskId = running.id;
        taskEl.textContent = taskId;
        const saved = localStorage.getItem('pd_last_id_' + taskId);
        lastId = saved ? parseInt(saved, 10) : 0;
        log('Attached to running task: ' + taskId + ' (last_id=' + lastId + ')');
        updateStatus(running, 'attached');
        connect();
      }

      startBtn.onclick = async () => {
        logEl.textContent = '';
        lastId = 0;
        const project_path = document.getElementById('path').value.trim();
        const body = project_path ? { project_path } : {};
        const resp = await fetch('/api/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        const data = await resp.json();
        if (!resp.ok) {
          if (resp.status === 409 && data.task_id) {
            taskId = data.task_id;
            taskEl.textContent = taskId;
            log('已有 running 任务，已附加：' + taskId);
            connect();
            return;
          }
          log('ERROR: ' + JSON.stringify(data));
          return;
        }
        taskId = data.task_id;
        taskEl.textContent = taskId;
        saveState();
        log('Task created: ' + taskId);
        setPill(stEl, 'queued');
        setPill(phEl, 'main');
        opEl.textContent = 'queued';
        connect();
      };

      pauseBtn.onclick = async () => {
        if (!taskId) return;
        await fetch(`/api/tasks/${taskId}/pause`, { method: 'POST' });
        log('Pause requested.');
      };

      resumeBtn.onclick = async () => {
        if (!taskId) return;
        await fetch(`/api/tasks/${taskId}/resume`, { method: 'POST' });
        log('Resume requested.');
        connect();
      };

      // Auto-attach on refresh / restart.
      window.addEventListener('load', async () => {
        loadState();
        await attachMostRecent();
      });
    </script>
  </body>
</html>"""
    return Response(html, mimetype="text/html; charset=utf-8")


@pages.get("/stream")
def stream_hint():
    return Response(
        "SSE endpoint is /api/progress/<task_id>. Create a task via POST /api/analyze first.",
        mimetype="text/plain; charset=utf-8",
        status=404,
    )


@pages.get("/cleanup")
def cleanup_page():
    html = """<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Task Cleanup</title>
    <style>
      :root{
        --bg:#050711; --panel: rgba(255,255,255,.06); --stroke: rgba(255,255,255,.12);
        --text:#e7ecff; --muted:#9aa3c7; --accent:#fb7185;
      }
      body{
        margin:0;
        font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
        background:
          radial-gradient(1000px 600px at 20% 10%, rgba(251,113,133,.18), transparent 60%),
          radial-gradient(900px 600px at 80% 30%, rgba(124,92,255,.14), transparent 60%),
          var(--bg);
        color: var(--text);
      }
      .wrap{ max-width: 980px; margin: 28px auto; padding: 0 18px; }
      .panel{
        margin-top: 14px;
        border: 1px solid var(--stroke);
        background: var(--panel);
        border-radius: 14px;
        padding: 16px;
        backdrop-filter: blur(10px);
        box-shadow: 0 10px 40px rgba(0,0,0,.35);
      }
      .muted{ color: var(--muted); font-size: 12px; }
      input{
        width: min(900px, 95vw);
        padding: 12px 12px;
        border-radius: 10px;
        border: 1px solid var(--stroke);
        background: rgba(0,0,0,.25);
        color: var(--text);
        outline: none;
      }
      input:focus{ border-color: rgba(251,113,133,.55); box-shadow: 0 0 0 3px rgba(251,113,133,.16); }
      button{
        padding: 11px 14px;
        border-radius: 10px;
        border: 1px solid rgba(251,113,133,.45);
        background: rgba(251,113,133,.12);
        color: var(--text);
        cursor:pointer;
      }
      button:disabled{ opacity:.45; cursor:not-allowed; }
      pre{
        margin: 12px 0 0;
        background: rgba(0,0,0,.35);
        color: #d7e0ff;
        padding: 14px;
        border-radius: 14px;
        border: 1px solid rgba(255,255,255,.10);
        overflow: auto;
        min-height: 240px;
      }
      label{ display:flex; gap:8px; align-items:center; margin-top:10px; }
      a{ color:#c7d2fe; text-decoration:none; }
    </style>
  </head>
  <body>
    <div class="wrap">
      <h2 style="margin:0;">Task Cleanup</h2>
      <div class="muted">危险操作：永久删除某个任务及其日志/AI 调用记录。不会删除项目级 commits/branches/MD 输出。</div>
      <div class="panel">
        <div class="muted">Task ID</div>
        <input id="taskId" placeholder="例如：4e2e84b334304110bff31b6ef2de1286" />
        <label class="muted"><input id="confirm" type="checkbox" /> 我确认要永久删除该任务相关数据</label>
        <div style="margin-top:10px; display:flex; gap:10px; flex-wrap:wrap;">
          <button id="purge" disabled>清除该任务数据</button>
          <a href="/">返回首页</a>
        </div>
        <pre id="out"></pre>
      </div>
    </div>
    <script>
      const taskIdEl = document.getElementById('taskId');
      const confirmEl = document.getElementById('confirm');
      const purgeBtn = document.getElementById('purge');
      const outEl = document.getElementById('out');

      function refreshState(){
        purgeBtn.disabled = !(confirmEl.checked && taskIdEl.value.trim().length > 6);
      }
      confirmEl.onchange = refreshState;
      taskIdEl.oninput = refreshState;

      purgeBtn.onclick = async () => {
        const taskId = taskIdEl.value.trim();
        outEl.textContent = 'Purging...\\n';
        const resp = await fetch(`/api/tasks/${taskId}/purge`, { method: 'DELETE' });
        const data = await resp.json().catch(() => ({}));
        outEl.textContent += 'HTTP ' + resp.status + '\\n' + JSON.stringify(data, null, 2) + '\\n';
      };
      refreshState();
    </script>
  </body>
</html>"""
    return Response(html, mimetype="text/html; charset=utf-8")

