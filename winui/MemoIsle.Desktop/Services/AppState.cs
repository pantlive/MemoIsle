using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using MemoIsle.Desktop.Models;
using Microsoft.UI.Xaml.Media.Imaging;

namespace MemoIsle.Desktop.Services;

/// <summary>应用状态与业务动作：持有一份服务端数据快照，供界面直接绑定。</summary>
public sealed class AppState : INotifyPropertyChanged
{
    private readonly MemoApiClient _api;
    private readonly TokenStore _tokenStore = new();

    public AppState(string? apiBaseUrl = null)
    {
        var resolved = string.IsNullOrWhiteSpace(apiBaseUrl)
            ? Environment.GetEnvironmentVariable("MEMOISLE_API_BASE_URL")
            : apiBaseUrl;
        if (string.IsNullOrWhiteSpace(resolved))
        {
            resolved = "http://127.0.0.1:8000/api/v1";
        }
        _api = new MemoApiClient(resolved!);
    }

    public ObservableCollection<Memo> Memos { get; } = new();
    public ObservableCollection<Memo> TrashedMemos { get; } = new();
    public ObservableCollection<Memo> ReviewItems { get; } = new();
    public ObservableCollection<ResourceCategoryOption> Categories { get; } = new();

    public AuthProvidersResponse? Providers { get; private set; }
    public AuthUser? CurrentUser { get; private set; }

    private string _statusMessage = string.Empty;
    public string StatusMessage
    {
        get => _statusMessage;
        private set => SetField(ref _statusMessage, value);
    }

    private bool _isBusy;
    public bool IsBusy
    {
        get => _isBusy;
        private set => SetField(ref _isBusy, value);
    }

    public bool DevLoginAvailable => Providers?.DevLoginAvailable ?? false;

    /// <summary>服务端返回的准确计数（不受当前分页/筛选影响）。</summary>
    private MemoCountsResponse? _counts;
    private int _trashTotal;
    public int TotalCountTotal => _counts?.TotalCount ?? Memos.Count;
    public int WordCountTotal => _counts?.WordCount ?? Memos.Count(m => m.IsWord);
    public int ResourceCountTotal => _counts?.ResourceCount ?? Memos.Count(m => m.IsResource);
    public int IdeaCountTotal => _counts?.IdeaCount ?? Memos.Count(m => m.IsIdea);
    public int ImageCountTotal => _counts?.ImageCount ?? Memos.Count(m => m.IsImage);

    /// <summary>复习队列总数：取服务端队列统计，而不是当前已加载的条目数。</summary>
    public int ReviewTotal => ReviewWordCount + ReviewResourceCount + ReviewIdeaCount;

    /// <summary>回收站总数：取服务端总数，避免只统计已加载的一页。</summary>
    public int TrashTotal => _trashTotal > 0 ? _trashTotal : TrashedMemos.Count;

    /// <summary>拉取侧栏计数：条目总数、回收站数量、复习队列与巡检摘要。</summary>
    public async Task RefreshCountsAsync()
    {
        var counts = await SafeAsync(() => _api.GetMemoCountsAsync());
        if (counts is not null)
        {
            _counts = counts;
        }
        // 回收站：只取 1 条数据换取总数，避免拉全量。
        var trash = await SafeAsync(() => _api.ListMemosAsync(status: "trashed", limit: 1));
        if (trash is not null)
        {
            _trashTotal = trash.TotalCount;
        }
        // 复习队列：读取服务端统计（队列上限 20，但数量需要真实值）。
        var review = await SafeAsync(() => _api.GetReviewQueueAsync(limit: 1));
        if (review is not null)
        {
            ReviewWordCount = review.WordCount;
            ReviewResourceCount = review.ResourceCount;
            ReviewIdeaCount = review.IdeaCount;
        }
        // 巡检：读取各状态数量摘要。
        var health = await SafeAsync(() => _api.GetLinkHealthAsync(limit: 1));
        if (health is not null)
        {
            LinkHealthCounts = health.Counts;
        }
        RaiseCounts();
    }

    /// <summary>启动时恢复登录态；成功返回 true。</summary>
    public async Task<bool> InitializeAsync()
    {
        _tokenStore.Load();
        Providers = await SafeAsync(() => _api.GetAuthProvidersAsync());
        if (string.IsNullOrWhiteSpace(_tokenStore.AccessToken))
        {
            return false;
        }
        _api.AccessToken = _tokenStore.AccessToken;
        try
        {
            CurrentUser = await _api.GetCurrentUserAsync();
            await RefreshAsync();
            return true;
        }
        catch (Exception)
        {
            _tokenStore.Clear();
            _api.AccessToken = null;
            CurrentUser = null;
            return false;
        }
    }

