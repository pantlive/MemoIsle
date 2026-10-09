using Windows.Globalization;
using Windows.Media.SpeechRecognition;

namespace MemoIsle.Desktop.Services;

/// <summary>语音转写不可用的原因，用于给用户可操作的提示。</summary>
public enum TranscriberStatus
{
    Ready,
    NoLanguagePack,
    PermissionDenied,
    Failed,
}

/// <summary>
/// 录音期间的实时语音转写（WinRT SpeechRecognizer，优先中文、回退已安装语言）。
/// 失败时区分"缺语言包 / 权限被拒 / 其他"，方便界面给出可操作的引导。
/// </summary>
public sealed class SpeechTranscriber : IDisposable
{
    private SpeechRecognizer? _recognizer;

    public event Action<string>? TextRecognized;

    public TranscriberStatus Status { get; private set; } = TranscriberStatus.Failed;

    /// <summary>面向用户的状态说明（含可操作的解决建议）。</summary>
    public string StatusHint => Status switch
    {
        TranscriberStatus.Ready => string.Empty,
        TranscriberStatus.NoLanguagePack =>
            "系统未安装语音识别语言包，转写已停用；可在 设置 → 时间和语言 → 语言和区域 中给中文或英文安装语音识别后重试。",
        TranscriberStatus.PermissionDenied =>
            "语音识别权限被拒绝，转写已停用；可在 设置 → 隐私和安全性 → 语音 中允许后重试。",
        _ => "语音转写当前不可用，可手动填写文字。",
    };

    /// <summary>系统是否存在任意可用的语音识别语言包（用于界面提前提示）。</summary>
    public static bool HasAnyLanguagePack()
    {
        try
        {
            return SpeechRecognizer.SupportedTopicLanguages.Count > 0;
        }
        catch (Exception)
        {
            return false;
        }
    }

    public async Task<bool> StartAsync()
    {
        var language = ResolveLanguage();
        if (language is null)
        {
            Status = TranscriberStatus.NoLanguagePack;
            return false;
        }
        try
        {
            _recognizer = new SpeechRecognizer(language);
            _recognizer.ContinuousRecognitionSession.ResultGenerated += (_, args) =>
            {
                var text = args.Result?.Text;
                if (!string.IsNullOrWhiteSpace(text))
                {
                    TextRecognized?.Invoke(text.Trim());
                }
            };
            await _recognizer.ContinuousRecognitionSession.StartAsync();
            Status = TranscriberStatus.Ready;
            return true;
        }
        catch (UnauthorizedAccessException)
        {
            Status = TranscriberStatus.PermissionDenied;
            _recognizer?.Dispose();
            _recognizer = null;
            return false;
        }
        catch (Exception)
        {
            Status = TranscriberStatus.Failed;
            _recognizer?.Dispose();
            _recognizer = null;
            return false;
        }
    }

    public async Task StopAsync()
    {
        if (_recognizer is null)
        {
            return;
        }
        try
        {
            await _recognizer.ContinuousRecognitionSession.StopAsync();
            _recognizer.Dispose();
            _recognizer = null;
        }
        catch (Exception)
        {
            // 会话已结束时忽略。
        }
    }

    /// <summary>在系统已安装的语言包中优先选中文、其次英文，否则用第一个可用语言。</summary>
    private static Language? ResolveLanguage()
    {
        try
        {
            var installed = SpeechRecognizer.SupportedTopicLanguages;
            if (installed.Count == 0)
            {
                return null;
            }
            foreach (var preferred in new[] { "zh", "en" })
            {
                var match = installed.FirstOrDefault(
                    language => language.LanguageTag.StartsWith(preferred, StringComparison.OrdinalIgnoreCase));
                if (match is not null)
                {
                    return match;
                }
            }
            return installed[0];
        }
        catch (Exception)
        {
            return null;
        }
    }

    public void Dispose()
    {
        _recognizer?.Dispose();
        _recognizer = null;
    }
}
