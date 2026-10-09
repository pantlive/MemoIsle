using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace MemoIsle.Desktop.Services;

/// <summary>翻译结果：译文、识别出的源语言、或错误信息。</summary>
public sealed record TranslationResult(string? Translation, string? SourceLanguage, string? Error)
{
    public bool Succeeded => Error is null && !string.IsNullOrWhiteSpace(Translation);
}

/// <summary>
/// 划词翻译服务：
/// - Google 免费接口（translate.googleapis.com，无需密钥）
/// - 自配大模型（任意 OpenAI 兼容 /chat/completions 端点）
/// 供全局快捷键调用，在独立小窗中展示结果。
/// </summary>
public sealed class TranslationService
{
    private static readonly HttpClient Http = new()
    {
        Timeout = TimeSpan.FromSeconds(20),
    };

    public async Task<TranslationResult> TranslateAsync(string text, CancellationToken ct = default)
    {
        var clean = text.Trim();
        if (clean.Length == 0)
        {
            return new TranslationResult(null, null, "没有可翻译的文本。");
        }
        if (clean.Length > 5000)
        {
            clean = clean[..5000];
        }
        var config = TranslationSettings.Current;
        switch (config.ResolvedProvider)
        {
            case TranslationProvider.Llm:
                return await TranslateWithLlmAsync(clean, config, ct);
            case TranslationProvider.Auto:
                // 自动模式：先用免费的 Google，失败且大模型已配置时回退。
                var google = await TranslateWithGoogleAsync(clean, config, ct);
                if (google.Succeeded || !config.LlmConfigured)
                {
                    return google;
                }
                var fallback = await TranslateWithLlmAsync(clean, config, ct);
                return fallback.Succeeded
                    ? fallback with { SourceLanguage = google.SourceLanguage }
                    : google;
            default:
                return await TranslateWithGoogleAsync(clean, config, ct);
        }
    }

    /// <summary>Google 免费翻译接口（非官方，无需 API Key）。</summary>
    private static async Task<TranslationResult> TranslateWithGoogleAsync(
        string text,
        TranslationConfig config,
        CancellationToken ct)
    {
        try
        {
            var url =
                "https://translate.googleapis.com/translate_a/single?client=gtx"
                + $"&sl=auto&tl={Uri.EscapeDataString(config.TargetLanguage)}&dt=t"
                + $"&q={Uri.EscapeDataString(text)}";
            using var response = await Http.GetAsync(url, ct);
            var body = await response.Content.ReadAsStringAsync(ct);
            if (!response.IsSuccessStatusCode)
            {
                var reason = (int)response.StatusCode switch
                {
                    429 => "请求过于频繁（免费接口有速率限制），稍后重试或在设置里改用大模型翻译。",
                    403 or 400 => "接口拒绝了请求，可能网络受限，建议改用大模型翻译。",
                    _ => $"Google 翻译请求失败（{response.StatusCode}）。",
                };
                return new TranslationResult(null, null, reason);
            }

            using var document = JsonDocument.Parse(body);
            var root = document.RootElement;
            if (root.ValueKind != JsonValueKind.Array || root.GetArrayLength() == 0)
            {
                return new TranslationResult(null, null, "Google 翻译返回了无法解析的内容。");
            }
            // 结构：[[["译文","原文",...], ...], null, "源语言", ...]
            var builder = new StringBuilder();
            if (root[0].ValueKind == JsonValueKind.Array)
            {
                foreach (var segment in root[0].EnumerateArray())
                {
                    if (segment.ValueKind == JsonValueKind.Array &&
                        segment.GetArrayLength() > 0 &&
                        segment[0].ValueKind == JsonValueKind.String)
                    {
                        builder.Append(segment[0].GetString());
                    }
                }
            }
            var detected = root.GetArrayLength() > 2 && root[2].ValueKind == JsonValueKind.String
                ? root[2].GetString()
                : null;
            var translation = builder.ToString().Trim();
            return translation.Length == 0
                ? new TranslationResult(null, detected, "Google 翻译没有返回译文。")
                : new TranslationResult(translation, detected, null);
        }
        catch (TaskCanceledException)
        {
            return new TranslationResult(null, null, "Google 翻译请求超时（可能被网络限制）。");
        }
        catch (Exception ex)
        {
            return new TranslationResult(null, null, $"Google 翻译不可用：{ex.Message}");
        }
    }

