using System.Net.Http;
using System.Diagnostics;
using NAudio.Wave;
using SherpaOnnx;

namespace MemoIsle.Desktop.Services;

/// <summary>基于 sherpa-onnx SenseVoice 的离线语音转写服务。</summary>
public sealed class SherpaOnnxSpeechToText
{
    private const string DefaultModelArchiveUrl =
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
        + "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17.tar.bz2";
    private const int TargetSampleRate = 16_000;
    private const int FrameSamples = 320; // 20ms：VAD 能量帧长度
    private const int MinimumSpeechFrames = 8; // 160ms：过滤短噪声
    private const int MergeGapFrames = 20; // 400ms：合并句中小停顿
    private const int PaddingFrames = 5; // 100ms：给识别片段保留前后文
    private const int MaximumSegmentSamples = TargetSampleRate * 30; // SenseVoice 单段最长 30 秒

    private static readonly HttpClient HttpClient = new()
    {
        Timeout = TimeSpan.FromMinutes(30),
    };

    private static readonly SemaphoreSlim ModelLock = new(1, 1);

    /// <summary>带时间戳的语音识别片段；Speaker 为 -1 表示未启用说话人分离。</summary>
    public sealed record SpeechSegment(TimeSpan Start, TimeSpan End, string Text, int Speaker = -1);

    public async Task<string> TranscribeAsync(
        string audioPath,
        string? asrWavePath = null,
        IProgress<string>? progress = null,
        CancellationToken cancellationToken = default)
    {
        var segments = await TranscribeSegmentsAsync(audioPath, asrWavePath, progress, cancellationToken);
        var text = string.Join(" ", segments.Select(segment => segment.Text.Trim()).Where(text => text.Length > 0));
        return text.Length == 0
            ? throw new InvalidOperationException("没有识别到语音内容")
            : text.Trim();
    }

    /// <summary>识别单条音轨，并返回带时间戳的语音片段。</summary>
    public async Task<IReadOnlyList<SpeechSegment>> TranscribeSegmentsAsync(
        string audioPath,
        string? asrWavePath,
        IProgress<string>? progress = null,
        CancellationToken cancellationToken = default,
        IReadOnlyList<SherpaOnnxSpeakerDiarization.SpeakerDiarizationSegment>? speakerSegments = null)
    {
        if (!File.Exists(audioPath))
        {
            throw new FileNotFoundException("录音文件不存在", audioPath);
        }

        // 模型加载和 CPU 解码都在后台执行，避免长时间会议阻塞 UI。
        return await Task.Run(
            async () =>
            {
                var (modelPath, tokensPath) = await EnsureModelAsync(progress, cancellationToken);
                progress?.Report("正在离线转写录音…");
                using var recognizer = CreateRecognizer(modelPath, tokensPath);
                return RecognizeSegments(recognizer, audioPath, asrWavePath, speakerSegments);
            },
            cancellationToken);
    }

    /// <summary>分别识别系统声音和麦克风音轨；两条音轨共用一次模型加载。</summary>
    public async Task<(
        IReadOnlyList<SpeechSegment> SystemSegments,
        IReadOnlyList<SpeechSegment> MicrophoneSegments
        )> TranscribeSpeakerTracksAsync(
        string audioPath,
        string systemAsrWavePath,
        string microphoneAsrWavePath,
        IProgress<string>? progress = null,
        CancellationToken cancellationToken = default,
        IReadOnlyList<SherpaOnnxSpeakerDiarization.SpeakerDiarizationSegment>? systemSpeakerSegments = null)
    {
        if (!File.Exists(audioPath))
        {
            throw new FileNotFoundException("录音文件不存在", audioPath);
        }
        if (!File.Exists(systemAsrWavePath))
        {
            throw new FileNotFoundException("系统声音转写音轨不存在", systemAsrWavePath);
        }
        if (!File.Exists(microphoneAsrWavePath))
        {
            throw new FileNotFoundException("麦克风转写音轨不存在", microphoneAsrWavePath);
        }

        return await Task.Run(
            async () =>
            {
                var (modelPath, tokensPath) = await EnsureModelAsync(progress, cancellationToken);
                using var recognizer = CreateRecognizer(modelPath, tokensPath);

                progress?.Report("正在识别“对方”声音…");
                var systemSegments = RecognizeSegments(
                    recognizer,
                    audioPath,
                    systemAsrWavePath,
                    systemSpeakerSegments);

                progress?.Report("正在识别“我”的声音…");
                var microphoneSegments = RecognizeSegments(recognizer, audioPath, microphoneAsrWavePath);

                return (systemSegments, microphoneSegments);
            },
            cancellationToken);
    }

