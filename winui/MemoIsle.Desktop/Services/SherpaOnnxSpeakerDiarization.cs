using System.Diagnostics;
using System.Globalization;
using System.Net.Http;
using NAudio.Wave;
using SherpaOnnx;

namespace MemoIsle.Desktop.Services;

/// <summary>基于 sherpa-onnx 的离线说话人分离服务，用于区分系统声音中的远端参会人。</summary>
public sealed class SherpaOnnxSpeakerDiarization
{
    private const string DefaultSegmentationModelUrl =
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/"
        + "sherpa-onnx-pyannote-segmentation-3-0.tar.bz2";
    private const string DefaultEmbeddingModelUrl =
        "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
        + "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx";
    private const int TargetSampleRate = 16_000;

    private static readonly HttpClient HttpClient = new()
    {
        Timeout = TimeSpan.FromMinutes(30),
    };

    private static readonly SemaphoreSlim ModelLock = new(1, 1);

    /// <summary>说话人分离结果；Speaker 是聚类编号，不代表真实姓名。</summary>
    public sealed record SpeakerDiarizationSegment(TimeSpan Start, TimeSpan End, int Speaker);

    /// <summary>分离单条 16 kHz 音轨中的说话人，并按开始时间返回片段。</summary>
    public async Task<IReadOnlyList<SpeakerDiarizationSegment>> ProcessAsync(
        string audioPath,
        IProgress<string>? progress = null,
        CancellationToken cancellationToken = default)
    {
        if (!File.Exists(audioPath))
        {
            throw new FileNotFoundException("说话人分离音轨不存在", audioPath);
        }

        // 下载、声纹提取和聚类都在后台执行，避免阻塞会议保存界面。
        return await Task.Run(
            async () =>
            {
                var (segmentationPath, embeddingPath) = await EnsureModelsAsync(
                    progress,
                    cancellationToken);
                progress?.Report("正在分离远端说话人…");

                var samples = ReadSamples(audioPath);
                using var diarization = CreateDiarization(segmentationPath, embeddingPath);
                if (diarization.SampleRate != TargetSampleRate)
                {
                    throw new InvalidOperationException(
                        $"说话人分离模型要求 {TargetSampleRate} Hz 音频，当前为 {diarization.SampleRate} Hz");
                }

                var lastPercent = -1;
                var callback = new OfflineSpeakerDiarizationProgressCallback(
                    (processedChunks, totalChunks, _) =>
                    {
                        if (totalChunks <= 0)
                        {
                            return 0;
                        }

                        var percent = processedChunks * 100 / totalChunks;
                        if (percent != lastPercent && percent % 5 == 0)
                        {
                            progress?.Report($"正在分离远端说话人… {percent}%");
                            lastPercent = percent;
                        }

                        return 0;
                    });

                var rawSegments = diarization.ProcessWithCallback(
                    samples,
                    callback,
                    IntPtr.Zero);
                return rawSegments
                    .Where(segment => segment.End > segment.Start)
                    .Select(segment => new SpeakerDiarizationSegment(
                        TimeSpan.FromSeconds(segment.Start),
                        TimeSpan.FromSeconds(segment.End),
                        segment.Speaker))
                    .OrderBy(segment => segment.Start)
                    .ToList();
            },
            cancellationToken);
    }

    /// <summary>确保 pyannote 分段模型和 3DSpeaker 声纹模型已经下载。</summary>
    private static async Task<(string SegmentationPath, string EmbeddingPath)> EnsureModelsAsync(
        IProgress<string>? progress,
        CancellationToken cancellationToken)
    {
        var directory = Environment.GetEnvironmentVariable("MEMOISLE_SPEAKER_DIARIZATION_DIR");
        directory = string.IsNullOrWhiteSpace(directory)
            ? Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "MemoIsle",
                "models",
                "speaker-diarization")
            : directory!;

        var segmentationPath = Path.Combine(directory, "segmentation.onnx");
        var embeddingPath = Path.Combine(directory, "speaker-embedding.onnx");
        if (IsModelReady(segmentationPath, embeddingPath))
        {
            return (segmentationPath, embeddingPath);
        }

