"""Memo API 路由汇总。

各领域的路由在 ``app.routes`` 下分模块维护；这里按原有顺序挂到同一个路由器，
``main.py`` 仍然只引入 ``app.api.router``。同一路径前缀的路由都在同一个模块里，
模块之间不会出现路径匹配先后的问题。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.routes import (
    auth,
    browser,
    data_transfer,
    ebooks,
    memos,
    resources,
    review,
    system,
)

router = APIRouter()
for module in (system, auth, data_transfer, browser, memos, resources, review, ebooks):
    router.include_router(module.router)