    public async Task<string?> LoginAsync(string email, string password)
    {
        IsBusy = true;
        try
        {
            var session = await _api.LoginWithEmailAsync(email, password);
            _tokenStore.Save(session.AccessToken, session.User.Id);
            CurrentUser = session.User;
            await RefreshAsync();
            StatusMessage = "登录成功";
            return null;
        }
        catch (Exception ex)
        {
            return DescribeError(ex);
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task<string?> DevLoginAsync()
    {
        IsBusy = true;
        try
        {
            var session = await _api.DevLoginAsync();
            _tokenStore.Save(session.AccessToken, session.User.Id);
            CurrentUser = session.User;
            await RefreshAsync();
            return null;
        }
        catch (Exception ex)
        {
            return DescribeError(ex);
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task<string?> RegisterAsync(
        string email,
        string password,
        string confirmPassword,
        string verificationCode,
        string? displayName)
    {
        IsBusy = true;
        try
        {
            await _api.RegisterWithEmailAsync(
                email,
                password,
                confirmPassword,
                verificationCode,
                displayName);
            StatusMessage = "注册成功，请使用邮箱登录。";
            return null;
        }
        catch (Exception ex)
        {
            return DescribeError(ex);
        }
        finally
        {
            IsBusy = false;
        }
    }

    public async Task<string?> RequestVerificationCodeAsync(string email)
    {
        try
        {
            await _api.RequestVerificationCodeAsync(email);
            StatusMessage = "验证码已发送，请查收邮箱（10 分钟内有效，60 秒后可重发）。";
            return null;
        }
        catch (Exception ex)
        {
            return DescribeError(ex);
        }
    }

    /// <summary>请求密码重置邮件。</summary>
    public async Task<string?> RequestPasswordResetAsync(string email)
    {
        if (string.IsNullOrWhiteSpace(email))
        {
            return "请先填写邮箱";
        }
        try
        {
            await _api.RequestPasswordResetAsync(email.Trim());
            StatusMessage = "如果该邮箱已注册，重置链接已发送，请查收邮件。";
            return null;
        }
        catch (Exception ex)
        {
            return DescribeError(ex);
        }
    }

    /// <summary>用邮件里的令牌设置新密码。</summary>
    public async Task<string?> ResetPasswordAsync(string token, string password, string confirmPassword)
    {
        if (password != confirmPassword)
        {
            return "两次输入的密码不一致";
        }
        if (password.Length < 8)
        {
            return "密码至少 8 位";
        }
        try
        {
            await _api.ConfirmPasswordResetAsync(token.Trim(), password, confirmPassword);
            StatusMessage = "密码已重置，请使用新密码登录。";
            return null;
        }
        catch (Exception ex)
        {
            return DescribeError(ex);
        }
    }

    /// <summary>重新发送邮箱验证链接（需已登录）。</summary>
    public async Task<string?> ResendEmailVerificationAsync()
    {
        var email = CurrentUser?.Email;
        if (string.IsNullOrWhiteSpace(email))
        {
            return "当前账号没有邮箱地址";
        }
        try
        {
            await _api.RequestEmailVerificationAsync(email);
            StatusMessage = "验证邮件已发送，请查收邮箱并点击其中的链接。";
            return null;
        }
        catch (Exception ex)
        {
            return DescribeError(ex);
        }
    }

    public async Task LogoutAsync()
    {
        try
        {
            await _api.LogoutAsync();
        }
        catch (Exception)
        {
            // 服务端不可达时仍允许本地退出。
        }
        _tokenStore.Clear();
        _api.AccessToken = null;
        CurrentUser = null;
        Memos.Clear();
        TrashedMemos.Clear();
        ReviewItems.Clear();
        StatusMessage = "已退出登录";
        OnPropertyChanged(nameof(CurrentUser));
    }

    public async Task RefreshAsync(string? query = null, bool paged = false)
    {
        if (query is not null)
        {
            _searchQuery = query.Trim();
        }
        var effectiveQuery = _searchQuery.Length == 0 ? null : _searchQuery;
        var items = new List<Memo>();
        if (paged)
        {
            // 资料视图：服务端分页 + 服务端分类/星标过滤，保证筛选与分页结果一致。
            var page = await _api.ListMemosAsync(
                query: effectiveQuery,
                limit: PageSize,
                offset: (ResourcePage - 1) * PageSize,
                sort: SortOrder,
                category: ResourceCategoryFilter,
                starredOnly: ResourceStarredOnly);
            items.AddRange(page.Items);
            ResourceTotalCount = page.TotalCount;
        }
        else
        {
            // 其他视图：分页累积拉取，避免条目多时被截断（后端单页上限 200）。
            const int pageSize = 200;
            const int maxItems = 2000;
            var offset = 0;
            while (true)
            {
                var page = await _api.ListMemosAsync(
                    query: effectiveQuery,
                    limit: pageSize,
                    offset: offset,
                    sort: SortOrder);
                items.AddRange(page.Items);
                if (page.Items.Count < pageSize || items.Count >= maxItems)
                {
                    break;
                }
                offset += pageSize;
            }
            ResourceTotalCount = items.Count;
        }
        ReplaceAll(Memos, items.Where(m => m.Status != "trashed"));
        // 图片缩略图需要登录态下载：在列表物化后统一预取，x:Bind 重新求值时即可显示。
        await LoadImageThumbnailsAsync(Memos);
        RaiseCounts();
        StatusMessage = _searchQuery.Length == 0
            ? $"已同步 {Memos.Count} 条内容"
            : $"搜索「{_searchQuery}」命中 {Memos.Count} 条";
        await RefreshCountsAsync();
        if (Categories.Count == 0)
        {
            await LoadCategoriesAsync();
        }
    }

    public string SortOrder { get; private set; } = "updated_desc";
    public int ResourcePage { get; private set; } = 1;
    public int ResourceTotalCount { get; private set; }
    public int PageSize { get; } = 20;

    /// <summary>资料视图的服务端筛选条件（分类编码 / 仅星标）。</summary>
    public string? ResourceCategoryFilter { get; private set; }
    public bool ResourceStarredOnly { get; private set; }

    public void SetResourceFilters(string? categoryCode, bool starredOnly)
    {
        ResourceCategoryFilter = categoryCode;
        ResourceStarredOnly = starredOnly;
    }

    public int ResourcePageCount =>
        ResourceTotalCount == 0 ? 1 : (int)Math.Ceiling(ResourceTotalCount / (double)PageSize);

    public void SetSortOrder(string sort) => SortOrder = sort;

    public void SetResourcePage(int page) => ResourcePage = Math.Max(1, page);

    public void ResetResourcePage() => ResourcePage = 1;

    private string _searchQuery = string.Empty;
    private Memo? _lastCreated;

    /// <summary>当前生效的服务端搜索词（空表示未搜索）。</summary>
    public string ActiveSearchQuery => _searchQuery;

    /// <summary>最近一次新建的条目，供状态栏"撤销"使用。</summary>
    public Memo? UndoableMemo => _lastCreated;

    public async Task<string?> UndoLastCreateAsync()
    {
        var target = _lastCreated;
        if (target is null)
        {
            return null;
        }
        _lastCreated = null;
        return await TrashAsync(target);
    }

    public void ClearUndo() => _lastCreated = null;

    /// <summary>加载系统分类与用户自定义分类，用于资料视图过滤。</summary>
    public async Task LoadCategoriesAsync()
    {
        var categories = await SafeAsync(() => _api.ListResourceCategoriesAsync());
        if (categories is null)
        {
            return;
        }
        Categories.Clear();
        foreach (var category in categories.Where(c => c.IsActive))
        {
            Categories.Add(category);
        }
    }

    public async Task<string?> CreateIdeaAsync(string body)
    {
        return await WriteAsync(async () =>
        {
            var request = new MemoCreateRequest
            {
                Type = MemoTypes.Idea,
                Body = body.Trim(),
            };
            var created = await _api.CreateMemoAsync(request);
            _lastCreated = created.ClientId == request.ClientId ? created : null;
            StatusMessage = "灵感已保存";
        });
    }

    public async Task<string?> CreateResourceAsync(string url, string title, string note)
    {
        var normalized = NormalizeUrl(url);
        if (normalized is null)
        {
            return "请输入有效的网址，例如 https://example.com/article";
        }
        var cleanTitle = string.IsNullOrWhiteSpace(title) ? Memo.ResourceHost(normalized) : title.Trim();
        return await WriteAsync(async () =>
        {
            var request = new MemoCreateRequest
            {
                Type = MemoTypes.Resource,
                Title = cleanTitle,
                Body = string.IsNullOrWhiteSpace(note) ? normalized : note.Trim(),
                SourceUrl = normalized,
                SourceTitle = cleanTitle,
            };
            var created = await _api.CreateMemoAsync(request);
            // 服务端按 URL 去重时返回已有条目，此时不提供撤销。
            _lastCreated = created.ClientId == request.ClientId ? created : null;
            StatusMessage = "网页资料已保存";
        });
    }

    public async Task<string?> CreateWordAsync(
        string lemma,
        string phonetic,
        string meaning,
        string example,
        bool allowDuplicate)
    {
        var cleanLemma = lemma.Trim();
        if (cleanLemma.Length == 0)
        {
            return "请输入要收藏的单词或短语";
        }
        return await WriteAsync(async () =>
        {
            var request = new MemoCreateRequest
            {
                Type = MemoTypes.Word,
                Title = cleanLemma,
                Body = string.IsNullOrWhiteSpace(meaning) ? cleanLemma : meaning.Trim(),
                WordPhonetic = NullIfBlank(phonetic),
                WordMeaning = NullIfBlank(meaning),
                WordExample = NullIfBlank(example),
                AllowDuplicate = allowDuplicate ? true : null,
            };
            var created = await _api.CreateMemoAsync(request);
            _lastCreated = created.ClientId == request.ClientId ? created : null;
            StatusMessage = "单词已保存";
        });
    }

    /// <summary>单词创建结果：失败原因，或冲突时服务端已有的重复词条。</summary>
    public sealed record WordCreateOutcome(string? Error, Memo? Duplicate);

    /// <summary>创建单词并回传冲突详情，供界面提供"查看 / 合并例句 / 仍然保存"。</summary>
    public async Task<WordCreateOutcome> CreateWordDetailedAsync(
        string lemma,
        string phonetic,
        string meaning,
        string example,
        bool allowDuplicate)
    {
        var cleanLemma = lemma.Trim();
        if (cleanLemma.Length == 0)
        {
            return new WordCreateOutcome("请输入要收藏的单词或短语", null);
        }
        await _writeLock.WaitAsync();
        IsBusy = true;
        try
        {
            var request = new MemoCreateRequest
            {
                Type = MemoTypes.Word,
                Title = cleanLemma,
                Body = string.IsNullOrWhiteSpace(meaning) ? cleanLemma : meaning.Trim(),
                WordPhonetic = NullIfBlank(phonetic),
                WordMeaning = NullIfBlank(meaning),
                WordExample = NullIfBlank(example),
                AllowDuplicate = allowDuplicate ? true : null,
            };
            var created = await _api.CreateMemoAsync(request);
            _lastCreated = created.ClientId == request.ClientId ? created : null;
            StatusMessage = "单词已保存";
            return new WordCreateOutcome(null, null);
        }
        catch (MemoApiException ex) when (ex.Code == "duplicate_lemma" && !allowDuplicate)
        {
            return new WordCreateOutcome(
                "已收藏相同词形：可查看原条目、合并例句，或仍然保存为重复词条。",
                ex.Current);
        }
        catch (Exception ex)
        {
            return new WordCreateOutcome(DescribeError(ex), null);
        }
        finally
        {
            IsBusy = false;
            _writeLock.Release();
        }
    }

    /// <summary>把新输入的音标/释义/例句合并进已存在的同词形条目。</summary>
    public Task<string?> MergeWordAsync(Memo existing, string phonetic, string meaning, string example) =>
        WriteAsync(async () =>
        {
            var merged = await _api.MergeWordAsync(
                existing.Id!,
                existing.Version,
                NullIfBlank(phonetic),
                NullIfBlank(meaning),
                NullIfBlank(example));
            StatusMessage = $"已合并到「{merged.Title}」";
        }, refreshAfter: true);

    public async Task<string?> UpdateIdeaAsync(Memo memo, string body)
    {
        return await WriteAsync(async () =>
        {
            await _api.UpdateMemoAsync(
                memo.Id!,
                new MemoUpdateRequest
                {
                    ExpectedVersion = memo.Version,
                    Title = DeriveTitle(body),
                    Body = body.Trim(),
                });
            StatusMessage = "已保存修改";
        });
    }

    public async Task<string?> UpdateResourceAsync(Memo memo, string url, string title, string note)
    {
        var normalized = NormalizeUrl(url);
        if (normalized is null)
        {
            return "请输入有效的网址";
        }
        var cleanTitle = string.IsNullOrWhiteSpace(title) ? Memo.ResourceHost(normalized) : title.Trim();
        return await WriteAsync(async () =>
        {
            await _api.UpdateMemoAsync(
                memo.Id!,
                new MemoUpdateRequest
                {
                    ExpectedVersion = memo.Version,
                    Title = cleanTitle,
                    Body = string.IsNullOrWhiteSpace(note) ? normalized : note.Trim(),
                    SourceUrl = normalized,
                    SourceTitle = cleanTitle,
                });
            StatusMessage = "已保存修改";
        });
    }

    public async Task<string?> UpdateWordAsync(
        Memo memo,
        string lemma,
        string phonetic,
        string meaning,
        string example)
    {
        return await WriteAsync(async () =>
        {
            await _api.UpdateMemoAsync(
                memo.Id!,
                new MemoUpdateRequest
                {
                    ExpectedVersion = memo.Version,
                    Title = lemma.Trim(),
                    Body = string.IsNullOrWhiteSpace(meaning) ? lemma.Trim() : meaning.Trim(),
                    WordPhonetic = NullIfBlank(phonetic),
                    WordMeaning = NullIfBlank(meaning),
                    WordExample = NullIfBlank(example),
                });
            StatusMessage = "已保存修改";
        });
    }

    public async Task<string?> ToggleStarAsync(Memo memo)
    {
        return await WriteAsync(async () =>
        {
            await _api.UpdateMemoAsync(
                memo.Id!,
                new MemoUpdateRequest
                {
                    ExpectedVersion = memo.Version,
                    Starred = !memo.Starred,
                });
            StatusMessage = memo.Starred ? "已取消星标" : "已标为星标";
        });
    }

    public async Task<string?> TrashAsync(Memo memo)
    {
        var removed = RemoveFrom(Memos, memo);
        return await WriteAsync(async () =>
        {
            await _api.UpdateMemoAsync(
                memo.Id!,
                new MemoUpdateRequest
                {
                    ExpectedVersion = memo.Version,
                    Status = "trashed",
                });
            StatusMessage = "已移入回收站（30 天内可恢复）";
        }, restoreOnFailure: () => RestoreTo(Memos, removed));
    }

    public async Task LoadTrashAsync()
    {
        try
        {
            // 后端单页上限 200：分页累积拉取，避免回收站条目多时被截断。
            var items = new List<Memo>();
            var offset = 0;
            while (true)
            {
                var page = await _api.ListMemosAsync("trashed", limit: 200, offset: offset);
                items.AddRange(page.Items);
                _trashTotal = page.TotalCount;
                if (page.Items.Count < 200 || items.Count >= 2000)
                {
                    break;
                }
                offset += 200;
            }
            ReplaceAll(TrashedMemos, items);
            RaiseCounts();
        }
        catch (Exception ex)
        {
            StatusMessage = DescribeError(ex);
        }
    }

    public Task<string?> RestoreAsync(Memo memo) => WriteAsync(async () =>
    {
        await _api.RestoreMemoAsync(memo.Id!, memo.Version);
        TrashedMemos.Remove(memo);
        StatusMessage = $"已恢复「{memo.Title}」";
    }, refreshAfter: true);

    /// <summary>清空回收站（永久删除全部回收站条目）。</summary>
    public async Task<string?> EmptyTrashAsync()
    {
        try
        {
            var deleted = await _api.EmptyTrashAsync();
            TrashedMemos.Clear();
            _trashTotal = 0;
            StatusMessage = deleted == 0 ? "回收站已经是空的。" : $"已永久删除 {deleted} 条内容。";
            RaiseCounts();
            return null;
        }
        catch (Exception ex)
        {
            return DescribeError(ex);
        }
    }

    /// <summary>批量移入回收站。</summary>
    public async Task<string?> TrashManyAsync(IReadOnlyCollection<Memo> memos)
    {
        var failed = 0;
        foreach (var memo in memos.Where(m => m.Id is not null))
        {
            try
            {
                await _api.UpdateMemoAsync(
                    memo.Id!,
                    new MemoUpdateRequest { ExpectedVersion = memo.Version, Status = "trashed" });
            }
            catch (Exception)
            {
                failed += 1;
            }
        }
        await RefreshAsync(paged: false);
        StatusMessage = failed == 0
            ? $"已把 {memos.Count} 条内容移入回收站"
            : $"已移入回收站 {memos.Count - failed} 条，{failed} 条失败";
        return null;
    }

    /// <summary>批量设置星标。</summary>
    public async Task<string?> StarManyAsync(IReadOnlyCollection<Memo> memos, bool starred)
    {
        var failed = 0;
        foreach (var memo in memos.Where(m => m.Id is not null))
        {
            try
            {
                await _api.UpdateMemoAsync(
                    memo.Id!,
                    new MemoUpdateRequest { ExpectedVersion = memo.Version, Starred = starred });
            }
            catch (Exception)
            {
                failed += 1;
            }
        }
        await RefreshAsync(paged: false);
        StatusMessage = failed == 0
            ? $"已{(starred ? "标记" : "取消")}星标 {memos.Count} 条"
            : $"已处理 {memos.Count - failed} 条，{failed} 条失败";
        return null;
    }

    /// <summary>批量恢复回收站条目。</summary>
    public async Task<string?> RestoreManyAsync(IReadOnlyCollection<Memo> memos)
    {
        var failed = 0;
        foreach (var memo in memos.Where(m => m.Id is not null))
        {
            try
            {
                await _api.RestoreMemoAsync(memo.Id!, memo.Version);
            }
            catch (Exception)
            {
                failed += 1;
            }
        }
        await LoadTrashAsync();
        await RefreshAsync(paged: false);
        StatusMessage = failed == 0
            ? $"已恢复 {memos.Count} 条内容"
            : $"已恢复 {memos.Count - failed} 条，{failed} 条失败";
        return null;
    }

    public async Task<string?> PurgeAsync(Memo memo)
    {
        return await WriteAsync(async () =>
        {
            await _api.PermanentlyDeleteMemoAsync(memo.Id!, memo.Version);
            TrashedMemos.Remove(memo);
            StatusMessage = $"已永久删除「{memo.Title}」";
        });
    }

    // ---------- 语音灵感 ----------

    /// <summary>保存语音灵感：先建 idea 草稿，再上传录音文件（audio/mp4）。</summary>
    public async Task<string?> SaveVoiceIdeaAsync(string transcript, string audioPath, int durationMs)
    {
        await _writeLock.WaitAsync();
        IsBusy = true;
        try
        {
            var body = string.IsNullOrWhiteSpace(transcript) ? "语音记录" : transcript.Trim();
            var request = new MemoCreateRequest
            {
                Type = MemoTypes.Idea,
                Body = body,
                Tags = new List<string> { "语音" },
            };
            var created = await _api.CreateMemoAsync(request);
            if (created.Id is null)
            {
                return "保存失败：服务端未返回条目标识";
            }
            _lastCreated = created.ClientId == request.ClientId ? created : null;
            await _api.UploadAudioAsync(created.Id, created.Version, durationMs, audioPath);
            StatusMessage = "语音灵感已保存";
            return null;
        }
        catch (Exception ex)
        {
            return DescribeError(ex);
        }
        finally
        {
            IsBusy = false;
            _writeLock.Release();
        }
    }

    /// <summary>调用后端 LLM，把会议转写整理成结构化纪要。</summary>
    public async Task<(string? Summary, string? Error)> SummarizeMeetingAsync(
        string title,
        string transcript)
    {
        try
        {
            var response = await _api.SummarizeMeetingAsync(
                string.IsNullOrWhiteSpace(title) ? "未命名会议" : title.Trim(),
                transcript.Trim());
            return (response.Summary, null);
        }
        catch (Exception ex)
        {
            return (null, DescribeError(ex));
        }
    }

    /// <summary>保存会议记录：纪要作为正文，原始转写写入 transcript，随后上传录音。</summary>
    public async Task<string?> SaveMeetingAsync(
        string title,
        string transcript,
        string summary,
        string audioPath,
        int durationMs)
    {
        await _writeLock.WaitAsync();
        IsBusy = true;
        try
        {
            var cleanSummary = summary.Trim();
            var cleanTranscript = transcript.Trim();
            var body = cleanSummary.Length > 0
                ? cleanSummary
                : cleanTranscript.Length > 0 ? cleanTranscript : "会议记录";
            var request = new MemoCreateRequest
            {
                Type = MemoTypes.Idea,
                Title = string.IsNullOrWhiteSpace(title) ? null : title.Trim(),
                Body = body,
                Transcript = cleanTranscript.Length > 0 ? cleanTranscript : null,
                Tags = new List<string> { "会议", "录音" },
            };
            var created = await _api.CreateMemoAsync(request);
            if (created.Id is null)
            {
                return "保存失败：服务端未返回条目标识";
            }
            _lastCreated = created.ClientId == request.ClientId ? created : null;
            await _api.UploadAudioAsync(created.Id, created.Version, durationMs, audioPath);
            StatusMessage = "会议记录已保存";
            return null;
        }
        catch (Exception ex)
        {
            return DescribeError(ex);
        }
        finally
        {
            IsBusy = false;
            _writeLock.Release();
        }
    }

    /// <summary>下载录音原始字节用于播放。</summary>
    public async Task<byte[]?> DownloadAudioAsync(Memo memo)
    {
        if (memo.Id is null)
        {
            return null;
        }
        try
        {
            return await _api.DownloadAudioAsync(memo.Id);
        }
        catch (Exception ex)
        {
            StatusMessage = DescribeError(ex);
            return null;
        }
    }

    // ---------- 图片收藏 ----------

    /// <summary>创建图片收藏条目（此时还没有图片，随后调用 UploadImageAsync 上传原图）。</summary>
    public async Task<(Memo? Memo, string? Error)> CreateImageAsync(string title, string body)
    {
        await _writeLock.WaitAsync();
        IsBusy = true;
        try
        {
            var created = await _api.CreateImageMemoAsync(title, body);
            _lastCreated = created;
            StatusMessage = "图片收藏已创建，正在上传图片…";
            return (created, null);
        }
        catch (Exception ex)
        {
            return (null, DescribeError(ex));
        }
        finally
        {
            IsBusy = false;
            _writeLock.Release();
        }
    }

    /// <summary>修改图片收藏的标题与备注（备注允许清空）。</summary>
    public Task<string?> UpdateImageAsync(Memo memo, string title, string body) => WriteAsync(async () =>
    {
        var updated = await _api.UpdateMemoAsync(
            memo.Id!,
            new MemoUpdateRequest
            {
                ExpectedVersion = memo.Version,
                Title = title.Trim(),
                Body = body ?? string.Empty,
            });
        ReplaceMemo(updated);
        StatusMessage = "已保存修改";
    });

    /// <summary>上传或替换图片收藏的原图；超出后端限制时先自动压缩，成功后刷新缩略图并替换列表中的条目。</summary>
    public async Task<string?> UploadImageAsync(Memo memo, string filePath, string mimeType)
    {
        var resolvedMime = string.IsNullOrWhiteSpace(mimeType)
            ? MemoImageFiles.MimeTypeFor(filePath)
            : mimeType;
        if (resolvedMime is null)
        {
            return "仅支持 PNG / JPG / WebP / GIF 图片";
        }
        if (memo.Id is null)
        {
            return "保存失败：条目尚未创建";
        }
        if (!File.Exists(filePath))
        {
            return "图片文件不存在或无法读取";
        }

        // 本次上传不再沿用上一次的压缩提示。
        LastImageCompressionNotice = null;
        return await WriteAsync(async () =>
        {
            // 同一会话中该条目可能刚被 UpdateImageAsync 更新过版本号，优先取最新引用。
            var current = Memos.FirstOrDefault(item => item.Id == memo.Id) ?? memo;
            // 仅当图片会超出后端限制时才压缩，其余情况原样上传。
            var compression = await MemoImageCompressor.CompressIfNeededAsync(filePath, resolvedMime);
            var updated = await _api.UploadMemoImageAsync(
                current.Id!,
                current.Version,
                compression.Bytes,
                compression.NewMimeType);
            ReplaceMemo(updated);
            await LoadImageThumbnailAsync(updated);
            if (compression.Compressed)
            {
                LastImageCompressionNotice = MemoImageCompressor.DescribeCompression(compression);
                StatusMessage = LastImageCompressionNotice;
            }
            else
            {
                StatusMessage = "图片已保存";
            }
        });
    }

    /// <summary>最近一次图片压缩的用户提示；未发生压缩时为 null。</summary>
    public string? LastImageCompressionNotice { get; private set; }

    /// <summary>
    /// 取出最近一次压缩提示并清除，同时把它重新写回状态栏：
    /// 上传后的列表刷新会覆盖状态栏文本，界面在刷新完成后再调用本方法保证提示可见。
    /// </summary>
    public string? ConsumeImageCompressionNotice()
    {
        var notice = LastImageCompressionNotice;
        LastImageCompressionNotice = null;
        if (!string.IsNullOrEmpty(notice))
        {
            StatusMessage = notice;
        }
        return notice;
    }

    /// <summary>下载图片收藏的原图或缩略图字节；失败时写入状态栏并返回 null。</summary>
    public async Task<byte[]?> DownloadImageAsync(Memo memo, bool thumbnail)
    {
        if (memo.Id is null)
        {
            return null;
        }
        try
        {
            return await _api.DownloadMemoImageAsync(memo.Id, thumbnail);
        }
        catch (Exception ex)
        {
            StatusMessage = DescribeError(ex);
            return null;
        }
    }

    /// <summary>
    /// 手动（重新）识别图片收藏的文字。失败时返回错误文案（服务端未启用时带上 503 的 detail，
    /// 如「服务端未启用图片 OCR」）；成功时替换列表条目、刷新缩略图并更新状态栏。
    /// </summary>
    public async Task<string?> RecognizeImageOcrAsync(Memo memo)
    {
        if (memo.Id is null)
        {
            return "保存失败：条目尚未创建";
        }
        var error = await WriteAsync(async () =>
        {
            StatusMessage = "正在识别图片文字…";
            var updated = await _api.RecognizeMemoImageOcrAsync(memo.Id!);
            ReplaceMemo(updated);
            await LoadImageThumbnailAsync(updated);
            StatusMessage = "图片文字识别完成";
        });
        if (error is not null)
        {
            StatusMessage = error;
        }
        return error;
    }

    /// <summary>重新拉取单条 memo（GET memos/{id}）并替换列表引用，用于等待后台 OCR 结果。</summary>
    public async Task<Memo?> RefreshMemoAsync(string memoId)
    {
        try
        {
            var updated = await _api.GetMemoAsync(memoId);
            ReplaceMemo(updated);
            await LoadImageThumbnailAsync(updated);
            return updated;
        }
        catch (Exception ex)
        {
            StatusMessage = DescribeError(ex);
            return null;
        }
    }

    /// <summary>按 id 查当前列表中的条目（版本号可能已被写操作刷新）。</summary>
    public Memo? FindMemo(string? memoId) =>
        memoId is null ? null : Memos.FirstOrDefault(item => item.Id == memoId);

    /// <summary>批量预取图片缩略图（有界并发，逐条容错，失败保留占位图标）。</summary>
    private async Task LoadImageThumbnailsAsync(IReadOnlyCollection<Memo> items)
    {
        var targets = items
            .Where(memo => memo.IsImage && memo.Id is not null && memo.HasImage)
            .ToList();
        if (targets.Count == 0)
        {
            return;
        }
        using var gate = new SemaphoreSlim(4);
        var tasks = targets.Select(async memo =>
        {
            await gate.WaitAsync();
            try
            {
                await LoadImageThumbnailAsync(memo);
            }
            finally
            {
                gate.Release();
            }
        });
        await Task.WhenAll(tasks);
    }

    /// <summary>下载单条图片的缩略图并解码为 BitmapImage（在 UI 线程上赋值）。</summary>
    private async Task LoadImageThumbnailAsync(Memo memo)
    {
        if (memo.Id is null || !memo.HasImage)
        {
            return;
        }
        // 以 id + 图片哈希缓存，避免每次刷新都重复下载同一张缩略图。
        var cacheKey = $"{memo.Id}:{memo.ImageHash ?? memo.UpdatedAt}";
        if (_imageSourceCache.TryGetValue(cacheKey, out var cached))
        {
            memo.MemoImageSource = cached;
            return;
        }
        try
        {
            var bytes = await _api.DownloadMemoImageAsync(memo.Id, thumbnail: true);
            if (bytes.Length == 0)
            {
                return;
            }
            var bitmap = new BitmapImage { DecodePixelWidth = 320 };
            using var stream = new MemoryStream(bytes);
            await bitmap.SetSourceAsync(stream.AsRandomAccessStream());
            memo.MemoImageSource = bitmap;
            if (_imageSourceCache.Count >= MaxCachedThumbnails)
            {
                _imageSourceCache.Clear();
            }
            _imageSourceCache[cacheKey] = bitmap;
        }
        catch (Exception)
        {
            // 缩略图加载失败时保持占位图标，不阻塞列表展示。
            memo.MemoImageSource = null;
        }
    }

    private const int MaxCachedThumbnails = 200;
    private readonly Dictionary<string, Microsoft.UI.Xaml.Media.ImageSource> _imageSourceCache = new();

    /// <summary>用服务端返回的最新条目替换列表中的同 id 条目。</summary>
    private void ReplaceMemo(Memo updated)
    {
        if (updated.Id is null)
        {
            return;
        }
        for (var index = 0; index < Memos.Count; index++)
        {
            if (Memos[index].Id == updated.Id)
            {
                Memos[index] = updated;
                return;
            }
        }
        Memos.Insert(0, updated);
    }

    // ---------- 分类模板与规则 ----------

    public ObservableCollection<ResourceCategoryRule> CategoryRules { get; } = new();

    public async Task<string?> CreateCategoryAsync(
        string name,
        string? description,
        string? parentCode = null)
    {
        var error = await WriteAsync(async () =>
        {
            await _api.CreateResourceCategoryAsync(name, description, parentCode);
            StatusMessage = $"已创建分类「{name}」";
        });
        if (error is null)
        {
            await LoadCategoriesAsync();
        }
        return error;
    }

    public async Task<string?> SetCategoryActiveAsync(ResourceCategoryOption category, bool active)
    {
        if (category.Id is null)
        {
            return "系统分类不可修改";
        }
        var error = await WriteAsync(async () =>
        {
            await _api.UpdateResourceCategoryAsync(category.Id!, category.Version, active);
            StatusMessage = active ? $"已启用「{category.Name}」" : $"已停用「{category.Name}」";
        });
        if (error is null)
        {
            await LoadCategoriesAsync();
        }
        return error;
    }

    public async Task<string?> RenameCategoryAsync(
        ResourceCategoryOption category,
        string name,
        string? description)
    {
        if (category.Id is null)
        {
            return "系统分类不可修改";
        }
        var cleanedName = name.Trim();
        if (string.IsNullOrWhiteSpace(cleanedName))
        {
            return "分类名称不能为空";
        }
        var error = await WriteAsync(async () =>
        {
            await _api.UpdateResourceCategoryAsync(
                category.Id!,
                category.Version,
                isActive: null,
                name: cleanedName,
                description: string.IsNullOrWhiteSpace(description) ? null : description.Trim());
            StatusMessage = $"已更新「{cleanedName}」";
        });
        if (error is null)
        {
            await LoadCategoriesAsync();
            await LoadCategoryRulesAsync();
        }
        return error;
    }

    public async Task<string?> DeleteCategoryAsync(ResourceCategoryOption category)
    {
        if (category.Id is null)
        {
            return "系统分类不可删除";
        }
        var error = await WriteAsync(async () =>
        {
            await _api.DeleteResourceCategoryAsync(category.Id!);
            StatusMessage = $"已删除「{category.Name}」";
        });
        if (error is null)
        {
            await LoadCategoriesAsync();
            await LoadCategoryRulesAsync();
        }
        return error;
    }

    public async Task LoadCategoryRulesAsync()
    {
        var rules = await SafeAsync(() => _api.ListResourceCategoryRulesAsync());
        if (rules is null)
        {
            return;
        }
        ReplaceAll(CategoryRules, rules);
    }

    public async Task<string?> CreateCategoryRuleAsync(
        string? name,
        string categoryCode,
        string matchType,
        string pattern,
        int priority)
    {
        var error = await WriteAsync(async () =>
        {
            await _api.CreateResourceCategoryRuleAsync(name, categoryCode, matchType, pattern, priority);
            StatusMessage = "已添加分类规则，已有资料会在后台按新规则重新整理";
        });
        if (error is null)
        {
            await LoadCategoryRulesAsync();
        }
        return error;
    }

    public async Task<string?> DeleteCategoryRuleAsync(ResourceCategoryRule rule)
    {
        return await WriteAsync(async () =>
        {
            await _api.DeleteResourceCategoryRuleAsync(rule.Id);
            CategoryRules.Remove(rule);
            StatusMessage = "已删除分类规则";
        });
    }

    // ---------- 书签批量导入 ----------

    public async Task<(BookmarkImportPreview? Preview, string? Error)> PreviewBookmarksAsync(
        IReadOnlyCollection<BookmarkInput> items)
    {
        try
        {
            var preview = await _api.PreviewBookmarkImportAsync(items);
            StatusMessage = $"书签预览：可导入 {preview.ValidCount} 条 / 共 {preview.TotalCount} 条";
            return (preview, null);
        }
        catch (Exception ex)
        {
            return (null, DescribeError(ex));
        }
    }

    public async Task<(BookmarkImportBatch? Batch, string? Error)> StartBookmarkImportAsync(
        IReadOnlyCollection<BookmarkInput> items)
    {
        try
        {
            var batch = await _api.CreateBookmarkImportAsync(items);
            StatusMessage = "书签导入已开始";
            return (batch, null);
        }
        catch (Exception ex)
        {
            return (null, DescribeError(ex));
        }
    }

    public async Task<BookmarkImportBatch?> GetBookmarkImportAsync(string batchId)
    {
        try
        {
            return await _api.GetBookmarkImportAsync(batchId);
        }
        catch (Exception)
        {
            return null;
        }
    }

    public async Task<string?> RetryBookmarkImportAsync(string batchId)
    {
        try
        {
            await _api.RetryBookmarkImportAsync(batchId);
            StatusMessage = "已重试失败的导入项";
            return null;
        }
        catch (Exception ex)
        {
            return DescribeError(ex);
        }
    }

    public async Task<string?> UndoBookmarkImportAsync(string batchId)
    {
        try
        {
            await _api.UndoBookmarkImportAsync(batchId);
            StatusMessage = "已撤销本次书签导入（未编辑的条目已移入回收站）";
            await RefreshAsync(paged: false);
            return null;
        }
        catch (Exception ex)
        {
            return DescribeError(ex);
        }
    }

    // ---------- 网页巡检 ----------

    public ObservableCollection<Memo> LinkHealthItems { get; } = new();
    public Dictionary<string, int> LinkHealthCounts { get; private set; } = new();
    public string? LinkHealthFilter { get; private set; }

    /// <summary>需要用户处理的巡检问题数量（用于导航徽章）。</summary>
    public int HealthIssueCount => LinkHealthCounts
        .Where(pair => pair.Key is "failed" or "redirected" or "changed" or "temporary_failure" or "auth_required")
        .Sum(pair => pair.Value);

    public async Task LoadLinkHealthAsync(string? status = null)
    {
        try
        {
            LinkHealthFilter = status;
            // 后端单页上限 200：分页累积拉取，避免问题条目多时只显示前 200 条。
            var items = new List<Memo>();
            var offset = 0;
            while (true)
            {
                var page = await _api.GetLinkHealthAsync(status, limit: 200, offset: offset);
                items.AddRange(page.Items);
                LinkHealthCounts = page.Counts;
                if (page.Items.Count < 200 || items.Count >= 2000)
                {
                    break;
                }
                offset += 200;
            }
            ReplaceAll(LinkHealthItems, items);
            StatusMessage = LinkHealthItems.Count == 0
                ? "网页巡检：没有待处理的问题"
                : $"网页巡检：{LinkHealthItems.Count} 条待处理";
            RaiseCounts();
        }
        catch (Exception ex)
        {
            StatusMessage = DescribeError(ex);
        }
    }

    public async Task<string?> ApplyLinkHealthActionAsync(Memo memo, string action, string? newUrl = null)
    {
        var error = await WriteAsync(async () =>
        {
            await _api.ApplyLinkHealthActionAsync(memo.Id!, memo.Version, action, newUrl);
            StatusMessage = action switch
            {
                "retry" => "已重新检查该网页",
                "ignore" => "已忽略该网页的巡检",
                "resume" => "已恢复该网页的巡检",
                "adopt_redirect" => "已采用跳转后的新网址",
                "update_url" => "已更新网址",
                "update_metadata" => "已更新资料信息",
                "delete" => "已删除该资料",
                _ => "已处理",
            };
        });
        if (error is null)
        {
            await LoadLinkHealthAsync(LinkHealthFilter);
        }
        return error;
    }

    public int ReviewWordCount { get; private set; }
    public int ReviewResourceCount { get; private set; }
    public int ReviewIdeaCount { get; private set; }

    public async Task LoadReviewAsync(string? type = null)
    {
        try
        {
            var queue = await _api.GetReviewQueueAsync(limit: 20, type: type);
            ReplaceAll(ReviewItems, queue.Items);
            ReviewWordCount = queue.WordCount;
            ReviewResourceCount = queue.ResourceCount;
            ReviewIdeaCount = queue.IdeaCount;
            StatusMessage = queue.TotalCount == 0
                ? "今天没有需要回顾的内容"
                : $"今天有 {queue.TotalCount} 条值得回顾";
            RaiseCounts();
        }
        catch (Exception ex)
        {
            StatusMessage = DescribeError(ex);
        }
    }

    /// <summary>打开资料后标记为"阅读中"（对齐 Web 行为）。</summary>
    public Task<string?> MarkResourceReadingAsync(Memo memo) => WriteAsync(async () =>
    {
        await _api.UpdateMemoAsync(
            memo.Id!,
            new MemoUpdateRequest
            {
                ExpectedVersion = memo.Version,
                ResourceReadingStatus = "reading",
            });
        StatusMessage = "已标记为阅读中";
    });

    /// <summary>手动设置资料阅读状态（未读 / 阅读中 / 已完成 / 已归档）。</summary>
    public Task<string?> SetReadingStatusAsync(Memo memo, string status) => WriteAsync(async () =>
    {
        await _api.UpdateMemoAsync(
            memo.Id!,
            new MemoUpdateRequest
            {
                ExpectedVersion = memo.Version,
                ResourceReadingStatus = status,
            });
        StatusMessage = $"阅读状态已改为「{(status switch
        {
            "reading" => "阅读中",
            "completed" => "已完成",
            "archived" => "已归档",
            _ => "未读",
        })}」";
    }, refreshAfter: true);

    /// <summary>修改资料分类（传 null 表示清除分类）。</summary>
    public Task<string?> SetResourceCategoryAsync(Memo memo, string? categoryCode) => WriteAsync(async () =>
    {
        await _api.UpdateMemoAsync(
            memo.Id!,
            new MemoUpdateRequest
            {
                ExpectedVersion = memo.Version,
                ResourceCategory = categoryCode,
            });
        StatusMessage = categoryCode is null ? "已清除分类" : "已更新分类";
    }, refreshAfter: true);

    /// <summary>朗读文本：优先服务端 TTS，失败回退 Windows 系统语音。</summary>
    public async Task<string?> SpeakAsync(string text)
    {
        var clean = text.Trim();
        if (clean.Length == 0)
        {
            return null;
        }
        var wav = await SafeAsync(() => _api.SynthesizeSpeechAsync(clean));
        if (wav is { Length: > 0 })
        {
            SpeechService.PlayWav(wav);
            return null;
        }
        var spoken = await SpeechService.SpeakAsync(clean);
        return spoken ? null : "语音播放失败：服务端 TTS 与系统语音都不可用。";
    }

    /// <summary>灵感"整理完成"：状态改为 active 并移出复习队列。</summary>
    public Task<string?> OrganizeIdeaAsync(Memo memo) => WriteAsync(async () =>
    {
        await _api.UpdateMemoAsync(
            memo.Id!,
            new MemoUpdateRequest { ExpectedVersion = memo.Version, Status = "active" });
        ReviewItems.Remove(memo);
        StatusMessage = $"已整理「{memo.Title}」";
    }, refreshAfter: true);

    /// <summary>灵感归档。</summary>
    public Task<string?> ArchiveIdeaAsync(Memo memo) => WriteAsync(async () =>
    {
        await _api.UpdateMemoAsync(
            memo.Id!,
            new MemoUpdateRequest { ExpectedVersion = memo.Version, Status = "archived" });
        ReviewItems.Remove(memo);
        StatusMessage = $"已归档「{memo.Title}」";
    });

    /// <summary>复习队列内切换星标（同步更新队列项）。</summary>
    public Task<string?> ToggleReviewStarAsync(Memo memo) => WriteAsync(async () =>
    {
        var updated = await _api.UpdateMemoAsync(
            memo.Id!,
            new MemoUpdateRequest { ExpectedVersion = memo.Version, Starred = !memo.Starred });
        var index = ReviewItems.IndexOf(memo);
        if (index >= 0)
        {
            ReviewItems[index] = updated;
        }
        StatusMessage = updated.Starred ? "已标为星标" : "已取消星标";
    });

    public async Task<string?> SubmitReviewAsync(Memo memo, string feedback)
    {
        return await WriteAsync(async () =>
        {
            await _api.SubmitReviewAsync(memo.Id!, memo.Version, feedback);
            ReviewItems.Remove(memo);
            StatusMessage = $"已记录「{memo.Title}」的复习结果";
        }, refreshAfter: true);
    }

    public async Task<string?> SkipReviewAsync(Memo memo)
    {
        return await WriteAsync(async () =>
        {
            await _api.SkipReviewAsync(memo.Id!, memo.Version);
            ReviewItems.Remove(memo);
            StatusMessage = $"已跳过「{memo.Title}」";
        });
    }

    public async Task<WordLookupResponse?> LookupWordAsync(string lemma)
    {
        try
        {
            var result = await _api.LookupWordAsync(lemma.Trim());
            StatusMessage = result.Senses.Count == 0
                ? $"词典没有返回「{lemma}」的释义，可手动填写。"
                : $"已填入「{result.Lemma}」的释义，可修改后保存。";
            return result;
        }
        catch (Exception ex)
        {
            StatusMessage = DescribeError(ex);
            return null;
        }
    }

    private readonly SemaphoreSlim _writeLock = new(1, 1);

    private async Task<string?> WriteAsync(
        Func<Task> action,
        bool refreshAfter = false,
        Action? restoreOnFailure = null)
    {
        // 串行执行写操作：快速连点时排队等待，而不是静默丢弃。
        await _writeLock.WaitAsync();
        IsBusy = true;
        try
        {
            await action();
            if (refreshAfter)
            {
                await RefreshAsync();
            }
            return null;
        }
        catch (MemoApiException ex) when (ex.Code == "duplicate_lemma")
        {
            restoreOnFailure?.Invoke();
            return "已收藏相同词形，勾选「仍然保存」可保留为重复词条。";
        }
        catch (Exception ex)
        {
            restoreOnFailure?.Invoke();
            return DescribeError(ex);
        }
        finally
        {
            IsBusy = false;
            _writeLock.Release();
        }
    }

    private async Task<T?> SafeAsync<T>(Func<Task<T>> action)
    {
        try
        {
            return await action();
        }
        catch (Exception)
        {
            return default;
        }
    }

    private static string DescribeError(Exception ex) => ex switch
    {
        MemoApiException api when api.StatusCode == 401 => "登录已过期，请重新登录",
        MemoApiException api => api.Detail is null
            ? $"请求失败（{api.StatusCode}）"
            : $"请求失败（{api.StatusCode}）：{api.Detail}",
        HttpRequestException => "无法连接 MemoIsle 服务，请确认后端已启动",
        TaskCanceledException => "请求超时，请稍后重试",
        _ => ex.Message,
    };

    private static void ReplaceAll<T>(ObservableCollection<T> target, IEnumerable<T> items)
    {
        target.Clear();
        foreach (var item in items)
        {
            target.Add(item);
        }
    }

    private static Memo? RemoveFrom(ObservableCollection<Memo> collection, Memo memo)
    {
        if (collection.Remove(memo))
        {
            return memo;
        }
        return null;
    }

    private static void RestoreTo(ObservableCollection<Memo> collection, Memo? memo)
    {
        if (memo is not null)
        {
            collection.Insert(0, memo);
        }
    }

    private static string? NullIfBlank(string value) => string.IsNullOrWhiteSpace(value) ? null : value.Trim();

    private static string DeriveTitle(string body)
    {
        var firstLine = body.Split('\n').Select(l => l.Trim()).FirstOrDefault(l => l.Length > 0) ?? "灵感";
        return firstLine.Length <= 80 ? firstLine : firstLine[..77] + "...";
    }

    public static string? NormalizeUrl(string value)
    {
        var cleaned = value.Trim();
        if (cleaned.Length == 0)
        {
            return null;
        }
        var candidate = cleaned.StartsWith("http://", StringComparison.OrdinalIgnoreCase) ||
                        cleaned.StartsWith("https://", StringComparison.OrdinalIgnoreCase)
            ? cleaned
            : "https://" + cleaned;
        return Uri.TryCreate(candidate, UriKind.Absolute, out var uri) &&
               (uri.Scheme == Uri.UriSchemeHttp || uri.Scheme == Uri.UriSchemeHttps) &&
               !string.IsNullOrEmpty(uri.Host)
            ? uri.ToString()
            : null;
    }

    private void RaiseCounts()
    {
        OnPropertyChanged(nameof(TotalCountTotal));
        OnPropertyChanged(nameof(WordCountTotal));
        OnPropertyChanged(nameof(ResourceCountTotal));
        OnPropertyChanged(nameof(IdeaCountTotal));
        OnPropertyChanged(nameof(ImageCountTotal));
        OnPropertyChanged(nameof(ReviewTotal));
        OnPropertyChanged(nameof(TrashTotal));
        OnPropertyChanged(nameof(HealthIssueCount));
        OnPropertyChanged(nameof(DevLoginAvailable));
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    private void SetField<T>(ref T field, T value, [CallerMemberName] string? name = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value))
        {
            return;
        }
        field = value;
        OnPropertyChanged(name);
    }

    private void OnPropertyChanged(string? name) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}
