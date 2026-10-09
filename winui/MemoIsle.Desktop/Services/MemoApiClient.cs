using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using MemoIsle.Desktop.Models;

namespace MemoIsle.Desktop.Services;

/// <summary>后端返回非 2xx 时抛出的异常，携带状态码与错误码。</summary>
public sealed class MemoApiException : Exception
{
    private static readonly JsonSerializerOptions ErrorJsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
    };

    public int StatusCode { get; }
    public string ResponseBody { get; }
    public string? Code { get; }
    public string? Detail { get; }

    /// <summary>409 冲突时服务端回带的现有条目（如重复词形）。</summary>
    public Memo? Current { get; }

    public MemoApiException(int statusCode, string responseBody)
        : base(ReadMessage(statusCode, responseBody))
    {
        StatusCode = statusCode;
        ResponseBody = responseBody;
        Code = ReadErrorCode(responseBody);
        Detail = ReadDetail(responseBody);
        Current = ReadCurrent(responseBody);
    }

    private static string ReadMessage(int statusCode, string body)
    {
        var detail = ReadDetail(body);
        return string.IsNullOrWhiteSpace(detail)
            ? $"API 请求失败（{statusCode}）"
            : detail;
    }

    private static string? ReadDetail(string body)
    {
        try
        {
            using var document = JsonDocument.Parse(body);
            if (document.RootElement.TryGetProperty("detail", out var detail))
            {
                return detail.ValueKind == JsonValueKind.String
                    ? detail.GetString()
                    : detail.ToString();
            }
        }
        catch (JsonException)
        {
            // 错误体不是 JSON 时保留状态码提示。
        }
        return null;
    }

    private static string? ReadErrorCode(string body)
    {
        try
        {
            using var document = JsonDocument.Parse(body);
            if (document.RootElement.TryGetProperty("detail", out var detail) &&
                detail.ValueKind == JsonValueKind.Object &&
                detail.TryGetProperty("code", out var code))
            {
                return code.GetString();
            }
        }
        catch (JsonException)
        {
            // 错误体不是 JSON 时忽略。
        }
        return null;
    }

    private static Memo? ReadCurrent(string body)
    {
        try
        {
            using var document = JsonDocument.Parse(body);
            if (document.RootElement.TryGetProperty("detail", out var detail) &&
                detail.ValueKind == JsonValueKind.Object &&
                detail.TryGetProperty("current", out var current) &&
                current.ValueKind == JsonValueKind.Object)
            {
                return current.Deserialize<Memo>(ErrorJsonOptions);
            }
        }
        catch (JsonException)
        {
            // 没有 current 字段时忽略。
        }
        return null;
    }
}

