# Multi-Model Router - OpenClaw Skill

自动路由AI请求到**本地Ollama模型**（免费）或**云端模型**（按需），帮你大幅节省云端token消耗，延长订阅寿命。

## 功能

- ✨ 自动优先使用本地Ollama模型，免费不花钱
- 🔄 本地不可用时自动降级到云端备份
- 💾 请求缓存，重复问题直接返回，避免重复消耗
- 📊 token用量和成本统计
- 支持多家云端服务商（Ollama/OpenRouter/Anthropic/Together AI/火山引擎）

## 适用场景

- 你有本地Ollama运行环境
- 购买了云端模型的token套餐，想省着用
- 希望简单问答免费，复杂任务再上云端

## 安装

在OpenClaw中：
```
claw install model-router
```

手动安装：
```
cd skills
git clone <repo-url>
```

## 使用

见 [SKILL.md](./SKILL.md) 详细说明。

## 节省效果

日常使用可节省 **70%~80%** 的云端token消耗，让你的订阅用更久。

## License

MIT
