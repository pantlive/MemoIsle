using System.Text.Json.Serialization;

namespace MemoIsle.Desktop.Models;

/// <summary>与后端 /memos 返回结构对齐的资料条目。</summary>
public sealed class Memo
{
    public string? Id { get; set; }
    public string ClientId { get; set; } = string.Empty;
    public string Type { get; set; } = "idea";
    public string Title { get; set; } = string.Empty;
    public string Body { get; set; } = string.Empty;
    public string? SourceUrl { get; set; }
    public string? SourceTitle { get; set; }
    public string? ResourceDescription { get; set; }
    public string? ResourceSiteName { get; set; }
    public string? ResourceImageUrl { get; set; }
    public string? ResourceCategory { get; set; }
    public string? ResourceCategoryLabel { get; set; }
    public List<string> ResourceCategories { get; set; } = new();
    public string? ResourceKind { get; set; }
    public string? ResourceReadingStatus { get; set; }
    public string ResourceCategoryStatus { get; set; } = "none";
    public string ResourceMetadataStatus { get; set; } = "none";
    public List<string> ResourceAutoTags { get; set; } = new();
    public string? ResourceImportFolder { get; set; }
    public string LinkHealthStatus { get; set; } = "unchecked";
    public int? LinkHealthHttpStatus { get; set; }
    public string? LinkHealthError { get; set; }
    public string? LinkLastCheckedAt { get; set; }
    public string? LinkLastSuccessAt { get; set; }
    public string? LinkEffectiveUrl { get; set; }
    public string? WordPhonetic { get; set; }
    public string? WordMeaning { get; set; }
    public string? WordExample { get; set; }
    public int Familiarity { get; set; }
    public int ReviewCount { get; set; }
    public string? LastReviewAt { get; set; }
    public string? NextReviewAt { get; set; }
    public string? AudioMimeType { get; set; }
    public int? AudioSizeBytes { get; set; }
    public int? AudioDurationMs { get; set; }
    public string? ImageMimeType { get; set; }
    public int? ImageSizeBytes { get; set; }
    public int? ImageWidth { get; set; }
    public int? ImageHeight { get; set; }
    public string? ImageHash { get; set; }
    public string? ImageOcrText { get; set; }
    public string ImageOcrStatus { get; set; } = "none";
    public string? ImageOcrError { get; set; }
    public string? ImageOcrSource { get; set; }
    public List<string> ImageAutoTags { get; set; } = new();
    public string? ImageOcrUpdatedAt { get; set; }
    public string? Transcript { get; set; }
    public string TranscriptStatus { get; set; } = "none";
    public List<string> Tags { get; set; } = new();
    public List<string> Collections { get; set; } = new();
    public bool Starred { get; set; }
    public string Status { get; set; } = "active";
    public int Version { get; set; }
    public string CreatedAt { get; set; } = string.Empty;
    public string UpdatedAt { get; set; } = string.Empty;
    public string? DeletedAt { get; set; }

    [JsonIgnore]
    public bool IsWord => Type == MemoTypes.Word;

    [JsonIgnore]
    public bool IsResource => Type == MemoTypes.Resource;

    [JsonIgnore]
    public bool IsIdea => Type == MemoTypes.Idea;

    [JsonIgnore]
    public bool IsImage => Type == MemoTypes.Image;

    [JsonIgnore]
    public bool IsNotImage => Type != MemoTypes.Image;

    /// <summary>是否已上传图片（MIME 非空即视为已关联图片）。</summary>
    [JsonIgnore]
    public bool HasImage => !string.IsNullOrWhiteSpace(ImageMimeType);

    /// <summary>
    /// 列表/卡片/详情展示用的缩略图。图片需要登录态下载，因此不参与 JSON 序列化，
    /// 由 AppState 在刷新时填充；列表 ItemsSource 重新赋值后 x:Bind 会读取最新值。
    /// </summary>
    [JsonIgnore]
    public Microsoft.UI.Xaml.Media.ImageSource? MemoImageSource { get; set; }

    /// <summary>缩略图是否已就绪（与占位图标互斥显示）。</summary>
    [JsonIgnore]
    public bool HasMemoImageSource => MemoImageSource is not null;

    /// <summary>是否显示类型占位图标（图片缩略图就绪后隐藏）。</summary>
    [JsonIgnore]
    public bool ShowTypeGlyph => MemoImageSource is null;

