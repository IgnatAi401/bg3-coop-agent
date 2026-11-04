"""Capture the game window as a small JPEG with the Windows API (GDI to copy, GDI+ to encode).

Standard library only, in-process: no PowerShell, no window of its own, so a game in exclusive
fullscreen keeps the focus. Also runs on its own (`pythonw wincap.py out.jpg log.txt`) for the
development path in screen.py."""

from __future__ import annotations

import ctypes
import os
import sys
import tempfile
import uuid
from ctypes import wintypes as W

GAME_EXES = ("bg3_dx11.exe", "bg3.exe")
JPEG_CLSID = "557cf401-1a04-11d3-9a73-0000f81ef32e"
QUALITY_GUID = "1d5be4b5-fa4a-452d-9cdd-5db35105e7eb"


class CaptureError(Exception):
    """No picture; the message says why."""


class _GUID(ctypes.Structure):
    _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort),
                ("d4", ctypes.c_ubyte * 8)]


def _guid(s: str) -> _GUID:
    return _GUID.from_buffer_copy(uuid.UUID(s).bytes_le)


class _EncoderParameter(ctypes.Structure):
    _fields_ = [("guid", _GUID), ("count", ctypes.c_ulong), ("type", ctypes.c_ulong),
                ("value", ctypes.c_void_p)]


class _EncoderParameters(ctypes.Structure):
    _fields_ = [("count", ctypes.c_uint), ("param", _EncoderParameter * 1)]


class _StartupInput(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("callback", ctypes.c_void_p),
                ("no_thread", W.BOOL), ("no_codecs", W.BOOL)]


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [("biSize", W.DWORD), ("biWidth", W.LONG), ("biHeight", W.LONG), ("biPlanes", W.WORD),
                ("biBitCount", W.WORD), ("biCompression", W.DWORD), ("biSizeImage", W.DWORD),
                ("biXPelsPerMeter", W.LONG), ("biYPelsPerMeter", W.LONG), ("biClrUsed", W.DWORD),
                ("biClrImportant", W.DWORD)]


def _api():
    u, g, k, gp = (ctypes.WinDLL(n, use_last_error=True) for n in ("user32", "gdi32", "kernel32", "gdiplus"))
    H = ctypes.c_void_p
    sig = {
        (u, "EnumWindows"): (W.BOOL, [ctypes.c_void_p, W.LPARAM]),
        (u, "IsWindowVisible"): (W.BOOL, [W.HWND]),
        (u, "IsIconic"): (W.BOOL, [W.HWND]),
        (u, "GetForegroundWindow"): (W.HWND, []),
        (u, "GetWindowThreadProcessId"): (W.DWORD, [W.HWND, ctypes.POINTER(W.DWORD)]),
        (u, "GetClientRect"): (W.BOOL, [W.HWND, ctypes.POINTER(W.RECT)]),
        (u, "ClientToScreen"): (W.BOOL, [W.HWND, ctypes.POINTER(W.POINT)]),
        (u, "GetDC"): (H, [W.HWND]),
        (u, "ReleaseDC"): (ctypes.c_int, [W.HWND, H]),
        (g, "CreateCompatibleDC"): (H, [H]),
        (g, "CreateDIBSection"): (H, [H, ctypes.c_void_p, W.UINT, ctypes.POINTER(ctypes.c_void_p), H, W.DWORD]),
        (g, "SelectObject"): (H, [H, H]),
        (g, "DeleteObject"): (W.BOOL, [H]),
        (g, "DeleteDC"): (W.BOOL, [H]),
        (g, "SetStretchBltMode"): (ctypes.c_int, [H, ctypes.c_int]),
        (g, "SetBrushOrgEx"): (W.BOOL, [H, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]),
        (g, "StretchBlt"): (W.BOOL, [H, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                     H, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, W.DWORD]),
        (k, "OpenProcess"): (H, [W.DWORD, W.BOOL, W.DWORD]),
        (k, "CloseHandle"): (W.BOOL, [H]),
        (k, "QueryFullProcessImageNameW"): (W.BOOL, [H, W.DWORD, W.LPWSTR, ctypes.POINTER(W.DWORD)]),
        (gp, "GdiplusStartup"): (ctypes.c_int, [ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(_StartupInput), ctypes.c_void_p]),
        (gp, "GdiplusShutdown"): (None, [ctypes.c_size_t]),
        (gp, "GdipCreateBitmapFromScan0"): (ctypes.c_int, [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                                           ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]),
        (gp, "GdipSaveImageToFile"): (ctypes.c_int, [ctypes.c_void_p, W.LPCWSTR, ctypes.POINTER(_GUID),
                                                     ctypes.POINTER(_EncoderParameters)]),
        (gp, "GdipDisposeImage"): (ctypes.c_int, [ctypes.c_void_p]),
    }
    for (dll, name), (res, args) in sig.items():
        fn = getattr(dll, name)
        fn.restype, fn.argtypes = res, args
    try:  # physical pixels on a scaled display, for this thread only
        u.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        u.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        u.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    except AttributeError:
        pass
    return u, g, k, gp


