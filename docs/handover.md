# comic18 项目问题与修复交接

更新日期：2026-07-28  
项目目录：`F:\project\comic18`  
技术栈：Python 3.9、PySide6、requests、SQLite、Tkinter 桌宠

## 交接目标

按本文优先级修复当前项目问题。先处理会造成代码丢失、用户数据丢失、敏感信息泄露和已确认测试失败的问题，再进行结构优化。当前工作区很脏，禁止覆盖或回退用户已有改动。

## P0：先恢复可交付的仓库状态

### 1. 新目录尚未被 Git 跟踪

当前结果：

- `.venv_build` 仍有约 6201 个文件被 Git 跟踪。
- `src/`、`ui/`、`res/`、`tests/`、`script/`、`run.py`、`docs/` 当前被跟踪文件数为 0。
- `git status` 约有 2886 个删除、343 个修改，并包含整套新目录未跟踪项。

处理要求：

1. 先核对旧布局与新布局的对应关系，确认迁移完整。
2. 从 Git 索引移除 `.venv_build`，不要删除用户本地虚拟环境。
3. 将新布局源码、UI、资源、测试和入口纳入版本控制。
4. 将 `data/`、`logs/`、`.tmp_app_icon.png` 加入 `.gitignore`。
5. 不要在未核对迁移完整性前直接提交所有删除项。

## P1：可能造成数据丢失或敏感信息泄露

### 2. 下载失败会删除整本漫画目录

位置：

- `src/jm_app/backend/workers.py:458-462`
- `src/jm_app/backend/workers.py:715-737`

现状：任意章节失败或取消都会调用 `_cleanup_incomplete_album()`，其中对整个 `album_dir` 执行 `shutil.rmtree()`。重试已有下载时，一张图片失败可能删除之前完整下载的章节。

修复要求：

- 每次下载写入独立临时目录或记录本次新建文件。
- 失败时只清理本次临时产物或当前失败章节。
- 完成后使用原子替换/移动生成最终输出。
- 增加测试：已有章节存在时，新章节失败不得删除原文件。

### 3. 运行数据和凭据保存在项目目录或明文配置

位置：

- `src/jm_app/backend/runtime_paths.py:31-35`
- `src/jm_app/backend/runtime_paths.py:195-198`
- `src/jm_app/backend/runtime_paths.py:233-234`
- `src/jm_app/frontend/ui.py:2654`
- `src/jm_app/frontend/ui.py:2677`
- `src/jm_app/frontend/ui.py:2719`

现状：

- 应用数据位于项目内 `data/`，日志位于项目内 `logs/`。
- Cookie 会写入配置和 `data/session/cookies.json`。
- 登录密码仅 base64 编码，可直接恢复明文。
- 桌宠 API Key 也保存在普通 JSON 配置中。

修复要求：

- 开发和打包环境统一迁移至 `%LOCALAPPDATA%\comic18` 或 `%APPDATA%\comic18`。
- 密码/API Key 使用 Windows Credential Manager、DPAPI 或 `keyring`。
- Cookie 文件至少限制为用户目录，并避免重复写入多个配置文件。
- 提供旧数据迁移逻辑，不能直接让现有用户丢失配置和历史。

### 4. 外部超分命令存在命令注入风险

位置：`src/jm_app/backend/library_tools.py:78-88`

现状：用户命令模板和文件路径拼接为字符串后使用 `subprocess.run(..., shell=True)`。

修复要求：

- 改为明确的可执行文件路径和参数数组。
- 校验程序路径与占位参数。
- 不要依赖 Bash quoting；当前环境为 Windows 11 / PowerShell 7。
- 增加包含空格、`&`、括号等 Windows 路径测试。

## P2：已确认的功能和测试问题

### 5. 取消下载不会及时停止

位置：

- `src/jm_app/backend/workers.py:430-447`
- `src/jm_app/backend/workers.py:554-573`

现状：整章图片任务会一次性提交到线程池。取消后主循环抛错，但共享线程池退出时仍等待已提交任务，慢网络下后台会继续运行。

修复要求：

- 取消时停止提交新任务并取消未开始的 futures。
- 明确使用 `shutdown(cancel_futures=True)`。
- 网络下载函数需定期检查取消事件。
- 增加取消延迟测试，避免使用脆弱的固定墙钟阈值。

### 6. “保留图片目录”开关没有效果

位置：

- `ui/settings.ui` 中 `keepImagesCheck`
- `src/jm_app/backend/models.py:66`
- `src/jm_app/frontend/ui.py:8789`

现状：配置会保存和传入 `keep_images`，但 `DownloadWorker` 完全没有读取该字段。

修复要求：

