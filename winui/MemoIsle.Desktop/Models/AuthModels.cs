using System.Text.Json.Serialization;

namespace MemoIsle.Desktop.Models;

public sealed class AuthProviderInfo
{
    public string Provider { get; set; } = string.Empty;
    public string Label { get; set; } = string.Empty;
    public bool Enabled { get; set; }
}

public sealed class AuthProvidersResponse
{
    public List<AuthProviderInfo> Providers { get; set; } = new();
    public bool DevLoginAvailable { get; set; }
    public bool EmailLoginEnabled { get; set; } = true;
}

public sealed class AuthUser
{
    public string Id { get; set; } = string.Empty;
    public string? Email { get; set; }
    public bool EmailVerified { get; set; }
    public string DisplayName { get; set; } = string.Empty;
}

public sealed class AuthSession
{
    public string AccessToken { get; set; } = string.Empty;
    public AuthUser User { get; set; } = new();
}

public sealed class EmailRegisterResponse
{
    public AuthUser User { get; set; } = new();
}

public sealed class MemoListResponse
{
    public List<Memo> Items { get; set; } = new();
    public int TotalCount { get; set; }
}

/// <summary>当前用户各类型的条目数量（侧栏计数用，不受当前分页影响）。</summary>
public sealed class MemoCountsResponse
{
    public int TotalCount { get; set; }
    public int WordCount { get; set; }
    public int ResourceCount { get; set; }
    public int IdeaCount { get; set; }
    public int ImageCount { get; set; }
    public int InboxCount { get; set; }
}

public sealed class WordLookupSense
{
    public int Index { get; set; }
    public string? PartOfSpeech { get; set; }
    public string Definition { get; set; } = string.Empty;
    public string? Example { get; set; }
}

public sealed class WordLookupResponse
{
    public string Word { get; set; } = string.Empty;
    public string Lemma { get; set; } = string.Empty;
    public string? Phonetic { get; set; }
    public string? UsAudioUrl { get; set; }
    public string? UkAudioUrl { get; set; }
    public List<WordLookupSense> Senses { get; set; } = new();
}

public sealed class ReviewQueueResponse
{
    public List<Memo> Items { get; set; } = new();
    public int WordCount { get; set; }
    public int ResourceCount { get; set; }
    public int IdeaCount { get; set; }

    [JsonIgnore]
    public int TotalCount => WordCount + ResourceCount + IdeaCount;
}

/// <summary>创建资料请求体（字段名按 snake_case 序列化）。</summary>
public sealed class MemoCreateRequest
{
    public string ClientId { get; set; } = Guid.NewGuid().ToString("D");
    public string Type { get; set; } = MemoTypes.Idea;
    public string? Title { get; set; }
    public string Body { get; set; } = string.Empty;
    public string? Transcript { get; set; }
    public string? SourceUrl { get; set; }
    public string? SourceTitle { get; set; }
    public string? WordPhonetic { get; set; }
    public string? WordMeaning { get; set; }
    public string? WordExample { get; set; }
    public List<string> Tags { get; set; } = new();
    public bool Starred { get; set; }
    public bool? AllowDuplicate { get; set; }
}

/// <summary>会议纪要生成结果。</summary>
public sealed class MeetingSummaryResponse
{
    public string Summary { get; set; } = string.Empty;
}

/// <summary>更新资料请求体：携带 expected_version 做乐观并发。</summary>
public sealed class MemoUpdateRequest
{
    public int ExpectedVersion { get; set; }
    public string? Title { get; set; }
    public string? Body { get; set; }
    public string? SourceUrl { get; set; }
    public string? SourceTitle { get; set; }
    public string? WordPhonetic { get; set; }
    public string? WordMeaning { get; set; }
    public string? WordExample { get; set; }
    public string? ResourceReadingStatus { get; set; }
    public string? ResourceCategory { get; set; }
    public List<string>? ResourceCategories { get; set; }
    public List<string>? Collections { get; set; }
    public bool? Starred { get; set; }
    public string? Status { get; set; }
}

public sealed class ReviewSubmitRequest
{
    public int ExpectedVersion { get; set; }
    public string Feedback { get; set; } = "remembered";
}

/// <summary>后端返回的系统/用户自定义资料分类。</summary>
public sealed class ResourceCategoryOption
{
    public string? Id { get; set; }
    public string Code { get; set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
    public string? Description { get; set; }
    public bool IsSystem { get; set; }
    public bool IsActive { get; set; }
    public int Version { get; set; }
    public string? ParentCode { get; set; }
    public int Depth { get; set; } = 1;
    public string? Path { get; set; }
}

/// <summary>网页巡检中心列表与状态摘要。</summary>
public sealed class LinkHealthListResponse
{
    public List<Memo> Items { get; set; } = new();
    public Dictionary<string, int> Counts { get; set; } = new();
}

/// <summary>处理一条巡检结果。</summary>
public sealed class LinkHealthActionRequest
{
    public int ExpectedVersion { get; set; }
    public string Action { get; set; } = "retry";
    public string? NewUrl { get; set; }
}
