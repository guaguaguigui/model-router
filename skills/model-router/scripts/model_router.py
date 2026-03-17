# Multi-Model Router for OpenClaw
# 自动路由请求到本地/云端模型，节省token消耗
# Copyright © 2026 XC

import os
import json
import hashlib
import time
import requests
from typing import Dict, Tuple, Optional, Any

# Configuration
MODEL_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "model_config.json")
CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
LOG_FILE = os.path.join(os.path.dirname(__file__), "model_router.log")

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
        "name": "volcengine:ark-code-latest",
        "type": "cloud",
        "provider": "volcengine",
        "priority": 2
    }
]

# Caching
CACHE_TTL = 3600  # 1 hour cache
CACHE_MAX_SIZE_MB = 100

# Retry
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2

# Cost estimation (per 1K tokens)
COST_ESTIMATE = {
    "qwen3.5:9b": 0.0,
    "gpt-4o-mini": 0.08,
    "claude-3-haiku": 0.25,
    "volcengine:ark-code-latest": 0.1
}


class ModelRouter:
    def __init__(self, config_path: str = None):
        self.config_path = config_path or MODEL_CONFIG_FILE
        self.config = self.load_config()
        self.ensure_cache_dir()
        
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
    
    def get_best_available_model(self, task_type: str = "auto") -> Optional[Dict]:
        """Get the best available model based on priority and health"""
        # By task type: simple/local tasks prefer local, complex prefer cloud
        models = self.config.get("backup_models", BACKUP_MODELS)
        
        # Sort by priority
        models = sorted(models, key=lambda m: m.get("priority", 99))
        
        # Task-based filtering
        if task_type == "simple" or task_type == "local":
            # Try local first
            for model in models:
                if model["type"] == "local" and self.check_model_health(model):
                    return model
            # No local available, try any
            for model in models:
                if self.check_model_health(model):
                    return model
        elif task_type == "complex" or task_type == "cloud":
            # Try cloud first
            for model in models:
                if model["type"] == "cloud" and self.check_model_health(model):
                    return model
            # Fallback to local
            for model in models:
                if self.check_model_health(model):
                    return model
        else:
            # auto: try all in priority order
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
                return cached
        
        # Get best model
        model = self.get_best_available_model(task_type)
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
        
        return response
    
    def _generate_with_provider(self, prompt: str, model: Dict, max_tokens: int) -> Dict:
        """Actual generation per provider"""
        provider = model["provider"]
        
        if provider == "ollama":
            return self._generate_ollama(prompt, model, max_tokens)
        elif provider in ["openai", "openrouter"]:
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


if __name__ == "__main__":
    print("=== OpenClaw Multi-Model Router ===")
    router = ModelRouter()
    stats = router.get_stats()
    print(f"Cached responses: {stats['cached_responses']}")
    print(f"Cache size: {stats['cache_size_mb']:.2f} MB")
    
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