    /// <summary>图片尺寸文案，如 "1280 × 720"；信息缺失时为空。</summary>
    [JsonIgnore]
    public string ImageDimensionLabel =>
        ImageWidth is int width && ImageHeight is int height && width > 0 && height > 0
            ? $"{width} × {height}"
            : string.Empty;

    /// <summary>图片大小文案（人类可读）。</summary>
    [JsonIgnore]
    public string ImageSizeLabel => FormatBytes(ImageSizeBytes);

    /// <summary>图片详情：尺寸 · 大小 · MIME，如 "1280 × 720 · 1.2 MB · image/png"。</summary>
    [JsonIgnore]
    public string ImageDetailLabel => string.Join(
        " · ",
        new[] { ImageDimensionLabel, ImageSizeLabel, ImageMimeType }
            .Where(value => !string.IsNullOrWhiteSpace(value)));

    /// <summary>是否已识别出图片文字（空字符串视为未识别到文字）。</summary>
    [JsonIgnore]
    public bool HasImageOcrText => !string.IsNullOrWhiteSpace(ImageOcrText);

    /// <summary>是否有 OCR 自动标签。</summary>
    [JsonIgnore]
    public bool HasImageAutoTags => ImageAutoTags is { Count: > 0 };

    /// <summary>是否正在排队 / 识别中（此时禁用对话框的重新识别按钮）。</summary>
    [JsonIgnore]
    public bool IsImageOcrBusy => ImageOcrStatus is "pending" or "processing";

    /// <summary>OCR 状态中文文案（none 未识别 / pending 排队中 / processing 识别中 / ready 已识别 / failed 识别失败 / disabled 服务端未启用）。</summary>
    [JsonIgnore]
    public string ImageOcrStatusLabel => DescribeImageOcrStatus(ImageOcrStatus);

    /// <summary>OCR 来源中文文案。</summary>
    [JsonIgnore]
    public string ImageOcrSourceLabel => ImageOcrSource switch
    {
        "local" => "本地识别",
        "llm" => "视觉模型",
        _ => string.Empty,
    };

    /// <summary>OCR 摘要：来源 + 识别时间，如 "本地识别 · 2025-01-02 03:04"；信息缺失时为空。</summary>
    [JsonIgnore]
    public string ImageOcrMetaLabel
    {
        get
        {
            var parts = new List<string>();
            if (!string.IsNullOrWhiteSpace(ImageOcrSourceLabel))
            {
                parts.Add(ImageOcrSourceLabel);
            }
            if (DateTimeOffset.TryParse(ImageOcrUpdatedAt, out var updated))
            {
                parts.Add(updated.ToLocalTime().ToString("yyyy-MM-dd HH:mm"));
            }
            return string.Join(" · ", parts);
        }
    }

    /// <summary>识别失败 / 服务端未启用时的错误文案；其他状态为空。</summary>
    [JsonIgnore]
    public string ImageOcrErrorText => ImageOcrStatus switch
    {
        "failed" => string.IsNullOrWhiteSpace(ImageOcrError)
            ? "图片文字识别失败，请稍后重试。"
            : ImageOcrError!,
        "disabled" => string.IsNullOrWhiteSpace(ImageOcrError)
            ? "服务端未启用图片文字识别。"
            : ImageOcrError!,
        _ => string.Empty,
    };

    /// <summary>状态码转中文文案（对话框在没有条目时也能复用）。</summary>
    public static string DescribeImageOcrStatus(string? status) => status switch
    {
        "pending" => "排队中",
        "processing" => "识别中",
        "ready" => "已识别",
        "failed" => "识别失败",
        "disabled" => "服务端未启用",
        _ => "未识别",
    };

    /// <summary>是否含可打开的链接（资料卡片显示"打开"按钮）。</summary>
    [JsonIgnore]
    public bool HasUrl => !string.IsNullOrWhiteSpace(SourceUrl);

    /// <summary>是否含可展示的缩略图/图标。</summary>
    [JsonIgnore]
    public bool HasThumbnail => !string.IsNullOrWhiteSpace(ResourceImageUrl);

