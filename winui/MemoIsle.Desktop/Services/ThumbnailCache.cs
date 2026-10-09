using System.Collections.Concurrent;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;

namespace MemoIsle.Desktop.Services;

/// <summary>
/// 缩略图缓存：避免列表滚动时对同一 URL 反复下载解码。
/// 内存缓存按 URL 复用 BitmapImage（DecodePixelWidth 限尺寸），并限制条目数。
/// </summary>
public static class ThumbnailCache
{
    private const int MaxEntries = 200;
    private const int DecodeWidth = 320;

    private static readonly ConcurrentDictionary<string, BitmapImage> Cache = new();
    private static readonly ConcurrentQueue<string> Order = new();

    public static ImageSource? Get(string? url)
    {
        if (string.IsNullOrWhiteSpace(url) || !Uri.TryCreate(url, UriKind.Absolute, out var uri))
        {
            return null;
        }
        var key = uri.ToString();
        if (Cache.TryGetValue(key, out var cached))
        {
            return cached;
        }
        try
        {
            var image = new BitmapImage(uri)
            {
                // 缩略图按显示宽度解码，减少内存占用。
                DecodePixelWidth = DecodeWidth,
                CreateOptions = BitmapCreateOptions.IgnoreImageCache,
            };
            Cache[key] = image;
            Order.Enqueue(key);
            TrimIfNeeded();
            return image;
        }
        catch (Exception)
        {
            return null;
        }
    }

    private static void TrimIfNeeded()
    {
        while (Order.Count > MaxEntries && Order.TryDequeue(out var oldest))
        {
            Cache.TryRemove(oldest, out _);
        }
    }
}
