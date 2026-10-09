using MemoIsle.Desktop.Services;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace MemoIsle.Desktop;

/// <summary>语音灵感：录音 → 试听 → 补充转写文字 → 保存（含音频上传）。</summary>
internal sealed class VoiceCaptureDialog
{
    private readonly AppState _state;
    private readonly ContentDialog _dialog;
    private readonly AudioRecorderService _recorder = new();
    private readonly SpeechTranscriber _transcriber = new();
    private readonly TextBlock _status = new()
    {
        TextWrapping = TextWrapping.Wrap,
        FontSize = 13,
        Foreground = new SolidColorBrush(Microsoft.UI.Colors.Gray),
    };
    private readonly TextBox _transcript = new()
    {
        Header = "转写 / 配套文字（可手动输入，也可留空）",
        AcceptsReturn = true,
        TextWrapping = TextWrapping.Wrap,
        Height = 120,
        Width = 420,
    };
    private readonly Button _startButton = new() { Content = "● 开始录音" };
    private readonly Button _stopButton = new() { Content = "■ 结束录音", IsEnabled = false };
    private readonly Button _playButton = new() { Content = "试听", IsEnabled = false };
    private readonly Button _discardButton = new() { Content = "重新录制", IsEnabled = false };
    private readonly Button _saveButton = new() { Content = "保存语音灵感", IsEnabled = false };

    private DispatcherQueueTimer? _tickTimer;
    private string? _audioPath;
    private int _durationMs;
    private bool _transcriberReady;
    private string _transcriberHint = string.Empty;

    public VoiceCaptureDialog(AppState state)
    {
        _state = state;

        _startButton.Click += async (_, _) => await StartRecordingAsync();
        _stopButton.Click += async (_, _) => await StopRecordingAsync();
        _playButton.Click += (_, _) => _recorder.PlayPreview();
        _discardButton.Click += (_, _) => ResetRecording();
        _saveButton.Click += async (_, _) => await SaveAsync();

        var actions = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        actions.Children.Add(_startButton);
        actions.Children.Add(_stopButton);
        actions.Children.Add(_playButton);
        actions.Children.Add(_discardButton);
        actions.Children.Add(_saveButton);

        var panel = new StackPanel { Spacing = 12, Width = 440 };
        panel.Children.Add(new TextBlock
        {
            Text = "用麦克风记录语音灵感；保存时会先创建条目再上传录音，可在其他端播放。",
            FontSize = 12,
            TextWrapping = TextWrapping.Wrap,
            Foreground = new SolidColorBrush(Microsoft.UI.Colors.Gray),
        });
        panel.Children.Add(actions);
        panel.Children.Add(_transcript);
        panel.Children.Add(_status);

        _dialog = new ContentDialog
        {
            Title = "语音灵感",
            PrimaryButtonText = "关闭",
            DefaultButton = ContentDialogButton.Primary,
            Content = panel,
        };

        // 实时转写：识别结果自动追加到文本框（不可用时降级为手动输入）。
        _transcriber.TextRecognized += text =>
        {
            _dialog.DispatcherQueue.TryEnqueue(() =>
            {
                _transcript.Text = string.IsNullOrWhiteSpace(_transcript.Text)
                    ? text
                    : _transcript.Text.TrimEnd() + " " + text;
            });
        };
    }

    public async Task ShowAsync(XamlRoot root)
    {
        _dialog.XamlRoot = root;
        // 提前检测系统语音识别能力，避免用户以为转写坏了。
        _status.Text = SpeechTranscriber.HasAnyLanguagePack()
            ? "准备就绪：点击「开始录音」，录制中会自动转写。"
            : "准备就绪：点击「开始录音」。系统未安装语音识别语言包，本次不会自动转写，可在录音后手动填写文字。";
        try
        {
            await _dialog.ShowAsync();
        }
        finally
        {
            _tickTimer?.Stop();
            _tickTimer = null;
            if (_recorder.IsRecording)
            {
                await _recorder.StopAsync();
            }
            await _transcriber.StopAsync();
            _transcriber.Dispose();
            _recorder.Dispose();
        }
    }

    private async Task StartRecordingAsync()
    {
        try
        {
            _status.Text = "正在启动麦克风…";
            await _recorder.StartAsync();
        }
        catch (Exception ex)
        {
            _status.Text = $"无法开始录音：{ex.Message}。请检查 系统设置 → 隐私和安全性 → 麦克风 是否允许桌面应用访问。";
            return;
        }
        _transcriberReady = await _transcriber.StartAsync();
        _transcriberHint = _transcriberReady ? string.Empty : _transcriber.StatusHint;
        _startButton.IsEnabled = false;
        _stopButton.IsEnabled = true;
        _playButton.IsEnabled = false;
        _discardButton.IsEnabled = false;
        _saveButton.IsEnabled = false;
        StartTick();
    }

    private async Task StopRecordingAsync()
    {
        var result = await _recorder.StopAsync();
        await _transcriber.StopAsync();
        _tickTimer?.Stop();
        if (result is null)
        {
            _status.Text = "录音未开始或已停止。";
            return;
        }
        _audioPath = result.Value.Path;
        _durationMs = result.Value.DurationMs;
        _startButton.IsEnabled = true;
        _stopButton.IsEnabled = false;
        _playButton.IsEnabled = true;
        _discardButton.IsEnabled = true;
        _saveButton.IsEnabled = true;
        var transcriptionNote = _transcriberReady
            ? string.Empty
            : _transcriberHint.Length > 0 ? $"\n{_transcriberHint}" : string.Empty;
        _status.Text = $"录制完成：时长 {_durationMs / 1000.0:F1} 秒。可试听、重新录制，或补充文字后保存。{transcriptionNote}";
    }

    private void ResetRecording()
    {
        _recorder.StopPreview();
        _audioPath = null;
        _durationMs = 0;
        _playButton.IsEnabled = false;
        _discardButton.IsEnabled = false;
        _saveButton.IsEnabled = false;
        _status.Text = "已放弃刚才的录音，点击「开始录音」重新录制。";
    }

    private async Task SaveAsync()
    {
        if (_audioPath is null)
        {
            return;
        }
        _saveButton.IsEnabled = false;
        _status.Text = "正在保存语音灵感…";
        var error = await _state.SaveVoiceIdeaAsync(_transcript.Text, _audioPath, _durationMs);
        if (error is not null)
        {
            _status.Text = error;
            _saveButton.IsEnabled = true;
            return;
        }
        _status.Text = "已保存。";
        _dialog.Hide();
    }

    private void StartTick()
    {
        _tickTimer ??= CreateTickTimer();
        _tickTimer.Start();
    }

    private DispatcherQueueTimer CreateTickTimer()
    {
        var timer = _dialog.DispatcherQueue.CreateTimer();
        timer.Interval = TimeSpan.FromMilliseconds(200);
        timer.IsRepeating = true;
        timer.Tick += (_, _) =>
        {
            if (_recorder.IsRecording)
            {
                var hint = _transcriberReady ? string.Empty : "（转写未启用）";
                _status.Text = $"录音中… {_recorder.Duration.TotalSeconds:F1} 秒{hint}";
            }
        };
        return timer;
    }
}
