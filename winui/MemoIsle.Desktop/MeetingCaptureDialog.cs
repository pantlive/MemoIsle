using MemoIsle.Desktop.Services;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace MemoIsle.Desktop;

/// <summary>会议记录：录音 → 自动保存（含音频上传），保存后可在列表播放。</summary>
internal sealed class MeetingCaptureDialog
{
    /// <summary>带说话人标签的对话片段，用于合并系统声音和麦克风两条音轨。</summary>
    private sealed record DialogueSegment(
        string Speaker,
        SherpaOnnxSpeechToText.SpeechSegment Segment);

    private readonly AppState _state;
    private readonly ContentDialog _dialog;
    private readonly AudioRecorderService _recorder = new();
    private readonly SpeechTranscriber _transcriber = new();
    private readonly SherpaOnnxSpeechToText _speechToText = new();
    private readonly SherpaOnnxSpeakerDiarization _speakerDiarization = new();
    private readonly TextBlock _status = new()
    {
        TextWrapping = TextWrapping.Wrap,
        FontSize = 13,
        Foreground = new SolidColorBrush(Microsoft.UI.Colors.Gray),
    };
    private readonly TextBox _title = new()
    {
        Header = "会议标题",
        PlaceholderText = "例如：产品周会",
        MaxLength = 200,
        Width = 500,
    };
    private readonly Button _startButton = new() { Content = "● 开始录音" };
    private readonly Button _pauseButton = new() { Content = "⏸ 暂停", IsEnabled = false };
    private readonly Button _stopButton = new() { Content = "■ 结束并保存", IsEnabled = false };
    private readonly ComboBox _sourceSelector = new()
    {
        Header = "录制来源",
        Width = 500,
        SelectedIndex = 0,
    };
    private readonly ComboBox _outputDeviceSelector = new()
    {
        Header = "输出设备（系统声音）",
        Width = 430,
    };
    private readonly ComboBox _inputDeviceSelector = new()
    {
        Header = "输入设备（麦克风）",
        Width = 430,
    };
    private readonly Button _refreshDevicesButton = new()
    {
        Content = "刷新设备",
    };

    private DispatcherQueueTimer? _tickTimer;
    private string? _audioPath;
    private int _durationMs;
    private string _transcriptText = string.Empty;
    private bool _isSaving;
    private bool _transcriberReady;
    private string? _transcriberHint;
    private bool _transcriptReady;

    public MeetingCaptureDialog(AppState state)
    {
        _state = state;

        _startButton.Click += async (_, _) => await StartRecordingAsync();
        _pauseButton.Click += async (_, _) => await TogglePauseAsync();
        _stopButton.Click += async (_, _) => await StopRecordingAsync();

        _sourceSelector.Items.Add(new ComboBoxItem
        {
            Content = "系统声音 + 麦克风（腾讯会议）",
            Tag = AudioRecorderService.AudioCaptureSource.SystemAudioAndMicrophone,
        });
        _sourceSelector.Items.Add(new ComboBoxItem
        {
            Content = "仅系统声音",
            Tag = AudioRecorderService.AudioCaptureSource.SystemAudio,
        });
        _sourceSelector.Items.Add(new ComboBoxItem
        {
            Content = "仅麦克风",
            Tag = AudioRecorderService.AudioCaptureSource.Microphone,
        });
        _sourceSelector.SelectionChanged += (_, _) => UpdateDeviceSelectorState();
        _refreshDevicesButton.Click += (_, _) => LoadAudioDevices();

        LoadAudioDevices();

        var recordActions = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        recordActions.Children.Add(_startButton);
        recordActions.Children.Add(_pauseButton);
        recordActions.Children.Add(_stopButton);

        var panel = new StackPanel { Spacing = 12, Width = 520 };
        panel.Children.Add(new TextBlock
        {
            Text = "选择声音来源后开始录音；结束后会自动生成“我 / 对方1 / 对方2”对话转写、会议总结并保存。",
            FontSize = 12,
            TextWrapping = TextWrapping.Wrap,
            Foreground = new SolidColorBrush(Microsoft.UI.Colors.Gray),
        });
        panel.Children.Add(_title);
        panel.Children.Add(_sourceSelector);
        panel.Children.Add(CreateDeviceRow(_outputDeviceSelector, _refreshDevicesButton));
        panel.Children.Add(_inputDeviceSelector);
        panel.Children.Add(recordActions);
        panel.Children.Add(_status);

        _dialog = new ContentDialog
        {
            Title = "会议录音",
            PrimaryButtonText = "关闭",
            DefaultButton = ContentDialogButton.Primary,
            Content = panel,
        };

        // WinRT 识别结果在后台事件中返回，必须切回 UI 线程再更新文本框。
        _transcriber.TextRecognized += text =>
        {
            _dialog.DispatcherQueue.TryEnqueue(() =>
            {
                _transcriptText = string.IsNullOrWhiteSpace(_transcriptText)
                    ? text
                    : $"{_transcriptText.TrimEnd()} {text}";
            });
        };
    }

