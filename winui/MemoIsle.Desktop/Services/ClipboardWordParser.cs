using System.Text.RegularExpressions;

namespace MemoIsle.Desktop.Services;

/// <summary>从剪贴板文本识别出的单词草稿。</summary>
public sealed record ClipboardWordDraft(string Lemma, string? Phonetic, string? Meaning);

/// <summary>
/// 剪贴板单词解析（移植 Web 端 parseClipboardWord）：
/// 识别 /音标/、英文 + 中文混合行，过滤 URL 与文件路径等噪声。
/// </summary>
public static class ClipboardWordParser
{
    private static readonly Regex PhoneticPattern = new(@"([/\[])([^/\[\]]{1,80})\1");
    private static readonly Regex MixedPattern = new(
        @"^([A-Za-z][A-Za-z0-9'’.\-]*(?:[\s-][A-Za-z][A-Za-z0-9'’.\-]*){0,5})\s+([^\s].+)$");
    private static readonly Regex DomainLikePattern = new(
        @"^[a-z0-9.-]+\.[a-z]{2,}([/:?#].*)?$",
        RegexOptions.IgnoreCase);
    private static readonly Regex LemmaPattern = new(
        @"^[A-Za-z][A-Za-z0-9'’.\-]*(?:[ \-][A-Za-z][A-Za-z0-9'’.\-]*){0,5}$");
    private static readonly Regex FileSuffixPattern = new(
        @"\.[a-z0-9]{1,8}$",
        RegexOptions.IgnoreCase);

    public static ClipboardWordDraft? Parse(string raw)
    {
        var text = raw.Replace('\u00a0', ' ').Replace("\r\n", "\n").Trim();
        if (text.Length == 0)
        {
            return null;
        }
        var firstToken = text.Split(' ').FirstOrDefault() ?? string.Empty;
        if (IsClipboardUrl(text) || IsClipboardUrl(firstToken))
        {
            return null;
        }

        var lines = text
            .Split('\n')
            .Select(line => line.Trim())
            .Where(line => line.Length > 0)
            .ToList();
        if (lines.Count == 0)
        {
            return null;
        }

        var firstLine = lines[0];
        string? phonetic = null;
        var phoneticMatch = PhoneticPattern.Match(firstLine);
        if (phoneticMatch.Success)
        {
            phonetic = $"/{phoneticMatch.Groups[2].Value}/";
            if (phonetic.Length > 120)
            {
                phonetic = phonetic[..120];
            }
            firstLine = firstLine.Remove(phoneticMatch.Index, phoneticMatch.Length);
            firstLine = Regex.Replace(firstLine, @"\s+", " ").Trim();
        }

        var lemma = firstLine;
        string? meaning = lines.Count > 1
            ? string.Join("\n", lines.Skip(1)).Trim()
            : null;
        if (string.IsNullOrEmpty(meaning))
        {
            meaning = null;
        }

        var mixed = MixedPattern.Match(firstLine);
        if (mixed.Success && HasCjk(mixed.Groups[2].Value) && !HasCjk(mixed.Groups[1].Value))
        {
            lemma = mixed.Groups[1].Value.Trim();
            meaning = string.Join(
                "\n",
                new[] { mixed.Groups[2].Value.Trim(), meaning }
                    .Where(part => !string.IsNullOrWhiteSpace(part)));
        }

        lemma = Regex.Replace(lemma, @"\s+", " ").Trim();
        if (!IsPlausibleLemma(lemma))
        {
            return null;
        }
        return new ClipboardWordDraft(
            lemma.Length > 200 ? lemma[..200].Trim() : lemma,
            phonetic,
            meaning is { Length: > 5000 } ? meaning[..5000] : meaning);
    }

    private static bool IsClipboardUrl(string value)
    {
        var cleaned = value.Trim();
        return cleaned.StartsWith("http://", StringComparison.OrdinalIgnoreCase)
            || cleaned.StartsWith("https://", StringComparison.OrdinalIgnoreCase)
            || cleaned.StartsWith("file:", StringComparison.OrdinalIgnoreCase)
            || cleaned.StartsWith("www.", StringComparison.OrdinalIgnoreCase)
            || DomainLikePattern.IsMatch(cleaned);
    }

    private static bool IsPlausibleLemma(string lemma)
    {
        if (lemma.Length == 0 || lemma.Length > 80 || IsClipboardUrl(lemma))
        {
            return false;
        }
        if (HasCjk(lemma) || lemma.Contains('/') || lemma.Contains('\\'))
        {
            return false;
        }
        if (lemma.Contains('_') || lemma.Contains(':'))
        {
            return false;
        }
        if (FileSuffixPattern.IsMatch(lemma))
        {
            return false;
        }
        if (".,!?。！？".Contains(lemma[^1]))
        {
            return false;
        }
        if (!LemmaPattern.IsMatch(lemma))
        {
            return false;
        }
        return lemma.Split(' ', StringSplitOptions.RemoveEmptyEntries).Length <= 6;
    }

    private static bool HasCjk(string value) =>
        value.Any(ch => ch >= 0x3400 && ch <= 0x9FFF);
}
