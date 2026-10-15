"""AI配置对话框模块"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.pet_core import DesktopPet

from src.config import load_config, update_config
from src.constants import (
    AI_DEFAULT_BASE_URLS,
    AI_DEFAULT_MODELS,
    AI_MODELS,
    AI_PROVIDER_CUSTOM,
    AI_PROVIDER_DEEPSEEK,
    AI_PROVIDER_DOUBAO,
    AI_PROVIDER_GLM,
    AI_PROVIDER_KIMI,
    AI_PROVIDER_OPENAI,
    AI_PROVIDER_QWEN,
    AI_PROVIDERS,
    AI_PROVIDER_NAMES,
)


class AIConfigDialog:
    """AI配置对话框"""

    def __init__(self, app: DesktopPet):
        self.app = app
        self.dialog: tk.Toplevel | None = None
        self.config_vars: dict = {}

    def show(self) -> None:
        """显示配置对话框"""
        if self.dialog and self.dialog.winfo_exists():
            self.dialog.lift()
            return

        self._create_dialog()

    def _create_dialog(self) -> None:
        """创建对话框"""
        self.dialog = tk.Toplevel(self.app.root)
        self.dialog.title("AI助手配置")
        self.dialog.geometry("520x680")
        self.dialog.resizable(False, False)
        self.dialog.transient(self.app.root)
        self.dialog.grab_set()

        # 窗口置顶（短暂显示后取消，让其他窗口可以覆盖）
        self.dialog.attributes("-topmost", True)
        self.dialog.after(2000, lambda: self.dialog.attributes("-topmost", False))

        # 居中显示
        self.dialog.update_idletasks()
        x = (self.dialog.winfo_screenwidth() - 520) // 2
        y = (self.dialog.winfo_screenheight() - 680) // 2
        self.dialog.geometry(f"+{x}+{y}")

        # 设置主题样式
        self._setup_style()

        # 加载当前配置
        config = load_config()

        # 创建界面
        self._create_widgets(config)

    def _setup_style(self) -> None:
        """设置主题样式"""
        style = ttk.Style()
        style.theme_use("clam")

        # 配置主颜色
        primary_color = "#FF69B4"
        bg_color = "#FFF5F8"
        entry_bg = "#FFFFFF"

        style.configure(".", background=bg_color)
        style.configure("TFrame", background=bg_color)
        style.configure("TLabel", background=bg_color, foreground="#5C3B4A")
        style.configure("TCheckbutton", background=bg_color, foreground="#5C3B4A")

        # 配置按钮样式
        style.configure(
            "Primary.TButton",
            background=primary_color,
            foreground="white",
            borderwidth=0,
            focuscolor="none",
        )
        style.map(
            "Primary.TButton",
            background=[("active", "#FF85C1"), ("pressed", "#E85A9C")],
        )

        style.configure(
            "Secondary.TButton",
            background="#F0F0F0",
            foreground="#5C3B4A",
            borderwidth=1,
            focuscolor="none",
        )
        style.map(
            "Secondary.TButton",
            background=[("active", "#E0E0E0")],
        )

    def _create_widgets(self, config: dict) -> None:
        """创建界面组件"""
        # 主容器
        main_container = ttk.Frame(self.dialog, padding=0)
        main_container.pack(fill=tk.BOTH, expand=True)

        # 标题栏
        title_frame = tk.Frame(main_container, bg="#FF69B4", height=50)
        title_frame.pack(fill=tk.X)
        title_frame.pack_propagate(False)

        title_label = tk.Label(
            title_frame,
            text="🤖 AI助手配置",
            bg="#FF69B4",
            fg="white",
            font=("Microsoft YaHei", 14, "bold"),
        )
        title_label.pack(side=tk.LEFT, padx=20, pady=10)

        # 上方可滚动区域
        scroll_container = ttk.Frame(main_container)
        scroll_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=15)

        # Canvas和滚动条
        canvas = tk.Canvas(
            scroll_container,
            highlightthickness=0,
            bg="#FFF5F8",
            height=500,
        )
        scrollbar = ttk.Scrollbar(
            scroll_container, orient="vertical", command=canvas.yview
        )
        content_frame = ttk.Frame(canvas, padding="0")
        content_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=content_frame, anchor="nw", width=460)
        canvas.configure(yscrollcommand=scrollbar.set)

        # 绑定鼠标滚轮
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<MouseWheel>", _on_mousewheel)
        content_frame.bind("<MouseWheel>", _on_mousewheel)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 启用AI
        self.config_vars["enabled"] = tk.BooleanVar(
            value=config.get("ai_enabled", False)
        )
        enabled_check = ttk.Checkbutton(
            content_frame,
            text="启用AI对话功能",
            variable=self.config_vars["enabled"],
        )
        enabled_check.pack(anchor=tk.W, pady=(0, 10))

        # 分隔线
        ttk.Separator(content_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=10)

        # API提供商
        ttk.Label(
            content_frame, text="AI服务商:", font=("Microsoft YaHei", 10, "bold")
        ).pack(anchor=tk.W, pady=(5, 5))

        self.config_vars["provider"] = tk.StringVar(
            value=config.get("ai_provider", AI_PROVIDER_DEEPSEEK)
        )

        # 服务商选择按钮组
        provider_frame = tk.Frame(content_frame, bg="#FFF5F8")
        provider_frame.pack(fill=tk.X, pady=(0, 10))

        self.provider_buttons = {}
        for i, provider in enumerate(AI_PROVIDERS):
            name = AI_PROVIDER_NAMES.get(provider, provider)
            btn = tk.Radiobutton(
                provider_frame,
                text=name,
                variable=self.config_vars["provider"],
                value=provider,
                bg="#FFF5F8",
                fg="#5C3B4A",
                selectcolor="#FFE4EE",
                activebackground="#FFF5F8",
                font=("Microsoft YaHei", 9),
                command=self._on_provider_change,
            )
            btn.grid(row=i // 3, column=i % 3, sticky="w", padx=5, pady=3)
            self.provider_buttons[provider] = btn

        # API密钥
        ttk.Label(
            content_frame, text="API密钥:", font=("Microsoft YaHei", 10, "bold")
        ).pack(anchor=tk.W, pady=(10, 5))

        api_key_frame = tk.Frame(content_frame, bg="#FFF5F8")
        api_key_frame.pack(fill=tk.X, pady=(0, 8))

        self.config_vars["api_key"] = tk.StringVar(value=config.get("ai_api_key", ""))
        api_key_entry = ttk.Entry(
            api_key_frame,
            textvariable=self.config_vars["api_key"],
            show="*",
            font=("Microsoft YaHei", 9),
        )
        api_key_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 显示/隐藏密码
        self.show_key_var = tk.BooleanVar(value=False)
        show_btn = tk.Checkbutton(
            api_key_frame,
            text="显示",
            variable=self.show_key_var,
            bg="#FFF5F8",
            fg="#5C3B4A",
            selectcolor="#FFE4EE",
            font=("Microsoft YaHei", 8),
            command=lambda: api_key_entry.config(
                show="" if self.show_key_var.get() else "*"
            ),
        )
        show_btn.pack(side=tk.RIGHT, padx=(8, 0))

        # 模型选择
        ttk.Label(
            content_frame, text="模型:", font=("Microsoft YaHei", 10, "bold")
        ).pack(anchor=tk.W, pady=(10, 5))

        # 模型选择框架（带手动添加按钮）
        model_frame = tk.Frame(content_frame, bg="#FFF5F8")
        model_frame.pack(fill=tk.X, pady=(0, 5))

        self.config_vars["model"] = tk.StringVar(
            value=config.get("ai_model", AI_DEFAULT_MODELS.get(AI_PROVIDER_DEEPSEEK))
        )
        self.model_combo = ttk.Combobox(
            model_frame,
            textvariable=self.config_vars["model"],
            values=AI_MODELS.get(AI_PROVIDER_DEEPSEEK, []),
            font=("Microsoft YaHei", 9),
        )
        self.model_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.model_combo.bind("<<ComboboxSelected>>", self._on_model_change)

        # 手动添加模型按钮
        btn_add_model = tk.Button(
            model_frame,
            text="+",
            bg="#4ECDC4",
            fg="white",
            font=("Microsoft YaHei", 12, "bold"),
            borderwidth=0,
            width=3,
            pady=0,
            cursor="hand2",
            command=self._add_custom_model,
        )
        btn_add_model.pack(side=tk.RIGHT, padx=(5, 0))

        # 模型输入提示
        model_hint = tk.Label(
            content_frame,
            text="可直接输入自定义模型名称",
            bg="#FFF5F8",
            fg="#888888",
            font=("Microsoft YaHei", 8),
            anchor="w",
        )
        model_hint.pack(fill=tk.X, pady=(0, 8))

        # Base URL（可选）
        ttk.Label(
            content_frame,
            text="Base URL (自定义API地址):",
            font=("Microsoft YaHei", 10, "bold"),
        ).pack(anchor=tk.W, pady=(10, 5))

        self.config_vars["base_url"] = tk.StringVar(value=config.get("ai_base_url", ""))
        self.base_url_entry = ttk.Entry(
            content_frame,
            textvariable=self.config_vars["base_url"],
            font=("Microsoft YaHei", 9),
        )
        self.base_url_entry.pack(fill=tk.X, pady=(0, 5))

        # Base URL提示
        self.base_url_hint = tk.Label(
            content_frame,
            text="",
            bg="#FFF5F8",
            fg="#888888",
            font=("Microsoft YaHei", 8),
            anchor="w",
        )
        self.base_url_hint.pack(fill=tk.X, pady=(0, 10))

        # 性格选择
        ttk.Label(
            content_frame, text="选择性格:", font=("Microsoft YaHei", 10, "bold")
        ).pack(anchor=tk.W, pady=(10, 5))

        self.config_vars["personality"] = tk.StringVar(
            value=config.get("ai_personality", "aemeath")
        )
        personality_combo = ttk.Combobox(
            content_frame,
            textvariable=self.config_vars["personality"],
            values=["aemeath", "default", "helpful", "cute", "tsundere"],
            state="readonly",
            font=("Microsoft YaHei", 9),
        )
        personality_combo.pack(fill=tk.X, pady=(0, 5))

        # 性格说明
        personality_desc = {
            "aemeath": "爱弥斯（Aemeath）- 鸣潮角色，粉色头发电子幽灵少女",
            "default": "活泼友善，带可爱语气",
            "helpful": "专业准确，实用建议",
            "cute": "超级可爱，喜欢颜文字",
            "tsundere": "傲娇属性，外冷内热",
        }
        self.desc_label = tk.Label(
            content_frame,
            text=personality_desc.get(self.config_vars["personality"].get(), ""),
            bg="#FFF5F8",
            fg="#888888",
            font=("Microsoft YaHei", 9),
            anchor="w",
            wraplength=450,
        )
        self.desc_label.pack(anchor=tk.W, pady=(0, 10))
        personality_combo.bind(
            "<<ComboboxSelected>>",
            lambda e: self.desc_label.config(
                text=personality_desc.get(self.config_vars["personality"].get(), "")
            ),
        )

        # 下方固定按钮区域
        button_frame = tk.Frame(main_container, bg="#FFF5F8", height=60)
        button_frame.pack(fill=tk.X, side=tk.BOTTOM)
        button_frame.pack_propagate(False)

        # 分隔线
        sep = ttk.Separator(main_container, orient=tk.HORIZONTAL)
        sep.pack(fill=tk.X, side=tk.BOTTOM)

        # 按钮
        btn_save = tk.Button(
            button_frame,
            text="💾 保存配置",
            bg="#FF69B4",
            fg="white",
            font=("Microsoft YaHei", 10),
            borderwidth=0,
            padx=20,
            pady=8,
            cursor="hand2",
            command=self._save_config,
        )
        btn_save.pack(side=tk.LEFT, padx=(15, 10), pady=12)

        btn_test = tk.Button(
            button_frame,
            text="🔗 测试连接",
            bg="#4ECDC4",
            fg="white",
            font=("Microsoft YaHei", 10),
            borderwidth=0,
            padx=20,
            pady=8,
            cursor="hand2",
            command=self._test_connection,
        )
        btn_test.pack(side=tk.LEFT, padx=(0, 10), pady=12)

        btn_cancel = tk.Button(
            button_frame,
            text="✕ 取消",
            bg="#CCCCCC",
            fg="#5C3B4A",
            font=("Microsoft YaHei", 10),
            borderwidth=0,
            padx=20,
            pady=8,
            cursor="hand2",
            command=self.dialog.destroy,
        )
        btn_cancel.pack(side=tk.RIGHT, padx=(0, 15), pady=12)

        # 初始化服务商状态
        self._on_provider_change()

    def _on_provider_change(self, event=None) -> None:
        """服务商改变时更新默认模型和Base URL"""
        provider = self.config_vars["provider"].get()

        # 更新模型列表
        models = AI_MODELS.get(provider, [])
        self.model_combo["values"] = models
        default_model = AI_DEFAULT_MODELS.get(provider, models[0] if models else "")
        self.config_vars["model"].set(default_model)
        self.model_combo.set(default_model)

        # 更新Base URL提示和模型提示
        if provider == AI_PROVIDER_CUSTOM:
            self.base_url_hint.config(text="请输入自定义API的Base URL地址")
            self.base_url_entry.config(state="normal")
            # 自定义API时清空模型列表，让用户手动添加
            self.model_combo["values"] = []
            self.config_vars["model"].set("")
            self.model_combo.set("")
        else:
            default_url = AI_DEFAULT_BASE_URLS.get(provider, "")
            self.base_url_hint.config(text=f"默认: {default_url}")
            # 如果用户没有自定义URL，自动填入默认URL
            if not self.config_vars["base_url"].get():
                self.config_vars["base_url"].set(default_url)
            self.base_url_entry.config(state="normal")

    def _on_model_change(self, event=None) -> None:
        """模型改变时的回调"""
        pass

    def _add_custom_model(self) -> None:
        """手动添加自定义模型"""
        # 创建输入对话框
        input_dialog = tk.Toplevel(self.dialog)
        input_dialog.title("添加自定义模型")
        input_dialog.geometry("350x150")
        input_dialog.resizable(False, False)
        input_dialog.transient(self.dialog)
        input_dialog.grab_set()
        input_dialog.configure(bg="#FFF5F8")

        # 标题
        title_frame = tk.Frame(input_dialog, bg="#FF69B4", height=30)
        title_frame.pack(fill=tk.X)
        title_frame.pack_propagate(False)

        tk.Label(
            title_frame,
            text="➕ 添加自定义模型",
            bg="#FF69B4",
            fg="white",
            font=("Microsoft YaHei", 11, "bold"),
        ).pack(side=tk.LEFT, padx=15, pady=5)

        # 内容
        content_frame = tk.Frame(input_dialog, bg="#FFF5F8")
        content_frame.pack(expand=True, fill=tk.BOTH, padx=20, pady=15)

        tk.Label(
            content_frame,
            text="请输入模型名称:",
            bg="#FFF5F8",
            fg="#5C3B4A",
            font=("Microsoft YaHei", 10),
            anchor="w",
        ).pack(fill=tk.X)

        model_entry = ttk.Entry(content_frame, font=("Microsoft YaHei", 10))
        model_entry.pack(fill=tk.X, pady=(5, 10))
        model_entry.focus()

        # 按钮
        btn_frame = tk.Frame(content_frame, bg="#FFF5F8")
        btn_frame.pack(fill=tk.X)

        def confirm():
            model_name = model_entry.get().strip()
            if not model_name:
                messagebox.showwarning("提示", "请输入模型名称", parent=input_dialog)
                return

            # 添加到当前模型列表
            current_values = list(self.model_combo["values"])
            if model_name not in current_values:
                current_values.append(model_name)
                self.model_combo["values"] = current_values

            # 选中新添加的模型
            self.config_vars["model"].set(model_name)
            self.model_combo.set(model_name)

            input_dialog.destroy()

        tk.Button(
            btn_frame,
            text="✓ 添加",
            bg="#FF69B4",
            fg="white",
            font=("Microsoft YaHei", 10),
            borderwidth=0,
            padx=20,
            pady=5,
            cursor="hand2",
            command=confirm,
        ).pack(side=tk.LEFT, padx=(0, 10))

        tk.Button(
            btn_frame,
            text="✕ 取消",
            bg="#CCCCCC",
            fg="#5C3B4A",
            font=("Microsoft YaHei", 10),
            borderwidth=0,
            padx=20,
            pady=5,
            cursor="hand2",
            command=input_dialog.destroy,
        ).pack(side=tk.LEFT)

        # 回车确认
        input_dialog.bind("<Return>", lambda e: confirm())

    def _save_config(self) -> None:
        """保存配置"""
        try:
            provider = self.config_vars["provider"].get()
            api_key = self.config_vars["api_key"].get().strip()
            base_url = self.config_vars["base_url"].get().strip()

            # 自定义API时必须填写base_url
            if provider == AI_PROVIDER_CUSTOM and not base_url:
                messagebox.showwarning(
                    "提示", "自定义API模式下请填写Base URL", parent=self.dialog
                )
                return

            update_config(
                ai_enabled=self.config_vars["enabled"].get(),
                ai_provider=provider,
                ai_api_key=api_key,
                ai_model=self.config_vars["model"].get().strip(),
                ai_base_url=base_url,
                ai_personality=self.config_vars["personality"].get(),
            )

            # 重新加载AI引擎配置
            if hasattr(self.app, "ai_chat") and self.app.ai_chat:
                self.app.ai_chat.reload_config()

            messagebox.showinfo("成功", "配置已保存！", parent=self.dialog)
            self.dialog.destroy()

        except Exception as e:
            messagebox.showerror("错误", f"保存配置失败: {e}", parent=self.dialog)

    def _test_connection(self) -> None:
        """测试API连接"""
        import threading

        api_key = self.config_vars["api_key"].get().strip()
        provider = self.config_vars["provider"].get()
        model = self.config_vars["model"].get().strip()
        base_url = self.config_vars["base_url"].get().strip()

        if not api_key:
            messagebox.showwarning("提示", "请先输入API密钥", parent=self.dialog)
            return

        if provider == AI_PROVIDER_CUSTOM and not base_url:
            messagebox.showwarning(
                "提示", "自定义API模式下请填写Base URL", parent=self.dialog
            )
            return

        # 设置默认base_url
        if not base_url:
            base_url = AI_DEFAULT_BASE_URLS.get(provider, "")

        def _test():
            try:
                import requests

                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                }

                # Kimi需要特殊处理
                if provider == AI_PROVIDER_KIMI:
                    headers["Authorization"] = f"Bearer {api_key}"
                # 千问需要特殊处理
                elif provider == AI_PROVIDER_QWEN:
                    headers["Authorization"] = f"Bearer {api_key}"

                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": "你好"}],
                    "max_tokens": 10,
                }

                response = requests.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=15,
                )

                if response.status_code == 200:
                    self.dialog.after(
                        0,
                        lambda: messagebox.showinfo(
                            "成功",
                            "连接测试成功！AI功能可以正常使用~",
                            parent=self.dialog,
                        ),
                    )
                elif response.status_code == 401:
                    self.dialog.after(
                        0,
                        lambda: messagebox.showerror(
                            "错误",
                            "API密钥无效，请检查密钥是否正确",
                            parent=self.dialog,
                        ),
                    )
                else:
                    error_text = response.text[:200]
                    self.dialog.after(
                        0,
                        lambda: messagebox.showerror(
                            "错误",
                            f"连接失败 (状态码: {response.status_code}):\n{error_text}",
                            parent=self.dialog,
                        ),
                    )

            except Exception as exc:
                error_message = str(exc)
                self.dialog.after(
                    0,
                    lambda message=error_message: messagebox.showerror(
                        "错误", f"测试连接时出错: {message}", parent=self.dialog
                    ),
                )

        # 显示测试中的提示
        test_window = tk.Toplevel(self.dialog)
        test_window.title("测试连接")
        test_window.geometry("280x120")
        test_window.transient(self.dialog)
        test_window.grab_set()
        test_window.resizable(False, False)
        test_window.configure(bg="#FFF5F8")

        # 标题栏风格
        title_frame = tk.Frame(test_window, bg="#FF69B4", height=30)
        title_frame.pack(fill=tk.X)
        title_frame.pack_propagate(False)

        tk.Label(
            title_frame,
            text="🔗 测试连接",
            bg="#FF69B4",
            fg="white",
            font=("Microsoft YaHei", 11, "bold"),
        ).pack(side=tk.LEFT, padx=15, pady=5)

        # 内容
        content_frame = tk.Frame(test_window, bg="#FFF5F8")
        content_frame.pack(expand=True, fill=tk.BOTH, padx=20, pady=15)

        # 加载动画标签
        loading_label = tk.Label(
            content_frame,
            text="⏳ 正在连接AI服务...",
            bg="#FFF5F8",
            fg="#5C3B4A",
            font=("Microsoft YaHei", 10),
        )
        loading_label.pack()

        # 取消按钮
        btn_cancel = tk.Button(
            content_frame,
            text="✕ 取消",
            bg="#CCCCCC",
            fg="#5C3B4A",
            font=("Microsoft YaHei", 9),
            borderwidth=0,
            padx=15,
            pady=4,
            cursor="hand2",
            command=test_window.destroy,
        )
        btn_cancel.pack(pady=(10, 0))

        def run_test_and_close():
            _test()
            test_window.destroy()

        threading.Thread(target=run_test_and_close, daemon=True).start()