    /// <summary>缩略图 ImageSource（x:Bind 函数绑定需要具体类型；走缓存避免重复下载）。</summary>
    [JsonIgnore]
    public Microsoft.UI.Xaml.Media.ImageSource? ThumbnailSource =>
        Services.ThumbnailCache.Get(ResourceImageUrl);

    /// <summary>资料分类显示名（优先自定义标签）。</summary>
    [JsonIgnore]
    public string CategoryDisplay
    {
        get
        {
            var primary = ResourceCategoryLabel
                ?? ResourceCategory switch
                {
                    "learning" => "学习资料",
                    "article" => "文章阅读",
                    "media" => "视频与音频",
                    "tool" => "工具与服务",
                    "book_paper" => "书籍与论文",
                    "product" => "商品与好物",
                    "other" => "其他",
                    null => string.Empty,
                    _ => ResourceCategory!,
                };
            var extraCount = ResourceCategories?.Count > 0
                ? ResourceCategories.Count - 1
                : 0;
            return extraCount > 0 ? $"{primary} 等{extraCount + 1}个" : primary;
        }
    }

    /// <summary>阅读状态显示名。</summary>
    [JsonIgnore]
    public string ReadingStatusDisplay => ResourceReadingStatus switch
    {
        "reading" => "阅读中",
        "completed" => "已完成",
        "archived" => "已归档",
        _ => "未读",
    };

    [JsonIgnore]
    public bool IsNotResource => Type != MemoTypes.Resource;

    /// <summary>资料链接的 Uri 形式，供标题直接作为超链接导航。</summary>
    [JsonIgnore]
    public Uri? SourceUri =>
        !string.IsNullOrWhiteSpace(SourceUrl) &&
        Uri.TryCreate(SourceUrl, UriKind.Absolute, out var uri)
            ? uri
            : null;

    /// <summary>是否含录音（灵感卡片显示"播放"按钮）。</summary>
    [JsonIgnore]
    public bool HasAudio => AudioDurationMs is not null || !string.IsNullOrWhiteSpace(AudioMimeType);

    /// <summary>是否含会议转写（列表显示"转写"查看按钮）。</summary>
    [JsonIgnore]
    public bool HasTranscript => !string.IsNullOrWhiteSpace(Transcript);

    /// <summary>回收站条目的保留剩余天数文案。</summary>
    [JsonIgnore]
    public string TrashRetentionLabel
    {
        get
        {
            var startText = DeletedAt ?? UpdatedAt;
            if (!DateTimeOffset.TryParse(startText, out var start))
            {
                return string.Empty;
            }
            var days = 30 - (int)(DateTimeOffset.UtcNow - start).TotalDays;
            return days <= 0 ? "即将永久删除" : $"还剩 {days} 天";
        }
    }

    /// <summary>巡检状态标签。</summary>
    [JsonIgnore]
    public string HealthStatusLabel => LinkHealthStatus switch
    {
        "failed" => "网页已失效",
        "redirected" => "网址已跳转",
        "changed" => "网页有更新",
        "auth_required" => "需要登录",
        "temporary_failure" => "暂时无法访问",
        "ignored" => "已忽略巡检",
        "healthy" => "网页正常",
        _ => "等待检查",
    };

    /// <summary>巡检详情（错误、HTTP 状态、跳转目标、检查时间）。</summary>
    [JsonIgnore]
    public string HealthDetail
    {
        get
        {
            var parts = new List<string>();
            if (!string.IsNullOrWhiteSpace(LinkHealthError))
            {
                parts.Add(LinkHealthError!);
            }
            if (LinkHealthHttpStatus is int httpStatus)
            {
                parts.Add($"HTTP {httpStatus}");
            }
            if (HasRedirectCandidate)
            {
                parts.Add($"建议改用 {LinkEffectiveUrl}");
            }
            if (!string.IsNullOrWhiteSpace(LinkLastCheckedAt))
            {
                var stamp = LinkLastCheckedAt!.Length >= 16
                    ? LinkLastCheckedAt[..16].Replace('T', ' ')
                    : LinkLastCheckedAt;
                parts.Add($"检查于 {stamp}");
            }
            return string.Join(" · ", parts);
        }
    }

    /// <summary>是否存在可采用的跳转候选网址。</summary>
    [JsonIgnore]
    public bool HasRedirectCandidate =>
        !string.IsNullOrWhiteSpace(LinkEffectiveUrl) &&
        !string.Equals(LinkEffectiveUrl, SourceUrl, StringComparison.OrdinalIgnoreCase);

