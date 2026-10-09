using Windows.ApplicationModel.DataTransfer;

namespace MemoIsle.Desktop.Services;

/// <summary>
/// 剪贴板读写与备份/还原。
/// 划词翻译会自动模拟 Ctrl+C 取词，为避免破坏用户原有剪贴板内容，取词后尝试还原。
/// </summary>
public static class ClipboardHelper
{
    private const int MaxAttempts = 6;

    /// <summary>读取剪贴板文本（读取失败返回 null，例如被其他进程占用）。</summary>
    public static async Task<string?> ReadTextAsync()
    {
        for (var attempt = 0; attempt < MaxAttempts; attempt++)
        {
            try
            {
                var content = Clipboard.GetContent();
                if (content.Contains(StandardDataFormats.Text))
                {
                    return await content.GetTextAsync();
                }
                return null;
            }
            catch (Exception)
            {
                // 剪贴板被占用时短暂等待后重试。
                await Task.Delay(30);
            }
        }
        return null;
    }

    /// <summary>写入文本到剪贴板。</summary>
    public static bool WriteText(string text)
    {
        for (var attempt = 0; attempt < MaxAttempts; attempt++)
        {
            try
            {
                var package = new DataPackage();
                package.SetText(text);
                Clipboard.SetContent(package);
                return true;
            }
            catch (Exception)
            {
                Thread.Sleep(30);
            }
        }
        return false;
    }

    /// <summary>备份剪贴板中的文本（非文本内容返回 null，表示无法还原）。</summary>
    public static async Task<string?> BackupTextAsync() => await ReadTextAsync();

    /// <summary>还原之前备份的文本。</summary>
    public static void RestoreText(string? backup)
    {
        if (!string.IsNullOrEmpty(backup))
        {
            WriteText(backup);
        }
    }
}