    /// <summary>确保 SenseVoice 模型和词表已经下载；首次使用会下载约 155 MB 压缩包。</summary>
    private static async Task<(string ModelPath, string TokensPath)> EnsureModelAsync(
        IProgress<string>? progress,
        CancellationToken cancellationToken)
    {
        var directory = Environment.GetEnvironmentVariable("MEMOISLE_SENSEVOICE_DIR");
        directory = string.IsNullOrWhiteSpace(directory)
            ? Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "MemoIsle",
                "models",
                "sensevoice")
            : directory!;
        var modelPath = Path.Combine(directory, "model.int8.onnx");
        var tokensPath = Path.Combine(directory, "tokens.txt");
        if (IsModelReady(modelPath, tokensPath))
        {
            return (modelPath, tokensPath);
        }

        await ModelLock.WaitAsync(cancellationToken);
        try
        {
            if (IsModelReady(modelPath, tokensPath))
            {
                return (modelPath, tokensPath);
            }

            Directory.CreateDirectory(directory);
            var archiveUrl = Environment.GetEnvironmentVariable("MEMOISLE_SENSEVOICE_MODEL_URL")
                ?? DefaultModelArchiveUrl;
            var archivePath = Path.Combine(
                Path.GetTempPath(),
                "memoisle-sensevoice.tar.bz2");
            progress?.Report("正在下载离线语音模型（首次约 155 MB）…");
            await DownloadFileAsync(archiveUrl, archivePath, progress, cancellationToken);

            progress?.Report("正在准备离线语音模型…");
            await ExtractModelFilesAsync(archivePath, modelPath, tokensPath, cancellationToken);
            if (!IsModelReady(modelPath, tokensPath))
            {
                throw new InvalidOperationException("语音模型压缩包缺少 model.int8.onnx 或 tokens.txt");
            }

            return (modelPath, tokensPath);
        }
        finally
        {
            // 下载临时压缩包在成功或失败后都不保留，避免占用用户磁盘。
            TryDelete(Path.Combine(Path.GetTempPath(), "memoisle-sensevoice.tar.bz2"));
            ModelLock.Release();
        }
    }

    private static bool IsModelReady(string modelPath, string tokensPath)
    {
        // 用最小大小过滤半成品文件，避免模型下载中断后被误认为可用。
        return File.Exists(modelPath)
            && File.Exists(tokensPath)
            && new FileInfo(modelPath).Length > 100_000_000
            && new FileInfo(tokensPath).Length > 0;
    }

    private static async Task DownloadFileAsync(
        string url,
        string targetPath,
        IProgress<string>? progress,
        CancellationToken cancellationToken)
    {
        using var response = await HttpClient.GetAsync(
            url,
            HttpCompletionOption.ResponseHeadersRead,
            cancellationToken);
        response.EnsureSuccessStatusCode();
        await using var source = await response.Content.ReadAsStreamAsync(cancellationToken);
        await using var target = File.Create(targetPath);
        var buffer = new byte[1024 * 512];
        long totalBytes = response.Content.Headers.ContentLength ?? 0;
        long writtenBytes = 0;
        int lastPercent = -1;
        int bytesRead;
        while ((bytesRead = await source.ReadAsync(buffer, cancellationToken)) > 0)
        {
            await target.WriteAsync(buffer.AsMemory(0, bytesRead), cancellationToken);
            writtenBytes += bytesRead;
            if (totalBytes > 0)
            {
                var percent = (int)(writtenBytes * 100 / totalBytes);
                if (percent != lastPercent && percent % 5 == 0)
                {
                    progress?.Report($"正在下载离线语音模型… {percent}%");
                    lastPercent = percent;
                }
            }
        }
    }

    private static async Task ExtractModelFilesAsync(
        string archivePath,
        string modelPath,
        string tokensPath,
        CancellationToken cancellationToken)
    {
        var extractDirectory = Path.Combine(
            Path.GetTempPath(),
            "memoisle-sensevoice-extract");
        if (Directory.Exists(extractDirectory))
        {
            Directory.Delete(extractDirectory, recursive: true);
        }
        Directory.CreateDirectory(extractDirectory);

        // Windows 10/11 自带 bsdtar，可处理 tar + bzip2；SharpCompress 不支持 BZip2。
        var tarPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.System),
            "tar.exe");
        var startInfo = new ProcessStartInfo
        {
            FileName = tarPath,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardError = true,
        };
        startInfo.ArgumentList.Add("-xjf");
        startInfo.ArgumentList.Add(archivePath);
        startInfo.ArgumentList.Add("-C");
        startInfo.ArgumentList.Add(extractDirectory);

        using var process = Process.Start(startInfo)
            ?? throw new InvalidOperationException("无法启动 Windows tar 解压程序");
        var standardError = await process.StandardError.ReadToEndAsync(cancellationToken);
        await process.WaitForExitAsync(cancellationToken).WaitAsync(
            TimeSpan.FromMinutes(5),
            cancellationToken);
        if (process.ExitCode != 0)
        {
            throw new InvalidOperationException(
                $"语音模型解压失败：{standardError.Trim()}");
        }

        var extractedModelPath = Directory.EnumerateFiles(
            extractDirectory,
            "model.int8.onnx",
            SearchOption.AllDirectories).FirstOrDefault()
            ?? throw new InvalidOperationException("语音模型压缩包缺少 model.int8.onnx");
        var extractedTokensPath = Directory.EnumerateFiles(
            extractDirectory,
            "tokens.txt",
            SearchOption.AllDirectories).FirstOrDefault()
            ?? throw new InvalidOperationException("语音模型压缩包缺少 tokens.txt");

        Directory.CreateDirectory(Path.GetDirectoryName(modelPath)!);
        File.Move(extractedModelPath, modelPath, true);
        File.Move(extractedTokensPath, tokensPath, true);
        Directory.Delete(extractDirectory, recursive: true);
    }

    /// <summary>创建 SenseVoice 离线识别器。</summary>
    private static OfflineRecognizer CreateRecognizer(string modelPath, string tokensPath)
    {
        var config = new OfflineRecognizerConfig
        {
            FeatConfig = new FeatureConfig
            {
                SampleRate = TargetSampleRate,
                FeatureDim = 80,
            },
            ModelConfig = new OfflineModelConfig
            {
                Tokens = tokensPath,
                NumThreads = Math.Clamp(Environment.ProcessorCount, 1, 4),
                Debug = 0,
                Provider = "cpu",
                SenseVoice = new OfflineSenseVoiceModelConfig
                {
                    Model = modelPath,
                    Language = "",
                    UseInverseTextNormalization = 1,
                },
            },
            DecodingMethod = "greedy_search",
        };

        return new OfflineRecognizer(config);
    }

    /// <summary>按能量 VAD 切分语音并识别，返回带起止时间的片段。</summary>
    private static IReadOnlyList<SpeechSegment> RecognizeSegments(
        OfflineRecognizer recognizer,
        string audioPath,
        string? asrWavePath,
        IReadOnlyList<SherpaOnnxSpeakerDiarization.SpeakerDiarizationSegment>? speakerSegments = null)
    {
        // 有 diarization 结果时按说话人边界识别；失败或无结果时回退到能量 VAD。
        var ranges = speakerSegments is { Count: > 0 }
            ? CreateDiarizationRanges(speakerSegments)
            : AnalyzeAudio(audioPath, asrWavePath).Ranges;
        var segments = new List<SpeechSegment>();
        foreach (var (range, samples) in ReadAudioSegments(audioPath, asrWavePath, ranges))
        {
            using var stream = recognizer.CreateStream();
            stream.AcceptWaveform(TargetSampleRate, samples);
            recognizer.Decode(stream);
            var segmentText = stream.Result.Text.Trim();
            if (segmentText.Length > 0)
            {
                // 时间戳来自 16 kHz 采样位置，用于后续把两条音轨按对话顺序合并。
                segments.Add(new SpeechSegment(
                    TimeSpan.FromSeconds(range.StartSample / (double)TargetSampleRate),
                    TimeSpan.FromSeconds(range.EndSample / (double)TargetSampleRate),
                    segmentText,
                    range.Speaker));
            }
        }

        return segments;
    }

    /// <summary>把 diarization 秒级区间转换成 16 kHz 采样区间，并保持说话人编号。</summary>
    private static IReadOnlyList<AudioRange> CreateDiarizationRanges(
        IReadOnlyList<SherpaOnnxSpeakerDiarization.SpeakerDiarizationSegment> speakerSegments)
    {
        var ranges = new List<AudioRange>();
        long previousEndSample = 0;
        foreach (var segment in speakerSegments
            .Where(segment => segment.End > segment.Start)
            .OrderBy(segment => segment.Start)
            .ThenBy(segment => segment.End))
        {
            var startSample = Math.Max(0L, (long)(segment.Start.TotalSeconds * TargetSampleRate));
            var endSample = (long)(segment.End.TotalSeconds * TargetSampleRate);
            if (startSample < previousEndSample)
            {
                startSample = previousEndSample;
            }

            while (endSample > startSample)
            {
                var segmentEndSample = Math.Min(
                    endSample,
                    startSample + MaximumSegmentSamples);
                ranges.Add(new AudioRange(startSample, segmentEndSample, segment.Speaker));
                startSample = segmentEndSample;
            }

            if (endSample > previousEndSample)
            {
                previousEndSample = endSample;
            }
        }

        return ranges;
    }

    /// <summary>分析音频能量，找出疑似语音区间。</summary>
    private static (IReadOnlyList<AudioRange> Ranges, long TotalSamples) AnalyzeAudio(
        string audioPath,
        string? asrWavePath)
    {
        var frameEnergies = new List<float>();
        long totalSamples = 0;
        double frameSquareSum = 0;
        var frameSampleCount = 0;
        var buffer = new byte[64 * 1024];
        int bytesRead;

        var targetFormat = new WaveFormat(TargetSampleRate, 16, 1);
        var useAsrWave = !string.IsNullOrWhiteSpace(asrWavePath) && File.Exists(asrWavePath);
        using WaveStream sourceReader = useAsrWave
            ? new WaveFileReader(asrWavePath!)
            : new MediaFoundationReader(audioPath);
        using (var reader = new MediaFoundationResampler(sourceReader, targetFormat))
        {
            while ((bytesRead = reader.Read(buffer, 0, buffer.Length)) > 0)
            {
                // 目标格式固定为 16-bit 单声道，两个字节对应一个采样。
                for (var offset = 0; offset + 1 < bytesRead; offset += 2)
                {
                    var sample = BitConverter.ToInt16(buffer, offset) / 32768f;
                    totalSamples++;
                    frameSquareSum += sample * sample;
                    frameSampleCount++;

                    if (frameSampleCount == FrameSamples)
                    {
                        frameEnergies.Add((float)Math.Sqrt(frameSquareSum / frameSampleCount));
                        frameSquareSum = 0;
                        frameSampleCount = 0;
                    }
                }
            }
        }

        if (frameSampleCount > 0)
        {
            frameEnergies.Add((float)Math.Sqrt(frameSquareSum / frameSampleCount));
        }

        return (CreateSpeechRanges(frameEnergies, totalSamples), totalSamples);
    }

    /// <summary>使用帧能量阈值生成语音区间，并按 SenseVoice 最长 30 秒切分。</summary>
    private static IReadOnlyList<AudioRange> CreateSpeechRanges(
        IReadOnlyList<float> frameEnergies,
        long totalSamples)
    {
        if (frameEnergies.Count == 0 || totalSamples == 0)
        {
            return Array.Empty<AudioRange>();
        }

        var sortedEnergies = frameEnergies.OrderBy(energy => energy).ToArray();
        var noiseFloor = Percentile(sortedEnergies, 0.20f);
        var speechLevel = Percentile(sortedEnergies, 0.90f);
        var threshold = MathF.Max(0.004f, MathF.Max(noiseFloor * 3f, speechLevel * 0.12f));
        var ranges = BuildSpeechRanges(frameEnergies, totalSamples, threshold);

        // 少数很轻的语音可能低于首轮阈值；降低阈值重试一次，避免整轨漏识别。
        if (ranges.Count == 0 && speechLevel > 0.0008f)
        {
            threshold = MathF.Max(0.001f, noiseFloor * 1.5f);
            ranges = BuildSpeechRanges(frameEnergies, totalSamples, threshold);
        }

        return ranges;
    }

    private static List<AudioRange> BuildSpeechRanges(
        IReadOnlyList<float> frameEnergies,
        long totalSamples,
        float threshold)
    {
        var ranges = new List<AudioRange>();
        int? startFrame = null;
        var lastActiveFrame = 0;
        var activeFrameCount = 0;

        for (var frameIndex = 0; frameIndex < frameEnergies.Count; frameIndex++)
        {
            if (frameEnergies[frameIndex] >= threshold)
            {
                startFrame ??= frameIndex;
                lastActiveFrame = frameIndex;
                activeFrameCount++;
                continue;
            }

            if (startFrame is not null && frameIndex - lastActiveFrame >= MergeGapFrames)
            {
                AddSpeechRange(
                    ranges,
                    startFrame.Value,
                    lastActiveFrame,
                    activeFrameCount,
                    totalSamples);
                startFrame = null;
                activeFrameCount = 0;
            }
        }

        if (startFrame is not null)
        {
            AddSpeechRange(
                ranges,
                startFrame.Value,
                lastActiveFrame,
                activeFrameCount,
                totalSamples);
        }

        return ranges;
    }

    private static void AddSpeechRange(
        List<AudioRange> ranges,
        int startFrame,
        int lastActiveFrame,
        int activeFrameCount,
        long totalSamples)
    {
        if (activeFrameCount < MinimumSpeechFrames)
        {
            return;
        }

        long startSample = Math.Max(
            0L,
            (startFrame * FrameSamples) - (PaddingFrames * FrameSamples));
        long endSample = Math.Min(
            totalSamples,
            ((lastActiveFrame + 1) * FrameSamples) + (PaddingFrames * FrameSamples));

        // 补前后文后相邻区间可能重叠，保留不重叠边界，避免同一句话重复识别。
        if (ranges.Count > 0 && ranges[^1].EndSample >= startSample)
        {
            startSample = ranges[^1].EndSample;
        }

        while (endSample > startSample)
        {
            var segmentEnd = Math.Min(endSample, startSample + MaximumSegmentSamples);
            if (segmentEnd > startSample)
            {
                ranges.Add(new AudioRange(startSample, segmentEnd, -1));
            }
            startSample = segmentEnd;
        }
    }

    private static float Percentile(float[] sortedValues, float percentile)
    {
        var index = (int)Math.Round(percentile * (sortedValues.Length - 1));
        return sortedValues[index];
    }

    /// <summary>顺序读取指定语音区间，避免把整场会议一次性加载进内存。</summary>
    private static IEnumerable<(AudioRange Range, float[] Samples)> ReadAudioSegments(
        string audioPath,
        string? asrWavePath,
        IReadOnlyList<AudioRange> ranges)
    {
        var targetFormat = new WaveFormat(TargetSampleRate, 16, 1);
        var useAsrWave = !string.IsNullOrWhiteSpace(asrWavePath) && File.Exists(asrWavePath);
        using WaveStream sourceReader = useAsrWave
            ? new WaveFileReader(asrWavePath!)
            : new MediaFoundationReader(audioPath);
        using var reader = new MediaFoundationResampler(sourceReader, targetFormat);
        var buffer = new byte[64 * 1024];
        long currentSample = 0;

        foreach (var range in ranges)
        {
            while (currentSample < range.StartSample)
            {
                var samplesToRead = (int)Math.Min(
                    range.StartSample - currentSample,
                    buffer.Length / 2);
                var bytesRead = reader.Read(buffer, 0, samplesToRead * 2);
                if (bytesRead <= 0)
                {
                    yield break;
                }

                currentSample += bytesRead / 2;
            }

            // 单个识别片段最长 30 秒，转换成 int 供数组分配使用。
            var samples = new float[checked((int)(range.EndSample - range.StartSample))];
            var readSamples = 0;
            while (readSamples < samples.Length)
            {
                var samplesToRead = Math.Min(samples.Length - readSamples, buffer.Length / 2);
                var bytesRead = reader.Read(buffer, 0, samplesToRead * 2);
                if (bytesRead <= 0)
                {
                    break;
                }

                var validBytes = bytesRead - (bytesRead % 2);
                for (var offset = 0; offset < validBytes; offset += 2)
                {
                    samples[readSamples++] = BitConverter.ToInt16(buffer, offset) / 32768f;
                }
                currentSample += validBytes / 2;
            }

            if (readSamples > 0)
            {
                Array.Resize(ref samples, readSamples);
                yield return (range, samples);
            }
        }
    }

    private readonly record struct AudioRange(long StartSample, long EndSample, int Speaker);

    private static void TryDelete(string path)
    {
        try
        {
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch (IOException)
        {
            // 临时文件被短暂占用时忽略；下一次下载前会再次尝试删除。
        }
    }
}