    [JsonIgnore]
    public bool IsHealthIgnored => LinkHealthStatus == "ignored";

    /// <summary>网页内容有变化：可更新资料信息（标题/描述等元数据）。</summary>
    [JsonIgnore]
    public bool IsHealthChanged => LinkHealthStatus == "changed";

    [JsonIgnore]
    public bool IsHealthRetryable => !IsHealthIgnored;

    [JsonIgnore]
    public bool IsHealthIgnorable => !IsHealthIgnored && LinkHealthStatus != "healthy";

    /// <summary>列表卡片的摘要文本。</summary>
    [JsonIgnore]
    public string Summary => IsWord
        ? (string.IsNullOrWhiteSpace(WordMeaning) ? Body : WordMeaning!)
        : IsImage
            ? (string.IsNullOrWhiteSpace(Body) ? Title : Body)
            : Body;

    /// <summary>卡片右上角的附加信息（时间/来源/音标/图片尺寸）。</summary>
    [JsonIgnore]
    public string MetaLine
    {
        get
        {
            var time = UpdatedAt.Length >= 16 ? UpdatedAt[..16].Replace('T', ' ') : UpdatedAt;
            if (IsImage)
            {
                var parts = new[] { ImageDimensionLabel, ImageSizeLabel, time }
                    .Where(part => !string.IsNullOrWhiteSpace(part));
                return string.Join(" · ", parts);
            }
            if (IsResource)
            {
                var host = ResourceHost(SourceUrl);
                var parts = new[] { host, ResourceCategoryLabel, time }
                    .Where(part => !string.IsNullOrWhiteSpace(part));
                return string.Join(" · ", parts);
            }
            if (IsWord && !string.IsNullOrWhiteSpace(WordPhonetic))
            {
                return WordPhonetic!;
            }
            return time;
        }
    }

    [JsonIgnore]
    public string TypeLabel => Type switch
    {
        MemoTypes.Word => "单词",
        MemoTypes.Resource => "资料",
        MemoTypes.Image => "图片",
        _ => "灵感",
    };

    [JsonIgnore]
    public string StarLabel => Starred ? "★" : "☆";

    /// <summary>类型图标（Segoe Fluent Icons）。</summary>
    [JsonIgnore]
    public string TypeGlyph => Type switch
    {
        MemoTypes.Word => "\uE8C1",
        MemoTypes.Resource => "\uE8B7",
        MemoTypes.Image => "\uEB9F",
        _ => "\uE82F",
    };

    /// <summary>类型色块背景（对应 DESIGN.md 的 soft 色；深色模式使用低亮度版本）。</summary>
    [JsonIgnore]
    public Microsoft.UI.Xaml.Media.Brush TypeSoftBrush => Type switch
    {
        MemoTypes.Word => IsDarkTheme ? WordSoftDark : WordSoft,
        MemoTypes.Resource => IsDarkTheme ? ResourceSoftDark : ResourceSoft,
        MemoTypes.Image => IsDarkTheme ? ImageSoftDark : ImageSoft,
        _ => IsDarkTheme ? IdeaSoftDark : IdeaSoft,
    };

    /// <summary>类型图标前景色。</summary>
    [JsonIgnore]
    public Microsoft.UI.Xaml.Media.Brush TypeAccentBrush => Type switch
    {
        MemoTypes.Word => IsDarkTheme ? WordAccentDark : WordAccent,
        MemoTypes.Resource => IsDarkTheme ? ResourceAccentDark : ResourceAccent,
        MemoTypes.Image => IsDarkTheme ? ImageAccentDark : ImageAccent,
        _ => IsDarkTheme ? IdeaAccentDark : IdeaAccent,
    };

    /// <summary>当前是否处于深色主题。</summary>
    private static bool IsDarkTheme =>
        Microsoft.UI.Xaml.Application.Current?.RequestedTheme ==
        Microsoft.UI.Xaml.ApplicationTheme.Dark;

    private static readonly Microsoft.UI.Xaml.Media.SolidColorBrush WordSoft =
        new(Windows.UI.Color.FromArgb(255, 0xE2, 0xF2, 0xEE));

