using System.Runtime.InteropServices;

namespace MemoIsle.Desktop.Services;

/// <summary>
/// 统一的窗口消息钩子（子类化窗口过程）：全局热键与托盘图标都需要接收窗口消息，
/// 这里只挂一次钩子并按消息分发，避免多次子类化互相覆盖。
/// </summary>
internal sealed class WindowMessageHook : IDisposable
{
    private const int GwlWndProc = -4;

    private delegate IntPtr WindowProc(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW", SetLastError = true)]
    private static extern IntPtr SetWindowLongPtr(IntPtr hWnd, int nIndex, IntPtr dwNewLong);

    [DllImport("user32.dll")]
    private static extern IntPtr CallWindowProc(
        IntPtr lpPrevWndFunc,
        IntPtr hWnd,
        uint msg,
        IntPtr wParam,
        IntPtr lParam);

    private readonly IntPtr _hwnd;
    private readonly WindowProc _hookProc;
    private readonly List<Func<uint, IntPtr, IntPtr, bool>> _handlers = new();
    private IntPtr _previousProc;
    private bool _installed;

    public WindowMessageHook(IntPtr hwnd)
    {
        _hwnd = hwnd;
        _hookProc = HookedWindowProc;
        _previousProc = SetWindowLongPtr(_hwnd, GwlWndProc, Marshal.GetFunctionPointerForDelegate(_hookProc));
        _installed = true;
    }

    /// <summary>注册消息处理；返回 true 表示已处理（不再向下传递）。</summary>
    public void AddHandler(Func<uint, IntPtr, IntPtr, bool> handler) => _handlers.Add(handler);

    private IntPtr HookedWindowProc(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam)
    {
        foreach (var handler in _handlers)
        {
            try
            {
                if (handler(msg, wParam, lParam))
                {
                    return IntPtr.Zero;
                }
            }
            catch (Exception)
            {
                // 单个处理器异常不影响消息继续传递。
            }
        }
        return _previousProc != IntPtr.Zero
            ? CallWindowProc(_previousProc, hWnd, msg, wParam, lParam)
            : IntPtr.Zero;
    }

    public void Dispose()
    {
        if (_installed && _previousProc != IntPtr.Zero)
        {
            SetWindowLongPtr(_hwnd, GwlWndProc, _previousProc);
            _previousProc = IntPtr.Zero;
            _installed = false;
        }
    }
}
