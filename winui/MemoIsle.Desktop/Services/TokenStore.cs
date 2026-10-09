using System.Text.Json;

namespace MemoIsle.Desktop.Services;

/// <summary>登录凭证本地持久化：存于 %APPDATA%\MemoIsle\session.json。</summary>
public sealed class TokenStore
{
    private static readonly string DirectoryPath = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        "MemoIsle");

    private static readonly string FilePath = Path.Combine(DirectoryPath, "session.json");

    private sealed class SessionFile
    {
        public string? AccessToken { get; set; }
        public string? UserId { get; set; }
    }

    public string? AccessToken { get; private set; }
    public string? UserId { get; private set; }

    public void Load()
    {
        try
        {
            if (!File.Exists(FilePath))
            {
                return;
            }
            var session = JsonSerializer.Deserialize<SessionFile>(File.ReadAllText(FilePath));
            AccessToken = session?.AccessToken;
            UserId = session?.UserId;
        }
        catch (Exception)
        {
            // 凭证文件损坏时按未登录处理。
            AccessToken = null;
            UserId = null;
        }
    }

    public void Save(string accessToken, string userId)
    {
        AccessToken = accessToken;
        UserId = userId;
        try
        {
            Directory.CreateDirectory(DirectoryPath);
            var payload = JsonSerializer.Serialize(new SessionFile
            {
                AccessToken = accessToken,
                UserId = userId,
            });
            File.WriteAllText(FilePath, payload);
        }
        catch (Exception)
        {
            // 写盘失败不阻断登录，仅本次会话有效。
        }
    }

    public void Clear()
    {
        AccessToken = null;
        UserId = null;
        try
        {
            if (File.Exists(FilePath))
            {
                File.Delete(FilePath);
            }
        }
        catch (Exception)
        {
            // 删除失败时忽略。
        }
    }
}