    private static readonly Microsoft.UI.Xaml.Media.SolidColorBrush ResourceSoft =
        new(Windows.UI.Color.FromArgb(255, 0xE8, 0xEE, 0xF5));

    private static readonly Microsoft.UI.Xaml.Media.SolidColorBrush ImageSoft =
        new(Windows.UI.Color.FromArgb(255, 0xF1, 0xE7, 0xF9));

    private static readonly Microsoft.UI.Xaml.Media.SolidColorBrush IdeaSoft =
        new(Windows.UI.Color.FromArgb(255, 0xFE, 0xF3, 0xE2));

    private static readonly Microsoft.UI.Xaml.Media.SolidColorBrush WordAccent =
        new(Windows.UI.Color.FromArgb(255, 0x17, 0x7A, 0x72));

    private static readonly Microsoft.UI.Xaml.Media.SolidColorBrush ResourceAccent =
        new(Windows.UI.Color.FromArgb(255, 0x3E, 0x63, 0x89));

    private static readonly Microsoft.UI.Xaml.Media.SolidColorBrush ImageAccent =
        new(Windows.UI.Color.FromArgb(255, 0x7B, 0x3F, 0xA8));

    private static readonly Microsoft.UI.Xaml.Media.SolidColorBrush IdeaAccent =
        new(Windows.UI.Color.FromArgb(255, 0xB3, 0x6A, 0x1E));

    // 深色模式：soft 背景压暗，前景提亮，保持类型可辨识。
    private static readonly Microsoft.UI.Xaml.Media.SolidColorBrush WordSoftDark =
        new(Windows.UI.Color.FromArgb(255, 0x12, 0x3A, 0x36));

    private static readonly Microsoft.UI.Xaml.Media.SolidColorBrush ResourceSoftDark =
        new(Windows.UI.Color.FromArgb(255, 0x1C, 0x2A, 0x3A));

    private static readonly Microsoft.UI.Xaml.Media.SolidColorBrush ImageSoftDark =
        new(Windows.UI.Color.FromArgb(255, 0x2C, 0x1F, 0x3A));

    private static readonly Microsoft.UI.Xaml.Media.SolidColorBrush IdeaSoftDark =
        new(Windows.UI.Color.FromArgb(255, 0x3A, 0x2C, 0x15));

    private static readonly Microsoft.UI.Xaml.Media.SolidColorBrush WordAccentDark =
        new(Windows.UI.Color.FromArgb(255, 0x5F, 0xBD, 0xB4));

    private static readonly Microsoft.UI.Xaml.Media.SolidColorBrush ResourceAccentDark =
        new(Windows.UI.Color.FromArgb(255, 0x8A, 0xB4, 0xE0));

    private static readonly Microsoft.UI.Xaml.Media.SolidColorBrush ImageAccentDark =
        new(Windows.UI.Color.FromArgb(255, 0xC2, 0x9B, 0xE8));

    private static readonly Microsoft.UI.Xaml.Media.SolidColorBrush IdeaAccentDark =
        new(Windows.UI.Color.FromArgb(255, 0xE6, 0xA6, 0x5C));

    /// <summary>复习卡片中展示的释义/正文。</summary>
    [JsonIgnore]
    public string ReviewDetail => IsWord
        ? string.Join(
            "  ",
            new[] { WordPhonetic, WordMeaning, WordExample }.Where(v => !string.IsNullOrWhiteSpace(v)))
        : Body;

    public static string ResourceHost(string? url)
    {
        if (string.IsNullOrWhiteSpace(url))
        {
            return string.Empty;
        }
        return Uri.TryCreate(url, UriKind.Absolute, out var uri)
            ? uri.Host.Replace("www.", string.Empty)
            : string.Empty;
    }

    /// <summary>字节数转人类可读文案（1.2 MB / 340 KB / 512 B）。</summary>
    private static string FormatBytes(int? bytes)
    {
        if (bytes is not int value || value <= 0)
        {
            return string.Empty;
        }
        if (value >= 1024 * 1024)
        {
            return $"{value / 1024.0 / 1024.0:0.#} MB";
        }
        if (value >= 1024)
        {
            return $"{value / 1024.0:0.#} KB";
        }
        return $"{value} B";
    }
}

public static class MemoTypes
{
    public const string Idea = "idea";
    public const string Word = "word";
    public const string Resource = "resource";
    public const string Image = "image";
}