/// <summary>MemoIsle 后端 HTTP 客户端（snake_case 自动映射）。</summary>
public sealed class MemoApiClient
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
    };

    private readonly HttpClient _http;

    public string? AccessToken { get; set; }

    public MemoApiClient(string baseUrl)
    {
        var normalized = baseUrl.TrimEnd('/') + "/";
        _http = new HttpClient
        {
            BaseAddress = new Uri(normalized),
            Timeout = TimeSpan.FromSeconds(90),
        };
    }

    public Task<AuthProvidersResponse> GetAuthProvidersAsync(CancellationToken ct = default)
        => SendAsync<AuthProvidersResponse>(HttpMethod.Get, "auth/providers", null, ct);

    public async Task<AuthSession> LoginWithEmailAsync(string email, string password, CancellationToken ct = default)
    {
        var session = await SendAsync<AuthSession>(
            HttpMethod.Post,
            "auth/login",
            new { email, password },
            ct);
        AccessToken = session.AccessToken;
        return session;
    }

    public async Task<AuthSession> DevLoginAsync(CancellationToken ct = default)
    {
        var session = await SendAsync<AuthSession>(HttpMethod.Post, "auth/dev-login", null, ct);
        AccessToken = session.AccessToken;
        return session;
    }

    public Task<EmailRegisterResponse> RegisterWithEmailAsync(
        string email,
        string password,
        string confirmPassword,
        string verificationCode,
        string? displayName,
        CancellationToken ct = default)
        => SendAsync<EmailRegisterResponse>(
            HttpMethod.Post,
            "auth/register",
            new
            {
                email,
                password,
                confirm_password = confirmPassword,
                verification_code = verificationCode,
                display_name = displayName,
            },
            ct);

    public Task RequestVerificationCodeAsync(string email, CancellationToken ct = default)
        => SendAsync<JsonElement>(HttpMethod.Post, "auth/verification-code", new { email }, ct);

    /// <summary>请求密码重置邮件（不暴露邮箱是否注册）。</summary>
    public Task RequestPasswordResetAsync(string email, CancellationToken ct = default)
        => SendAsync<JsonElement>(HttpMethod.Post, "auth/password-reset/request", new { email }, ct);

    /// <summary>用一次性令牌设置新密码。</summary>
    public Task ConfirmPasswordResetAsync(
        string token,
        string password,
        string confirmPassword,
        CancellationToken ct = default)
        => SendAsync<JsonElement>(
            HttpMethod.Post,
            "auth/password-reset",
            new { token, password, confirm_password = confirmPassword },
            ct);

    /// <summary>重新发送邮箱验证链接。</summary>
    public Task RequestEmailVerificationAsync(string email, CancellationToken ct = default)
        => SendAsync<JsonElement>(HttpMethod.Post, "auth/verify-email/request", new { email }, ct);

    /// <summary>用一次性令牌完成邮箱验证。</summary>
    public Task ConfirmEmailVerificationAsync(string token, CancellationToken ct = default)
        => SendAsync<JsonElement>(HttpMethod.Post, "auth/verify-email", new { token }, ct);

    public Task<AuthUser> GetCurrentUserAsync(CancellationToken ct = default)
        => SendAsync<AuthUser>(HttpMethod.Get, "auth/me", null, ct);

    public Task LogoutAsync(CancellationToken ct = default)
        => SendAsync<JsonElement>(HttpMethod.Post, "auth/logout", null, ct);

    public Task<MemoListResponse> ListMemosAsync(
        string? status = null,
        string? query = null,
        string? type = null,
        int limit = 200,
        int offset = 0,
        string? sort = null,
        string? category = null,
        bool starredOnly = false,
        CancellationToken ct = default)
    {
        var parameters = new List<string> { $"limit={limit}" };
        if (offset > 0)
        {
            parameters.Add($"offset={offset}");
        }
        if (!string.IsNullOrWhiteSpace(status))
        {
            parameters.Add($"status={Uri.EscapeDataString(status)}");
        }
        if (!string.IsNullOrWhiteSpace(query))
        {
            parameters.Add($"q={Uri.EscapeDataString(query)}");
        }
        if (!string.IsNullOrWhiteSpace(type))
        {
            parameters.Add($"type={Uri.EscapeDataString(type)}");
        }
        if (!string.IsNullOrWhiteSpace(sort))
        {
            parameters.Add($"sort={Uri.EscapeDataString(sort)}");
        }
        if (!string.IsNullOrWhiteSpace(category))
        {
            parameters.Add($"category={Uri.EscapeDataString(category)}");
        }
        if (starredOnly)
        {
            parameters.Add("starred=true");
        }
        return SendAsync<MemoListResponse>(
            HttpMethod.Get,
            "memos?" + string.Join("&", parameters),
            null,
            ct);
    }

    public Task<Memo> CreateMemoAsync(MemoCreateRequest request, CancellationToken ct = default)
        => SendAsync<Memo>(HttpMethod.Post, "memos", request, ct);

    /// <summary>调用 OpenAI 兼容后端，把会议转写整理成纪要。</summary>
    public Task<MeetingSummaryResponse> SummarizeMeetingAsync(
        string title,
        string transcript,
        CancellationToken ct = default)
        => SendAsync<MeetingSummaryResponse>(
            HttpMethod.Post,
            "meeting/summary",
            new { title, transcript },
            ct);

    public Task<MemoCountsResponse> GetMemoCountsAsync(CancellationToken ct = default)
        => SendAsync<MemoCountsResponse>(HttpMethod.Get, "memos/counts", null, ct);

    public Task<Memo> UpdateMemoAsync(string memoId, MemoUpdateRequest request, CancellationToken ct = default)
        => SendAsync<Memo>(HttpMethod.Patch, $"memos/{memoId}", request, ct);

    public Task<Memo> RestoreMemoAsync(string memoId, int expectedVersion, CancellationToken ct = default)
        => SendAsync<Memo>(
            HttpMethod.Post,
            $"memos/{memoId}/restore?expected_version={expectedVersion}",
            null,
            ct);

    public Task PermanentlyDeleteMemoAsync(string memoId, int expectedVersion, CancellationToken ct = default)
        => SendAsync<JsonElement>(
            HttpMethod.Delete,
            $"memos/{memoId}/permanent?expected_version={expectedVersion}",
            null,
            ct);

    /// <summary>清空回收站，返回永久删除的条目数。</summary>
    public async Task<int> EmptyTrashAsync(CancellationToken ct = default)
    {
        var result = await SendAsync<JsonElement>(HttpMethod.Delete, "memos/trash", null, ct);
        return result.ValueKind == JsonValueKind.Object &&
               result.TryGetProperty("deleted_count", out var count)
            ? count.GetInt32()
            : 0;
    }

    public Task<WordLookupResponse> LookupWordAsync(string word, CancellationToken ct = default)
        => SendAsync<WordLookupResponse>(HttpMethod.Post, "words/lookup", new { word }, ct);

    public Task<ReviewQueueResponse> GetReviewQueueAsync(
        int limit = 20,
        string? type = null,
        CancellationToken ct = default)
    {
        var path = $"review-queue?limit={limit}";
        if (!string.IsNullOrWhiteSpace(type))
        {
            path += $"&type={Uri.EscapeDataString(type)}";
        }
        return SendAsync<ReviewQueueResponse>(HttpMethod.Get, path, null, ct);
    }

    public Task<List<ResourceCategoryOption>> ListResourceCategoriesAsync(CancellationToken ct = default)
        => SendAsync<List<ResourceCategoryOption>>(HttpMethod.Get, "resource-categories", null, ct);

    public Task<ResourceCategoryOption> CreateResourceCategoryAsync(
        string name,
        string? description,
        string? parentCode = null,
        CancellationToken ct = default)
        => SendAsync<ResourceCategoryOption>(
            HttpMethod.Post,
            "resource-categories",
            new { Name = name, Description = description, ParentCode = parentCode },
            ct);

    public Task<ResourceCategoryOption> UpdateResourceCategoryAsync(
        string categoryId,
        int expectedVersion,
        bool? isActive,
        string? name = null,
        string? description = null,
        CancellationToken ct = default)
        => SendAsync<ResourceCategoryOption>(
            HttpMethod.Patch,
            $"resource-categories/{categoryId}",
            new
            {
                ExpectedVersion = expectedVersion,
                IsActive = isActive,
                Name = name,
                Description = description,
            },
            ct);

    public Task<List<ResourceCategoryRule>> ListResourceCategoryRulesAsync(CancellationToken ct = default)
        => SendAsync<List<ResourceCategoryRule>>(HttpMethod.Get, "resource-category-rules", null, ct);

    public Task<ResourceCategoryRule> CreateResourceCategoryRuleAsync(
        string? name,
        string categoryCode,
        string matchType,
        string pattern,
        int priority,
        CancellationToken ct = default)
        => SendAsync<ResourceCategoryRule>(
            HttpMethod.Post,
            "resource-category-rules",
            new
            {
                Name = name,
                CategoryCode = categoryCode,
                MatchType = matchType,
                Pattern = pattern,
                Priority = priority,
            },
            ct);

    public Task DeleteResourceCategoryAsync(string categoryId, CancellationToken ct = default)
        => SendAsync<JsonElement>(
            HttpMethod.Delete,
            $"resource-categories/{categoryId}",
            null,
            ct);

    public Task DeleteResourceCategoryRuleAsync(string ruleId, CancellationToken ct = default)
        => SendAsync<JsonElement>(
            HttpMethod.Delete,
            $"resource-category-rules/{ruleId}",
            null,
            ct);

    public Task<LinkHealthListResponse> GetLinkHealthAsync(
        string? status = null,
        int limit = 200,
        int offset = 0,
        CancellationToken ct = default)
    {
        var path = $"resources/link-health?limit={limit}&offset={offset}";
        if (!string.IsNullOrWhiteSpace(status))
        {
            path += $"&status={Uri.EscapeDataString(status)}";
        }
        return SendAsync<LinkHealthListResponse>(HttpMethod.Get, path, null, ct);
    }

    public Task<Memo> ApplyLinkHealthActionAsync(
        string memoId,
        int expectedVersion,
        string action,
        string? newUrl = null,
        CancellationToken ct = default)
        => SendAsync<Memo>(
            HttpMethod.Post,
            $"resources/{memoId}/link-health-actions",
            new LinkHealthActionRequest
            {
                ExpectedVersion = expectedVersion,
                Action = action,
                NewUrl = newUrl,
            },
            ct);

    public Task<Memo> MergeWordAsync(
        string memoId,
        int expectedVersion,
        string? phonetic,
        string? meaning,
        string? example,
        CancellationToken ct = default)
        => SendAsync<Memo>(
            HttpMethod.Post,
            $"words/{memoId}/merge",
            new
            {
                ExpectedVersion = expectedVersion,
                WordPhonetic = phonetic,
                WordMeaning = meaning,
                WordExample = example,
            },
            ct);

    /// <summary>服务端语音合成（sanoTTS），返回 WAV 字节。不可用时抛出异常。</summary>
    public async Task<byte[]> SynthesizeSpeechAsync(
        string text,
        string? voice = null,
        CancellationToken ct = default)
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, "speech/tts");
        if (!string.IsNullOrWhiteSpace(AccessToken))
        {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", AccessToken);
        }
        var payload = JsonSerializer.Serialize(
            new { text, voice = string.IsNullOrWhiteSpace(voice) ? null : voice },
            JsonOptions);
        request.Content = new StringContent(payload, Encoding.UTF8, "application/json");
        request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("audio/wav"));

        using var response = await _http.SendAsync(request, ct);
        var body = await response.Content.ReadAsByteArrayAsync(ct);
        if (!response.IsSuccessStatusCode)
        {
            throw new MemoApiException((int)response.StatusCode, Encoding.UTF8.GetString(body));
        }
        return body;
    }

    public Task<BookmarkImportPreview> PreviewBookmarkImportAsync(
        IReadOnlyCollection<BookmarkInput> items,
        CancellationToken ct = default)
        => SendAsync<BookmarkImportPreview>(
            HttpMethod.Post,
            "bookmark-imports/preview",
            new { Items = items },
            ct);

    public Task<BookmarkImportBatch> CreateBookmarkImportAsync(
        IReadOnlyCollection<BookmarkInput> items,
        CancellationToken ct = default)
        => SendAsync<BookmarkImportBatch>(
            HttpMethod.Post,
            "bookmark-imports",
            new { Items = items },
            ct);

    public Task<BookmarkImportBatch> GetBookmarkImportAsync(string batchId, CancellationToken ct = default)
        => SendAsync<BookmarkImportBatch>(HttpMethod.Get, $"bookmark-imports/{batchId}", null, ct);

    public Task<BookmarkImportBatch> RetryBookmarkImportAsync(string batchId, CancellationToken ct = default)
        => SendAsync<BookmarkImportBatch>(
            HttpMethod.Post,
            $"bookmark-imports/{batchId}/retry",
            null,
            ct);

    public Task<BookmarkImportBatch> UndoBookmarkImportAsync(string batchId, CancellationToken ct = default)
        => SendAsync<BookmarkImportBatch>(
            HttpMethod.Post,
            $"bookmark-imports/{batchId}/undo",
            null,
            ct);

    public Task<Memo> SubmitReviewAsync(string memoId, int expectedVersion, string feedback, CancellationToken ct = default)
        => SendAsync<Memo>(
            HttpMethod.Post,
            $"words/{memoId}/reviews",
            new ReviewSubmitRequest { ExpectedVersion = expectedVersion, Feedback = feedback },
            ct);

    public Task<Memo> SkipReviewAsync(string memoId, int expectedVersion, CancellationToken ct = default)
        => SendAsync<Memo>(
            HttpMethod.Post,
            $"review-queue/{memoId}/skip",
            new { expected_version = expectedVersion },
            ct);

    /// <summary>上传语音录音（裸 audio/mp4 请求体 + 时长头）。</summary>
    public async Task<Memo> UploadAudioAsync(
        string memoId,
        int expectedVersion,
        int durationMs,
        string filePath,
        CancellationToken ct = default)
    {
        using var request = new HttpRequestMessage(
            HttpMethod.Post,
            $"memos/{memoId}/audio?expected_version={expectedVersion}");
        if (!string.IsNullOrWhiteSpace(AccessToken))
        {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", AccessToken);
        }
        request.Headers.Add("X-Audio-Duration-Ms", durationMs.ToString());
        var bytes = await File.ReadAllBytesAsync(filePath, ct);
        var content = new ByteArrayContent(bytes);
        content.Headers.ContentType = new MediaTypeHeaderValue("audio/mp4");
        request.Content = content;

        using var response = await _http.SendAsync(request, ct);
        var text = await response.Content.ReadAsStringAsync(ct);
        if (!response.IsSuccessStatusCode)
        {
            throw new MemoApiException((int)response.StatusCode, text);
        }
        return JsonSerializer.Deserialize<Memo>(text, JsonOptions)!;
    }

    /// <summary>下载某条录音的原始字节（用于播放）。</summary>
    public async Task<byte[]> DownloadAudioAsync(string memoId, CancellationToken ct = default)
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, $"memos/{memoId}/audio");
        if (!string.IsNullOrWhiteSpace(AccessToken))
        {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", AccessToken);
        }
        using var response = await _http.SendAsync(request, ct);
        if (!response.IsSuccessStatusCode)
        {
            var text = await response.Content.ReadAsStringAsync(ct);
            throw new MemoApiException((int)response.StatusCode, text);
        }
        return await response.Content.ReadAsByteArrayAsync(ct);
    }

    /// <summary>创建一条图片收藏（正文可为空，图片随后以裸字节上传）。</summary>
    public Task<Memo> CreateImageMemoAsync(
        string? title,
        string body,
        CancellationToken ct = default)
        => SendAsync<Memo>(
            HttpMethod.Post,
            "memos",
            new MemoCreateRequest
            {
                Type = MemoTypes.Image,
                Title = string.IsNullOrWhiteSpace(title) ? null : title.Trim(),
                Body = body ?? string.Empty,
            },
            ct);

    /// <summary>上传或替换图片收藏的原图（读取本地文件后按裸二进制请求体发送）。</summary>
    public async Task<Memo> UploadMemoImageAsync(
        string memoId,
        int expectedVersion,
        string filePath,
        string mimeType,
        CancellationToken ct = default)
    {
        var bytes = await File.ReadAllBytesAsync(filePath, ct);
        return await UploadMemoImageAsync(memoId, expectedVersion, bytes, mimeType, ct);
    }

    /// <summary>上传或替换图片收藏的原图（裸二进制请求体，支持压缩后的字节数组）。</summary>
    public async Task<Memo> UploadMemoImageAsync(
        string memoId,
        int expectedVersion,
        byte[] bytes,
        string mimeType,
        CancellationToken ct = default)
    {
        using var request = new HttpRequestMessage(
            HttpMethod.Post,
            $"memos/{memoId}/image?expected_version={expectedVersion}");
        if (!string.IsNullOrWhiteSpace(AccessToken))
        {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", AccessToken);
        }
        var content = new ByteArrayContent(bytes);
        content.Headers.ContentType = new MediaTypeHeaderValue(mimeType);
        request.Content = content;

        using var response = await _http.SendAsync(request, ct);
        var text = await response.Content.ReadAsStringAsync(ct);
        if (!response.IsSuccessStatusCode)
        {
            throw new MemoApiException((int)response.StatusCode, text);
        }
        return JsonSerializer.Deserialize<Memo>(text, JsonOptions)!;
    }

    /// <summary>下载图片收藏的原图或缩略图字节（需要登录态）。</summary>
    public async Task<byte[]> DownloadMemoImageAsync(
        string memoId,
        bool thumbnail = false,
        CancellationToken ct = default)
    {
        var path = thumbnail ? $"memos/{memoId}/image/thumbnail" : $"memos/{memoId}/image";
        using var request = new HttpRequestMessage(HttpMethod.Get, path);
        if (!string.IsNullOrWhiteSpace(AccessToken))
        {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", AccessToken);
        }
        using var response = await _http.SendAsync(request, ct);
        if (!response.IsSuccessStatusCode)
        {
            var text = await response.Content.ReadAsStringAsync(ct);
            throw new MemoApiException((int)response.StatusCode, text);
        }
        return await response.Content.ReadAsByteArrayAsync(ct);
    }

    /// <summary>按 id 读取单条 memo（上传后的后台 OCR 结果需要重新拉取才会出现）。</summary>
    public Task<Memo> GetMemoAsync(string memoId, CancellationToken ct = default)
        => SendAsync<Memo>(HttpMethod.Get, $"memos/{memoId}", null, ct);

    /// <summary>手动（重新）识别图片收藏的文字：POST memos/{id}/image/ocr，返回更新后的 memo。</summary>
    public Task<Memo> RecognizeMemoImageOcrAsync(string memoId, CancellationToken ct = default)
        => SendAsync<Memo>(HttpMethod.Post, $"memos/{memoId}/image/ocr", null, ct);

    private async Task<T> SendAsync<T>(
        HttpMethod method,
        string path,
        object? body,
        CancellationToken ct)
    {
        using var request = new HttpRequestMessage(method, path);
        if (!string.IsNullOrWhiteSpace(AccessToken))
        {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", AccessToken);
        }
        if (body is not null)
        {
            var json = JsonSerializer.Serialize(body, JsonOptions);
            request.Content = new StringContent(json, Encoding.UTF8, "application/json");
        }

        using var response = await _http.SendAsync(request, ct);
        var text = await response.Content.ReadAsStringAsync(ct);
        if (!response.IsSuccessStatusCode)
        {
            throw new MemoApiException((int)response.StatusCode, text);
        }
        if (typeof(T) == typeof(JsonElement))
        {
            return text.Length == 0
                ? (T)(object)default(JsonElement)
                : (T)(object)JsonDocument.Parse(text).RootElement.Clone();
        }
        if (string.IsNullOrWhiteSpace(text))
        {
            return default!;
        }
        return JsonSerializer.Deserialize<T>(text, JsonOptions)
            ?? throw new MemoApiException((int)response.StatusCode, "响应内容无法解析");
    }
}
