namespace MemoIsle.Desktop.Models;

/// <summary>用户自定义分类规则（domain / url / text）。</summary>
public sealed class ResourceCategoryRule
{
    public string Id { get; set; } = string.Empty;
    public string Name { get; set; } = string.Empty;
    public string CategoryCode { get; set; } = string.Empty;
    public string CategoryLabel { get; set; } = string.Empty;
    public string MatchType { get; set; } = "domain";
    public string Pattern { get; set; } = string.Empty;
    public int Priority { get; set; } = 100;
    public bool Enabled { get; set; } = true;
    public int Version { get; set; }
    public string CreatedAt { get; set; } = string.Empty;

    public string MatchLabel => MatchType switch
    {
        "domain" => "域名",
        "url" => "网址",
        "text" => "正文",
        _ => MatchType,
    };

    public string Summary =>
        $"{CategoryLabel} · {MatchLabel}：{Pattern} · 优先级 {Priority}"
        + (Enabled ? string.Empty : "（已停用）");
}
