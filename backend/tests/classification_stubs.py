"""分类测试共用的桩：把后台批量分类的判定入口替换成可控函数。"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from app.resource_processing import CategoryDecision, ResourceMetadata


def patch_web_classifier(
    monkeypatch: pytest.MonkeyPatch,
    classify: Callable[..., CategoryDecision],
) -> None:
    """替换后台任务的判定入口，并保持旧的按位置参数顺序。

    旧测试桩的签名是 ``classify(metadata, categories, api_key, base_url, model,
    threshold)``；后台任务现在用关键字调用统一入口，这里把关键字还原成位置参数，
    让“账号配置确实传到了模型调用”这类断言继续成立。
    """

    def wrapper(metadata: ResourceMetadata, **kwargs: object) -> CategoryDecision:
        return classify(
            metadata,
            kwargs.get("category_options"),
            kwargs.get("jev_api_key"),
            kwargs.get("jev_base_url"),
            kwargs.get("jev_model"),
            kwargs.get("jev_min_confidence"),
        )

    monkeypatch.setattr(
        "app.resource_classification_service.classify_resource",
        wrapper,
    )
