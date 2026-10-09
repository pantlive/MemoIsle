using System.Runtime.InteropServices;

namespace MemoIsle.Desktop.Services;

/// <summary>
/// 系统托盘图标（Win32 Shell_NotifyIcon，无第三方依赖）：
/// 关闭窗口后驻留托盘，保证全局收藏热键继续可用。
/// </summary>
internal sealed class TrayIcon : IDisposable
{
    private const int WmApp = 0x8000;
    private const int TrayMessage = WmApp + 1;
    private const int WmLButtonDblClk = 0x0203;
    private const int WmRButtonUp = 0x0205;
    private const int NimAdd = 0x00000000;
    private const int NimModify = 0x00000001;
    private const int NimDelete = 0x00000002;
    private const int NifMessage = 0x00000001;
    private const int NifIcon = 0x00000002;
    private const int NifTip = 0x00000004;
    private const uint MfString = 0x00000000;
    private const uint MfSeparator = 0x00000800;
    private const uint TpmRightButton = 0x0002;
    private const uint TpmReturnCmd = 0x0100;
    private const uint ImageIcon = 1;
    private const uint LrLoadFromFile = 0x0010;
    private const int FirstMenuItemId = 100;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct NotifyIconData
    {
        public int cbSize;
        public IntPtr hWnd;
        public uint uID;
        public uint uFlags;
        public uint uCallbackMessage;
        public IntPtr hIcon;

        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)]
        public string szTip;
    }

    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    private static extern bool Shell_NotifyIcon(uint dwMessage, ref NotifyIconData lpData);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr LoadImage(IntPtr hinst, string lpszName, uint uType, int cx, int cy, uint fuLoad);

    [DllImport("user32.dll")]
    private static extern bool DestroyIcon(IntPtr hIcon);

    [DllImport("user32.dll")]
    private static extern IntPtr CreatePopupMenu();

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern bool AppendMenu(IntPtr hMenu, uint uFlags, IntPtr uIDNewItem, string lpNewItem);

    [DllImport("user32.dll")]
    private static extern bool DestroyMenu(IntPtr hMenu);

    [DllImport("user32.dll")]
    private static extern int TrackPopupMenu(
        IntPtr hMenu, uint uFlags, int x, int y, int nReserved, IntPtr hWnd, IntPtr prcRect);

    [DllImport("user32.dll")]
    private static extern bool GetCursorPos(out Point lpPoint);

    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr hWnd);

    [StructLayout(LayoutKind.Sequential)]
    private struct Point
    {
        public int X;
        public int Y;
    }

    private readonly IntPtr _hwnd;
    private readonly List<(int Id, string Text, Action Callback)> _menuItems = new();
    private NotifyIconData _data;
    private IntPtr _iconHandle;
    private bool _created;

    public TrayIcon(IntPtr hwnd)
    {
        _hwnd = hwnd;
    }

    public event Action? DoubleClicked;

    /// <summary>添加菜单项（在 Create 之前调用）。</summary>
    public void AddMenuItem(string text, Action callback) =>
        _menuItems.Add((FirstMenuItemId + _menuItems.Count, text, callback));

    public void AddSeparator() =>
        _menuItems.Add((0, string.Empty, () => { }));

    public bool Create(string iconPath, string tooltip)
    {
        try
        {
            if (File.Exists(iconPath))
            {
                _iconHandle = LoadImage(IntPtr.Zero, iconPath, ImageIcon, 16, 16, LrLoadFromFile);
            }
            _data = new NotifyIconData
            {
                cbSize = Marshal.SizeOf<NotifyIconData>(),
                hWnd = _hwnd,
                uID = 1,
                uFlags = NifMessage | NifIcon | NifTip,
                uCallbackMessage = TrayMessage,
                hIcon = _iconHandle,
                szTip = tooltip.Length > 120 ? tooltip[..120] : tooltip,
            };
            _created = Shell_NotifyIcon(NimAdd, ref _data);
            return _created;
        }
        catch (Exception)
        {
            return false;
        }
    }

    public void UpdateTooltip(string tooltip)
    {
        if (!_created)
        {
            return;
        }
        _data.szTip = tooltip.Length > 120 ? tooltip[..120] : tooltip;
        _data.uFlags = NifTip;
        Shell_NotifyIcon(NimModify, ref _data);
    }

    /// <summary>由窗口消息钩子调用；返回 true 表示消息已处理。</summary>
    public bool HandleMessage(uint msg, IntPtr wParam, IntPtr lParam)
    {
        if (msg != TrayMessage || !_created)
        {
            return false;
        }
        var mouseMessage = lParam.ToInt32();
        if (mouseMessage == WmLButtonDblClk)
        {
            DoubleClicked?.Invoke();
            return true;
        }
        if (mouseMessage == WmRButtonUp)
        {
            ShowContextMenu();
            return true;
        }
        return false;
    }

    private void ShowContextMenu()
    {
        var menu = CreatePopupMenu();
        if (menu == IntPtr.Zero)
        {
            return;
        }
        try
        {
            foreach (var (id, text, _) in _menuItems)
            {
                if (id == 0)
                {
                    AppendMenu(menu, MfSeparator, IntPtr.Zero, string.Empty);
                }
                else
                {
                    AppendMenu(menu, MfString, new IntPtr(id), text);
                }
            }
            GetCursorPos(out var cursor);
            // 先置前窗口，否则弹出的菜单不会在点击别处时关闭。
            SetForegroundWindow(_hwnd);
            var selected = TrackPopupMenu(
                menu,
                TpmRightButton | TpmReturnCmd,
                cursor.X,
                cursor.Y,
                0,
                _hwnd,
                IntPtr.Zero);
            var item = _menuItems.FirstOrDefault(entry => entry.Id == selected);
            item.Callback?.Invoke();
        }
        finally
        {
            DestroyMenu(menu);
        }
    }

    public void Dispose()
    {
        if (_created)
        {
            _data.uFlags = 0;
            Shell_NotifyIcon(NimDelete, ref _data);
            _created = false;
        }
        if (_iconHandle != IntPtr.Zero)
        {
            DestroyIcon(_iconHandle);
            _iconHandle = IntPtr.Zero;
        }
    }
}
