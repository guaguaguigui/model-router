---
name: Multi-Model Router
description: 自动路由AI请求到本地Ollama模型或云端模型，最大程度节省云端token消耗。支持缓存、降级、成本统计。
---

# Multi-Model Router

自动路由AI请求到**本地Ollama模型**（免费）或**云端模型**（按需），根据任务类型自动选择最优方案，显著减少云端token消耗，延长订阅寿命。

## 特点

- ✨ **优先本地**：简单任务默认用本地Ollama，不消耗云端token
- 🔄 **自动降级**：本地不可用时自动切换到云端备份
- 💾 **请求缓存**：相同问题直接返回缓存结果，避免重复消耗
- 📊 **成本统计**：追踪token用量和预估花费
- ⚙️ **多提供商**：支持Ollama、OpenRouter、Anthropic、Together AI、火山引擎

## 目录结构

```
model-router/
├── SKILL.md              # 本文档
├── scripts/
│   ├── model_router.py   # 主程序
│   └── model_config.json # 配置文件
├── references/           # 额外参考文档
└── assets/              # 静态资源
```

## 使用方法

### Python API

```python
from scripts.model_router import generate

# 简单问答 -> 自动优先本地模型
result = generate("帮我写一个Python冒泡排序", task_type="simple")
print(result["text"])
print(f"模型: {result['model_used']}, 花费: ${result['cost']:.4f}")

# 复杂任务 -> 强制云端
result = generate("帮我调试这个复杂的生产环境bug", task_type="complex")
```

### 命令行测试

```bash
cd skills/model-router
python scripts/model_router.py
```

### 配置

编辑 `scripts/model_config.json` 修改模型优先级、API端点、缓存时间等。

## 集成到OpenClaw

OpenClaw核心可以通过以下方式使用本技能：

```python
from skills.model-router.scripts.model_router import get_router, generate
```

## 节省效果估算

| 任务类型 | 路由选择 | 节省token |
|---------|---------|----------|
| 简单查询、日常问答 | 本地Ollama | 100% |
| 编码辅助、文档整理 | 本地Ollama | 100% |
| 复杂推理、调试分析 | 云端 | 0%（仍需云端） |

**总体节省：** 日常使用可节省 **70%~80%** 的云端token消耗，显著延长订阅时长。

## 要求

- Ollama 本地运行（可选，但推荐）
- 已有本地模型（如 qwen3.5:9b）
- 云端API密钥（配置到环境变量）