    /// <summary>自配大模型翻译（OpenAI 兼容接口）。</summary>
    private static async Task<TranslationResult> TranslateWithLlmAsync(
        string text,
        TranslationConfig config,
        CancellationToken ct)
    {
        if (string.IsNullOrWhiteSpace(config.ApiBase) || string.IsNullOrWhiteSpace(config.Model))
        {
            return new TranslationResult(null, null, "请先在设置里填写大模型的接口地址与模型名。");
        }
        try
        {
            var endpoint = config.ApiBase.TrimEnd('/') + "/chat/completions";
            var target = TranslationSettings.LanguageLabel(config.TargetLanguage);
            var systemPrompt = config.SystemPrompt.Replace("{target}", target);
            var payload = JsonSerializer.Serialize(new
            {
                model = config.Model,
                temperature = 0.2,
                messages = new object[]
                {
                    new { role = "system", content = systemPrompt },
                    new { role = "user", content = text },
                },
            });

            using var request = new HttpRequestMessage(HttpMethod.Post, endpoint);
            request.Content = new StringContent(payload, Encoding.UTF8, "application/json");
            if (!string.IsNullOrWhiteSpace(config.ApiKey))
            {
                request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", config.ApiKey.Trim());
            }
            using var response = await Http.SendAsync(request, ct);
            var body = await response.Content.ReadAsStringAsync(ct);
            if (!response.IsSuccessStatusCode)
            {
                return new TranslationResult(
                    null,
                    null,
                    $"大模型翻译失败（{(int)response.StatusCode}）：{Truncate(body, 160)}");
            }

            // 兼容两种常见响应格式：OpenAI chat/completions 与 responses API。
            using var document = JsonDocument.Parse(body);
            var root = document.RootElement;
            var content = ReadFirstChoice(root) ?? ReadResponsesOutput(root);
            return string.IsNullOrWhiteSpace(content)
                ? new TranslationResult(null, null, "大模型没有返回译文内容。")
                : new TranslationResult(content.Trim(), null, null);
        }
        catch (TaskCanceledException)
        {
            return new TranslationResult(null, null, "大模型翻译请求超时。");
        }
        catch (Exception ex)
        {
            return new TranslationResult(null, null, $"大模型翻译不可用：{ex.Message}");
        }
    }

    private static string? ReadFirstChoice(JsonElement root)
    {
        if (root.TryGetProperty("choices", out var choices) &&
            choices.ValueKind == JsonValueKind.Array &&
            choices.GetArrayLength() > 0)
        {
            var first = choices[0];
            if (first.TryGetProperty("message", out var message) &&
                message.TryGetProperty("content", out var content) &&
                content.ValueKind == JsonValueKind.String)
            {
                return content.GetString();
            }
            if (first.TryGetProperty("text", out var text) && text.ValueKind == JsonValueKind.String)
            {
                return text.GetString();
            }
        }
        return null;
    }

    private static string? ReadResponsesOutput(JsonElement root)
    {
        if (!root.TryGetProperty("output", out var output) || output.ValueKind != JsonValueKind.Array)
        {
            return null;
        }
        var builder = new StringBuilder();
        foreach (var item in output.EnumerateArray())
        {
            if (!item.TryGetProperty("content", out var content) || content.ValueKind != JsonValueKind.Array)
            {
                continue;
            }
            foreach (var part in content.EnumerateArray())
            {
                if (part.TryGetProperty("text", out var text) && text.ValueKind == JsonValueKind.String)
                {
                    builder.Append(text.GetString());
                }
            }
        }
        return builder.Length > 0 ? builder.ToString() : null;
    }

    private static string Truncate(string value, int max) =>
        value.Length <= max ? value : value[..max] + "…";
}
