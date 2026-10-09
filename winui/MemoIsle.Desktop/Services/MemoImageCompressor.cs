using Windows.Foundation;
using Windows.Graphics.Imaging;
using Windows.Storage;
using Windows.Storage.Streams;

namespace MemoIsle.Desktop.Services;

/// <summary>
/// 图片收藏上传前的自动压缩：仅当图片会超出后端限制（20 MB / 单边 12000 px / 总像素 5000 万）时，
/// 才解码、缩放并重新编码；已在上限内的图片原样上传，不重编码、不损失画质。
/// </summary>
public static class MemoImageCompressor
{
    /// <summary>后端单张图片上限 20 MB。</summary>
    public const long MaxBytes = MemoImageFiles.MaxBytes;

    /// <summary>后端单边长度上限 12000 px。</summary>
    public const int MaxDimension = 12000;

    /// <summary>后端总像素上限 50 000 000。</summary>
    public const long MaxPixels = 50_000_000L;

    /// <summary>JPEG 起始画质。</summary>
    private const double InitialJpegQuality = 0.9;

    /// <summary>JPEG 最低画质：再低就改为继续缩小尺寸。</summary>
    private const double MinJpegQuality = 0.55;

    /// <summary>JPEG 画质下调步长。</summary>
    private const double JpegQualityStep = 0.1;

    /// <summary>需要继续压缩时每次缩小的比例。</summary>
    private const double ShrinkFactor = 0.75;

    /// <summary>编码尝试次数上限。</summary>
    private const int MaxAttempts = 12;

    /// <summary>
    /// 是否必须压缩：字节数、单边长度或总像素任一超出后端限制。
    /// 纯判断逻辑，不触碰文件与 WinRT，便于单独验证。
    /// </summary>
    public static bool ShouldCompress(long byteCount, int width, int height) =>
        byteCount > MaxBytes ||
        width > MaxDimension ||
        height > MaxDimension ||
        (long)width * height > MaxPixels;

    /// <summary>压缩结果：未压缩时 <see cref="Compressed"/> 为 false，字节与 MIME 均为原样。</summary>
    public sealed record MemoImageCompressionResult(
        byte[] Bytes,
        bool Compressed,
        string OriginalMimeType,
        string NewMimeType,
        long OriginalBytes,
        long NewBytes,
        int OriginalWidth,
        int OriginalHeight,
        int NewWidth,
        int NewHeight,
        bool AnimationDropped);

    /// <summary>
    /// 需要时压缩图片并返回可直接上传的字节；不需要压缩时原样返回文件内容。
    /// PNG / GIF 源保持 PNG（保留透明），其余源输出 JPEG；动图重编码后只剩第一帧。
    /// 解码或编码失败时抛出带中文提示的异常。
    /// </summary>
    public static async Task<MemoImageCompressionResult> CompressIfNeededAsync(
        string filePath,
        string mimeType,
        CancellationToken ct = default)
    {
        var originalBytes = new FileInfo(filePath).Length;
        var sourceMime = string.IsNullOrWhiteSpace(mimeType)
            ? MemoImageFiles.MimeTypeFor(filePath) ?? string.Empty
            : mimeType.Trim().ToLowerInvariant();

        uint pixelWidth;
        uint pixelHeight;
        uint frameCount;
        IRandomAccessStreamWithContentType stream;
        BitmapDecoder decoder;
        try
        {
            var file = await StorageFile.GetFileFromPathAsync(filePath);
            stream = await file.OpenReadAsync();
        }
        catch (Exception ex)
        {
            throw new InvalidOperationException("图片过大或已损坏，无法压缩", ex);
        }

        using (stream)
        {
            try
            {
                decoder = await BitmapDecoder.CreateAsync(stream);
            }
            catch (Exception ex)
            {
                throw new InvalidOperationException("图片过大或已损坏，无法压缩", ex);
            }

            pixelWidth = decoder.PixelWidth;
            pixelHeight = decoder.PixelHeight;
            frameCount = decoder.FrameCount;

            var width = (int)pixelWidth;
            var height = (int)pixelHeight;

            // 未超限：原样上传，绝不重编码。
            if (!ShouldCompress(originalBytes, width, height))
            {
                var raw = await File.ReadAllBytesAsync(filePath, ct);
                return new MemoImageCompressionResult(
                    raw,
                    false,
                    sourceMime,
                    sourceMime,
                    originalBytes,
                    raw.LongLength,
                    width,
                    height,
                    width,
                    height,
                    false);
            }

            // PNG / GIF 源保留 PNG（透明通道），其余源转 JPEG。
            var preserveAlpha = sourceMime is "image/png" or "image/gif";
            var encoderId = preserveAlpha ? BitmapEncoder.PngEncoderId : BitmapEncoder.JpegEncoderId;
            var newMime = preserveAlpha ? "image/png" : "image/jpeg";
            var animationDropped = sourceMime == "image/gif" && frameCount > 1;

            // 先按后端上限算一次目标尺寸，之后每次失败再按比例缩小（不会放大）。
            var scale = 1.0;
            var longestSide = Math.Max(width, height);
            if (longestSide > MaxDimension)
            {
                scale = Math.Min(scale, (double)MaxDimension / longestSide);
            }
            var totalPixels = (double)width * height;
            if (totalPixels > MaxPixels)
            {
                scale = Math.Min(scale, Math.Sqrt(MaxPixels / totalPixels));
            }

            var targetWidth = Math.Max(1, (int)Math.Floor(width * scale));
            var targetHeight = Math.Max(1, (int)Math.Floor(height * scale));
            var quality = InitialJpegQuality;
            byte[]? encoded = null;
            var encodedWidth = targetWidth;
            var encodedHeight = targetHeight;

            try
            {
                for (var attempt = 0; attempt < MaxAttempts; attempt++)
                {
                    ct.ThrowIfCancellationRequested();
                    var candidate = await EncodeAsync(
                        decoder,
                        targetWidth,
                        targetHeight,
                        encoderId,
                        preserveAlpha,
                        quality,
                        ct);
                    if (candidate.LongLength <= MaxBytes)
                    {
                        encoded = candidate;
                        encodedWidth = targetWidth;
                        encodedHeight = targetHeight;
                        break;
                    }

                    // JPEG 先把画质从 0.9 降到 0.55，再改为继续缩小尺寸。
                    if (!preserveAlpha && quality > MinJpegQuality)
                    {
                        quality = Math.Max(MinJpegQuality, quality - JpegQualityStep);
                        continue;
                    }

                    var nextWidth = Math.Max(1, (int)Math.Floor(targetWidth * ShrinkFactor));
                    var nextHeight = Math.Max(1, (int)Math.Floor(targetHeight * ShrinkFactor));
                    if (nextWidth == targetWidth && nextHeight == targetHeight)
                    {
                        break;
                    }
                    targetWidth = nextWidth;
                    targetHeight = nextHeight;
                    quality = InitialJpegQuality;
                }
            }
            catch (OperationCanceledException)
            {
                throw;
            }
            catch (Exception ex)
            {
                throw new InvalidOperationException("图片过大或已损坏，无法压缩", ex);
            }

            if (encoded is null)
            {
                throw new InvalidOperationException("图片压缩后仍超过 20 MB，请改用更小的图片。");
            }

            return new MemoImageCompressionResult(
                encoded,
                true,
                sourceMime,
                newMime,
                originalBytes,
                encoded.LongLength,
                width,
                height,
                encodedWidth,
                encodedHeight,
                animationDropped);
        }
    }

