namespace MemoIsle.Desktop.Services;

/// <summary>
/// 图片收藏支持的文件类型与限制，与后端 <c>POST /memos/{id}/image</c> 契约保持一致。
/// 后端按 Content-Type 校验并二次解码，客户端只在选择阶段做一次预检，避免明显的无效上传。
/// </summary>
public static class MemoImageFiles
{
    /// <summary>后端单张图片上限 20 MB。</summary>
    public const long MaxBytes = 20L * 1024 * 1024;

    /// <summary>文件选择器与拖拽校验使用的扩展名集合。</summary>
    public static IReadOnlyList<string> Extensions { get; } =
        new[] { ".png", ".jpg", ".jpeg", ".webp", ".gif" };

    /// <summary>扩展名是否受支持。</summary>
    public static bool IsSupported(string? filePath) => MimeTypeFor(filePath) is not null;

    /// <summary>按扩展名推断 MIME（与后端接受的类型一致），不支持时返回 null。</summary>
    public static string? MimeTypeFor(string? filePath)
    {
        var extension = Path.GetExtension(filePath ?? string.Empty).ToLowerInvariant();
        return extension switch
        {
            ".png" => "image/png",
            ".jpg" or ".jpeg" => "image/jpeg",
            ".webp" => "image/webp",
            ".gif" => "image/gif",
            _ => null,
        };
    }

    /// <summary>服务端返回的 MIME 对应的保存扩展名（未知时回退 .png）。</summary>
    public static string ExtensionForMime(string? mimeType) => mimeType?.ToLowerInvariant() switch
    {
        "image/jpeg" => ".jpg",
        "image/webp" => ".webp",
        "image/gif" => ".gif",
        _ => ".png",
    };
}
