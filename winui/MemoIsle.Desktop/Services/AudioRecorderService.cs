using Windows.Media.Core;
using Windows.Media.MediaProperties;
using Windows.Media.Playback;
using Windows.Media.Transcoding;
using Windows.Storage;
using NAudio.CoreAudioApi;
using NAudio.Wave;
using NAudio.Wave.SampleProviders;

namespace MemoIsle.Desktop.Services;

/// <summary>语音/会议录音：支持麦克风、系统回环和两者混合，可指定音频设备。</summary>
public sealed class AudioRecorderService : IDisposable
{
    /// <summary>录音来源；会议默认使用系统回环和麦克风混合。</summary>
    public enum AudioCaptureSource
    {
        Microphone,
        SystemAudio,
        SystemAudioAndMicrophone,
    }

    /// <summary>UI 中可选择的 Windows 音频设备。</summary>
    public sealed record AudioDeviceOption(string Id, string Name, bool IsDefault);

    private readonly MediaPlayer _player = new();
    private readonly System.Diagnostics.Stopwatch _stopwatch = new();
    private WasapiLoopbackCapture? _loopbackCapture;
    private WaveFileWriter? _loopbackWriter;
    private string? _loopbackWavePath;
    private TaskCompletionSource<bool>? _loopbackStopTask;
    private bool _loopbackStopping;

    private WasapiCapture? _microphoneCapture;
    private WaveFileWriter? _microphoneWriter;
    private string? _microphoneWavePath;
    private TaskCompletionSource<bool>? _microphoneStopTask;
    private bool _microphoneStopping;

    private string? _currentFilePath;
    private AudioCaptureSource _source = AudioCaptureSource.Microphone;

    public bool IsRecording { get; private set; }

    public bool IsPaused { get; private set; }

    public TimeSpan Duration => _stopwatch.Elapsed;

    public string? CurrentFilePath => _currentFilePath;

    public AudioCaptureSource Source => _source;

    /// <summary>结束录音后保留的系统声音 16 kHz ASR 音频。</summary>
    public string? SystemTranscriptionWavePath { get; private set; }

    /// <summary>结束录音后保留的麦克风 16 kHz ASR 音频。</summary>
    public string? MicrophoneTranscriptionWavePath { get; private set; }

    /// <summary>列出可用输出设备；蓝牙耳机在 Windows 启用后会出现在这里。</summary>
    public static IReadOnlyList<AudioDeviceOption> ListOutputDevices()
        => ListDevices(DataFlow.Render);

    /// <summary>列出可用输入设备；蓝牙麦克风/耳机麦克风会出现在这里。</summary>
    public static IReadOnlyList<AudioDeviceOption> ListInputDevices()
        => ListDevices(DataFlow.Capture);

    public async Task<string> StartAsync(
        AudioCaptureSource source = AudioCaptureSource.Microphone,
        string? outputDeviceId = null,
        string? inputDeviceId = null)
    {
        if (IsRecording)
        {
            return _currentFilePath ?? string.Empty;
        }

        DeleteTranscriptionWaves();
        _source = source;
        try
        {
            switch (source)
            {
                case AudioCaptureSource.SystemAudio:
                    StartLoopbackCapture(outputDeviceId);
                    BeginCaptureState();
                    return _loopbackWavePath ?? string.Empty;

                case AudioCaptureSource.Microphone:
                    StartMicrophoneCapture(inputDeviceId);
                    BeginCaptureState();
                    return _microphoneWavePath ?? string.Empty;

                case AudioCaptureSource.SystemAudioAndMicrophone:
                    StartLoopbackCapture(outputDeviceId);
                    try
                    {
                        StartMicrophoneCapture(inputDeviceId);
                    }
                    catch
                    {
                        var startedWavePath = await StopLoopbackCaptureAsync();
                        File.Delete(startedWavePath);
                        throw;
                    }

                    BeginCaptureState();
                    return _loopbackWavePath ?? string.Empty;

                default:
                    throw new ArgumentOutOfRangeException(nameof(source), source, "未知录音来源");
            }
        }
        catch
        {
            IsRecording = false;
            IsPaused = false;
            throw;
        }
    }

