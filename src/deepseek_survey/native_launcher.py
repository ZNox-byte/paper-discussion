"""Small Win32 launcher; uses Windows itself, with no Tcl/Tk or browser runtime dependency."""
from __future__ import annotations

import ctypes
import webbrowser
from ctypes import wintypes


def show_launcher(url: str, root: str, *, smoke=False):
    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM)

    class WindowClass(ctypes.Structure):
        _fields_ = [("style", wintypes.UINT), ("procedure", callback_type),
                    ("class_extra", ctypes.c_int), ("window_extra", ctypes.c_int),
                    ("instance", wintypes.HINSTANCE), ("icon", wintypes.HICON),
                    ("cursor", wintypes.HANDLE), ("background", wintypes.HBRUSH),
                    ("menu", wintypes.LPCWSTR), ("name", wintypes.LPCWSTR)]

    kernel.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel.GetModuleHandleW.restype = wintypes.HMODULE
    user.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.DefWindowProcW.restype = ctypes.c_ssize_t
    user.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
        wintypes.HINSTANCE, wintypes.LPVOID]
    user.CreateWindowExW.restype = wintypes.HWND
    user.RegisterClassW.argtypes = [ctypes.POINTER(WindowClass)]
    user.RegisterClassW.restype = wintypes.ATOM
    user.DestroyWindow.argtypes = [wintypes.HWND]
    user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user.UpdateWindow.argtypes = [wintypes.HWND]
    user.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, wintypes.LPVOID]
    user.SetTimer.restype = ctypes.c_size_t
    user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.SendMessageW.restype = ctypes.c_ssize_t
    user.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user.DispatchMessageW.restype = ctypes.c_ssize_t
    gdi.GetStockObject.argtypes = [ctypes.c_int]
    gdi.GetStockObject.restype = wintypes.HGDIOBJ
    instance = kernel.GetModuleHandleW(None)
    font = gdi.GetStockObject(17)  # DEFAULT_GUI_FONT, owned by the OS.

    @callback_type
    def procedure(window, message, wparam, lparam):
        if message == 0x0113 and smoke:  # WM_TIMER; only for packaged startup verification.
            user.DestroyWindow(window)
            return 0
        if message == 0x0111:  # WM_COMMAND
            if (wparam & 0xffff) == 100:
                webbrowser.open(url)
            elif (wparam & 0xffff) == 101:
                user.DestroyWindow(window)
            return 0
        if message == 0x0002:  # WM_DESTROY
            user.PostQuitMessage(0)
            return 0
        return user.DefWindowProcW(window, message, wparam, lparam)

    name = "PaperAtlasLauncher"
    definition = WindowClass(0, procedure, 0, 0, instance, None, None, 16, None, name)
    if not user.RegisterClassW(ctypes.byref(definition)):
        raise ctypes.WinError(ctypes.get_last_error())
    window = user.CreateWindowExW(0, name, "Paper Atlas · 论文研究工作台", 0x00CA0000,
                                  240, 170, 550, 315, None, None, instance, None)
    if not window:
        raise ctypes.WinError(ctypes.get_last_error())

    def control(kind, text, left, top, width, height, identifier=0):
        child = user.CreateWindowExW(0, kind, text, 0x50000000 | (0x10000 if kind == "BUTTON" else 0),
                                     left, top, width, height, window, identifier, instance, None)
        if not child:
            raise ctypes.WinError(ctypes.get_last_error())
        user.SendMessageW(child, 0x0030, font, 1)  # WM_SETFONT

    control("STATIC", "Paper Atlas  |  Codex 订阅终审", 26, 22, 490, 26)
    control("STATIC", "应用已启动，研究界面将在默认浏览器中打开。\r\n无需打开 VS Code，首次使用请在界面中登录订阅账号。",
            26, 64, 490, 44)
    control("STATIC", "研究数据目录：\r\n" + root, 26, 122, 490, 46)
    control("STATIC", "关闭浏览器不停止任务；退出应用会停止任务。", 26, 181, 490, 22)
    control("BUTTON", "打开研究工作台", 26, 220, 185, 34, 100)
    control("BUTTON", "退出应用", 375, 220, 135, 34, 101)
    user.ShowWindow(window, 0 if smoke else 1)
    user.UpdateWindow(window)
    if smoke:
        if not user.SetTimer(window, 1, 150, None):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        webbrowser.open(url)
    message = wintypes.MSG()
    while (result := user.GetMessageW(ctypes.byref(message), None, 0, 0)) > 0:
        user.TranslateMessage(ctypes.byref(message))
        user.DispatchMessageW(ctypes.byref(message))
    if result == -1:
        raise ctypes.WinError(ctypes.get_last_error())
