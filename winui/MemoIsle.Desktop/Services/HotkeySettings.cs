using System.Text.Json;
using Windows.System;

namespace MemoIsle.Desktop.Services;

/// <summary>可自定义快捷键的动作。</summary>
public enum HotkeyAction
{
    NewGeneral,
    NewIdea,
    NewWord,
    NewResource,
    FocusSearch,
    Refresh,
    QuickCaptureWord,
    QuickCaptureResource,
    QuickCaptureIdea,
    TranslateSelection,
}

/// <summary>一条快捷键绑定：主键 + 修饰键集合。</summary>
public sealed class HotkeyBinding
{
    public string Key { get; set; } = "W";
    public List<string> Modifiers { get; set; } = new() { "Control" };

    public VirtualKey ToVirtualKey() =>
        Enum.TryParse<VirtualKey>(Key, ignoreCase: true, out var parsed) ? parsed : VirtualKey.None;

    public VirtualKeyModifiers ToVirtualModifiers()
    {
        var result = VirtualKeyModifiers.None;
        foreach (var modifier in Modifiers)
        {
            if (Enum.TryParse<VirtualKeyModifiers>(modifier, ignoreCase: true, out var parsed))
            {
                result |= parsed;
            }
        }
        return result;
    }

    public HotkeyBinding Clone() => new()
    {
        Key = Key,
        Modifiers = new List<string>(Modifiers),
    };
}

