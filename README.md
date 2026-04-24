## Project Distillation (multi-agent)

基于 **Python + Flask + MySQL** 的多 Agent 项目，用 AI 分析本地开源项目（含 `.git`）的 **branch/commit 演进**，把长期开发思路蒸馏成可复用的输出（MD 知识库 + 数据库记录）。

### 快速开始

- **1) 安装依赖**

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
```

- **2) 配置环境变量**

复制 `.env.example` 为 `.env` 并填写：

- MySQL 连接信息
- AI 接口信息（GLM-4.7）

- **3) 初始化数据库**

```bash
python -m app.init_db
```

- **4) 启动服务**

```bash
python -m app.server
```

### Web API

- **启动分析任务**：`POST /api/analyze`
  - body: `{ "project_path": "D:/path/to/repo" }`
- **SSE 获取进度**：`GET /api/progress/<task_id>`
- **暂停任务**：`POST /api/tasks/<task_id>/pause`
- **恢复任务**：`POST /api/tasks/<task_id>/resume`

### 输出目录（MD 知识库）

默认在 `OUTPUT_ROOT`（默认 `./distilled`）下生成：

```text
<projectName>/
├── 00_索引与模板/
│   ├── README.md
│   ├── index.md
│   └── templates/
├── 01_commit/
├── 02_branch/
└── 03_summary/
    └── summary.md
```