    public async Task PauseAsync()
    {
        if (!IsRecording || IsPaused)
        {
            return;
        }

        // WASAPI 捕获没有统一暂停接口，这里通过跳过采样实现可恢复暂停。
        _stopwatch.Stop();
        IsPaused = true;
        await Task.CompletedTask;
    }

    public async Task ResumeAsync()
    {
        if (!IsRecording || !IsPaused)
        {
            return;
        }

        _stopwatch.Start();
        IsPaused = false;
        await Task.CompletedTask;
    }

    public async Task<(string Path, int DurationMs)?> StopAsync()
    {
        if (!IsRecording)
        {
            return null;
        }

        _stopwatch.Stop();
        var durationMs = (int)_stopwatch.Elapsed.TotalMilliseconds;
        try
        {
            switch (_source)
            {
                case AudioCaptureSource.SystemAudio:
                {
                    var wavePath = await StopLoopbackCaptureAsync();
                    SystemTranscriptionWavePath = CreateTranscriptionWave(wavePath);
                    return await FinishRecordingAsync(wavePath, durationMs);
                }

                case AudioCaptureSource.Microphone:
                {
                    var wavePath = await StopMicrophoneCaptureAsync();
                    MicrophoneTranscriptionWavePath = CreateTranscriptionWave(wavePath);
                    return await FinishRecordingAsync(wavePath, durationMs);
                }

                case AudioCaptureSource.SystemAudioAndMicrophone:
                {
                    var systemWavePathTask = StopLoopbackCaptureAsync();
                    var microphoneWavePathTask = StopMicrophoneCaptureAsync();
                    await Task.WhenAll(systemWavePathTask, microphoneWavePathTask);
                    SystemTranscriptionWavePath = CreateTranscriptionWave(systemWavePathTask.Result);
                    MicrophoneTranscriptionWavePath = CreateTranscriptionWave(microphoneWavePathTask.Result);
                    var mixedWavePath = await Task.Run(
                        () => MixWaveFiles(systemWavePathTask.Result, microphoneWavePathTask.Result));
                    File.Delete(systemWavePathTask.Result);
                    File.Delete(microphoneWavePathTask.Result);
                    return await FinishRecordingAsync(mixedWavePath, durationMs);
                }

                default:
                    throw new InvalidOperationException("未知录音来源");
            }
        }
        catch
        {
            IsRecording = false;
            IsPaused = false;
            throw;
        }
    }

    public void PlayPreview()
    {
        if (_currentFilePath is null)
        {
            return;
        }

        _player.Source = MediaSource.CreateFromUri(new Uri(_currentFilePath));
        _player.Play();
    }

    public void StopPreview()
    {
        _player.Pause();
    }

    public void Dispose()
    {
        DeleteTranscriptionWaves();
        _player.Dispose();
        _loopbackWriter?.Dispose();
        _loopbackCapture?.Dispose();
        _microphoneWriter?.Dispose();
        _microphoneCapture?.Dispose();
    }

    private static List<AudioDeviceOption> ListDevices(DataFlow dataFlow)
    {
        using var enumerator = new MMDeviceEnumerator();
        string? defaultDeviceId = null;
        if (enumerator.HasDefaultAudioEndpoint(dataFlow, Role.Console))
        {
            using var defaultDevice = enumerator.GetDefaultAudioEndpoint(dataFlow, Role.Console);
            defaultDeviceId = defaultDevice.ID;
        }

        return enumerator
            .EnumerateAudioEndPoints(dataFlow, DeviceState.Active)
            .Select(device => new AudioDeviceOption(
                device.ID,
                device.FriendlyName,
                string.Equals(device.ID, defaultDeviceId, StringComparison.Ordinal)))
            .OrderByDescending(device => device.IsDefault)
            .ThenBy(device => device.Name, StringComparer.CurrentCulture)
            .ToList();
    }

    private static MMDevice ResolveDevice(DataFlow dataFlow, string? deviceId)
    {
        var enumerator = new MMDeviceEnumerator();
        return string.IsNullOrWhiteSpace(deviceId)
            ? enumerator.GetDefaultAudioEndpoint(dataFlow, Role.Console)
            : enumerator.GetDevice(deviceId);
    }

