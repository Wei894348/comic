# JM 漫画下载器

这是一个 Python + Qt 漫画下载器。界面已改为“先登录，再进入下载器”的结构，主界面包含左侧导航、漫画检索、章节选择、下载队列、下载中和已完成页面。

## 安装

```powershell
pip install -r requirements.txt
```

## 运行

```powershell
python .\jm_qt_downloader.py
```

## 使用流程

1. 在登录页输入账号和密码。
2. 如果站点要求安全验证，请在系统浏览器完成登录/验证后，把请求 Cookie 粘贴到登录页或设置页。
3. 进入主页后，可以按列表页抓取漫画，也可以输入 JM ID 或 album 链接。
4. 选择漫画后点击“加载章节”，可勾选单集、多集，或全选章节。
5. 点击“加入队列”，再到“队列中”页面点击“开始下载队列”。
6. 每一集下载完成后会单独生成一个 PDF，例如 `001-第1集.pdf`、`002-第2集.pdf`。

## 代码结构

```text
jm_qt_downloader.py      # 启动入口
jm_app/
  constants.py           # 站点地址、默认 User-Agent
  models.py              # 漫画、章节、网络配置、下载配置
  utils.py               # ID、Cookie、安全验证页等通用工具
  parsers.py             # 列表页、详情页、章节、图片链接解析
  pdf_utils.py           # 图片转 PDF
  http_client.py         # requests 会话、限速、重试、403/429 处理
  workers.py             # Qt 后台采集、章节加载、下载线程
  ui.py                  # 登录页、侧边栏主界面、队列和完成页
  main.py                # QApplication 初始化
```

## 说明

程序不会绕过安全验证、破解验证码、使用代理池或对抗站点风控。若请求返回安全验证页、`403` 或 `429`，请暂停并在系统浏览器完成验证后复制 Cookie。
