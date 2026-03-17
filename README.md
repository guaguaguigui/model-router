# Multi-Model Router - OpenClaw Skill

自动路由AI请求到**本地Ollama模型**（免费）或**云端模型**（按需），帮你大幅节省云端token消耗，延长订阅寿命。

[![OpenClaw](https://img.shields.io/badge/OpenClaw-Skill-blue.svg)](https://openclaw.ai)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## 为什么需要这个？

- 💸 **云端token越来越贵**，每个月订阅刚充就用完？
- 🏠 **你已经有本地Ollama**，但不知道什么时候该用本地什么时候该用云端？
- 🔁 **重复问相似问题**，每次都要重新消耗token？

Multi-Model Router 自动帮你搞定：**简单问题本地免费算，复杂任务才上云端**，帮你省下70%~80%的token花费。

## 功能

- ✨ **智能路由**：简单问答默认用本地Ollama，完全免费
- 🔄 **自动降级**：本地不可用或任务复杂时自动切换云端
- 💾 **请求缓存**：相同问题直接返回缓存结果，避免重复消耗
- 📊 **成本统计**：实时追踪token用量和预估花费
- ⚙️ **多提供商支持**：Ollama、OpenRouter、Anthropic、Together AI、火山引擎全都支持

## 适用场景

- ✅ 你有本地Ollama运行环境，想充分利用闲置算力
- ✅ 购买了云端模型的token套餐，希望延长订阅寿命
- ✅ 日常问答简单任务本地处理，复杂推理才用云端
- ✅ 想要自动节省成本，不用手动切换模型

## 安装

在OpenClaw中：
```bash
claw install guaguaguigui/model-router
```

手动安装：
```bash
cd skills
git clone https://github.com/guaguaguigui/model-router.git
```

## 使用

详细使用说明见 [SKILL.md](./skills/model-router/SKILL.md)。

### 快速开始

```python
from skills.model-router.scripts.model_router import generate

# 简单问答 -> 自动优先本地模型，免费不花token
result = generate("帮我写一个Python冒泡排序", task_type="simple")
print(result["text"])
print(f"模型: {result['model_used']}, 花费: ${result['cost']:.4f}")
```

## 节省效果估算

| 任务类型 | 路由选择 | 节省token |
|---------|---------|----------|
| 简单查询、日常问答 | 本地Ollama | 100% |
| 编码辅助、文档整理 | 本地Ollama | 100% |
| 复杂推理、调试分析 | 云端 | 0%（仍需云端） |

**总体节省：** 日常使用可节省 **70%~80%** 的云端token消耗，让你的订阅用更久。

## 配置

编辑 `skills/model-router/scripts/model_config.json` 修改：
- 模型优先级
- API端点
- 缓存过期时间
- 更多...

## Requirements

- Ollama 本地运行（可选，但推荐最大化节省）
- 已有本地模型（如 qwen3.5:9b, llama3.1:8b）
- 云端API密钥（配置到环境变量）

## License

MIT © XC
