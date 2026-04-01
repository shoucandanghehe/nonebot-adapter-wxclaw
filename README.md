<div align="center">

# NoneBot Adapter WxClaw

_✨ 基于 openclaw-weixin 协议的 NoneBot2 微信智能体适配器 ✨_

[![License](https://img.shields.io/github/license/shoucandanghehe/nonebot-adapter-wxclaw)](https://github.com/shoucandanghehe/nonebot-adapter-wxclaw)
[![PyPI](https://img.shields.io/pypi/v/nonebot-adapter-wxclaw)](https://pypi.org/project/nonebot-adapter-wxclaw/)
[![Python](https://img.shields.io/pypi/pyversions/nonebot-adapter-wxclaw)](https://pypi.org/project/nonebot-adapter-wxclaw/)
[![NoneBot](https://img.shields.io/badge/nonebot-2.5.0+-red)](https://nonebot.dev/)

</div>

---

基于 [`@tencent-weixin/openclaw-weixin`](https://www.npmjs.com/package/@tencent-weixin/openclaw-weixin) 协议实现的 [NoneBot2](https://nonebot.dev/) 适配器，用于对接微信智能体（企微客服 iLink 通道）。

## 📦 安装

### nb-cli（推荐）

```bash
nb adapter install nonebot-adapter-wxclaw
```

### uv

```bash
uv add nonebot-adapter-wxclaw
```

### PDM

```bash
pdm add nonebot-adapter-wxclaw
```

### Poetry

```bash
poetry add nonebot-adapter-wxclaw
```

### pip（不推荐）

```bash
pip install nonebot-adapter-wxclaw
```

> **注意**: 本适配器需要支持 HTTP 客户端类型的驱动器。请参阅 [NoneBot 驱动器文档](https://nonebot.dev/docs/advanced/driver) 选择并安装合适的驱动器。

## ⚙️ 配置

在 NoneBot 项目的 `.env` 或环境变量中配置：

```env
DRIVER=~xxx  # 需要 HTTP 客户端类型的驱动器，参阅 https://nonebot.dev/docs/advanced/driver

# 账号列表（JSON 数组）
WXCLAW_ACCOUNTS='[{"account_id": "你的bot_id", "token": "你的token", "base_url": "https://ilinkai.weixin.qq.com"}]'
```

### 配置项

| 配置项 | 类型 | 默认值 | 说明 |
|:-------|:-----|:-------|:-----|
| `wxclaw_accounts` | `list[WxClawAccountInfo]` | `[]` | 账号列表 |
| `wxclaw_ilink_app_id` | `str` | `"bot"` | iLink App ID |
| `wxclaw_channel_version` | `str` | `"2.1.1"` | 通道版本号 |
| `wxclaw_long_poll_timeout` | `int` | `35000` | 长轮询超时（毫秒） |
| `wxclaw_api_timeout` | `int` | `15000` | API 请求超时（毫秒） |
| `wxclaw_cdn_base_url` | `str` | `"https://novac2c.cdn.weixin.qq.com/c2c"` | CDN 基础 URL |

### 账号配置 (`WxClawAccountInfo`)

| 字段 | 类型 | 默认值 | 说明 |
|:-----|:-----|:-------|:-----|
| `account_id` | `str` | _必填_ | Bot ID |
| `token` | `str` | `""` | 认证 Token（可通过 QR 登录获取） |
| `base_url` | `str` | `"https://ilinkai.weixin.qq.com"` | API 基础 URL |
| `enabled` | `bool` | `True` | 是否启用 |

## 🚀 快速开始

### 📝 基本回复

```python
from nonebot import on_message
from nonebot.adapters.wxclaw import TextMessageEvent

echo = on_message()

@echo.handle()
async def handle_echo(event: TextMessageEvent):
    await echo.send(event.get_message())
```

### 🖼️ 发送媒体

```python
from nonebot import on_command
from nonebot.adapters.wxclaw import Bot, ImageMessageEvent

send_img = on_command("img")

@send_img.handle()
async def handle_send_img(bot: Bot, event: ImageMessageEvent):
    # 发送图片
    await bot.send_image(event.from_user_id, b"<image bytes>")

    # 发送文件
    await bot.send_file(event.from_user_id, b"<file bytes>", "report.pdf")

    # 发送视频
    await bot.send_video(event.from_user_id, b"<video bytes>")
```

### 🔐 QR 码登录

适配器支持在插件中发起扫码登录，无需预先配置 token：

```python
from nonebot import on_command
from nonebot.adapters.wxclaw import Adapter

login = on_command("login")

@login.handle()
async def handle_login():
    adapter = Adapter.get_adapter()  # type: ignore

    async with adapter.qr_login(auto_connect=True) as session:
        # session.qrcode_url 是二维码图片 URL，展示给用户扫描
        print(f"请扫描二维码: {session.qrcode_url}")

        # 等待扫描确认
        result = await session.wait()

        if result.connected:
            print(f"登录成功! account_id={result.account_id}")
        else:
            print(f"登录失败: {result.message}")
```

设置 `auto_connect=True` 后，登录成功会自动注册 Bot 并开始消息轮询。

## 📨 支持的消息类型

### 接收

| 事件类型 | 类 | 说明 |
|:---------|:-----|:-----|
| 文本消息 | `TextMessageEvent` | 纯文本消息 |
| 图片消息 | `ImageMessageEvent` | 包含 `image_item` |
| 语音消息 | `VoiceMessageEvent` | 包含 `voice_item` |
| 文件消息 | `FileMessageEvent` | 包含 `file_item` |
| 视频消息 | `VideoMessageEvent` | 包含 `video_item` |

### 发送

| 类型 | 方法 | 说明 |
|:-----|:-----|:-----|
| 文本 | `bot.send_text()` | 发送纯文本 |
| 图片 | `bot.send_image()` | 上传并发送图片 |
| 文件 | `bot.send_file()` | 上传并发送文件 |
| 视频 | `bot.send_video()` | 上传并发送视频 |

> **注意**: 上游协议不支持发送语音消息和引用回复。接收到的语音和引用消息可以正常解析，但无法通过 Bot 发送。

### 🔄 转发媒体

图片的 CDN 引用可以直接转发，无需重新上传：

```python
@matcher.handle()
async def handle_forward(bot: Bot, event: ImageMessageEvent):
    await bot.send(event, event.get_message())
```

文件和视频的 CDN 引用**不可直接转发**（服务器会静默丢弃），需先通过 `bot.fetch_media()` 下载后再发送：

```python
@matcher.handle()
async def handle_forward(bot: Bot, event: FileMessageEvent):
    msg = await bot.fetch_media(event.get_message())
    await bot.send(event, msg)
```

`fetch_media()` 也可用于下载图片内容进行本地处理：

```python
msg = await bot.fetch_media(event.get_message())
for seg in msg:
    if seg.data.get("content"):
        raw_bytes = seg.data["content"]
```

## 🧩 消息段

```python
from nonebot.adapters.wxclaw import MessageSegment

# 文本
MessageSegment.text("Hello")

# 图片（从 CDN 媒体引用构建）
MessageSegment.image(media=cdn_media)

# 文件
MessageSegment.file(media=cdn_media, file_name="doc.pdf")

# 视频
MessageSegment.video(media=cdn_media)
```

## 📡 Bot API

所有 API 方法通过 NoneBot 的 `call_api` 钩子系统路由，支持中间件拦截：

| 方法 | 说明 |
|:-----|:-----|
| `bot.get_updates()` | 长轮询获取消息 |
| `bot.send_message(msg=...)` | 发送原始协议消息 |
| `bot.send_typing(to_user_id=...)` | 发送正在输入状态 |
| `bot.get_config(user_id=...)` | 获取会话配置 |
| `bot.get_upload_url(req=...)` | 获取 CDN 上传地址 |
| `bot.download_media(media)` | 下载并解密 CDN 媒体 |
| `bot.fetch_media(message)` | 下载消息中所有 CDN 媒体到本地 bytes |
| `bot.prepare_and_upload_file(...)` | 加密并上传文件到 CDN |

## 🛠️ 开发

```bash
# 安装开发依赖
uv sync --group dev

# 运行测试
uv run pytest tests/

# 代码检查
uv run ruff check nonebot/ tests/
uv run ruff format nonebot/ tests/

# 类型检查
uv run basedpyright nonebot/
```

## 许可证

本项目尚未设置许可证。
