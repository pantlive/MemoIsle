"""FastAPI 应用入口。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.bookmark_service import run_pending_bookmark_imports
from app.config import Settings
from app.database import Database
from app.ebook_service import run_pending_ebook_jobs
from app.image_ocr_service import run_pending_image_ocr
from app.image_organization_service import image_organization_loop
from app.link_health_service import link_health_monitor_loop
from app.memo_tools_api import router as memo_tools_router
from app.model_settings_api import router as model_settings_router
from app.resource_classification_api import router as resource_classification_router
from app.resource_classification_service import resource_classification_loop


def create_app(
    settings: Settings | None = None,
    database: Database | None = None,
) -> FastAPI:
    """创建可注入配置和数据库的应用实例。"""

    resolved_settings = settings or Settings.from_environment()
    resolved_database = database or Database(resolved_settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """初始化表结构并在退出时释放连接。"""

        resolved_database.create_schema()
        stop_event = asyncio.Event()
        monitor_task: asyncio.Task[None] | None = None
        classification_task = asyncio.create_task(
            resource_classification_loop(
                resolved_settings.database_url, resolved_settings, stop_event,
            )
        )
        image_organization_task = asyncio.create_task(
            image_organization_loop(
                resolved_settings.database_url, resolved_settings, stop_event,
            )
        )
        bookmark_recovery_task = asyncio.create_task(
            asyncio.to_thread(
                run_pending_bookmark_imports,
                resolved_settings.database_url,
                resolved_settings,
            )
        )
        image_ocr_recovery_task = asyncio.create_task(
            asyncio.to_thread(
                run_pending_image_ocr,
                resolved_settings.database_url,
                resolved_settings,
            )
        )
        ebook_recovery_task = asyncio.create_task(
            asyncio.to_thread(
                run_pending_ebook_jobs,
                resolved_settings.database_url,
                resolved_settings,
            )
        )
        if resolved_settings.resource_health_monitor_enabled:
            monitor_task = asyncio.create_task(
                link_health_monitor_loop(
                    resolved_settings.database_url,
                    resolved_settings,
                    stop_event,
                )
            )
        try:
            yield
        finally:
            stop_event.set()
            if monitor_task is not None:
                await monitor_task
            await classification_task
            await image_organization_task
            await bookmark_recovery_task
            await image_ocr_recovery_task
            await ebook_recovery_task
            resolved_database.dispose()

    application = FastAPI(
        title="MemoIsle API",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.database = resolved_database
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.cors_origins),
        allow_origin_regex=r"chrome-extension://[a-p]{32}",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(router, prefix="/api/v1")
    application.include_router(model_settings_router, prefix="/api/v1")
    application.include_router(memo_tools_router, prefix="/api/v1")
    application.include_router(resource_classification_router, prefix="/api/v1")
    return application


app = create_app()
