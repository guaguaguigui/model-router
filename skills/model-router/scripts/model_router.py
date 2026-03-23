# Multi-Model Router for OpenClaw
# 自动路由请求到本地/云端模型，节省token消耗
# Copyright © 2026 XC

import os
import json
import hashlib
import time
import requests
import re
from typing import Dict, Tuple, Optional, Any, List
from datetime import datetime, timedelta

# Configuration
MODEL_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "model_config.json")
CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
LOG_FILE = os.path.join(os.path.dirname(__file__), "model_router.log")
STATS_FILE = os.path.join(os.path.dirname(__file__), "usage_stats.json")
QUOTA_FILE = os.path.join(os.path.dirname(__file__), "api_quota.json")

# Default configuration (if no config file exists)
DEFAULT_MODEL = {
    "name": "qwen3.5:9b",
    "type": "local",
    "endpoint": "http://localhost:11434/api/generate",
    "provider": "ollama"
}

BACKUP_MODELS = [
    {
        "name": "qwen3.5:9b",
        "type": "local",
        "endpoint": "http://localhost:11434/api/generate",
        "provider": "ollama",
        "priority": 1
    },
    {
        "name": "glm-4-flash",
        "type": "cloud-free",
        "provider": "zhipu",
        "endpoint": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "api_key_env": "ZHIPU_API_KEY",
        "priority": 2
    },
    {
        "name": "volcengine:ark-code-latest",
        "type": "cloud",
        "provider": "volcengine",
        "endpoint": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
        "api_key_env": "VOLCENGINE_API_KEY",
        "priority": 3
    }
]

# Caching
CACHE_TTL = 3600  # 1 hour cache
CACHE_MAX_SIZE_MB = 100

# Retry
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2

# Cost estimation (per 1K tokens) - 单位 USD
COST_ESTIMATE = {
    "qwen3.5:9b": 0.0,
    "gpt-4o-mini": 0.08,
    "claude-3-haiku": 0.25,
    "volcengine:ark-code-latest": 0.1,
    "glm-4-flash": 0.0  # 智谱AI GLM-4.7-Flash 官方免费
}

# API Quota alerts - 当剩余配额低于这些阈值时发出警告
QUOTA_WARNING_THRESHOLD = 0.15  # 15% 剩余时警告
QUOTA_CRITICAL_THRESHOLD = 0.05  # 5% 剩余时紧急警告

# Task classification keywords for auto-detection
SIMPLE_TASK_KEYWORDS = [
    "什么", "如何", "怎么", "解释", "说明", "帮忙", "简单", "查询",
    "what", "how", "explain", "help", "simple", "query", "what's", "how to"
]

COMPLEX_TASK_KEYWORDS = [
    "调试", "优化", "重构", "设计", "开发", "架构", "分析", "解决",
    "复杂", "debug", "optimize", "refactor", "design", "develop", 
    "architecture", "analyze", "complex", "problem", "implement"
]


