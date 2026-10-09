using System.Net;
using System.Text.RegularExpressions;
using MemoIsle.Desktop.Models;

namespace MemoIsle.Desktop.Services;

/// <summary>
/// 解析 Chrome / Edge 导出的 Netscape 书签 HTML（本地解析，不上传原始文件）。
/// 逐行扫描维护文件夹栈，与 Web 端 parseChromeBookmarksFile 行为对齐。
/// </summary>
public static class BookmarkFileParser
{
    public const int MaxItems = 5000;
    public const long MaxFileBytes = 10 * 1024 * 1024;

    public static List<BookmarkInput> Parse(string html)
    {
        var items = new List<BookmarkInput>();
        var folders = new Stack<string>();
        var index = 0;

        foreach (var rawLine in html.Split('\n'))
        {
            var line = rawLine.Trim();
            if (line.Length == 0)
            {
                continue;
            }
            if (line.Contains("</DL>", StringComparison.OrdinalIgnoreCase))
            {
                if (folders.Count > 0)
                {
                    folders.Pop();
                }
                continue;
            }
            if (line.Contains("<H3", StringComparison.OrdinalIgnoreCase))
            {
                var folderName = ExtractTagText(line, "H3");
                if (!string.IsNullOrWhiteSpace(folderName))
                {
                    folders.Push(folderName);
                }
                continue;
            }
            if (!line.Contains("<A HREF", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }

            var url = ExtractAttribute(line, "HREF");
            if (string.IsNullOrWhiteSpace(url) || url.Length > 2048)
            {
                continue;
            }
            var title = ExtractTagText(line, "A") ?? string.Empty;
            index += 1;
            items.Add(new BookmarkInput
            {
                ClientItemId = $"chrome-html:{index}",
                Title = title.Length > 300 ? title[..300] : title,
                Url = url,
                FolderPath = folders.Count == 0 ? null : string.Join(" / ", folders.Reverse()),
            });
            if (items.Count >= MaxItems)
            {
                break;
            }
        }
        return items;
    }

    private static string? ExtractTagText(string line, string tag)
    {
        var match = Regex.Match(
            line,
            $"<{tag}[^>]*>(?<text>.*?)</{tag}>",
            RegexOptions.IgnoreCase);
        return match.Success ? WebUtility.HtmlDecode(match.Groups["text"].Value).Trim() : null;
    }

    private static string? ExtractAttribute(string line, string name)
    {
        var match = Regex.Match(
            line,
            $"{name}=\"(?<value>[^\"]*)\"",
            RegexOptions.IgnoreCase);
        return match.Success ? WebUtility.HtmlDecode(match.Groups["value"].Value).Trim() : null;
    }
}