/// <summary>
/// 快捷键配置：读取 / 保存于 %APPDATA%\MemoIsle\hotkeys.json，未配置时使用默认值。
/// </summary>
public static class HotkeySettings
{
    private static readonly string DirectoryPath = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        "MemoIsle");

    private static readonly string FilePath = Path.Combine(DirectoryPath, "hotkeys.json");

    private static readonly Dictionary<HotkeyAction, HotkeyBinding> Defaults = new()
    {
        [HotkeyAction.NewGeneral] = new HotkeyBinding { Key = "N", Modifiers = { "Control" } },
        [HotkeyAction.NewIdea] = new HotkeyBinding { Key = "I", Modifiers = { "Control" } },
        [HotkeyAction.NewWord] = new HotkeyBinding { Key = "W", Modifiers = { "Control" } },
        [HotkeyAction.NewResource] = new HotkeyBinding { Key = "L", Modifiers = { "Control" } },
        [HotkeyAction.FocusSearch] = new HotkeyBinding { Key = "F", Modifiers = { "Control" } },
        [HotkeyAction.Refresh] = new HotkeyBinding { Key = "R", Modifiers = { "Control" } },
        [HotkeyAction.QuickCaptureWord] = new HotkeyBinding { Key = "W", Modifiers = { "Control", "Shift" } },
        [HotkeyAction.QuickCaptureResource] = new HotkeyBinding { Key = "L", Modifiers = { "Control", "Shift" } },
        [HotkeyAction.QuickCaptureIdea] = new HotkeyBinding { Key = "I", Modifiers = { "Control", "Shift" } },
        [HotkeyAction.TranslateSelection] = new HotkeyBinding { Key = "D", Modifiers = { "Control", "Menu" } },
    };

    private static Dictionary<HotkeyAction, HotkeyBinding>? _cache;

    public static string ActionLabel(HotkeyAction action) => action switch
    {
        HotkeyAction.NewGeneral => "新建（按当前视图）",
        HotkeyAction.NewIdea => "记录灵感",
        HotkeyAction.NewWord => "收藏单词",
        HotkeyAction.NewResource => "收藏网页资料",
        HotkeyAction.FocusSearch => "聚焦搜索框",
        HotkeyAction.QuickCaptureWord => "全局：收藏剪贴板单词",
        HotkeyAction.QuickCaptureResource => "全局：收藏剪贴板网址",
        HotkeyAction.QuickCaptureIdea => "全局：收藏剪贴板灵感",
        HotkeyAction.TranslateSelection => "全局：划词翻译剪贴板",
        _ => "刷新列表",
    };

    /// <summary>把绑定转为可读文本，例如 Ctrl+Shift+W。</summary>
    public static string Describe(HotkeyBinding binding)
    {
        var parts = new List<string>();
        if (binding.Modifiers.Contains("Control"))
        {
            parts.Add("Ctrl");
        }
        if (binding.Modifiers.Contains("Shift"))
        {
            parts.Add("Shift");
        }
        if (binding.Modifiers.Contains("Menu"))
        {
            parts.Add("Alt");
        }
        if (binding.Modifiers.Contains("Windows"))
        {
            parts.Add("Win");
        }
        parts.Add(binding.Key);
        return string.Join("+", parts);
    }

    public static HotkeyBinding Current(HotkeyAction action)
    {
        _cache ??= LoadAll();
        return _cache.TryGetValue(action, out var binding) && binding.Key.Length > 0
            ? binding
            : Defaults[action].Clone();
    }

    public static void Update(HotkeyAction action, HotkeyBinding binding)
    {
        _cache ??= LoadAll();
        _cache[action] = binding.Clone();
        SaveAll(_cache);
    }

    public static void ResetToDefaults()
    {
        _cache = Defaults.ToDictionary(pair => pair.Key, pair => pair.Value.Clone());
        SaveAll(_cache);
    }

    /// <summary>查找与该绑定冲突的其他动作（无冲突返回 null）。</summary>
    public static HotkeyAction? FindConflict(HotkeyAction action, HotkeyBinding binding)
    {
        foreach (var candidate in Enum.GetValues<HotkeyAction>())
        {
            if (candidate == action)
            {
                continue;
            }
            var existing = Current(candidate);
            if (string.Equals(existing.Key, binding.Key, StringComparison.OrdinalIgnoreCase) &&
                existing.ToVirtualModifiers() == binding.ToVirtualModifiers())
            {
                return candidate;
            }
        }
        return null;
    }

    /// <summary>校验绑定是否可用；不可用时返回原因。</summary>
    public static string? Validate(HotkeyBinding binding)
    {
        var key = binding.ToVirtualKey();
        if (key == VirtualKey.None)
        {
            return "请按下一个字母或数字键";
        }
        var modifiers = binding.ToVirtualModifiers();
        if (modifiers == VirtualKeyModifiers.None)
        {
            return "请至少搭配 Ctrl 或 Alt，避免与输入冲突";
        }
        if (!modifiers.HasFlag(VirtualKeyModifiers.Control) && !modifiers.HasFlag(VirtualKeyModifiers.Menu))
        {
            return "请至少包含 Ctrl 或 Alt";
        }
        // 功能键与编辑键容易与系统或输入框行为冲突，限制为字母与数字。
        var isLetter = key is >= VirtualKey.A and <= VirtualKey.Z;
        var isDigit = key is >= VirtualKey.Number0 and <= VirtualKey.Number9;
        if (!isLetter && !isDigit)
        {
            return "只支持字母与数字键";
        }
        return null;
    }

    private static Dictionary<HotkeyAction, HotkeyBinding> LoadAll()
    {
        var result = Defaults.ToDictionary(pair => pair.Key, pair => pair.Value.Clone());
        try
        {
            if (!File.Exists(FilePath))
            {
                return result;
            }
            var stored = JsonSerializer.Deserialize<Dictionary<string, HotkeyBinding>>(
                File.ReadAllText(FilePath));
            if (stored is null)
            {
                return result;
            }
            foreach (var (name, binding) in stored)
            {
                if (Enum.TryParse<HotkeyAction>(name, ignoreCase: true, out var action) &&
                    !string.IsNullOrWhiteSpace(binding.Key))
                {
                    result[action] = binding;
                }
            }
        }
        catch (Exception)
        {
            // 配置损坏时回退到默认值。
        }
        return result;
    }

    private static void SaveAll(Dictionary<HotkeyAction, HotkeyBinding> bindings)
    {
        try
        {
            Directory.CreateDirectory(DirectoryPath);
            var payload = bindings.ToDictionary(pair => pair.Key.ToString(), pair => pair.Value);
            File.WriteAllText(FilePath, JsonSerializer.Serialize(payload, new JsonSerializerOptions
            {
                WriteIndented = true,
            }));
        }
        catch (Exception)
        {
            // 写盘失败时不阻断使用（本次会话内仍然生效）。
        }
    }
}
