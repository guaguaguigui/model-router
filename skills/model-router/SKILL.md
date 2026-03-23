---
name: Multi-Model Router
description: 自动路由AI请求到本地Ollama模型→免费大模型→云端模型，三级路由最大程度节省云端token消耗。支持智能分类、缓存、降级、每日收益统计。
---

# Multi-Model Router

自动路由AI请求到**本地Ollama模型**（免费）→ **免费云端大模型** → **付费云端模型**，根据任务类型自动选择最优方案，最大程度节省云端token消耗，延长订阅寿命。

## 特点

- ✨ **三级路由策略**：本地优先 → 免费云端降级 → 付费云端保底，最大化节省
- 🧠 **智能任务分类**：自动识别简单/复杂任务，无需手动指定类型
- 🔄 **自动降级**：优先级模型不可用时自动切换下一级可用模型
- 💾 **请求缓存**：相同问题直接返回缓存结果，避免重复消耗token
- 📊 **详细统计**：追踪每日节省、累计成本节约，支持自动收益监控
- 🚨 **API配额监控**：实时跟踪API调用次数，支持多级告警，提前预警避免突然耗尽中断
- ⚙️ **多提供商**：支持Ollama、智谱AI GLM-4.7-Flash（30B免费）、OpenRouter、火山引擎

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

# 自动分类+路由
result = generate("你的问题")
print(f"使用模型: {result['model_used']}, 花费: ${result['cost']:.4f}")

# 获取每日收益报告
router = get_router()
print(router.get_earnings_summary())
```

## 路由优先级

路由按以下优先级尝试：

1. **本地Ollama** → 完全免费，0消耗，优先使用
2. **智谱AI GLM-4.7-Flash** → 官方免费，30B参数，无需信用卡，作为免费降级
3. **付费云端** → 只有前两级都不可用时才使用，最小化消耗

## 智能任务分类

自动根据问题内容分类：
- 包含"调试"、"开发"、"设计"、"代码" → 标记为复杂任务
- 包含短问题、查询类关键词 → 标记为简单任务
- 超过200字符自动偏向复杂分类

即使分类错误，也只会影响初始选择，不影响结果正确性。

## 获取每日收益报告

```python
from skills.model-router.scripts.model_router import get_router
router = get_router()
report = router.get_earnings_summary()
print(report)
```

输出示例：
```
💰 Multi-Model Router 每日收益报告
日期: 2026-03-19
今日节省: $0.1234
累计节省: $1.2345
预计月节省: $36.50

请求分布:
  总请求: 125
  缓存命中: 23
  本地处理: 78
  免费云处理: 15
  付费云处理: 9
总节省token: 45,230
```

## API配额监控

Multi-Model Router 内置完整的API配额监控系统，防止配额耗尽突然中断：

### 查看配额状态

```python
from skills.model-router.scripts.model_router import get_router
router = get_router()
print(router.get_quota_summary())
```

输出示例：
```
[API 配额监控]

[+] volcengine: 正常 剩余 15200/18000 (84.4%)
    今日使用: 124/1200
    本周使用: 2800/9000
[+] zhipu: OK - 无限制 (已用 0)

[OK] 所有API配额正常，无告警
```

### 告警机制

- **警告阈值**: 剩余 15% 时发出警告
- **紧急阈值**: 剩余 5% 时发出紧急告警
- **冷却机制**: 警告每6小时提醒一次，紧急每1小时提醒一次，避免骚扰
- **自动切换**: 配额耗尽后自动切换到低优先级可用模型，不会中断服务

### 配置配额

```python
from skills.model-router.scripts.model_router import get_router
router = get_router()
# 配置volcengine每月18000次请求限额
router.configure_provider_quota(
    "volcengine", 
    monthly_total=18000,
    weekly_limit=9000,
    daily_limit=1200,
    reset_cycle="monthly",
    warning_threshold=0.15,
    critical_threshold=0.05
)
```

## 节省效果估算

| 任务类型 | 路由选择 | 节省token |
|---------|---------|----------|
| 简单查询、日常问答 | 本地Ollama | 100% |
| 编码辅助、文档整理 | 本地Ollama | 100% |
| 复杂推理、调试分析 | 云端 | 0%（仍需云端） |

**总体节省：** 日常使用可节省 **70%~80%** 的云端token消耗，显著延长订阅时长。

## 要求

- **可选但推荐**：Ollama 本地运行 + 本地模型（如 qwen3.5:9b）
- **可选免费降级**：智谱AI API密钥（注册即可免费使用 GLM-4.7-Flash，无需信用卡）
- **保底**：付费云端API密钥（配置到环境变量）

## 环境变量配置

配置以下环境变量：
- `ZHIPU_API_KEY` - 智谱AI API密钥（免费GLM-4.7-Flash）
- `VOLCENGINE_API_KEY` - 火山引擎API密钥（付费保底）
- 其他提供商对应配置可在`model_config.json`中添加

## 项目目标

本项目旨在：
1. **最大限度节省云端token消耗**，延长订阅寿命
2. **通过节省赚token续费** - 节省的成本转化为收益后可为模型路由续期
3. **推广免费大模型方案** - 让更多人可以零成本使用大模型