    public async Task ShowAsync(XamlRoot root)
    {
        _dialog.XamlRoot = root;
        _status.Text = "准备就绪：结束后会自动保存，稍后在列表中播放。";
        UpdateDeviceSelectorState();
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
        SetRecordingBusy(true);
        var source = ((ComboBoxItem)_sourceSelector.SelectedItem).Tag
            is AudioRecorderService.AudioCaptureSource selectedSource
            ? selectedSource
            : AudioRecorderService.AudioCaptureSource.SystemAudioAndMicrophone;
        _status.Text = source == AudioRecorderService.AudioCaptureSource.SystemAudio
            ? "正在启动系统声音捕获…"
            : source == AudioRecorderService.AudioCaptureSource.Microphone
                ? "正在启动麦克风…"
                : "正在启动系统声音和麦克风…";
        try
        {
            _audioPath = await _recorder.StartAsync(
                source,
                GetSelectedDeviceId(_outputDeviceSelector),
                GetSelectedDeviceId(_inputDeviceSelector));
        }
        catch (Exception ex)
        {
            _status.Text = source switch
            {
                AudioRecorderService.AudioCaptureSource.SystemAudio =>
                    $"无法捕获系统声音：{ex.Message}。请确认所选输出设备和腾讯会议音频正常。",
                AudioRecorderService.AudioCaptureSource.Microphone =>
                    $"无法开始录音：{ex.Message}。请确认所选输入设备和麦克风隐私权限。",
                _ => $"无法开始录音：{ex.Message}。请确认所选输出/输入设备、扬声器播放和麦克风隐私权限。",
            };
            SetRecordingBusy(false);
            return;
        }

        if (source == AudioRecorderService.AudioCaptureSource.Microphone &&
            IsDefaultInputDeviceSelected())
        {
            _transcriberReady = await _transcriber.StartAsync();
            _transcriberHint = _transcriberReady ? null : _transcriber.StatusHint;
        }
        else
        {
            _transcriberReady = false;
            _transcriberHint = source == AudioRecorderService.AudioCaptureSource.Microphone
                ? "所选输入设备不是系统默认，本次不自动转写"
                : "系统声音模式不会自动转写，可手动粘贴会议转写";
            if (source != AudioRecorderService.AudioCaptureSource.Microphone)
            {
                _status.Text = source == AudioRecorderService.AudioCaptureSource.SystemAudio
                    ? "正在捕获系统声音……"
                    : "正在捕获系统声音和麦克风……";
            }
        }
        _durationMs = 0;
        _transcriptText = string.Empty;
        _transcriptReady = false;
        _title.IsEnabled = false;
        _sourceSelector.IsEnabled = false;
        _outputDeviceSelector.IsEnabled = false;
        _inputDeviceSelector.IsEnabled = false;
        _refreshDevicesButton.IsEnabled = false;
        _startButton.IsEnabled = false;
        _pauseButton.IsEnabled = true;
        _stopButton.IsEnabled = true;
        StartTick();
    }

