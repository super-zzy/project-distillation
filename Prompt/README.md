## Prompt 管理（第一阶段）

本目录用于集中管理三个 subAgent 与 AI（GLM-4.7）的交互提示词，按 **版本化 JSON** 文件维护，包含：

- **system_prompt**：系统角色设定
- **user_template**：用户提示词模板（包含变量占位符）
- **variables**：模板需要的变量清单（用于校验/渲染）
- **output_schema**：要求模型输出的 JSON 结构（用于解析与落库）

### 文件

- `commit_analysis.v1.json`：commitAgent 提示词与输出 schema
- `branch_analysis.v1.json`：branchAgent 提示词与输出 schema
- `project_summary.v1.json`：summaryAgent 提示词与输出 schema
- `prompt.schema.json`：Prompt 配置文件的通用 schema（用于校验 Prompt 文件格式）

### 模型输出约定

三个提示词都要求模型输出 **严格 JSON**：

```json
{
  "one_liner": "20~40字的一句话总结",
  "detail_md": "可直接写入 MD 的 Markdown 正文",
  "key_points": ["要点1", "要点2"]
}
```

其中：
- `one_liner`：必须存在，写入数据库与 MD 顶部
- `detail_md`：必须存在，写入 MD 的“详细分析”或“总结”主体
- `key_points`：可选，用于后续扩展（检索/标签/索引）

