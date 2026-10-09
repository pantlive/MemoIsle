namespace MemoIsle.Desktop.Models;

/// <summary>浏览器本地解析后提交的一条书签。</summary>
public sealed class BookmarkInput
{
    public string ClientItemId { get; set; } = string.Empty;
    public string Title { get; set; } = string.Empty;
    public string Url { get; set; } = string.Empty;
    public string? FolderPath { get; set; }
}

/// <summary>单条书签的导入校验结果。</summary>
public sealed class BookmarkPreviewItem
{
    public string ClientItemId { get; set; } = string.Empty;
    public string Title { get; set; } = string.Empty;
    public string Url { get; set; } = string.Empty;
    public string? NormalizedUrl { get; set; }
    public string? FolderPath { get; set; }
    public string Status { get; set; } = string.Empty;
    public string? ExistingMemoId { get; set; }
    public string? ErrorCode { get; set; }

    public string StatusLabel => Status switch
    {
        "valid" => "可导入",
        "duplicate" => "资料库已有",
        "invalid" => "链接无效",
        _ => Status,
    };
}

public sealed class BookmarkImportPreview
{
    public int TotalCount { get; set; }
    public int ValidCount { get; set; }
    public int DuplicateCount { get; set; }
    public int InvalidCount { get; set; }
    public List<BookmarkPreviewItem> Items { get; set; } = new();
}

public sealed class BookmarkImportItemRead
{
    public string ClientItemId { get; set; } = string.Empty;
    public string Title { get; set; } = string.Empty;
    public string SourceUrl { get; set; } = string.Empty;
    public string? NormalizedUrl { get; set; }
    public string? FolderPath { get; set; }
    public string Status { get; set; } = string.Empty;
    public string? MemoId { get; set; }
    public string? ExistingMemoId { get; set; }
    public string? ErrorCode { get; set; }
}

/// <summary>书签导入批次及其进度。</summary>
public sealed class BookmarkImportBatch
{
    public string Id { get; set; } = string.Empty;
    public string Status { get; set; } = string.Empty;
    public int TotalCount { get; set; }
    public int ValidCount { get; set; }
    public int DuplicateCount { get; set; }
    public int InvalidCount { get; set; }
    public int ImportedCount { get; set; }
    public int FailedCount { get; set; }
    public string CreatedAt { get; set; } = string.Empty;
    public string UpdatedAt { get; set; } = string.Empty;
    public string? UndoneAt { get; set; }
    public List<BookmarkImportItemRead> Items { get; set; } = new();

    public bool IsRunning => Status is "pending" or "processing";
    public string ProgressLabel =>
        $"已导入 {ImportedCount} 条 · 跳过重复 {DuplicateCount} 条 · 链接无效 {InvalidCount} 条 · 失败 {FailedCount} 条";
}
