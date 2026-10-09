using System.Text.Json;

namespace MemoIsle.Desktop.Services;

/// <summary>窗口位置与大小的本地记忆：%APPDATA%\MemoIsle\window.json。</summary>
public sealed class WindowStateStore
{
    public sealed class WindowState
    {
        public int Width { get; set; }
        public int Height { get; set; }
        public int X { get; set; }
        public int Y { get; set; }
    }

    private static readonly string DirectoryPath = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        "MemoIsle");

    private static readonly string FilePath = Path.Combine(DirectoryPath, "window.json");

    public static WindowState? Load()
    {
        try
        {
            if (!File.Exists(FilePath))
            {
                return null;
            }
            var state = JsonSerializer.Deserialize<WindowState>(File.ReadAllText(FilePath));
            return state is { Width: > 400, Height: > 300 } ? state : null;
        }
        catch (Exception)
        {
            return null;
        }
    }

    public static void Save(int width, int height, int x, int y)
    {
        try
        {
            Directory.CreateDirectory(DirectoryPath);
            File.WriteAllText(
                FilePath,
                JsonSerializer.Serialize(new WindowState
                {
                    Width = width,
                    Height = height,
                    X = x,
                    Y = y,
                }));
        }
        catch (Exception)
        {
            // 保存失败不影响使用。
        }
    }
}
