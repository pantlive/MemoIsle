"""公开正文、模板路径和分类证据的有效性测试。"""

import json

import httpx
import pytest
from app.resource_classification_quality import (
    MAX_PUBLIC_EXCERPT_CHARS,
    UncertainClassificationError,
    parse_jev_assessment,
)
from app.resource_processing import (
    ClassificationCategory,
    ResourceHTMLParser,
    ResourceMetadata,
    classify_resource_with_jev,
    fetch_resource_metadata,
)


def test_excerpt_prefers_main_and_excludes_hidden_forms_and_navigation() -> None:
    """公开正文排除导航、脚本、隐藏内容及表单，不采集输入值。"""

    parser = ResourceHTMLParser(include_text_excerpt=True)
    parser.feed(
        "<html><head><title>标题</title><script>private-key</script></head>"
        "<body>普通页头<nav>导航广告</nav><main><h1>张量课程</h1>"
        "<p>介绍 PyTorch 的训练流程。</p><div hidden>private-key</div>"
        '<div aria-hidden="true">private-key</div>'
        '<div style="display: none">private-key</div>'
        '<form><input value="private-key"><label>账号密码</label></form>'
        "<button>登录</button><script>private-key</script>"
        "<style>private-key</style></main><footer>版权导航</footer></body></html>"
    )
    metadata = parser.metadata("https://example.com/guide", 200)
    assert metadata.text_excerpt == "张量课程 介绍 PyTorch 的训练流程。"
    assert metadata.page_title == "标题"
    assert "private-key" not in metadata.text_excerpt


def test_excerpt_is_opt_in_and_bounded_even_with_nested_or_empty_tags() -> None:
    """普通巡检不提取正文，分类摘要有硬上限，空元素不破坏排除区域。"""

    html = "<body><nav/><main><p>" + "知识内容" * 2000 + "</p></main></body>"
    default = ResourceHTMLParser()
    default.feed(html)
    assert default.metadata("https://example.com", 200).text_excerpt is None
    parser = ResourceHTMLParser(include_text_excerpt=True)
    parser.feed(html)
    assert (
        len(parser.metadata("https://example.com", 200).text_excerpt)
        == MAX_PUBLIC_EXCERPT_CHARS
    )
    deep = ResourceHTMLParser(include_text_excerpt=True)
    deep.feed("<div>" * 300 + "private-key" + "</div>" * 300)
    assert deep.metadata("https://example.com", 200).text_excerpt is None


def test_excerpt_fetch_still_rejects_private_redirect_target() -> None:
    """正文补充沿用原抓取器的重定向地址校验。"""

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """模拟公开站点跳转到本机，第二个目标不得访问。"""

        calls.append(request.url.host)
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/secret"})

    from app.resource_processing import UnsafeResourceUrlError

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(UnsafeResourceUrlError):
            fetch_resource_metadata(
                "https://example.com/page",
                client=client,
                resolver=lambda host, _port: [
                    "127.0.0.1" if host == "127.0.0.1" else "93.184.216.34"
                ],
                include_text_excerpt=True,
            )
    assert calls == ["example.com"]


def test_jev_uses_public_excerpt_and_hierarchy_and_keeps_candidate_probabilities() -> (
    None
):
    """正文与路径发送给 Jev，置信度与候选概率保留为不同字段。"""

    metadata = ResourceMetadata(
        "https://example.com/page",
        "课程",
        None,
        "示例站",
        None,
        200,
        text_excerpt="公开的张量训练课程，介绍 PyTorch。",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        """检查真实请求内容并提供与置信度不同的候选概率。"""

        body = json.loads(request.content)
        assert body["state"]["public_text_excerpt"] == metadata.text_excerpt
        assert (
            body["questions"]["category"]["criteria"]["tensor"]["path"]
            == "学习资料 / 张量"
        )
        assert "private-note" not in request.content.decode()
        return httpx.Response(
            200,
            json={
                "answers": {
                    "category": {
                        "choice": "tensor",
                        "confidence": 0.8,
                        "probabilities": {"tensor": 0.9, "article": 0.1},
                    }
                }
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = classify_resource_with_jev(
            metadata,
            [
                ClassificationCategory("tensor", "张量", "张量学习", "学习资料 / 张量"),
                ClassificationCategory("article", "阅读"),
            ],
            "fake-key",
            "https://fake.example/v1",
            "typesafe/jev",
            0.7,
            client,
        )
    assert result.category == "tensor"
    assert result.category_label == "张量"
    assert result.confidence == 0.8
    assert result.assessment["candidates"][0]["probability"] == 0.9
    assert result.assessment["candidates"][0]["label"] == "学习资料 / 张量"
    assert result.assessment["input_source"] == "public_excerpt"


@pytest.mark.parametrize(
    "answer,reason",
    [
        (
            {
                "choice": "tool",
                "confidence": 0.4,
                "probabilities": {"tool": 0.6, "article": 0.4},
            },
            "low_confidence",
        ),
        ({"choice": "private-key", "confidence": 1}, "unknown_category"),
        ({"choice": "tool", "confidence": True}, "invalid_response"),
        ({"choice": "tool", "confidence": float("nan")}, "invalid_response"),
        ({"choice": "tool", "confidence": float("inf")}, "invalid_response"),
        ({"choice": "tool", "confidence": -0.1}, "invalid_response"),
        ({"choice": "tool", "confidence": 10**1000}, "invalid_response"),
        (
            {
                "choice": "tool",
                "confidence": 0.9,
                "probabilities": {"tool": 0.1, "article": 0.9},
            },
            "invalid_response",
        ),
        (
            {
                "choice": "tool",
                "confidence": 0.9,
                "probabilities": {"tool": 0.9, "article": 0.9},
            },
            "invalid_response",
        ),
        (
            {
                "choice": "tool",
                "confidence": 0.9,
                "probabilities": {"tool": "private-key"},
            },
            "invalid_response",
        ),
        ({"message": "private-key"}, "invalid_response"),
    ],
)
def test_uncertain_evidence_is_safe_and_does_not_relax_threshold(
    answer: dict[str, object],
    reason: str,
) -> None:
    """无效数据和低置信度不得自动接受，原始内容不能进入保存的证据。"""

    with pytest.raises(UncertainClassificationError) as raised:
        parse_jev_assessment(
            {"answers": {"category": answer}},
            {
                "tool": "工具",
                "article": "阅读",
            },
            0.7,
            "typesafe/jev",
            False,
        )
    assessment = raised.value.assessment
    assert assessment["reason_code"] == reason
    assert assessment["status"] == "uncertain"
    assert assessment["threshold"] == 0.7
    assert "private-key" not in json.dumps(assessment, ensure_ascii=False)
    assert assessment["attempted_at"].endswith("Z")


def test_provider_without_probabilities_does_not_invent_candidate_probability() -> None:
    """兼容省略概率的中转响应，不把置信度当作候选概率。"""

    selected, assessment = parse_jev_assessment(
        {
            "answers": {
                "category": {
                    "choice": "tool",
                    "confidence": 0.95,
                }
            }
        },
        {"tool": "工具"},
        0.7,
        "typesafe/jev",
        False,
    )
    assert selected == "tool"
    assert assessment["candidates"][0]["probability"] is None
