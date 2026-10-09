using Microsoft.Win32;

namespace MemoIsle.Desktop.Services;

/// <summary>
/// 开机自启：写入当前用户的 Run 注册表项（无需管理员权限）。
/// 与托盘配合，让全局收藏热键开机即可用。
/// </summary>
public static class StartupSettings
{
    private const string RunKeyPath = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string ValueName = "MemoIsle";

    public static bool IsEnabled()
    {
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(RunKeyPath, writable: false);
            return key?.GetValue(ValueName) is string value && value.Length > 0;
        }
        catch (Exception)
        {
            return false;
        }
    }

    /// <summary>启用或关闭开机自启；返回是否操作成功。</summary>
    public static bool SetEnabled(bool enabled, string? executablePath = null)
    {
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(RunKeyPath, writable: true)
                ?? Registry.CurrentUser.CreateSubKey(RunKeyPath, writable: true);
            if (key is null)
            {
                return false;
            }
            if (enabled)
            {
                var path = executablePath ?? Environment.ProcessPath;
                if (string.IsNullOrWhiteSpace(path))
                {
                    return false;
                }
                key.SetValue(ValueName, $"\"{path}\"", RegistryValueKind.String);
            }
            else
            {
                key.DeleteValue(ValueName, throwOnMissingValue: false);
            }
            return true;
        }
        catch (Exception)
        {
            return false;
        }
    }
}
