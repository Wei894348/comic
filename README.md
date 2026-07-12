# comic18

`comic18` 是一个 Windows 桌面漫画下载与本地阅读工具，使用 PyQt5 提供搜索、详情查看、章节选择、任务队列、下载历史和本地阅读体验；应用启动时还会一并启动内置的 Ameath 桌宠，提供 AI 对话、语音播报、音乐、翻译和番茄钟等辅助功能。

> 本项目仅用于个人学习与技术研究。请遵守所在地法律、目标站点规则及版权要求；下载、缓存或导出的内容仅限拥有合法访问与使用权的资源。

## 功能概览

### 漫画下载器

- 搜索、榜单浏览与漫画详情查看，支持章节选择后加入下载队列。
- 支持图片、ZIP、PDF 三种下载输出，并可按章节生成 PDF。
- 支持多个下载任务并发执行、进度展示、取消和重试。
- 支持 Cookie、代理、并发数、下载目录和阅读方式等设置。
- 内置在线阅读与本地阅读，支持滚动/翻页、阅读缓存和历史记录。
- 支持缓存导出、Cookie 校验、封面域名池与会话持久化。

### Ameath 桌宠

- 随主程序启动，也可通过托盘菜单控制显示、隐藏或退出。
- 支持点击互动、动画状态、鼠标跟随、缩放、透明度与鼠标穿透。
- 支持 AI 聊天及划词翻译，可配置 DeepSeek、OpenAI、千问、智谱 GLM、Kimi、豆包或兼容 OpenAI 接口的服务。
- 支持本地互动语音；配置 DashScope CosyVoice 后，AI 回复可合成语音播放。
- 支持背景音乐、番茄钟、作息提醒、全局快捷键和指定程序快速启动。

## 技术栈

| 类别 | 使用技术 |
| --- | --- |
| 桌面界面 | Python、PyQt5、PyQtWebEngine |
| 下载与解析 | requests、BeautifulSoup4、lxml、jmcomic |
| 图片与文档 | Pillow、pypdfium2 |
| 桌宠与系统集成 | Tkinter、pystray、pygame、pywin32、pyperclip |
| AI 与语音 | OpenAI 兼容 Chat Completions、DashScope CosyVoice、PyYAML |
| 本地服务与打包 | FastAPI、Uvicorn、PyInstaller |

## 项目结构

```text
comic18/
├── downloader.py                 # 程序入口；根据参数启动下载器或桌宠
├── jm_fastapi_backend.py         # FastAPI 服务入口
├── JM下载器.spec                  # PyInstaller 打包配置
├── requirements.txt              # 根项目依赖
├── assets/                       # 下载器图标、启动动画和阅读器资源
├── jm_app/
│   ├── main.py                   # PyQt 应用启动，负责拉起桌宠进程
│   ├── desktop_pet_launcher.py   # 桌宠子进程生命周期管理
│   ├── backend/                  # 接口访问、下载任务、缓存、Cookie、PDF 与运行路径
│   └── frontend/                 # 主窗口、登录页、阅读器、弹窗与启动页
├── desktop_pet/
│   ├── main.py                   # 桌宠独立入口
│   ├── config/                   # 可提交的默认 CosyVoice 配置
│   ├── assets/                   # 动画、图标、互动语音和音乐资源
│   └── src/
│       ├── ai/                   # 对话引擎、人格与 AI 配置窗口
│       ├── animation/            # GIF 解码、缓存与动画管理
│       ├── behavior/             # 行为模式、移动与提醒
│       ├── core/                 # 桌宠主窗口和状态管理
│       ├── interaction/          # 点击与拖动交互
│       ├── media/                # 音乐、互动语音与 CosyVoice 播放
│       ├── platform/             # 托盘、热键和 Windows 系统能力
│       ├── productivity/         # 番茄钟
│       ├── translate/            # 划词翻译
│       └── ui/                   # 气泡、快捷菜单、聊天和音乐面板
└── JM下载器数据/                  # 开发运行产生的数据，已被 Git 忽略
```

## 环境要求

- Windows 10/11。
- Python 3.9 或更高版本（项目现有打包环境为 Python 3.9.13）。
- `pip` 可用；打包时额外需要 `PyInstaller`。
- 在线搜索、下载、AI 对话和 CosyVoice 需要可用的网络连接。

## 安装与运行

在项目根目录执行：

```powershell
cd F:\project\comic18
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python .\downloader.py
```

程序启动后会显示下载器窗口，并自动启动桌宠。仅启动桌宠时可执行：

```powershell
python .\downloader.py --desktop-pet
```

首次使用下载器时，直接跳过登录即可。



### 桌宠 AI 对话

在桌宠托盘菜单或 AI 对话界面打开 AI 配置，填写以下内容并启用 AI：

- 服务商与模型，例如 DeepSeek 的 `deepseek-chat`。
- API Key。
- 服务地址。内置服务商会提供默认地址；自定义兼容接口时填写其 `base_url`。

桌宠配置保存在当前 Windows 用户目录：

```text
%APPDATA%\ameath_config.json
```


### CosyVoice AI 语音

仓库提交的默认配置是 [desktop_pet/config/cosyvoice.yaml](desktop_pet/config/cosyvoice.yaml)，默认关闭且不包含密钥。启用 AI 语音有两种方式。

方式一：在 `desktop_pet/config/` 新建本地文件 `cosyvoice.local.yaml`。该文件已被 `.gitignore` 忽略：

```yaml
cosyvoice:
  enabled: true
  api_key: "your-dashscope-api-key"
  voice_id: "your-cosyvoice-voice-id"
  model: "cosyvoice-v3.5-plus"
```

方式二：设置系统或当前终端环境变量：

```powershell
$env:DASHSCOPE_API_KEY = "your-dashscope-api-key"
$env:COSYVOICE_VOICE_ID = "your-cosyvoice-voice-id"
$env:COSYVOICE_MODEL = "cosyvoice-v3.5-plus"
```

环境变量优先于 YAML 配置。修改 CosyVoice 配置后请完全退出并重新启动下载器/桌宠；若只需桌宠点击音效，则无需配置 CosyVoice，本地 `desktop_pet/assets/voice/` 中的 wav 文件会直接播放。

```

## 常见问题

### AI 对话没有声音

确认 `cosyvoice.local.yaml` 或环境变量同时提供了有效的 `DASHSCOPE_API_KEY` 与 `COSYVOICE_VOICE_ID`，并且配置中的 `enabled` 为 `true`。打包版也需要把本地配置放在 `JM下载器.exe` 同级的 `desktop_pet/config/` 目录，或设置系统环境变量后重启程序。

### 点击桌宠没有互动语音

先检查系统音量和输出设备；再确认打包目录中存在 `desktop_pet/assets/voice/`。互动语音使用本地 wav 文件，与 AI API 配置无关。

### 下载或详情加载失败

检查网络、Cookie 是否有效、代理地址是否可用；可以在设置页面重新保存 Cookie，或通过 Cookie 校验功能更新会话。

## 致谢

桌宠模块基于 [Ameath](https://gitee.com/lzy-buaa-jdi/ameath) 二次开发。感谢原项目及本项目所使用的开源依赖作者。