    private async Task TogglePauseAsync()
    {
        if (!_recorder.IsRecording)
        {
            return;
        }

        try
        {
            if (_recorder.IsPaused)
            {
                await _recorder.ResumeAsync();
                if (_recorder.Source == AudioRecorderService.AudioCaptureSource.Microphone)
                {
                    _transcriberReady = await _transcriber.StartAsync();
                    _transcriberHint = _transcriberReady ? null : _transcriber.StatusHint;
                }
                _pauseButton.Content = "⏸ 暂停";
                _status.Text = "录音已继续。";
            }
            else
            {
                await _transcriber.StopAsync();
                await _recorder.PauseAsync();
                _pauseButton.Content = "▶ 继续";
                _status.Text = "录音已暂停。";
            }
        }
        catch (Exception ex)
        {
            _status.Text = $"暂停/继续失败：{ex.Message}";
        }
    }

    private async Task StopRecordingAsync()
    {
        if (_isSaving)
        {
            return;
        }

        if (!_recorder.IsRecording)
        {
            await SaveAsync();
            return;
        }

        _stopButton.IsEnabled = false;
        _status.Text = "正在结束录音并保存…";
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
        await SaveAsync();
    }

    private async Task SaveAsync()
    {
        if (_audioPath is null)
        {
            _status.Text = "请先完成录音后再保存。";
            return;
        }

        _isSaving = true;
        _startButton.IsEnabled = false;
        _pauseButton.IsEnabled = false;
        _stopButton.IsEnabled = false;

        // 会议统一使用离线转写，保证输出带“我 / 对方”说话人标签。
        var realtimeTranscript = _transcriptText;
        if (!_transcriptReady)
        {
            _status.Text = "正在生成“我 / 对方1 / 对方2”对话转写…";
            try
            {
                _transcriptText = await TranscribeMeetingAsync(
                    new Progress<string>(message => _status.Text = message));
                _transcriptReady = true;
                _recorder.DeleteTranscriptionWaves();
            }
            catch (Exception ex)
            {
                // 麦克风模式的 WinRT 实时转写可作为离线模型失败时的兜底。
                if (!string.IsNullOrWhiteSpace(realtimeTranscript))
                {
                    _transcriptText = $"我：{realtimeTranscript.Trim()}";
                    _transcriptReady = true;
                    _recorder.DeleteTranscriptionWaves();
                }
                else
                {
                    _isSaving = false;
                    _status.Text = $"自动转写失败：{ex.Message}";
                    _stopButton.Content = "↻ 重试保存";
                    _stopButton.IsEnabled = true;
                    return;
                }
            }
        }

        var summary = string.Empty;
        if (!string.IsNullOrWhiteSpace(_transcriptText))
        {
            _status.Text = "正在生成会议总结…";
            var (generatedSummary, error) = await _state.SummarizeMeetingAsync(
                _title.Text,
                _transcriptText);
            if (error is null)
            {
                summary = generatedSummary ?? string.Empty;
            }
        }

        _status.Text = "正在自动保存会议录音…";
        var saveError = await _state.SaveMeetingAsync(
            _title.Text,
            _transcriptText,
            summary,
            _audioPath,
            _durationMs);
        if (saveError is not null)
        {
            // 保存失败时保留临时音频，让“重试保存”按钮继续处理。
            _isSaving = false;
            _status.Text = saveError;
            _stopButton.Content = "↻ 重试保存";
            _stopButton.IsEnabled = true;
            return;
        }

        _status.Text = "会议录音已保存。";
        _dialog.Hide();
    }

    private void SetRecordingBusy(bool busy)
    {
        _startButton.IsEnabled = !busy;
        _pauseButton.IsEnabled = false;
        _stopButton.IsEnabled = false;
    }