        await ModelLock.WaitAsync(cancellationToken);
        try
        {
            if (IsModelReady(segmentationPath, embeddingPath))
            {
                return (segmentationPath, embeddingPath);
            }

            Directory.CreateDirectory(directory);
            var segmentationArchivePath = Path.Combine(
                Path.GetTempPath(),
                "memoisle-speaker-segmentation.tar.bz2");
            var embeddingArchivePath = Path.Combine(
                Path.GetTempPath(),
                "memoisle-speaker-embedding.onnx");

            if (!IsSegmentationModelReady(segmentationPath))
            {
                progress?.Report("正在下载说话人分段模型（首次约 7 MB）…");
                await DownloadFileAsync(
                    Environment.GetEnvironmentVariable("MEMOISLE_SPEAKER_SEGMENTATION_MODEL_URL")
                        ?? DefaultSegmentationModelUrl,
                    segmentationArchivePath,
                    "说话人分段模型",
                    progress,
                    cancellationToken);
                progress?.Report("正在准备说话人分段模型…");
                await ExtractSegmentationModelAsync(
                    segmentationArchivePath,
                    segmentationPath,
                    cancellationToken);
            }

            if (!IsEmbeddingModelReady(embeddingPath))
            {
                progress?.Report("正在下载说话人声纹模型（首次约 40 MB）…");
                await DownloadFileAsync(
                    Environment.GetEnvironmentVariable("MEMOISLE_SPEAKER_EMBEDDING_MODEL_URL")
                        ?? DefaultEmbeddingModelUrl,
                    embeddingArchivePath,
                    "说话人声纹模型",
                    progress,
                    cancellationToken);
                Directory.CreateDirectory(directory);
                File.Move(embeddingArchivePath, embeddingPath, true);
            }

            if (!IsModelReady(segmentationPath, embeddingPath))
            {
                throw new InvalidOperationException("说话人分离模型下载不完整，请重试");
            }

            return (segmentationPath, embeddingPath);
        }
        finally
        {
            TryDelete(Path.Combine(Path.GetTempPath(), "memoisle-speaker-segmentation.tar.bz2"));
            TryDelete(Path.Combine(Path.GetTempPath(), "memoisle-speaker-embedding.onnx"));
            ModelLock.Release();
        }
    }

    private static bool IsModelReady(string segmentationPath, string embeddingPath)
        => IsSegmentationModelReady(segmentationPath) && IsEmbeddingModelReady(embeddingPath);

    private static bool IsSegmentationModelReady(string path)
        => File.Exists(path) && new FileInfo(path).Length > 1_000_000;

    private static bool IsEmbeddingModelReady(string path)
        => File.Exists(path) && new FileInfo(path).Length > 30_000_000;

    private static async Task DownloadFileAsync(
        string url,
        string targetPath,
        string description,
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
        var buffer = new byte[512 * 1024];
        long totalBytes = response.Content.Headers.ContentLength ?? 0;
        long writtenBytes = 0;
        int lastPercent = -1;
        int bytesRead;

        while ((bytesRead = await source.ReadAsync(buffer, cancellationToken)) > 0)
        {
            await target.WriteAsync(buffer.AsMemory(0, bytesRead), cancellationToken);
            writtenBytes += bytesRead;
            if (totalBytes <= 0)
            {
                continue;
            }

            var percent = (int)(writtenBytes * 100 / totalBytes);
            if (percent != lastPercent && percent % 5 == 0)
            {
                progress?.Report($"正在下载{description}… {percent}%");
                lastPercent = percent;
            }
        }
    }

    /// <summary>解压 pyannote 压缩包，只保留 model.onnx 并改名为 segmentation.onnx。</summary>
    private static async Task ExtractSegmentationModelAsync(
        string archivePath,
        string segmentationPath,
        CancellationToken cancellationToken)
    {
        var extractDirectory = Path.Combine(
            Path.GetTempPath(),
            "memoisle-speaker-diarization-extract");
        if (Directory.Exists(extractDirectory))
        {
            Directory.Delete(extractDirectory, recursive: true);
        }

        Directory.CreateDirectory(extractDirectory);
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

        try
        {
            using var process = Process.Start(startInfo)
                ?? throw new InvalidOperationException("无法启动 Windows tar 解压程序");
            var standardError = await process.StandardError.ReadToEndAsync(cancellationToken);
            await process.WaitForExitAsync(cancellationToken).WaitAsync(
                TimeSpan.FromMinutes(5),
                cancellationToken);
            if (process.ExitCode != 0)
            {
                throw new InvalidOperationException($"说话人分段模型解压失败：{standardError.Trim()}");
            }

            var extractedModelPath = Directory.EnumerateFiles(
                extractDirectory,
                "model.onnx",
                SearchOption.AllDirectories).FirstOrDefault()
                ?? throw new InvalidOperationException("说话人分段模型压缩包缺少 model.onnx");
            Directory.CreateDirectory(Path.GetDirectoryName(segmentationPath)!);
            File.Move(extractedModelPath, segmentationPath, true);
        }
        finally
        {
            if (Directory.Exists(extractDirectory))
            {
                Directory.Delete(extractDirectory, recursive: true);
            }
        }
    }

    /// <summary>创建 pyannote + 3DSpeaker + 快速聚类配置。</summary>
    private static OfflineSpeakerDiarization CreateDiarization(
        string segmentationPath,
        string embeddingPath)
    {
        var threadCount = Math.Clamp(Environment.ProcessorCount, 1, 4);
        var config = new OfflineSpeakerDiarizationConfig
        {
            Segmentation = new OfflineSpeakerSegmentationModelConfig
            {
                Pyannote = new OfflineSpeakerSegmentationPyannoteModelConfig
                {
                    Model = segmentationPath,
                    WindowShiftRatio = 0.1f,
                },
                NumThreads = threadCount,
                Debug = 0,
                Provider = "cpu",
            },
            Embedding = new SpeakerEmbeddingExtractorConfig
            {
                Model = embeddingPath,
                NumThreads = threadCount,
                Debug = 0,
                Provider = "cpu",
            },
            Clustering = new FastClusteringConfig
            {
                NumClusters = -1,
                Threshold = GetClusteringThreshold(),
                ComputeConfidence = 0,
            },
            MinDurationOn = 0.3f,
            MinDurationOff = 0.5f,
        };

        return new OfflineSpeakerDiarization(config);
    }

    /// <summary>读取聚类阈值；允许用户按实际会议声纹差异微调。</summary>
    private static float GetClusteringThreshold()
    {
        var value = Environment.GetEnvironmentVariable("MEMOISLE_SPEAKER_DIARIZATION_THRESHOLD");
        return float.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out var threshold)
            ? Math.Clamp(threshold, 0.1f, 0.9f)
            : 0.5f;
    }

    /// <summary>读取 16 kHz 单声道采样；ASR 临时 WAV 通常已是目标格式。</summary>
    private static float[] ReadSamples(string audioPath)
    {
        using var sourceReader = new WaveFileReader(audioPath);
        if (sourceReader.WaveFormat.SampleRate == TargetSampleRate
            && sourceReader.WaveFormat.Channels == 1
            && sourceReader.WaveFormat.BitsPerSample == 16)
        {
            var samples = new float[sourceReader.Length / 2];
            var buffer = new byte[64 * 1024];
            var readSamples = 0;
            int bytesRead;
            while ((bytesRead = sourceReader.Read(buffer, 0, buffer.Length)) > 0)
            {
                var validBytes = bytesRead - bytesRead % 2;
                for (var offset = 0; offset < validBytes; offset += 2)
                {
                    samples[readSamples++] = BitConverter.ToInt16(buffer, offset) / 32768f;
                }
            }

            Array.Resize(ref samples, readSamples);
            return samples;
        }

        var targetFormat = new WaveFormat(TargetSampleRate, 16, 1);
        using var reader = new MediaFoundationResampler(sourceReader, targetFormat);
        using var output = new MemoryStream();
        var buffer2 = new byte[64 * 1024];
        int bytesCopied;
        while ((bytesCopied = reader.Read(buffer2, 0, buffer2.Length)) > 0)
        {
            output.Write(buffer2, 0, bytesCopied);
        }

        var bytes = output.ToArray();
        var resampledSamples = new float[bytes.Length / 2];
        for (var offset = 0; offset + 1 < bytes.Length; offset += 2)
        {
            resampledSamples[offset / 2] = BitConverter.ToInt16(bytes, offset) / 32768f;
        }

        return resampledSamples;
    }

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
            // 临时文件被占用时忽略；下次下载前会覆盖或重新删除。
        }
    }
}
