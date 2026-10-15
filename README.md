# comic18

`comic18` 是一个 Windows 桌面漫画浏览、下载与本地阅读工具。主界面使用 PySide6，包含首页、分类、每周必看、搜索、详情、评论、收藏、阅读历史与下载管理；应用也可启动内置 Ameath 桌宠。

> 本项目仅用于个人学习与技术研究。请遵守所在地法律、目标站点规则及版权要求，只处理你有权访问和使用的内容。

## 功能

- 漫画列表渐进加载、封面惰加载与滚动追加。
- 搜索、分类、每周必看、详情、评论、收藏和阅读历史。
- 图片、ZIP/CBZ、PDF 输出，支持取消、重试、并发下载和本地阅读。
- Cookie、代理、DoH、API/图片分流与测速设置。
- 浅色/深色主题、可收起侧边栏和系统托盘。
- Ameath 桌宠、AI 对话、翻译、音乐、番茄钟及可选 CosyVoice 语音。

## 环境

- Windows 10/11
- Python 3.9 或更高版本
- `pip`

安装运行依赖：

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 运行

在项目根目录执行：

```powershell
python .\run.py
```

实际启动链为 `run.py` → `script/downloader.py` → `src/jm_app/main.py`。

## 数据目录

设置、数据库、会话和日志保存在当前 Windows 用户目录：

```text
%LOCALAPPDATA%\comic18
```

旧版本项目目录内的 `data/`、`logs/` 和会话数据会在首次运行时安全迁移。下载目录仍可在设置中自定义；新安装默认使用 `%LOCALAPPDATA%\comic18\downloads`，已有项目下的 `commies/` 会继续原位使用且不会纳入 Git。

登录密码和桌宠 AI API Key 使用 Windows DPAPI 加密，密文只能由当前 Windows 用户解密。Cookie 只保存在用户数据目录，不再重复写入普通设置 JSON。

## 项目结构

```text
comic18/
├── run.py                         # 主入口
├── script/
│   ├── downloader.py              # Qt 环境与启动编排
│   └── run_tests.py               # 可复现测试入口
├── src/
│   ├── jm_app/
│   │   ├── main.py                # PySide6 应用启动
│   │   ├── backend/               # API、下载、缓存、存储与运行路径
│   │   │   └── jm_endpoints.py    # JM 域名、接口路径与媒体 URL 唯一配置源
│   │   ├── tasks/                 # 可取消后台任务与文件维护 Worker
│   │   └── frontend/              # 主窗口、页面、控制器、生命周期与阅读器
│   └── desktop_pet/                # Ameath 桌宠
├── ui/                             # Qt Designer UI 文件
├── res/assets/                     # 主应用资源
├── tests/                          # 单元与 UI 测试
├── docs/                           # 交接和工程文档
├── requirements.txt                # 运行依赖
└── requirements-dev.txt            # 测试依赖
```

## 测试

安装测试依赖：

```powershell
python -m pip install -r requirements-dev.txt
```

运行完整测试：

```powershell
python .\script\run_tests.py
```

提交前运行严格模式。该模式在测试文件进程发生 Qt 原生崩溃时立即失败，不使用逐用例重试掩盖问题：

```powershell
python .\script\run_tests.py --strict-file-process -q
```

运行指定文件或用例：

```powershell
python .\script\run_tests.py tests/test_download_performance.py -v
python .\script\run_tests.py tests/test_comment_cards.py -k category -v
```

测试入口会统一设置 `PYTHONPATH`、Qt 插件路径、offscreen 平台和 `COMIC18_TESTING=1`，并关闭无关 pytest 插件自动加载。

运行关键静态检查：

```powershell
python -m ruff check .
python -m compileall -q src script run.py
```

## 维护约定

- JM Web 域名、App API 域名、接口路径和媒体路径统一维护在 `src/jm_app/backend/jm_endpoints.py`，不要在页面或 Worker 中新增地址字面量。
- `frontend/ui.py` 负责窗口编排；网络、缓存和本地文件 Worker 放在 `src/jm_app/tasks/`，退出清理由 `frontend/lifecycle.py` 统一管理。
- 新增后台任务时，应接入生命周期控制器的任务枚举并补独立单元测试，避免只依赖完整窗口测试。
- 日常测试可使用默认隔离恢复模式；发布、合并和 CI 必须使用 `--strict-file-process`。

## 桌宠 AI

在桌宠 AI 设置中选择服务商、模型和服务地址，并填写 API Key。非敏感配置保存在：

```text
%LOCALAPPDATA%\comic18\desktop_pet.json
```

API Key 不写入该 JSON，而是使用 DPAPI 加密后保存到：

```text
%LOCALAPPDATA%\comic18\desktop_pet_credentials.json
```

### CosyVoice

默认配置位于 `src/desktop_pet/config/cosyvoice.yaml`。密钥建议通过环境变量提供：

```powershell
$env:DASHSCOPE_API_KEY = "your-dashscope-api-key"
$env:COSYVOICE_VOICE_ID = "your-cosyvoice-voice-id"
$env:COSYVOICE_MODEL = "cosyvoice-v3.5-plus"
```

也可创建不会提交到 Git 的本地配置 `src/desktop_pet/config/cosyvoice.local.yaml`。

## 常见问题

### 下载或详情加载失败

在设置页依次检查测速结果、API/图片分流、DoH、代理和 Cookie。转换 ZIP/CBZ/PDF 失败时，程序会保留完整图片目录作为回退结果。

### 取消下载后仍有短暂网络活动

取消会立即停止提交新图片、取消未开始任务并通知正在传输的请求退出。极少数正处于系统网络调用中的请求可能需要等待当前连接返回，但不会删除此前完整下载的章节。

### AI 对话或语音不可用

确认 API Key、服务地址和模型匹配。CosyVoice 还需要有效的 `DASHSCOPE_API_KEY` 与 `COSYVOICE_VOICE_ID`，修改后应完全退出并重启应用。

## 致谢

桌宠模块基于 [Ameath](https://gitee.com/lzy-buaa-jdi/ameath) 二次开发。感谢相关开源项目作者。