    /// <summary>识别会议音轨并输出带说话人标签的对话转写。</summary>
    private async Task<string> TranscribeMeetingAsync(IProgress<string> progress)
    {
        var systemWavePath = _recorder.SystemTranscriptionWavePath;
        var microphoneWavePath = _recorder.MicrophoneTranscriptionWavePath;

        // 双轨模式：麦克风是“我”，系统声音先做说话人分离，再按时间戳交错合并。
        if (File.Exists(systemWavePath) && File.Exists(microphoneWavePath))
        {
            var remoteSpeakerSegments = await TryDiarizeRemoteSpeakersAsync(systemWavePath, progress);
            var (systemSegments, microphoneSegments) = await _speechToText.TranscribeSpeakerTracksAsync(
                _audioPath!,
                systemWavePath,
                microphoneWavePath,
                progress,
                systemSpeakerSegments: remoteSpeakerSegments);
            return EnsureTranscript(FormatDialogue(
                CreateRemoteDialogueSegments(systemSegments, remoteSpeakerSegments)
                    .Concat(microphoneSegments.Select(segment => new DialogueSegment("我", segment)))));
        }

        // 单轨模式：系统声音优先区分远端说话人，麦克风统一标为“我”。
        if (File.Exists(systemWavePath))
        {
            var remoteSpeakerSegments = await TryDiarizeRemoteSpeakersAsync(systemWavePath, progress);
            var segments = await _speechToText.TranscribeSegmentsAsync(
                _audioPath!,
                systemWavePath,
                progress,
                speakerSegments: remoteSpeakerSegments);
            return EnsureTranscript(FormatDialogue(
                CreateRemoteDialogueSegments(segments, remoteSpeakerSegments)));
        }

        if (File.Exists(microphoneWavePath))
        {
            var segments = await _speechToText.TranscribeSegmentsAsync(
                _audioPath!,
                microphoneWavePath,
                progress);
            return EnsureTranscript(FormatDialogue(
                segments.Select(segment => new DialogueSegment("我", segment))));
        }

        // 极端情况下临时音轨缺失时，直接识别上传用音频，至少保留可用转写。
        return await _speechToText.TranscribeAsync(_audioPath!, null, progress);
    }

    /// <summary>尝试分离系统声音中的远端说话人；失败时回退为统称“对方”。</summary>
    private async Task<IReadOnlyList<SherpaOnnxSpeakerDiarization.SpeakerDiarizationSegment>?>
        TryDiarizeRemoteSpeakersAsync(string systemWavePath, IProgress<string> progress)
    {
        try
        {
            var segments = await _speakerDiarization.ProcessAsync(systemWavePath, progress);
            var speakerCount = segments.Select(segment => segment.Speaker).Distinct().Count();
            progress.Report(speakerCount > 1
                ? $"已识别 {speakerCount} 位远端说话人，正在识别发言内容…"
                : "远端声音未检测到多位说话人，正在识别发言内容…");
            return segments;
        }
        catch (Exception ex)
        {
            // 分离模型不是会议保存的硬依赖；下载或推理失败时仍保留可用转写。
            progress.Report($"说话人分离失败，将统称“对方”：{ex.Message}");
            return null;
        }
    }

    /// <summary>把系统声音识别片段转换成远端说话人对话片段。</summary>
    private static IEnumerable<DialogueSegment> CreateRemoteDialogueSegments(
        IEnumerable<SherpaOnnxSpeechToText.SpeechSegment> segments,
        IReadOnlyList<SherpaOnnxSpeakerDiarization.SpeakerDiarizationSegment>? speakerSegments)
    {
        // 只有多人时才显示编号；编号按首次出现顺序归一化，避免聚类 ID 不连续。
        var hasMultipleSpeakers = speakerSegments is not null
            && speakerSegments.Select(segment => segment.Speaker).Distinct().Count() > 1;
        var speakerLabels = new Dictionary<int, string>();
        if (hasMultipleSpeakers)
        {
            foreach (var speaker in speakerSegments!
                .OrderBy(segment => segment.Start)
                .Select(segment => segment.Speaker))
            {
                if (!speakerLabels.ContainsKey(speaker))
                {
                    speakerLabels[speaker] = $"对方{speakerLabels.Count + 1}";
                }
            }
        }

        foreach (var segment in segments)
        {
            var speaker = hasMultipleSpeakers
                && speakerLabels.TryGetValue(segment.Speaker, out var label)
                    ? label
                    : "对方";
            yield return new DialogueSegment(speaker, segment);
        }
    }

    /// <summary>双轨可能同时为空；统一在保存前给出可诊断错误。</summary>
    private static string EnsureTranscript(string transcript)
    {
        return string.IsNullOrWhiteSpace(transcript)
            ? throw new InvalidOperationException("没有识别到语音内容")
            : transcript;
    }