    private void BeginCaptureState()
    {
        _stopwatch.Restart();
        IsRecording = true;
        IsPaused = false;
    }

    private void StartLoopbackCapture(string? outputDeviceId)
    {
        var wavePath = Path.Combine(
            Path.GetTempPath(),
            $"memoisle-system-{Guid.NewGuid():N}.wav");
        var capture = new WasapiLoopbackCapture(ResolveDevice(DataFlow.Render, outputDeviceId));
        var writer = new WaveFileWriter(wavePath, capture.WaveFormat);
        var stopped = new TaskCompletionSource<bool>(
            TaskCreationOptions.RunContinuationsAsynchronously);

        capture.DataAvailable += (_, args) =>
        {
            // 暂停或停止后丢弃采样，保证 WAV 文件只包含有效会议片段。
            if (IsPaused || _loopbackStopping)
            {
                return;
            }
            writer.Write(args.Buffer, 0, args.BytesRecorded);
        };
        capture.RecordingStopped += (_, _) =>
        {
            writer.Dispose();
            stopped.TrySetResult(true);
        };

        _loopbackCapture = capture;
        _loopbackWriter = writer;
        _loopbackWavePath = wavePath;
        _loopbackStopTask = stopped;
        _loopbackStopping = false;
        try
        {
            capture.StartRecording();
        }
        catch
        {
            CleanupLoopbackCapture();
            File.Delete(wavePath);
            throw;
        }
    }

    private void StartMicrophoneCapture(string? inputDeviceId)
    {
        var wavePath = Path.Combine(
            Path.GetTempPath(),
            $"memoisle-microphone-{Guid.NewGuid():N}.wav");
        var capture = new WasapiCapture(ResolveDevice(DataFlow.Capture, inputDeviceId));
        var writer = new WaveFileWriter(wavePath, capture.WaveFormat);
        var stopped = new TaskCompletionSource<bool>(
            TaskCreationOptions.RunContinuationsAsynchronously);

        capture.DataAvailable += (_, args) =>
        {
            if (IsPaused || _microphoneStopping)
            {
                return;
            }
            writer.Write(args.Buffer, 0, args.BytesRecorded);
        };
        capture.RecordingStopped += (_, _) =>
        {
            writer.Dispose();
            stopped.TrySetResult(true);
        };

        _microphoneCapture = capture;
        _microphoneWriter = writer;
        _microphoneWavePath = wavePath;
        _microphoneStopTask = stopped;
        _microphoneStopping = false;
        try
        {
            capture.StartRecording();
        }
        catch
        {
            CleanupMicrophoneCapture();
            File.Delete(wavePath);
            throw;
        }
    }

    private async Task<string> StopLoopbackCaptureAsync()
    {
        var capture = _loopbackCapture
            ?? throw new InvalidOperationException("系统声音捕获未启动");
        var wavePath = _loopbackWavePath
            ?? throw new InvalidOperationException("系统声音文件不存在");

        _loopbackStopping = true;
        capture.StopRecording();
        if (_loopbackStopTask is not null)
        {
            await _loopbackStopTask.Task.WaitAsync(TimeSpan.FromSeconds(5));
        }

        capture.Dispose();
        CleanupLoopbackCapture();
        return wavePath;
    }

    private async Task<string> StopMicrophoneCaptureAsync()
    {
        var capture = _microphoneCapture
            ?? throw new InvalidOperationException("麦克风捕获未启动");
        var wavePath = _microphoneWavePath
            ?? throw new InvalidOperationException("麦克风文件不存在");

        _microphoneStopping = true;
        capture.StopRecording();
        if (_microphoneStopTask is not null)
        {
            await _microphoneStopTask.Task.WaitAsync(TimeSpan.FromSeconds(5));
        }

        capture.Dispose();
        CleanupMicrophoneCapture();
        return wavePath;
    }

    private void CleanupLoopbackCapture()
    {
        _loopbackCapture = null;
        _loopbackWriter = null;
        _loopbackStopTask = null;
        _loopbackStopping = false;
    }

