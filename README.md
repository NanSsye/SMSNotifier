# 🔔 微信离线通知插件 (SMSNotifier)

> 📱 通过 PushPlus 向微信离线用户发送通知，随时掌握微信在线状态！
> **本插件是 [XYBotv2](https://github.com/HenryXiaoYang/XYBotv2) 的一个插件。**

 <img src="https://github.com/user-attachments/assets/a2627960-69d8-400d-903c-309dbeadf125" width="400" height="600">

## ✨ 功能特点

- 🔄 **实时监控** - 自动检测微信账号的在线状态
- 📲 **即时通知** - 当微信账号离线时立即发送提醒
- 📋 **多渠道支持** - 支持微信公众号、短信、邮件等多种通知方式
- 🎨 **自定义模板** - 可自定义通知的标题和内容样式
- 🔍 **状态查询** - 随时查看监控状态和离线用户列表
- 🧪 **测试功能** - 支持发送测试通知验证配置正确性
- 💻 **远程管理** - 通过微信命令远程控制监控设置
- 🛡️ **权限控制** - 仅限管理员操作，保障系统安全

## 📋 使用指南

### 基本命令

发送测试通知：

```
sms_test
```

查看监控状态：

```
sms_status
```

重新加载配置：

```
sms_reload
```

### 监控管理

设置当前微信 ID：

```
sms_set_wxid wxid_xxxxxxxx
```

添加监控用户：

```
sms_monitor wxid_xxxxxxxx 接收者ID
```

移除监控用户：

```
sms_unmonitor wxid_xxxxxxxx
```

### 通知设置

更改通知渠道：

```
sms_channel wechat
```

支持的渠道：wechat, sms, mail, webhook, cp

设置消息模板：

```
sms_template title 新标题模板
sms_template content 新内容模板
```

### 测试和诊断

测试心跳状态：

```
sms_heartbeat
```

或指定微信 ID：

```
sms_heartbeat wxid_xxxxxxxx
```

## ⚙️ 配置说明

在`config.toml`中设置：

```toml
[basic]
# 是否启用插件
enable = true
# 是否启用调试模式
debug = false
# 当前微信ID
current_wxid = "wxid_xxxxxxxx"

[pushplus]
# PushPlus令牌
token = "your_pushplus_token"
# 通知渠道：wechat(微信公众号)、sms(短信)、mail(邮件)、webhook、cp(企业微信)
channel = "wechat"
# 消息模板
template = "html"
# 群组编码，不填仅发送给自己
topic = ""

[notification]
# 检查间隔，单位:秒
check_interval = 300
# 短信发送失败重试次数
retry_times = 3
# 重试间隔，单位:秒
retry_interval = 60
# 心跳失败阈值
heartbeat_threshold = 3

[message]
# 通知标题模板
title_template = "⚠️ 微信离线通知 - {time}"
# 测试通知标题模板
test_title_template = "📱 测试通知 - {time}"

# 通知文字内容
[message.notification_text]
title = "⚠️ 微信离线通知"
content = "您的微信账号 <b>{wxid}</b> 已于 <span style=\"color:#ff4757;font-weight:bold;\">{time}</span> 离线"
note = "请尽快检查您的设备连接状态或重新登录。"

# 测试通知文字内容
[message.test_text]
title = "📱 测试通知"
content = "这是一条测试消息，验证通知功能是否正常。"
account = "监控账号: <b>{wxid}</b>"
time = "发送时间: <span style=\"color:#2196f3;\">{time}</span>"
```

### 模板变量说明

可在标题和内容模板中使用以下变量：

- `{wxid}` - 微信 ID
- `{time}` - 当前时间（格式：YYYY-MM-DD HH:MM:SS）
- `{date}` - 当前日期（格式：YYYY-MM-DD）
- `{hour}` - 当前时间（格式：HH:MM）
- `{bot_name}` - 机器人名称
- `{bot_wxid}` - 机器人微信 ID

## 🔒 安全性注意事项

- 仅向可信任的管理员提供访问权限
- 遵循最小权限原则，仅监控必要的微信账号
- 通知内容中避免包含敏感信息
- 定期检查监控状态，确保系统稳定运行

## 📊 适用场景

- 微信机器人服务状态监控
- 重要微信账号的在线状态监控
- 企业服务提醒系统
- 关键业务流程中断预警
- 远程服务器微信应用健康检查

## 🚀 快速设置流程

1. 注册[PushPlus](http://www.pushplus.plus/)账号并获取 token
2. 将 token 填入 config.toml 配置文件
3. 设置当前微信 ID：`sms_set_wxid wxid_xxxxxxxx`
4. 发送测试通知验证配置：`sms_test`
5. 当配置无误后，微信离线时将自动接收通知

## 📝 开发日志

- v1.1.0: 优化心跳检测逻辑，提高稳定性
- v1.0.0: 初始版本发布，支持基本的离线通知功能

## 👨‍💻 作者

**老夏的金库** ©️ 2024

**开源不易，感谢打赏支持！**
![image](https://github.com/user-attachments/assets/2dde3b46-85a1-4f22-8a54-3928ef59b85f)

## �� 许可证

MIT License
