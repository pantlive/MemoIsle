using System.Runtime.InteropServices;

namespace MemoIsle.Desktop.Services;

/// <summary>
/// Win32 全局热键（RegisterHotKey）：在任何应用里都能触发，
/// 用于"复制内容 → 按键 → 直接收藏"的免切换流程。
/// 消息由 WindowMessageHook 统一分发（WM_HOTKEY）。
/// </summary>
internal sealed class GlobalHotkey : IDisposable
{
    private const int WmHotkey = 0x0312;
    private const uint ModAlt = 0x0001;
    private const uint ModControl = 0x0002;
    private const uint ModShift = 0x0004;
    private const uint ModNoRepeat = 0x4000;

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool RegisterHotKey(IntPtr hWnd, int id, uint fsModifiers, uint vk);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool UnregisterHotKey(IntPtr hWnd, int id);

    private readonly IntPtr _hwnd;
    private readonly int _id;
    private bool _registered;

    public event Action? Pressed;

    public GlobalHotkey(IntPtr hwnd, int id)
    {
        _hwnd = hwnd;
        _id = id;
    }

    /// <summary>注册热键；失败（通常已被其他程序占用）返回 false。</summary>
    public bool TryRegister(HotkeyBinding binding)
    {
        Unregister();
        var modifiers = 0u;
        if (binding.Modifiers.Contains("Control"))
        {
            modifiers |= ModControl;
        }
        if (binding.Modifiers.Contains("Shift"))
        {
            modifiers |= ModShift;
        }
        if (binding.Modifiers.Contains("Menu"))
        {
            modifiers |= ModAlt;
        }
        var key = (uint)binding.ToVirtualKey();
        if (key == 0)
        {
            return false;
        }
        _registered = RegisterHotKey(_hwnd, _id, modifiers | ModNoRepeat, key);
        return _registered;
    }

    public void Unregister()
    {
        if (_registered)
        {
            UnregisterHotKey(_hwnd, _id);
            _registered = false;
        }
    }

    /// <summary>由窗口消息钩子调用；返回 true 表示消息已处理。</summary>
    public bool HandleMessage(uint message, IntPtr wParam)
    {
        if (message == WmHotkey && wParam.ToInt32() == _id)
        {
            Pressed?.Invoke();
            return true;
        }
        return false;
    }

    public void Dispose() => Unregister();
}


