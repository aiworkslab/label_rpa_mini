import ctypes
import ctypes.wintypes
import json
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox


# 設定を保存するJSONファイル名です。
CONFIG_FILE = Path("label_rpa_config.json")

# テスト入力ボタンで入力する文字列です。
TEST_TEXT = "test input"


# Windows APIで使う定数です。
WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201
WM_QUIT = 0x0012
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

# ULONG_PTRはctypes.wintypesに無い環境があるため、同じポインタサイズのWPARAMで代用します。
ULONG_PTR = ctypes.wintypes.WPARAM


class POINT(ctypes.Structure):
    """Windows APIから受け取るマウス座標の入れ物です。"""

    _fields_ = [
        ("x", ctypes.c_long),
        ("y", ctypes.c_long),
    ]


class MSLLHOOKSTRUCT(ctypes.Structure):
    """低レベルマウスフックで受け取るクリック情報です。"""

    _fields_ = [
        ("pt", POINT),
        ("mouseData", ctypes.c_ulong),
        ("flags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    """SendInputでマウス操作を送るためのデータです。"""

    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    """SendInputでキーボード入力を送るためのデータです。"""

    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("union", INPUT_UNION),
    ]


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# 64bit Windowsでもポインタサイズの戻り値を正しく扱うための型です。
LRESULT = ctypes.c_ssize_t

LowLevelMouseProc = ctypes.WINFUNCTYPE(
    LRESULT,
    ctypes.c_int,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
)

# ctypesの既定値はint扱いになりやすいため、Windows APIの型を明示します。
# 特にCallNextHookExのLPARAMは64bitで値が大きくなることがあるため重要です。
kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = ctypes.wintypes.DWORD

user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int,
    LowLevelMouseProc,
    ctypes.wintypes.HINSTANCE,
    ctypes.wintypes.DWORD,
]
user32.SetWindowsHookExW.restype = ctypes.wintypes.HHOOK

user32.CallNextHookEx.argtypes = [
    ctypes.wintypes.HHOOK,
    ctypes.c_int,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
]
user32.CallNextHookEx.restype = LRESULT

user32.UnhookWindowsHookEx.argtypes = [ctypes.wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = ctypes.wintypes.BOOL

user32.PostThreadMessageW.argtypes = [
    ctypes.wintypes.DWORD,
    ctypes.wintypes.UINT,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
]
user32.PostThreadMessageW.restype = ctypes.wintypes.BOOL

user32.GetMessageW.argtypes = [
    ctypes.POINTER(ctypes.wintypes.MSG),
    ctypes.wintypes.HWND,
    ctypes.wintypes.UINT,
    ctypes.wintypes.UINT,
]
user32.GetMessageW.restype = ctypes.wintypes.BOOL

user32.TranslateMessage.argtypes = [ctypes.POINTER(ctypes.wintypes.MSG)]
user32.TranslateMessage.restype = ctypes.wintypes.BOOL

user32.DispatchMessageW.argtypes = [ctypes.POINTER(ctypes.wintypes.MSG)]
user32.DispatchMessageW.restype = LRESULT

user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = ctypes.wintypes.BOOL

user32.SendInput.argtypes = [
    ctypes.wintypes.UINT,
    ctypes.POINTER(INPUT),
    ctypes.c_int,
]
user32.SendInput.restype = ctypes.wintypes.UINT


class ClickCapture:
    """画面上の次の左クリック座標を1回だけ取得するクラスです。"""

    def __init__(self, on_click, on_error):
        self.on_click = on_click
        self.on_error = on_error
        self.hook_id = None
        self.thread_id = None
        self.callback = LowLevelMouseProc(self._mouse_proc)
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        # メッセージループを終了させます。
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)

    def _run(self):
        self.thread_id = kernel32.GetCurrentThreadId()
        self.hook_id = user32.SetWindowsHookExW(WH_MOUSE_LL, self.callback, None, 0)

        if not self.hook_id:
            self.on_error("クリック取得の準備に失敗しました。")
            return

        msg = ctypes.wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        user32.UnhookWindowsHookEx(self.hook_id)
        self.hook_id = None

    def _mouse_proc(self, n_code, w_param, l_param):
        if n_code == 0 and w_param == WM_LBUTTONDOWN:
            info = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            x, y = info.pt.x, info.pt.y

            # Tkinterの画面更新はメインスレッド側で行います。
            self.on_click(x, y)
            self.stop()
            return 1

        return user32.CallNextHookEx(self.hook_id, n_code, w_param, l_param)


class LabelRpaApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("ラベルRPAミニ")
        self.geometry("460x500")
        self.resizable(False, False)

        self.label_pos = None
        self.input_pos = None
        self.capture = None
        self.config_items = []

        self.status_var = tk.StringVar(value="ボタンを押して、画面上の位置をクリックしてください。")
        self.label_name_var = tk.StringVar(value="")
        self.label_var = tk.StringVar(value="ラベル座標: 未取得")
        self.input_var = tk.StringVar(value="入力欄座標: 未取得")
        self.offset_var = tk.StringVar(value="offset_x / offset_y: 未計算")

        self._load_config()
        self._build_ui()
        self._refresh_labels()
        self._refresh_registered_labels()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        # 画面全体の余白を用意します。
        main = tk.Frame(self, padx=18, pady=18)
        main.pack(fill="both", expand=True)

        title = tk.Label(main, text="クリック位置の関係を保存する簡易RPA", font=("Yu Gothic UI", 13, "bold"))
        title.pack(anchor="w", pady=(0, 14))

        # ラベル名はJSONに保存し、起動時に前回の内容を表示します。
        label_name_frame = tk.Frame(main)
        label_name_frame.pack(fill="x", pady=(0, 12))

        tk.Label(label_name_frame, text="ラベル名", width=10, anchor="w").pack(side="left")
        tk.Entry(label_name_frame, textvariable=self.label_name_var).pack(side="left", fill="x", expand=True)

        button_frame = tk.Frame(main)
        button_frame.pack(fill="x", pady=(0, 12))

        self.label_button = tk.Button(
            button_frame,
            text="ラベル位置を取得",
            command=lambda: self._start_capture("label"),
            width=18,
        )
        self.label_button.grid(row=0, column=0, padx=(0, 8), pady=4)

        self.input_button = tk.Button(
            button_frame,
            text="入力欄位置を取得",
            command=lambda: self._start_capture("input"),
            width=18,
        )
        self.input_button.grid(row=0, column=1, padx=(0, 8), pady=4)

        self.test_button = tk.Button(
            button_frame,
            text="テスト入力",
            command=self._test_input,
            width=14,
        )
        self.test_button.grid(row=0, column=2, pady=4)

        info_frame = tk.LabelFrame(main, text="取得した位置", padx=12, pady=10)
        info_frame.pack(fill="x", pady=(0, 12))

        tk.Label(info_frame, textvariable=self.label_var, anchor="w").pack(fill="x", pady=2)
        tk.Label(info_frame, textvariable=self.input_var, anchor="w").pack(fill="x", pady=2)
        tk.Label(info_frame, textvariable=self.offset_var, anchor="w").pack(fill="x", pady=2)

        save_frame = tk.Frame(main)
        save_frame.pack(fill="x", pady=(0, 12))

        tk.Button(save_frame, text="JSONに保存", command=self._save_config, width=18).pack(side="left")
        tk.Button(save_frame, text="設定を再読み込み", command=self._reload_config, width=18).pack(side="left", padx=8)

        registered_frame = tk.LabelFrame(main, text="登録済みラベル", padx=12, pady=10)
        registered_frame.pack(fill="x", pady=(0, 12))

        # 設定ファイル内のitems配列を確認するための読み取り専用一覧です。
        self.registered_list_var = tk.StringVar(value="")
        tk.Label(
            registered_frame,
            textvariable=self.registered_list_var,
            anchor="w",
            justify="left",
            wraplength=400,
        ).pack(fill="x")

        status_box = tk.Label(
            main,
            textvariable=self.status_var,
            anchor="w",
            justify="left",
            wraplength=410,
            relief="groove",
            padx=10,
            pady=8,
        )
        status_box.pack(fill="x")

    def _start_capture(self, target):
        if self.capture:
            messagebox.showinfo("取得中", "現在のクリック取得が終わってから、もう一度押してください。")
            return

        target_name = "ラベル" if target == "label" else "入力欄"
        self.status_var.set(f"{target_name}の位置を取得します。画面上の目的の場所を左クリックしてください。")
        self._set_buttons_enabled(False)

        def on_click(x, y):
            # 別スレッドから呼ばれるので、afterでメインスレッドに戻します。
            self.after(0, lambda: self._finish_capture(target, x, y))

        def on_error(message):
            self.after(0, lambda: self._capture_error(message))

        self.capture = ClickCapture(on_click=on_click, on_error=on_error)
        self.capture.start()

    def _finish_capture(self, target, x, y):
        if target == "label":
            self.label_pos = {"x": x, "y": y}
        else:
            self.input_pos = {"x": x, "y": y}

        self.capture = None
        self._set_buttons_enabled(True)
        self._refresh_labels()
        self._save_config(show_message=False)
        self.status_var.set(f"座標を取得しました: x={x}, y={y}")

    def _capture_error(self, message):
        self.capture = None
        self._set_buttons_enabled(True)
        self.status_var.set(message)
        messagebox.showerror("エラー", message)

    def _set_buttons_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        self.label_button.config(state=state)
        self.input_button.config(state=state)
        self.test_button.config(state=state)

    def _refresh_labels(self):
        if self.label_pos:
            self.label_var.set(f"ラベル座標: x={self.label_pos['x']}, y={self.label_pos['y']}")
        else:
            self.label_var.set("ラベル座標: 未取得")

        if self.input_pos:
            self.input_var.set(f"入力欄座標: x={self.input_pos['x']}, y={self.input_pos['y']}")
        else:
            self.input_var.set("入力欄座標: 未取得")

        if self.label_pos and self.input_pos:
            offset_x = self.input_pos["x"] - self.label_pos["x"]
            offset_y = self.input_pos["y"] - self.label_pos["y"]
            self.offset_var.set(f"offset_x={offset_x}, offset_y={offset_y}")
        else:
            self.offset_var.set("offset_x / offset_y: 未計算")

    def _build_config_item(self):
        offset = None
        if self.label_pos and self.input_pos:
            offset = {
                "offset_x": self.input_pos["x"] - self.label_pos["x"],
                "offset_y": self.input_pos["y"] - self.label_pos["y"],
            }

        return {
            "label_name": self.label_name_var.get(),
            "label_position": self.label_pos,
            "input_position": self.input_pos,
            "offset": offset,
            "test_text": TEST_TEXT,
        }

    def _build_config_data(self):
        # 今後の複数ラベル対応に備えて、設定はitems配列の1件として保存します。
        # 画面ではまだ1件だけ編集するため、先頭だけ現在の入力内容で更新します。
        items = [self._build_config_item()]
        if len(self.config_items) > 1:
            items.extend(self.config_items[1:])

        return {
            "items": items,
        }

    def _save_config(self, show_message=True):
        data = self._build_config_data()
        CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.config_items = data["items"]
        self._refresh_registered_labels()

        if show_message:
            self.status_var.set(f"設定を保存しました: {CONFIG_FILE}")
            messagebox.showinfo("保存完了", f"設定を保存しました。\n{CONFIG_FILE}")

    def _load_config(self):
        if not CONFIG_FILE.exists():
            return

        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            messagebox.showwarning("読み込み失敗", "JSON設定ファイルの形式が正しくありません。")
            return

        # 新形式はitems配列です。まだ画面は1件だけ扱うため、先頭の設定を読み込みます。
        items = data.get("items")
        if isinstance(items, list) and items:
            self.config_items = items
            data = items[0]
        elif isinstance(items, list):
            self.config_items = []
            data = {}
        else:
            self.config_items = [data]
        # 古いJSON形式は直下にlabel_positionなどがあるため、そのまま読み込みます。

        self.label_pos = data.get("label_position")
        self.input_pos = data.get("input_position")
        # 古いJSONにlabel_nameが無い場合は空文字として読み込みます。
        self.label_name_var.set(data.get("label_name", ""))

    def _reload_config(self):
        self._load_config()
        self._refresh_labels()
        self._refresh_registered_labels()
        self.status_var.set("設定を再読み込みしました。")

    def _refresh_registered_labels(self):
        if not hasattr(self, "registered_list_var"):
            return

        if not self.config_items:
            self.registered_list_var.set("登録されているラベルはありません")
            return

        # 一覧にはラベル名と入力する内容を表示します。
        lines = []
        for index, item in enumerate(self.config_items, start=1):
            label_name = item.get("label_name") or "名称未設定"
            test_text = item.get("test_text") or ""
            lines.append(f"{index}. ラベル名: {label_name} / 入力する内容: {test_text}")

        self.registered_list_var.set("\n".join(lines))

    def _test_input(self):
        if not self.input_pos:
            messagebox.showwarning("入力欄未取得", "先に「入力欄位置を取得」で座標を取得してください。")
            return

        self.status_var.set("3秒後に入力欄をクリックして、テスト文字列を入力します。")
        self.after(3000, self._send_test_input)

    def _send_test_input(self):
        x = self.input_pos["x"]
        y = self.input_pos["y"]

        # カーソルを入力欄座標へ移動して、左クリックします。
        user32.SetCursorPos(x, y)
        time.sleep(0.1)
        self._send_mouse_click()
        time.sleep(0.1)
        self._send_text(TEST_TEXT)

        self.status_var.set(f"テスト入力を送信しました: {TEST_TEXT}")

    def _send_mouse_click(self):
        down = INPUT(
            type=INPUT_MOUSE,
            union=INPUT_UNION(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, 0)),
        )
        up = INPUT(
            type=INPUT_MOUSE,
            union=INPUT_UNION(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, 0)),
        )
        inputs = (INPUT * 2)(down, up)
        user32.SendInput(2, inputs, ctypes.sizeof(INPUT))

    def _send_text(self, text):
        # Unicode入力なので、日本語などにも応用しやすい方式です。
        for char in text:
            code = ord(char)
            key_down = INPUT(
                type=INPUT_KEYBOARD,
                union=INPUT_UNION(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, 0)),
            )
            key_up = INPUT(
                type=INPUT_KEYBOARD,
                union=INPUT_UNION(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0)),
            )
            inputs = (INPUT * 2)(key_down, key_up)
            user32.SendInput(2, inputs, ctypes.sizeof(INPUT))

    def _on_close(self):
        if self.capture:
            self.capture.stop()
        self.destroy()


if __name__ == "__main__":
    app = LabelRpaApp()
    app.mainloop()
