"""会议转写总结服务。"""

from __future__ import annotations

import httpx

from app.config import Settings


class MeetingSummaryNotConfiguredError(RuntimeError):
    """服务端没有配置可用的 OpenAI 兼容 LLM。"""


class MeetingSummaryUnavailableError(RuntimeError):
    """LLM 请求失败或返回内容无效。"""


_SUMMARY_PROMPT = """你是一名专业会议助理。请根据会议转写内容输出简体中文纪要。

转写可能按“我：”“对方：”“对方1：”“对方2：”等标注说话人：我来自本机麦克风；对方和对方N来自系统声音/远端。
对方N 是声纹聚类得到的远端说话人编号，不代表真实姓名。
请在纪要中保留“我”“对方”“对方1”等原始称呼，不要自动映射或编造具体身份。

必须按以下标题分节，缺失的节写“暂无”：
会议概要
关键要点
决议
行动项（格式：事项 - 负责人 - 时间）
风险与待确认

要求：只保留会议中明确出现的信息，不要编造负责人或时间；语言简洁。"""


def summarize_meeting(
    transcript: str,
    title: str | None,
    settings: Settings,
    client: httpx.Client | None = None,
) -> str:
    """调用 OpenAI 兼容接口并返回会议纪要。"""

    if not transcript.strip():
        raise ValueError("会议转写不能为空")
    if not settings.llm_base_url or not settings.llm_model:
        raise MeetingSummaryNotConfiguredError(
            "会议总结服务未配置，请设置 MEMOISLE_LLM_BASE_URL 和 MEMOISLE_LLM_MODEL",
        )

    # 外部可注入 httpx.Client，便于测试和复用连接池。
    owned_client = client is None
    request_client = client or httpx.Client(timeout=settings.llm_timeout_seconds)
    try:
        response = request_client.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Content-Type": "application/json"}
            if not settings.llm_api_key
            else {
                "Authorization": f"Bearer {settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.llm_model,
                "messages": [
                    {"role": "system", "content": _SUMMARY_PROMPT},
                    {
                        "role": "user",
                        "content": f"会议标题：{(title or '未命名会议').strip()}\n\n"
                        f"会议转写：\n{transcript.strip()}",
                    },
                ],
                "temperature": 0.2,
                "max_tokens": 2048,
            },
        )
        response.raise_for_status()
        payload = response.json()
        summary = payload["choices"][0]["message"]["content"]
        if not isinstance(summary, str) or not summary.strip():
            raise MeetingSummaryUnavailableError("会议总结服务返回了空内容")
        return summary.strip()
    except MeetingSummaryUnavailableError:
        raise
    except (
        httpx.HTTPError,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
    ) as error:
        raise MeetingSummaryUnavailableError(
            "会议总结服务暂时不可用，请稍后重试",
        ) from error
    finally:
        # 只释放本函数创建的客户端，测试注入的连接由调用方管理。
        if owned_client:
            request_client.close()
