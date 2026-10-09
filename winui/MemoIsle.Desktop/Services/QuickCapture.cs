using System.Text.RegularExpressions;
using MemoIsle.Desktop.Models;
using Windows.ApplicationModel.DataTransfer;
using Windows.Data.Xml.Dom;
using Windows.UI.Notifications;

namespace MemoIsle.Desktop.Services;

/// <summary>
/// 无窗口快速收藏：读取剪贴板 → 直接落库 → 弹系统通知。
/// 供全局热键调用，全程不切换、不打开 MemoIsle 窗口。
/// </summary>
public sealed class QuickCapture
{
    private static readonly Regex UrlPattern = new(@"https?://\S+", RegexOptions.IgnoreCase);

    private readonly AppState _state;
    private Memo? _lastCaptured;

    public QuickCapture(AppState state)
    {
        _state = state;
    }

    /// <summary>剪贴板里的单词/短语：自动查词补全后收藏。</summary>
    public async Task<string> CaptureWordAsync()
    {
        var rawText = await ReadClipboardTextAsync();
        if (string.IsNullOrWhiteSpace(rawText))
        {
            return "剪贴板没有文本，已取消收藏。";
        }
        var draft = ClipboardWordParser.Parse(rawText);
        if (draft is null)
        {
            return "剪贴板内容不像单词或短语，已取消收藏。";
        }

        var phonetic = draft.Phonetic ?? string.Empty;
        var meaning = draft.Meaning ?? string.Empty;
        var example = string.Empty;
        // 剪贴板没带释义时自动查词补全。
        if (meaning.Length == 0)
        {
            var lookup = await _state.LookupWordAsync(draft.Lemma);
            if (lookup is not null)
            {
                phonetic = phonetic.Length > 0 ? phonetic : lookup.Phonetic ?? string.Empty;
                meaning = string.Join(
                    "\n",
                    lookup.Senses.Take(3).Select((sense, index) => $"{index + 1}. {sense.Definition}"));
                example = lookup.Senses
                    .FirstOrDefault(s => !string.IsNullOrWhiteSpace(s.Example))?.Example ?? string.Empty;
            }
        }

        var error = await _state.CreateWordAsync(
            draft.Lemma,
            phonetic,
            meaning,
            example,
            allowDuplicate: false);
        if (error is not null)
        {
            return error;
        }
        _lastCaptured = _state.UndoableMemo;
        return $"已收藏单词「{draft.Lemma}」";
    }

    /// <summary>剪贴板里的网址：收藏为网页资料（标题与描述由服务端补齐）。</summary>
    public async Task<string> CaptureResourceAsync()
    {
        var rawText = await ReadClipboardTextAsync();
        if (string.IsNullOrWhiteSpace(rawText))
        {
            return "剪贴板没有文本，已取消收藏。";
        }
        var match = UrlPattern.Match(rawText);
        var candidate = match.Success ? match.Value.TrimEnd('.', ',', '，', '。', ')', '）') : rawText.Trim();
        var normalized = AppState.NormalizeUrl(candidate);
        if (normalized is null)
        {
            return "剪贴板里没有可识别的网址，已取消收藏。";
        }

        var error = await _state.CreateResourceAsync(normalized, string.Empty, string.Empty);
        if (error is not null)
        {
            return error;
        }
        _lastCaptured = _state.UndoableMemo;
        return _lastCaptured is null
            ? "该网址已在资料库中，未重复收藏。"
            : $"已收藏网页「{Memo.ResourceHost(normalized)}」";
    }

    /// <summary>剪贴板里的整段文字：收藏为灵感。</summary>
    public async Task<string> CaptureIdeaAsync()
    {
        var rawText = await ReadClipboardTextAsync();
        if (string.IsNullOrWhiteSpace(rawText))
        {
            return "剪贴板没有文本，已取消收藏。";
        }
        var body = rawText.Trim();
        if (body.Length > 50_000)
        {
            body = body[..50_000];
        }
        var error = await _state.CreateIdeaAsync(body);
        if (error is not null)
        {
            return error;
        }
        _lastCaptured = _state.UndoableMemo;
        return "已收藏灵感";
    }

    /// <summary>撤销最近一次快速收藏。</summary>
    public async Task<string> UndoLastAsync()
    {
        if (_lastCaptured is null)
        {
            return "没有可撤销的快速收藏。";
        }
        var error = await _state.UndoLastCreateAsync();
        _lastCaptured = null;
        return error ?? "已撤销刚才的快速收藏（条目已移入回收站）";
    }

    public bool HasUndo => _lastCaptured is not null;

    private static async Task<string?> ReadClipboardTextAsync()
    {
        try
        {
            var content = Clipboard.GetContent();
            if (!content.Contains(StandardDataFormats.Text))
            {
                return null;
            }
            return await content.GetTextAsync();
        }
        catch (Exception)
        {
            return null;
        }
    }

    /// <summary>弹出系统提示（通知不可用时静默忽略）。</summary>
    public static void ShowToast(string message)
    {
        try
        {
            const string xml = """
                <toast>
                  <visual>
                    <binding template="ToastGeneric">
                      <text>MemoIsle</text>
                      <text>{0}</text>
                    </binding>
                  </visual>
                </toast>
                """;
            var document = new XmlDocument();
            document.LoadXml(xml.Replace("{0}", System.Security.SecurityElement.Escape(message) ?? string.Empty));
            ToastNotificationManager.CreateToastNotifier().Show(new ToastNotification(document));
        }
        catch (Exception)
        {
            // 通知不可用时仅依靠窗口状态栏提示。
        }
    }
}