- 图片输出模式始终保留目录。
- ZIP/PDF 成功生成且 `keep_images=False` 时，删除对应临时图片目录。
- ZIP/PDF 失败时必须保留图片作为回退结果。
- 增加三种输出格式和失败回退测试。

### 7. 分类页面按钮 objectName 被覆盖

位置：

- `src/jm_app/frontend/ui.py:3621-3631`
- `src/jm_app/frontend/ui.py:3646-3656`
- `tests/test_comment_cards.py:148-155`
- `tests/test_comment_cards.py:206-215`

现状：代码先通过 `categoryRankOverviewButton`、`categoryRankAllButton` 查找按钮，随后统一改名为 `categoryRankNavOption`。后续 `findChild` 返回 `None`。已确认失败：

`CommentCardTest::test_category_rank_navigation_opens_its_own_page`

修复要求：保留原始 objectName，使用动态属性或公共父容器 QSS 为按钮应用统一样式。

### 8. UI 测试 teardown 没有真正关闭窗口

位置：

- `tests/test_comment_cards.py:39-44`
- `tests/test_appearance_theme.py`
- `tests/test_home_list_view.py`
- `src/jm_app/frontend/ui.py:8143-8171`

现状：测试调用 `MainWindow.close()`，但托盘可见时 `closeEvent` 会忽略关闭并隐藏窗口。测试不断遗留 MainWindow、QTimer 和后台对象，完整套件运行极慢。

修复要求：

- 建立统一 `tests/conftest.py` 或 unittest fixture。
- 测试模式禁用托盘、自动登录、桌宠和后台恢复任务。
- teardown 设置允许最终关闭，执行 `close()`、`deleteLater()` 和必要的事件处理。
- 统一调用 `script.downloader.ensure_qt_plugin_path()`。
- CI/本地测试禁用无关 pytest 插件自动加载，或提供固定的测试启动脚本。

## P3：结构与工程优化

### 9. `frontend/ui.py` 仍是超大主窗口

当前约 12016 行，`MainWindow` 同时承担页面构建、导航、登录、设置、缓存、下载、历史、阅读器和退出生命周期。

优化方向：

- 继续按现有 `frontend/pages/`、`frontend/controllers/` 模式拆分。
- 优先迁移下载状态机、设置持久化、分类页面、关闭生命周期。
- 新模块需要有独立单元测试，避免继续依赖完整 MainWindow。

### 10. 异常处理过宽

`src/` 当前约有 137 处 `except Exception`。部分是线程边界所需，但也有大量静默忽略。

优化方向：收窄异常类型；用户可恢复错误与程序错误分开；程序错误至少记录 traceback 和上下文。

### 11. 退出依赖 `os._exit`

位置：

- `src/jm_app/main.py:46`
- `src/jm_app/frontend/ui.py:1866-1873`

优化方向：先修复 QThread、线程池和桌宠子进程的生命周期，再将 `os._exit` 降级为明确超时后的最终兜底。

### 12. 依赖、测试配置和文档不可复现

现状：

- 根目录没有 `pyproject.toml`、`pytest.ini`、锁文件或 CI 配置。
- `requirements.txt` 只有最低版本，没有上限或锁定版本。
- README 仍描述旧的 `downloader.py`、`assets/`、`jm_app/` 布局；实际入口是 `run.py`，源码在 `src/`，资源在 `res/assets/`。
- README 还存在多余的 Markdown 代码块结束标记。

优化方向：增加开发依赖与固定测试命令；加入 Ruff/格式检查；更新安装、运行、测试和打包文档。

## 已完成验证

以下命令已验证通过：

```powershell
python -m compileall -q src script run.py

$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python -m unittest discover -s tests -p test_download_performance.py -v
python -m unittest discover -s tests -p test_local_download_page.py -v
```

结果：下载性能测试 5/5、本地下载页测试 2/2 通过。

完整测试使用以下方式收集到 121 项：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python -c 'import script.downloader as d; d.ensure_qt_plugin_path(); import pytest; raise SystemExit(pytest.main(["-x", "-vv", "tests"]))'
```

首个确认失败为分类按钮 objectName 问题；同时完整测试因窗口未释放而执行极慢。

## 建议实施顺序

1. 保护现有工作区，整理 Git 索引和忽略规则。
2. 修复下载失败删除整本目录，并补数据保护测试。
3. 修复分类按钮 objectName 和测试窗口释放，先恢复可信测试反馈。
4. 实现快速取消和 `keep_images` 行为。
5. 迁移运行数据与凭据。
6. 移除 `shell=True`。
7. 拆分 MainWindow、收窄异常、治理退出流程。
8. 补齐依赖锁定、CI 和 README。

每完成一阶段都运行相关单测；不要在测试未通过时批量进行无关重构。
