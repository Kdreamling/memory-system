"""
场景检测器 - 纯规则引擎，零延迟
根据用户消息内容判断场景类型：daily / plot / meta
"""


class SceneDetector:
    """会话级场景状态管理器"""

    # meta 触发词（系统测试/调试类）
    META_KEYWORDS = [
        "测试", "test", "MCP", "工具", "tool", "服务器", "server",
        "API", "debug", "调试", "接口", "endpoint", "日志", "log"
    ]

    # plot 进入触发词
    PLOT_ENTER_KEYWORDS = [
        "剧本", "来演", "来玩", "角色扮演", "RP", "继续剧情", "接着演",
        "开始演", "进入剧情", "剧情开始"
    ]

    # plot 退出触发词
    PLOT_EXIT_KEYWORDS = [
        "不玩了", "回来", "正常聊", "出戏", "暂停",
        "停一下", "别演了", "回到现实", "不演了"
    ]

    def __init__(self):
        self._current_scene = "daily"
        self._previous_scene = "daily"
        self._scene_changed = False

    def detect(self, user_msg: str) -> str:
        """
        检测消息的场景类型
        返回 'daily' | 'plot' | 'meta'
        """
        if not user_msg:
            return self._current_scene

        msg_lower = user_msg.lower()
        self._previous_scene = self._current_scene
        self._scene_changed = False

        # 优先级1：meta 判定
        for kw in self.META_KEYWORDS:
            if kw.lower() in msg_lower:
                if self._current_scene != "meta":
                    self._scene_changed = True
                self._current_scene = "meta"
                return "meta"

        # 优先级2：plot 退出判定（先检查退出，再检查进入）
        for kw in self.PLOT_EXIT_KEYWORDS:
            if kw in user_msg:
                if self._current_scene != "daily":
                    self._scene_changed = True
                self._current_scene = "daily"
                return "daily"

        # 优先级3：plot 进入判定
        for kw in self.PLOT_ENTER_KEYWORDS:
            if kw in user_msg:
                if self._current_scene != "plot":
                    self._scene_changed = True
                self._current_scene = "plot"
                return "plot"

        # 优先级4：继承当前场景（plot模式下后续消息自动继承）
        # meta 不继承，单条消息有效后回到之前的场景
        if self._previous_scene == "meta":
            self._current_scene = "daily"
            return "daily"

        return self._current_scene

    def get_current_scene(self) -> str:
        """获取当前场景状态"""
        return self._current_scene

    def has_scene_changed(self) -> bool:
        """本次消息是否触发了场景切换"""
        return self._scene_changed

    def reset(self):
        """重置场景状态（用于测试或手动重置）"""
        self._current_scene = "daily"
        self._previous_scene = "daily"
        self._scene_changed = False