    private void CleanupMicrophoneCapture()
    {
        _microphoneCapture = null;
        _microphoneWriter = null;
        _microphoneStopTask = null;
        _microphoneStopping = false;
    }

    private async Task<(string Path, int DurationMs)> FinishRecordingAsync(
        string wavePath,
        int durationMs)
    {
        // 原始 WAV 只用于生成 AAC；说话人区分所需的 ASR WAV 已在 StopAsync 中单独保留。
        var audioPath = await TranscodeWaveToAacAsync(wavePath);
        File.Delete(wavePath);
        _currentFilePath = audioPath;
        IsRecording = false;
        IsPaused = false;
        return (audioPath, durationMs);
    }

    /// <summary>删除并清空 ASR 临时音轨；转写失败时保留文件以便重试。</summary>
    public void DeleteTranscriptionWaves()
    {
        TryDeleteFile(SystemTranscriptionWavePath);
        TryDeleteFile(MicrophoneTranscriptionWavePath);
        SystemTranscriptionWavePath = null;
        MicrophoneTranscriptionWavePath = null;
    }

    private static void TryDeleteFile(string? path)
    {
        try
        {
            if (!string.IsNullOrWhiteSpace(path) && File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch (IOException)
        {
            // 临时 WAV 被解码器短暂占用时忽略；下一次开始/关闭时会再次清理。
        }
    }

    private static string CreateTranscriptionWave(string wavePath)
    {
        var asrWavePath = Path.Combine(
            Path.GetTempPath(),
            $"memoisle-asr-{Guid.NewGuid():N}.wav");
        var targetFormat = new WaveFormat(16_000, 16, 1);
        using var sourceReader = new WaveFileReader(wavePath);
        using var resampler = new MediaFoundationResampler(sourceReader, targetFormat);
        WaveFileWriter.CreateWaveFile(asrWavePath, resampler);
        return asrWavePath;
    }

    private static string MixWaveFiles(string systemWavePath, string microphoneWavePath)
    {
        var mixedWavePath = Path.Combine(
            Path.GetTempPath(),
            $"memoisle-mixed-{Guid.NewGuid():N}.wav");
        var targetFormat = new WaveFormat(44_100, 16, 2);

        using var systemReader = new WaveFileReader(systemWavePath);
        using var systemResampler = new MediaFoundationResampler(systemReader, targetFormat);
        using var microphoneReader = new WaveFileReader(microphoneWavePath);
        using var microphoneResampler = new MediaFoundationResampler(microphoneReader, targetFormat);
        var mixer = new MixingSampleProvider(new[]
        {
            systemResampler.ToSampleProvider(),
            microphoneResampler.ToSampleProvider(),
        });
        WaveFileWriter.CreateWaveFile(mixedWavePath, mixer.ToWaveProvider());
        return mixedWavePath;
    }

    /// <summary>将中间 WAV 转成 32 kbps AAC，让长时间会议也能低于 20MB 上传限制。</summary>
    private static async Task<string> TranscodeWaveToAacAsync(string wavePath)
    {
        var outputDirectory = Path.GetDirectoryName(wavePath)!;
        var folder = await StorageFolder.GetFolderFromPathAsync(outputDirectory);
        var sourceFile = await folder.GetFileAsync(Path.GetFileName(wavePath));
        var destinationFile = await folder.CreateFileAsync(
            Path.GetFileNameWithoutExtension(wavePath) + ".mp4",
            CreationCollisionOption.GenerateUniqueName);

        // WinRT 的 MP4 profile 参数是视频质量枚举；随后清空视频轨，仅保留 AAC 音频。
        var profile = MediaEncodingProfile.CreateMp4(VideoEncodingQuality.Auto);
        profile.Video = null;
        profile.Audio = AudioEncodingProperties.CreateAac(44_100, 1, 32_000);
        var transcoder = new MediaTranscoder();
        var result = await transcoder.PrepareFileTranscodeAsync(
            sourceFile,
            destinationFile,
            profile);
        if (!result.CanTranscode)
        {
            throw new InvalidOperationException(
                $"录音转码失败：{result.FailureReason}");
        }

        await result.TranscodeAsync();
        return destinationFile.Path;
    }
}
