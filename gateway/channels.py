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
            "thinking_format": None,
        },
        "dzzi": {
            "provider": "openai_compatible",
            "base_url": "https://api.dzzi.ai/v1",  # TODO: 确认实际地址
            "api_key": s.dzzi_api_key,
            "models": ["claude-sonnet-4-20250514"],
            "supports_thinking": True,
            "thinking_format": "openai",
        },
        "openrouter": {
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": s.openrouter_api_key,
            "models": ["anthropic/claude-sonnet-4", "anthropic/claude-opus-4"],
            "supports_thinking": True,
            "thinking_format": "openai",
        },
    }


# 模型别名 — 简写映射
MODEL_ALIASES = {
    "claude": "claude-sonnet-4-20250514",
    "sonnet": "claude-sonnet-4-20250514",
    "deepseek": "deepseek-chat",
    "ds": "deepseek-chat",
}


def resolve_channel(model_name: str) -> tuple:
    """根据模型名找到对应通道
    返回: (channel_name, channel_config, resolved_model_name)
    """
    channels = get_channels()
    resolved = MODEL_ALIASES.get(model_name.lower(), model_name)

    for ch_name, ch_config in channels.items():
        if resolved in ch_config["models"]:
            return ch_name, ch_config, resolved

    # 找不到就走 deepseek
    return "deepseek", channels["deepseek"], "deepseek-chat"


def get_model_list() -> list:
    """给前端的模型列表"""
    channels = get_channels()
    models = []
    for ch_name, ch_config in channels.items():
        for model_id in ch_config["models"]:
            models.append({
                "id": model_id,
                "channel": ch_name,
                "supports_thinking": ch_config["supports_thinking"],
            })
    return models