class ModelRouter:
    def __init__(self, config_path: str = None):
        self.config_path = config_path or MODEL_CONFIG_FILE
        self.config = self.load_config()
        self.ensure_cache_dir()
        self.quota_config = self.load_quota_config()
    
    def load_quota_config(self) -> Dict:
        """Load API quota configuration from file"""
        if os.path.exists(QUOTA_FILE):
            with open(QUOTA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        # Default quota configuration based on TOOLS.md
        return {
            "providers": {
                "volcengine": {
                    "monthly_total": 18000,
                    "monthly_used": 0,
                    "weekly_limit": 9000,
                    "weekly_used": 0,
                    "daily_limit": 1200,  # 5h = 1200
                    "daily_used": 0,
                    "reset_cycle": "monthly",
                    "last_reset": datetime.now().isoformat(),
                    "warning_threshold": QUOTA_WARNING_THRESHOLD,
                    "critical_threshold": QUOTA_CRITICAL_THRESHOLD,
                    "enabled": True
                },
                "zhipu": {
                    "monthly_total": float('inf'),  # 智谱免费无限制
                    "monthly_used": 0,
                    "enabled": True
                }
            },
            "alerts": {
                "last_warning": None,
                "last_critical": None,
                "warning_cooldown_hours": 6,  # 警告冷却时间
                "critical_cooldown_hours": 1
            }
        }
    
    def save_quota_config(self):
        """Save quota configuration to file"""
        with open(QUOTA_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.quota_config, f, indent=2, ensure_ascii=False)
    
    def check_and_reset_quota(self):
        """Check if quota needs to be reset based on cycle"""
        now = datetime.now()
        providers = self.quota_config.get("providers", {})
        
        for provider_name, quota in providers.items():
            cycle = quota.get("reset_cycle")
            if not cycle:
                continue
                
            last_reset = datetime.fromisoformat(quota.get("last_reset", now.isoformat()))
            
            need_reset = False
            if cycle == "daily":
                if now.date() > last_reset.date():
                    need_reset = True
            elif cycle == "weekly":
                # Reset on Monday
                if now.isocalendar().week != last_reset.isocalendar().week:
                    need_reset = True
            elif cycle == "monthly":
                if now.month != last_reset.month or now.year != last_reset.year:
                    need_reset = True
            
            if need_reset:
                if "daily_used" in quota:
                    quota["daily_used"] = 0
                if "weekly_used" in quota:
                    quota["weekly_used"] = 0
                if "monthly_used" in quota:
                    quota["monthly_used"] = 0
                quota["last_reset"] = now.isoformat()
                self.log(f"Quota reset for {provider_name} ({cycle} cycle)")
        
        self.save_quota_config()
    
    def record_api_call(self, provider: str):
        """Record an API call for quota tracking"""
        self.check_and_reset_quota()
        
        providers = self.quota_config.get("providers", {})
        if provider not in providers:
            return
        
        quota = providers[provider]
        
        # Increment usage counters
        if "daily_used" in quota:
            quota["daily_used"] += 1
        if "weekly_used" in quota:
            quota["weekly_used"] += 1
        if "monthly_used" in quota:
            quota["monthly_used"] += 1
        
        self.save_quota_config()
    
    def get_quota_status(self, provider: str) -> Dict:
        """Get current quota status for a provider"""
        self.check_and_reset_quota()
        
        providers = self.quota_config.get("providers", {})
        if provider not in providers:
            return {"available": True, "status": "unknown"}
        
        quota = providers[provider]
        if not quota.get("enabled", True):
            return {"available": False, "status": "disabled"}
        
        monthly_total = quota.get("monthly_total", float('inf'))
        if monthly_total == float('inf'):
            return {"available": True, "status": "unlimited", "remaining": float('inf')}
        
        monthly_used = quota.get("monthly_used", 0)
        remaining = monthly_total - monthly_used
        remaining_ratio = remaining / monthly_total if monthly_total > 0 else 0
        
        warning_threshold = quota.get("warning_threshold", QUOTA_WARNING_THRESHOLD)
        critical_threshold = quota.get("critical_threshold", QUOTA_CRITICAL_THRESHOLD)
        
        status = "ok"
        available = True
        
        if remaining_ratio <= critical_threshold:
            status = "critical"
            available = False if remaining <= 0 else True
        elif remaining_ratio <= warning_threshold:
            status = "warning"
        
        return {
            "available": available,
            "status": status,
            "total": monthly_total,
            "used": monthly_used,
            "remaining": remaining,
            "remaining_ratio": remaining_ratio,
            "daily_used": quota.get("daily_used", 0),
            "weekly_used": quota.get("weekly_used", 0)
        }
    
    def should_alert(self, status: str) -> bool:
        """Check if we should send an alert based on cooldown"""
        alerts = self.quota_config.get("alerts", {})
        now = datetime.now()
        
        last_warning = alerts.get("last_warning")
        last_critical = alerts.get("last_critical")
        warning_cooldown = timedelta(hours=alerts.get("warning_cooldown_hours", 6))
        critical_cooldown = timedelta(hours=alerts.get("critical_cooldown_hours", 1))
        
        if status == "critical":
            if not last_critical:
                alerts["last_critical"] = now.isoformat()
                self.save_quota_config()
                return True
            last_dt = datetime.fromisoformat(last_critical)
            if now - last_dt >= critical_cooldown:
                alerts["last_critical"] = now.isoformat()
                self.save_quota_config()
                return True
        
        if status == "warning":
            if not last_warning:
                alerts["last_warning"] = now.isoformat()
                self.save_quota_config()
                return True
            last_dt = datetime.fromisoformat(last_warning)
            if now - last_dt >= warning_cooldown:
                alerts["last_warning"] = now.isoformat()
                self.save_quota_config()
                return True
        
        return False
    
    def is_provider_available(self, provider: str) -> bool:
        """Check if provider has available quota"""
        status = self.get_quota_status(provider)
        return status["available"]
    
    def configure_provider_quota(self, provider: str, total: int, **kwargs):
        """Configure quota for a provider"""
        providers = self.quota_config.get("providers", {})
        if provider not in providers:
            providers[provider] = {}
        
        providers[provider]["monthly_total"] = total
        providers[provider]["monthly_used"] = 0
        providers[provider]["last_reset"] = datetime.now().isoformat()
        providers[provider]["enabled"] = True
        
        for key, value in kwargs.items():
            providers[provider][key] = value
        
        self.save_quota_config()
        
    def load_config(self) -> Dict:
        """Load configuration from file or use defaults"""
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {
            "default_model": DEFAULT_MODEL,
            "backup_models": BACKUP_MODELS,
            "cache_ttl": CACHE_TTL,
            "max_retries": MAX_RETRIES
        }
    
    def save_config(self):
        """Save current configuration"""
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)
    
    def ensure_cache_dir(self):
        """Create cache directory if it doesn't exist"""
        if not os.path.exists(CACHE_DIR):
            os.makedirs(CACHE_DIR)
    
    def check_model_health(self, model: Dict) -> bool:
        """Check if a model is available"""
        try:
            provider = model["provider"]
            
            # Check quota first
            if provider in self.quota_config.get("providers", {}):
                if not self.is_provider_available(provider):
                    self.log(f"Model {model['name']} is out of quota for {provider}")
                    return False
            
            if model["provider"] == "ollama":
                # Check Ollama health - just test base URL
                base_url = model["endpoint"].split("/api")[0]
                endpoint = f"{base_url}/api/tags"
                resp = requests.get(endpoint, timeout=5)
                return resp.status_code == 200
            elif model.get("api_key_env"):
                # Check if API key is set in environment
                return os.environ.get(model["api_key_env"]) is not None
            return True
        except Exception as e:
            self.log(f"Health check failed for {model['name']}: {str(e)}")
            return False
    
    def get_cached_response(self, prompt: str, model_name: str) -> Tuple[Optional[Any], bool]:
        """Get cached response if exists and not expired"""
        cache_key = hashlib.md5(f"{prompt}{model_name}".encode()).hexdigest()[:16]
        cache_path = os.path.join(CACHE_DIR, f"{cache_key}.json")
        
        if not os.path.exists(cache_path):
            return None, False
        
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                cached = json.load(f)
            
            # Check if expired
            if time.time() - cached.get("timestamp", 0) > self.config.get("cache_ttl", CACHE_TTL):
                os.remove(cache_path)
                return None, False
            
            return cached.get("response"), True
        except Exception as e:
            self.log(f"Cache read error: {str(e)}")
            return None, False
    
    def cache_response(self, prompt: str, model_name: str, response: Any):
        """Cache a response"""
        cache_key = hashlib.md5(f"{prompt}{model_name}".encode()).hexdigest()[:16]
        cache_path = os.path.join(CACHE_DIR, f"{cache_key}.json")
        
        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "prompt": prompt,
                    "model": model_name,
                    "response": response,
                    "timestamp": time.time()
                }, f, ensure_ascii=False)
        except Exception as e:
            self.log(f"Cache write error: {str(e)}")
    
    def auto_classify_task(self, prompt: str) -> str:
        """Automatically classify task type based on content"""
        prompt_lower = prompt.lower()
        
        # Count keyword matches for complex tasks
        complex_score = sum(1 for kw in COMPLEX_TASK_KEYWORDS if kw in prompt_lower)
        simple_score = sum(1 for kw in SIMPLE_TASK_KEYWORDS if kw in prompt_lower)
        
        # Longer prompts (> 200 chars) are more likely complex
        if len(prompt) > 200:
            complex_score += 1
        
        # Code tasks are usually complex
        if '```' in prompt or 'def ' in prompt or 'function ' in prompt or '#include' in prompt:
            complex_score += 2
        
        if complex_score >= simple_score:
            return "complex"
        else:
            return "simple"
    
    def load_stats(self) -> Dict:
        """Load usage statistics from file"""
        if os.path.exists(STATS_FILE):
            try:
                with open(STATS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.log(f"Failed to load stats: {str(e)}")
        
        # Default empty stats
        return {
            "total_requests": 0,
            "cached_requests": 0,
            "local_requests": 0,
            "free_cloud_requests": 0,
            "paid_cloud_requests": 0,
            "total_tokens_prompt": 0,
            "total_tokens_completion": 0,
            "total_cost_saved": 0.0,
            "daily_stats": {}
        }
    
    def save_stats(self):
        """Save current usage statistics"""
        stats = self.load_stats()
        try:
            with open(STATS_FILE, 'w', encoding='utf-8') as f:
                json.dump(stats, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.log(f"Failed to save stats: {str(e)}")
    
    def record_usage(self, model: Dict, response: Dict, cached: bool):
        """Record usage for statistics"""
        stats = self.load_stats()
        
        stats["total_requests"] += 1
        
        if cached:
            stats["cached_requests"] += 1
        
        # Categorize by model type
        if model["type"] == "local":
            stats["local_requests"] += 1
        elif model["type"] == "cloud-free":
            stats["free_cloud_requests"] += 1
        elif model["type"] == "cloud":
            stats["paid_cloud_requests"] += 1
        
        # Accumulate tokens
        tokens_prompt = response.get("tokens_prompt", 0)
        tokens_completion = response.get("tokens_completion", 0)
        stats["total_tokens_prompt"] += tokens_prompt
        stats["total_tokens_completion"] += tokens_completion
        
        # Calculate cost saved (if we used paid cloud instead)
        # Assume average cost 0.1 per 1K tokens for paid cloud
        if model["type"] in ["local", "cloud-free"]:
            total_tokens = tokens_prompt + tokens_completion
            cost_saved = (total_tokens / 1000) * 0.1
            stats["total_cost_saved"] += cost_saved
        
        # Daily statistics
        today = time.strftime("%Y-%m-%d")
        if today not in stats["daily_stats"]:
            stats["daily_stats"][today] = {
                "requests": 0,
                "cost_saved": 0.0,
                "tokens": 0
            }
        
        stats["daily_stats"][today]["requests"] += 1
        stats["daily_stats"][today]["cost_saved"] += stats["total_cost_saved"] - (stats["daily_stats"][today].get("total_cost_saved", 0))
        stats["daily_stats"][today]["tokens"] += tokens_prompt + tokens_completion
        
        # Cleanup old daily stats (keep last 30 days)
        if len(stats["daily_stats"]) > 30:
            # Remove oldest
            oldest = sorted(stats["daily_stats"].keys())[0]
            del stats["daily_stats"][oldest]
        
        self.save_stats()
    
    def get_best_available_model(self, task_type: str = "auto", prompt: str = "") -> Optional[Dict]:
        """Get the best available model based on priority and health"""
        # Auto-classify if task_type is auto and we have a prompt
        if task_type == "auto" and prompt:
            task_type = self.auto_classify_task(prompt)
        
        # By task type: simple/local tasks prefer local -> free cloud -> paid cloud
        models = self.config.get("backup_models", BACKUP_MODELS)
        
        # Sort by priority
        models = sorted(models, key=lambda m: m.get("priority", 99))
        
        # Priority order: local -> free cloud -> paid cloud (for maximum savings)
        if task_type == "simple" or task_type == "local":
            # Try local first
            for model in models:
                if model["type"] == "local" and self.check_model_health(model):
                    return model
            # No local available, try free cloud
            for model in models:
                if model["type"] == "cloud-free" and self.check_model_health(model):
                    return model
            # Try any
            for model in models:
                if self.check_model_health(model):
                    return model
        elif task_type == "complex" or task_type == "cloud":
            # For complex tasks, still prefer cheaper options first if available
            # Try local if it can handle it (some local models are big enough)
            for model in models:
                if model["type"] == "local" and self.check_model_health(model):
                    return model
            # Try free cloud
            for model in models:
                if model["type"] == "cloud-free" and self.check_model_health(model):
                    return model
            # Finally paid cloud
            for model in models:
                if model["type"] == "cloud" and self.check_model_health(model):
                    return model
            # Fallback
            for model in models:
                if self.check_model_health(model):
                    return model
        else:
            # auto: try all in priority order (which is already local -> free -> paid)
            for model in models:
                if self.check_model_health(model):
                    return model
        
        return None
    
    def generate(self, prompt: str, task_type: str = "auto", 
                 max_tokens: int = 512, use_cache: bool = True) -> Dict:
        """Generate response using the best available model"""
        
        # Check cache first
        if use_cache:
            cached, found = self.get_cached_response(prompt, "any")
            if found:
                cached["cached"] = True
                # Still record stats for cached responses
                self.record_usage({"type": "cached"}, cached, True)
                return cached
        
        # Get best model (with auto classification)
        model = self.get_best_available_model(task_type, prompt)
        if not model:
            raise RuntimeError("No available models found. Please check your configuration.")
        
        # Generate based on provider
        response = self._generate_with_provider(prompt, model, max_tokens)
        response["model_used"] = model["name"]
        response["provider"] = model["provider"]
        response["cached"] = False
        
        # Cache the result
        if use_cache:
            self.cache_response(prompt, model["name"], response)
        
        # Log usage
        self.log(f"Generated response with {model['name']}, prompt length: {len(prompt)}")
        # Record statistics
        self.record_usage(model, response, False)
        
        return response
    
    def _generate_with_provider(self, prompt: str, model: Dict, max_tokens: int) -> Dict:
        """Actual generation per provider"""
        provider = model["provider"]
        
        if provider == "ollama":
            return self._generate_ollama(prompt, model, max_tokens)
        elif provider in ["openai", "openrouter", "zhipu"]:
            # 智谱AI使用OpenAI兼容接口
            return self._generate_openai_compatible(prompt, model, max_tokens)
        elif provider == "volcengine":
            return self._generate_volcengine(prompt, model, max_tokens)
        else:
            raise ValueError(f"Unsupported provider: {provider}")
    
    def _generate_ollama(self, prompt: str, model: Dict, max_tokens: int) -> Dict:
        """Generate with Ollama (local)"""
        payload = {
            "model": model["name"],
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens
            }
        }
        
        resp = requests.post(model["endpoint"], json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        
        return {
            "text": data.get("response", ""),
            "tokens_prompt": data.get("prompt_eval_count", 0),
            "tokens_completion": data.get("eval_count", 0),
            "cost": 0.0  # free!
        }
    
    def _generate_openai_compatible(self, prompt: str, model: Dict, max_tokens: int) -> Dict:
        """Generate with OpenAI-compatible API (OpenRouter, Together, etc.)"""
        api_key = os.environ.get(model.get("api_key_env", ""), "") if model.get("api_key_env") else model.get("api_key", "")
        
        # Record API call for quota tracking
        provider = model["provider"]
        self.record_api_call(provider)
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model["name"],
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens
        }
        
        resp = requests.post(model["endpoint"], json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        
        usage = data.get("usage", {})
        tokens_prompt = usage.get("prompt_tokens", 0)
        tokens_completion = usage.get("completion_tokens", 0)
        
        # Calculate estimated cost
        cost_per_k = COST_ESTIMATE.get(model["name"], 0.1)
        total_cost = ((tokens_prompt + tokens_completion) / 1000) * cost_per_k
        
        return {
            "text": data["choices"][0]["message"]["content"],
            "tokens_prompt": tokens_prompt,
            "tokens_completion": tokens_completion,
            "cost": total_cost
        }
    
    def _generate_volcengine(self, prompt: str, model: Dict, max_tokens: int) -> Dict:
        """Generate with Volcengine (Ark)"""
        # Volcengine uses OpenAI-compatible endpoint format
        return self._generate_openai_compatible(prompt, model, max_tokens)
    
    def log(self, message: str):
        """Log message"""
        try:
            with open(LOG_FILE, 'a', encoding='utf-8') as f:
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"[{timestamp}] {message}\n")
        except:
            pass
    
    def get_stats(self) -> Dict:
        """Get usage statistics"""
        # Count cached responses
        cached_count = len([f for f in os.listdir(CACHE_DIR) if f.endswith('.json')]) if os.path.exists(CACHE_DIR) else 0
        
        # Calculate cache size
        cache_size = 0
        if os.path.exists(CACHE_DIR):
            for f in os.listdir(CACHE_DIR):
                fp = os.path.join(CACHE_DIR, f)
                cache_size += os.path.getsize(fp)
        
        return {
            "cached_responses": cached_count,
            "cache_size_bytes": cache_size,
            "cache_size_mb": cache_size / (1024 * 1024)
        }
    
    def clear_cache(self):
        """Clear all cached responses"""
        if os.path.exists(CACHE_DIR):
            for f in os.listdir(CACHE_DIR):
                os.remove(os.path.join(CACHE_DIR, f))
    
    def get_daily_report(self) -> Dict:
        """Get daily usage report for today"""
        stats = self.load_stats()
        today = time.strftime("%Y-%m-%d")
        today_stats = stats["daily_stats"].get(today, {
            "requests": 0,
            "cost_saved": 0.0,
            "tokens": 0
        })
        
        # Calculate projected monthly savings
        avg_daily_saved = stats["total_cost_saved"] / max(1, len(stats["daily_stats"]))
        projected_monthly = avg_daily_saved * 30
        
        return {
            "today": today,
            "today_stats": today_stats,
            "total_stats": {
                "total_requests": stats["total_requests"],
                "cached_requests": stats["cached_requests"],
                "local_requests": stats["local_requests"],
                "free_cloud_requests": stats["free_cloud_requests"],
                "paid_cloud_requests": stats["paid_cloud_requests"],
                "total_tokens": stats["total_tokens_prompt"] + stats["total_tokens_completion"],
                "total_cost_saved": stats["total_cost_saved"]
            },
            "projected_monthly_savings": projected_monthly
        }
    
    def get_earnings_summary(self) -> str:
        """Get human-readable earnings summary for daily check-in"""
        report = self.get_daily_report()
        total = report["total_stats"]["total_cost_saved"]
        today_saved = report["today_stats"]["cost_saved"]
        projected = report["projected_monthly_savings"]
        
        return (
            f"Multi-Model Router 每日收益报告\n"
            f"日期: {report['today']}\n"
            f"今日节省: ${today_saved:.4f}\n"
            f"累计节省: ${total:.4f}\n"
            f"预计月节省: ${projected:.2f}\n"
            f"\n请求分布:\n"
            f"  总请求: {report['total_stats']['total_requests']}\n"
            f"  缓存命中: {report['total_stats']['cached_requests']}\n"
            f"  本地处理: {report['total_stats']['local_requests']}\n"
            f"  免费云处理: {report['total_stats']['free_cloud_requests']}\n"
            f"  付费云处理: {report['total_stats']['paid_cloud_requests']}\n"
            f"总节省token: {report['total_stats']['total_tokens']:,}"
        )
    
    def get_quota_summary(self) -> str:
        """Get human-readable API quota summary"""
        self.check_and_reset_quota()
        
        output = ["[API 配额监控]\n"]
        
        providers = self.quota_config.get("providers", {})
        has_alert = False
        
        for provider_name, quota in providers.items():
            if not quota.get("enabled", True):
                continue
                
            status = self.get_quota_status(provider_name)
            total = status.get("total", "∞")
            used = status.get("used", 0)
            remaining = status.get("remaining", "∞")
            provider_status = status.get("status", "ok")
            
            if total == float('inf'):
                output.append(f"[ ] {provider_name}: OK - 无限制 (已用 {used})")
                continue
            
            remaining_pct = status.get("remaining_ratio", 0) * 100
            
            if provider_status == "critical":
                output.append(f"[!] {provider_name}: 紧急! 剩余 {remaining}/{total} ({remaining_pct:.1f}%)")
                has_alert = True
            elif provider_status == "warning":
                output.append(f"[*] {provider_name}: 警告! 剩余 {remaining}/{total} ({remaining_pct:.1f}%)")
                has_alert = True
            else:
                output.append(f"[+] {provider_name}: 正常 剩余 {remaining}/{total} ({remaining_pct:.1f}%)")
            
            # Add daily/weekly if available
            if "daily_used" in quota:
                daily_limit = quota.get("daily_limit", "N/A")
                output.append(f"    今日使用: {quota['daily_used']}/{daily_limit}")
            if "weekly_used" in quota:
                weekly_limit = quota.get("weekly_limit", "N/A")
                output.append(f"    本周使用: {quota['weekly_used']}/{weekly_limit}")
        
        if not has_alert:
            output.append("\n[OK] 所有API配额正常，无告警")
        
        return "\n".join(output)
    
    def get_quota_alerts(self) -> Optional[str]:
        """Get active quota alerts if any should be sent"""
        self.check_and_reset_quota()
        
        alerts = []
        providers = self.quota_config.get("providers", {})
        
        for provider_name, quota in providers.items():
            if not quota.get("enabled", True):
                continue
                
            status = self.get_quota_status(provider_name)
            provider_status = status.get("status", "ok")
            
            if provider_status in ["warning", "critical"] and self.should_alert(provider_status):
                total = status.get("total", 0)
                remaining = status.get("remaining", 0)
                remaining_pct = status.get("remaining_ratio", 0) * 100
                
                if provider_status == "critical":
                    alerts.append(
                        f"*** 紧急配额告警 - {provider_name} ***\n"
                        f"剩余配额: {remaining}/{total} ({remaining_pct:.1f}%)\n"
                        f"即将耗尽，请尽快续费！"
                    )
                else:
                    alerts.append(
                        f"** 配额警告 - {provider_name} **\n"
                        f"剩余配额: {remaining}/{total} ({remaining_pct:.1f}%)\n"
                        f"请关注剩余量，准备续费。"
                    )
        
        if alerts:
            return "\n\n".join(alerts)
        return None


# Singleton instance
_router_instance = None

def get_router() -> ModelRouter:
    """Get the singleton router instance"""
    global _router_instance
    if _router_instance is None:
        _router_instance = ModelRouter()
    return _router_instance

def generate(prompt: str, task_type: str = "auto", max_tokens: int = 512) -> Dict:
    """Convenience function for generation"""
    return get_router().generate(prompt, task_type, max_tokens)


def main():
    """Main entry point for CLI"""
    print("=== OpenClaw Multi-Model Router ===")
    router = ModelRouter()
    cache_stats = router.get_stats()
    print(f"Cached responses: {cache_stats['cached_responses']}")
    print(f"Cache size: {cache_stats['cache_size_mb']:.2f} MB")
    
    print("\nChecking model availability...")
    for model in router.config.get("backup_models", BACKUP_MODELS):
        available = router.check_model_health(model)
        status = "[OK] Available" if available else "[--] Unavailable"
        print(f"  {model['name']} ({model['type']}): {status}")
    
    best = router.get_best_available_model()
    if best:
        print(f"\nBest available model: {best['name']} ({best['type']})")
    else:
        print("\nNo available models found!")
    
    # Show usage statistics
    print("\n" + "="*40)
    print(router.get_earnings_summary())
    
    # Show API quota status
    print("\n" + "="*40)
    print(router.get_quota_summary())
    
    # Check for active alerts
    alerts = router.get_quota_alerts()
    if alerts:
        print("\n" + "="*40)
        print("活跃告警:")
        print(alerts)
        # Exit with code 1 if there are critical alerts
        has_critical = any("紧急" in alert for alert in (alerts.split("\n\n") if alerts else []))
        if has_critical:
            exit(1)


def get_status_for_ui():
    """Get combined status for OpenClaw Control UI"""
    router = ModelRouter()
    return {
        "earnings": router.get_daily_report(),
        "earnings_text": router.get_earnings_summary(),
        "quota": {
            provider: router.get_quota_status(provider)
            for provider in router.quota_config.get("providers", {})
        },
        "quota_text": router.get_quota_summary(),
        "alerts": router.get_quota_alerts(),
        "cache": router.get_stats()
    }


if __name__ == "__main__":
    main()