    /// <summary>
    /// 生成给用户看的中文压缩提示，与 Web / Android 端文案保持一致，例如：
    /// <c>图片已自动压缩后收藏：12.0 MB → 2.4 MB；尺寸 14400 × 9000 → 12000 × 7500；格式 PNG → JPEG</c>。
    /// 尺寸或格式未变化时对应片段省略；GIF 动图额外说明只剩第一帧。
    /// </summary>
    public static string DescribeCompression(MemoImageCompressionResult result)
    {
        var parts = new List<string>
        {
            $"{FormatBytes(result.OriginalBytes)} → {FormatBytes(result.NewBytes)}",
        };
        if (result.OriginalWidth != result.NewWidth || result.OriginalHeight != result.NewHeight)
        {
            parts.Add(
                $"尺寸 {result.OriginalWidth} × {result.OriginalHeight} → {result.NewWidth} × {result.NewHeight}");
        }
        if (!string.Equals(result.OriginalMimeType, result.NewMimeType, StringComparison.OrdinalIgnoreCase))
        {
            parts.Add($"格式 {FormatMime(result.OriginalMimeType)} → {FormatMime(result.NewMimeType)}");
        }
        if (result.AnimationDropped)
        {
            parts.Add("动图已转为静态图，仅保留第一帧");
        }
        return "图片已自动压缩后收藏：" + string.Join("；", parts);
    }

    /// <summary>按目标尺寸与画质编码一帧；JPEG 画质参数不受支持时忽略并沿用默认画质。</summary>
    private static async Task<byte[]> EncodeAsync(
        BitmapDecoder decoder,
        int width,
        int height,
        Guid encoderId,
        bool preserveAlpha,
        double quality,
        CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        var transform = new BitmapTransform
        {
            ScaledWidth = (uint)width,
            ScaledHeight = (uint)height,
            InterpolationMode = BitmapInterpolationMode.Fant,
        };
        using var bitmap = await decoder.GetSoftwareBitmapAsync(
            BitmapPixelFormat.Bgra8,
            BitmapAlphaMode.Premultiplied,
            transform,
            ExifOrientationMode.RespectExifOrientation,
            ColorManagementMode.ColorManageToSRgb);

        using var output = new InMemoryRandomAccessStream();
        var encoder = await BitmapEncoder.CreateAsync(encoderId, output);
        encoder.SetSoftwareBitmap(bitmap);
        if (!preserveAlpha)
        {
            try
            {
                var properties = new BitmapPropertySet
                {
                    { "ImageQuality", new BitmapTypedValue((float)quality, PropertyType.Single) },
                };
                await encoder.BitmapProperties.SetPropertiesAsync(properties);
            }
            catch (Exception)
            {
                // 编码器不支持画质参数时按默认画质编码，不影响流程。
            }
        }
        await encoder.FlushAsync();
        return await ReadBytesAsync(output);
    }

    /// <summary>读取内存流中的全部字节（流位置不影响结果）。</summary>
    private static async Task<byte[]> ReadBytesAsync(InMemoryRandomAccessStream output)
    {
        var size = output.Size;
        if (size == 0)
        {
            return Array.Empty<byte>();
        }
        using var reader = new DataReader(output.GetInputStreamAt(0));
        await reader.LoadAsync((uint)size);
        var bytes = new byte[(int)size];
        reader.ReadBytes(bytes);
        return bytes;
    }

    private static string FormatBytes(long bytes)
    {
        if (bytes >= 1024L * 1024)
        {
            return $"{bytes / (1024.0 * 1024.0):0.0} MB";
        }
        if (bytes >= 1024)
        {
            return $"{bytes / 1024.0:0.0} KB";
        }
        return $"{bytes} B";
    }

    private static string FormatMime(string? mimeType) => mimeType?.ToLowerInvariant() switch
    {
        "image/png" => "PNG",
        "image/jpeg" => "JPEG",
        "image/webp" => "WebP",
        "image/gif" => "GIF",
        _ => "图片",
    };
}
