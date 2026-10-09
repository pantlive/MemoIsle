namespace MemoIsle.Desktop.Services;

/// <summary>
/// 轻量诊断日志：记录全局热键注册结果与翻译调用等关键动作，
/// 便于排查"按键没反应"这类问题（%APPDATA%\MemoIsle\diagnostics.log）。
/// </summary>
public static class DiagnosticsLog
{
    private static readonly string DirectoryPath = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        "MemoIsle");

    private static readonly string FilePath = Path.Combine(DirectoryPath, "diagnostics.log");

    public static void Write(IEnumerable<string> lines)
    {
        try
        {
            Directory.CreateDirectory(DirectoryPath);
            // 只保留最近 200 行，避免无限增长。
            var existing = File.Exists(FilePath)
                ? File.ReadAllLines(FilePath).TakeLast(160).ToList()
                : new List<string>();
            existing.AddRange(lines);
            File.WriteAllLines(FilePath, existing.TakeLast(200));
        }
        catch (Exception)
        {
            // 日志失败不影响功能。
        }
    }

    public static void Write(string line) => Write(new[] { line });
}
