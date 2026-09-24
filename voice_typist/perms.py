"""权限检测：辅助功能（打字、全局热键）是否已授权。"""


def accessibility_trusted(prompt=False):
    """返回 True/False；无法判断时返回 None。prompt=True 会弹系统授权引导。"""
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions
        opts = {"AXTrustedCheckOptionPrompt": prompt}
        return bool(AXIsProcessTrustedWithOptions(opts))
    except Exception:
        try:
            import Quartz
            return bool(Quartz.AXIsProcessTrusted())
        except Exception:
            return None