def _exe(k, pid: int) -> str:
    h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf, n = ctypes.create_unicode_buffer(520), W.DWORD(520)
        return os.path.basename(buf.value).lower() if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else ""
    finally:
        k.CloseHandle(h)


def _game_window(u, k) -> int | None:
    found: list[tuple[int, int]] = []
    names: dict[int, str] = {}

    @ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    def each(hwnd, _):
        if u.IsWindowVisible(hwnd):
            pid = W.DWORD()
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value not in names:
                names[pid.value] = _exe(k, pid.value)
            if names[pid.value] in GAME_EXES:
                r = W.RECT()
                u.GetClientRect(hwnd, ctypes.byref(r))
                found.append(((r.right - r.left) * (r.bottom - r.top), hwnd))
        return True

    u.EnumWindows(each, 0)
    return max(found)[1] if found else None


def capture(path: str, max_width: int = 1280, quality: int = 60) -> tuple[int, int]:
    """Write the game window, scaled to at most `max_width`, as a JPEG to `path`; (width, height)."""
    if sys.platform != "win32":
        raise CaptureError("screenshots need the game's Windows PC")
    u, g, k, gp = _api()
    hwnd = _game_window(u, k)
    if not hwnd:
        raise CaptureError("no game window")
    if u.IsIconic(hwnd):
        raise CaptureError("game window is minimized")
    if u.GetForegroundWindow() != hwnd:
        raise CaptureError("game window is not in front")  # the screen would show something else
    r, p = W.RECT(), W.POINT(0, 0)
    u.GetClientRect(hwnd, ctypes.byref(r))
    u.ClientToScreen(hwnd, ctypes.byref(p))
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        raise CaptureError("empty game window")
    sw = min(max_width, w)
    sh = max(1, h * sw // w)

    screen = u.GetDC(None)
    mem = g.CreateCompatibleDC(screen)
    bmi = _BitmapInfoHeader(ctypes.sizeof(_BitmapInfoHeader), sw, -sh, 1, 32, 0, 0, 0, 0, 0, 0)  # top-down
    bits = ctypes.c_void_p()
    dib = g.CreateDIBSection(screen, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    token = ctypes.c_size_t()
    try:
        if not (mem and dib and bits):
            raise CaptureError("could not make a bitmap")
        old = g.SelectObject(mem, dib)
        g.SetStretchBltMode(mem, 4)  # HALFTONE: averages pixels when shrinking
        g.SetBrushOrgEx(mem, 0, 0, None)
        ok = g.StretchBlt(mem, 0, 0, sw, sh, screen, p.x, p.y, w, h, 0x00CC0020)  # SRCCOPY
        g.SelectObject(mem, old)
        if not ok:
            raise CaptureError("could not copy the screen")
        pixels = ctypes.string_at(bits, sw * sh * 4)
        if not pixels[::4 * 97].strip(b"\0"):  # a sample of the blue channel
            raise CaptureError("the picture came out black")
        if gp.GdiplusStartup(ctypes.byref(token), ctypes.byref(_StartupInput(1, None, False, False)), None):
            raise CaptureError("GDI+ did not start")
        img = ctypes.c_void_p()
        if gp.GdipCreateBitmapFromScan0(sw, sh, sw * 4, 0x00022009, bits, ctypes.byref(img)):  # 32bppRGB
            raise CaptureError("GDI+ could not take the bitmap")
        try:
            q = ctypes.c_ulong(quality)
            params = _EncoderParameters(1)
            params.param[0] = _EncoderParameter(_guid(QUALITY_GUID), 1, 4, ctypes.cast(ctypes.byref(q), ctypes.c_void_p))
            if gp.GdipSaveImageToFile(img, path, ctypes.byref(_guid(JPEG_CLSID)), ctypes.byref(params)):
                raise CaptureError("GDI+ could not write the JPEG")
        finally:
            gp.GdipDisposeImage(img)
    finally:
        if token.value:
            gp.GdiplusShutdown(token.value)
        if dib:
            g.DeleteObject(dib)
        if mem:
            g.DeleteDC(mem)
        u.ReleaseDC(None, screen)
    return sw, sh


def capture_bytes(max_width: int = 1280, quality: int = 60) -> bytes:
    fd, path = tempfile.mkstemp(prefix="bg3coop-", suffix=".jpg")
    os.close(fd)
    try:
        capture(path, max_width, quality)
        with open(path, "rb") as f:
            return f.read()
    finally:
        os.remove(path)


if __name__ == "__main__":  # pythonw wincap.py out.jpg log.txt [max_width quality]
    out, log = sys.argv[1], sys.argv[2]
    extra = [int(a) for a in sys.argv[3:5]]
    try:
        size = capture(out, *extra)
        msg = f"OK {size[0]} {size[1]}"
    except Exception as e:  # noqa: BLE001  (the log is all the caller sees)
        msg = f"ERR {e}"
    with open(log, "w", encoding="utf-8") as f:
        f.write(msg + "\n")
