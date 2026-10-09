using System.Text.Json;
using System.Text.Json.Serialization;

namespace MemoIsle.Desktop.Services;

/// <summary>翻译提供方：Google 免费接口、自配大模型，或自动（Google 失败时回退大模型）。</summary>
public enum TranslationProvider
{
    Google,
    Llm,
    Auto,
}

/// <summary>翻译设置（存于 %APPDATA%\MemoIsle\translation.json）。</summary>
public sealed class TranslationConfig
{
    public string Provider { get; set; } = "google";
    public string TargetLanguage { get; set; } = "zh-CN";
    public string ApiBase { get; set; } = "https://api.openai.com/v1";
    public string ApiKey { get; set; } = string.Empty;
    public string Model { get; set; } = "gpt-4o-mini";
    public string SystemPrompt { get; set; } =
        "你是专业翻译引擎。把用户文本翻译成{target}，只输出译文，不要解释、不要加引号。";
    public bool AutoCopy { get; set; } = true;

    /// <summary>自动模拟 Ctrl+C 取词（关掉则需先手动复制）。</summary>
    public bool AutoCopySelection { get; set; } = true;

    [JsonIgnore]
    public TranslationProvider ResolvedProvider => Provider?.ToLowerInvariant() switch
    {
        "llm" => TranslationProvider.Llm,
        "auto" => TranslationProvider.Auto,
        _ => TranslationProvider.Google,
    };

    /// <summary>大模型通道是否已配置完整（用于自动回退与提示）。</summary>
    [JsonIgnore]
    public bool LlmConfigured =>
        !string.IsNullOrWhiteSpace(ApiBase) && !string.IsNullOrWhiteSpace(Model);

    public TranslationConfig Clone() => new()
    {
        Provider = Provider,
        TargetLanguage = TargetLanguage,
        ApiBase = ApiBase,
        ApiKey = ApiKey,
        Model = Model,
        SystemPrompt = SystemPrompt,
        AutoCopy = AutoCopy,
        AutoCopySelection = AutoCopySelection,
    };
}

/// <summary>翻译设置的读写与默认值。</summary>
public static class TranslationSettings
{
    private static readonly string DirectoryPath = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        "MemoIsle");

    private static readonly string FilePath = Path.Combine(DirectoryPath, "translation.json");

    private static TranslationConfig? _cache;

    /// <summary>常用目标语言（Google 代码 + 显示名）。</summary>
    public static readonly (string Code, string Label)[] TargetLanguages =
    {
        ("zh-CN", "简体中文"),
        ("zh-TW", "繁體中文"),
        ("en", "英语"),
        ("ja", "日语"),
        ("ko", "韩语"),
        ("fr", "法语"),
        ("de", "德语"),
        ("es", "西班牙语"),
        ("ru", "俄语"),
    };

    public static string LanguageLabel(string code) =>
        TargetLanguages.FirstOrDefault(item => item.Code == code).Label ?? code;

    public static TranslationConfig Current
    {
        get
        {
            _cache ??= Load();
            return _cache;
        }
    }

    public static void Save(TranslationConfig config)
    {
        _cache = config.Clone();
        try
        {
            Directory.CreateDirectory(DirectoryPath);
            File.WriteAllText(
                FilePath,
                JsonSerializer.Serialize(_cache, new JsonSerializerOptions { WriteIndented = true }));
        }
        catch (Exception)
        {
            // 写盘失败时本次会话仍生效。
        }
    }

    private static TranslationConfig Load()
    {
        try
        {
            if (!File.Exists(FilePath))
            {
                return new TranslationConfig();
            }
            return JsonSerializer.Deserialize<TranslationConfig>(File.ReadAllText(FilePath))
                   ?? new TranslationConfig();
        }
        catch (Exception)
        {
            return new TranslationConfig();
        }
    }
}