    /// <summary>按时间合并片段；同一说话人 1 秒内的相邻片段合并为一行。</summary>
    private static string FormatDialogue(IEnumerable<DialogueSegment> segments)
    {
        var orderedSegments = segments
            .OrderBy(segment => segment.Segment.Start)
            .ThenBy(segment => segment.Segment.End)
            .ThenBy(segment => segment.Speaker)
            .ToList();
        var lines = new List<(string Speaker, TimeSpan End, string Text)>();

        foreach (var segment in orderedSegments)
        {
            var text = segment.Segment.Text.Trim();
            if (text.Length == 0)
            {
                continue;
            }

            if (lines.Count > 0
                && lines[^1].Speaker == segment.Speaker
                && segment.Segment.Start - lines[^1].End <= TimeSpan.FromSeconds(1))
            {
                var previous = lines[^1];
                lines[^1] = (
                    previous.Speaker,
                    segment.Segment.End > previous.End ? segment.Segment.End : previous.End,
                    $"{previous.Text} {text}");
                continue;
            }

            lines.Add((segment.Speaker, segment.Segment.End, text));
        }

        return string.Join(
            Environment.NewLine,
            lines.Select(line => $"{line.Speaker}：{line.Text}"));
    }

    private static StackPanel CreateDeviceRow(ComboBox deviceSelector, Button refreshButton)
    {
        var row = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            Spacing = 8,
        };
        row.Children.Add(deviceSelector);
        row.Children.Add(refreshButton);
        return row;
    }

    private void LoadAudioDevices()
    {
        LoadDeviceSelector(_outputDeviceSelector, AudioRecorderService.ListOutputDevices());
        LoadDeviceSelector(_inputDeviceSelector, AudioRecorderService.ListInputDevices());
        UpdateDeviceSelectorState();
    }

    private static void LoadDeviceSelector(
        ComboBox selector,
        IReadOnlyList<AudioRecorderService.AudioDeviceOption> devices)
    {
        var selectedId = GetSelectedDeviceId(selector);
        selector.Items.Clear();
        foreach (var device in devices)
        {
            selector.Items.Add(new ComboBoxItem
            {
                Content = device.IsDefault ? $"{device.Name}（默认）" : device.Name,
                Tag = device.Id,
            });
        }

        var nextSelected = devices.FirstOrDefault(device => device.Id == selectedId)
            ?? devices.FirstOrDefault(device => device.IsDefault)
            ?? devices.FirstOrDefault();
        if (nextSelected is not null)
        {
        for (var deviceIndex = 0; deviceIndex < devices.Count; deviceIndex++)
        {
            if (devices[deviceIndex].Id == nextSelected.Id)
            {
                selector.SelectedIndex = deviceIndex;
                break;
            }
        }
        }
    }

    private static string? GetSelectedDeviceId(ComboBox selector)
    {
        return selector.SelectedItem is ComboBoxItem item
            ? item.Tag as string
            : null;
    }

    private bool IsDefaultInputDeviceSelected()
    {
        var selectedId = GetSelectedDeviceId(_inputDeviceSelector);
        return AudioRecorderService.ListInputDevices()
            .Any(device => device.IsDefault && device.Id == selectedId);
    }

    private void UpdateDeviceSelectorState()
    {
        var source = ((ComboBoxItem)_sourceSelector.SelectedItem).Tag
            is AudioRecorderService.AudioCaptureSource selectedSource
            ? selectedSource
            : AudioRecorderService.AudioCaptureSource.SystemAudioAndMicrophone;
        _outputDeviceSelector.IsEnabled =
            source != AudioRecorderService.AudioCaptureSource.Microphone;
        _inputDeviceSelector.IsEnabled =
            source != AudioRecorderService.AudioCaptureSource.SystemAudio;
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
                var state = _recorder.IsPaused ? "已暂停" : "录音中";
                var hint = string.IsNullOrWhiteSpace(_transcriberHint)
                    ? string.Empty
                    : $"。{_transcriberHint}";
                _status.Text = $"{state}… {_recorder.Duration.TotalSeconds:F1} 秒{hint}";
            }
        };
        return timer;
    }
}
