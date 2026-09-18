"""MCP 工具接入:配置连接 + 动态加载外部 MCP server 工具 + 瑞幸比价聚合"""

from . import connection, loader, luckin_compare  # noqa: F401

__all__ = ["connection", "loader", "luckin_compare"]
