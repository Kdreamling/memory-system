"""
多代理商通道管理
"""

from config import get_settings


def get_channels() -> dict:
    """获取所有通道配置（每次调用读最新 settings）"""
    s = get_settings()
    return {
        "deepseek": {
            "provider": "openai_compatible",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": s.llm_api_key,
            "models": ["deepseek-chat", "deepseek-reasoner"],
            "supports_thinking": False,
            "thinking_format": "openai",
            "model_overrides": {
                "deepseek-reasoner": {"supports_thinking": True},
            },
        },
        "dzzi": {
            "provider": "openai_compatible",
            "base_url": "https://api.dzzi.ai/v1",
            "api_key": s.dzzi_api_key,
            "models": ["[0.1]claude-opus-4-6-thinking"],
            "supports_thinking": True,
            "thinking_format": "openai",
        },
        "openrouter": {
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": s.openrouter_api_key,
            "models": [
                "anthropic/claude-opus-4.6",
            ],
            "supports_thinking": True,
            "thinking_format": "openai",
        },
    }


# 模型别名 — 简写映射
MODEL_ALIASES = {
    "opus": "anthropic/claude-opus-4.6",
    "claude": "anthropic/claude-opus-4.6",
    "dzzi": "[0.1]claude-opus-4-6-thinking",
    "deepseek": "deepseek-chat",
    "ds": "deepseek-chat",
    "reasoner": "deepseek-reasoner",
}


def resolve_channel(model_name: str) -> tuple:
    """根据模型名找到对应通道
    返回: (channel_name, channel_config, resolved_model_name)
    channel_config 已 merge model_overrides（不修改原始 dict）
    """
    channels = get_channels()
    resolved = MODEL_ALIASES.get(model_name.lower(), model_name)

    for ch_name, ch_config in channels.items():
        if resolved in ch_config["models"]:
            overrides = ch_config.get("model_overrides", {}).get(resolved, {})
            merged = {**ch_config, **overrides} if overrides else ch_config
            return ch_name, merged, resolved

    # 找不到就走 deepseek
    return "deepseek", channels["deepseek"], "deepseek-chat"


def get_model_list() -> list:
    """给前端的模型列表"""
    channels = get_channels()
    models = []
    for ch_name, ch_config in channels.items():
        overrides_map = ch_config.get("model_overrides", {})
        for model_id in ch_config["models"]:
            model_overrides = overrides_map.get(model_id, {})
            supports_thinking = model_overrides.get(
                "supports_thinking", ch_config["supports_thinking"]
            )
            models.append({
                "id": model_id,
                "channel": ch_name,
                "supports_thinking": supports_thinking,
            })
    return models