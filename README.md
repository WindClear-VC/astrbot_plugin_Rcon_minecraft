# Rcon Minecraft插件

通过 RCON 协议连接 Minecraft 服务器，支持多服务器管理、AI 自然语言控制、定时任务、性能监控与完整玩家管理。

## 功能

- `/mc status` — 查看服务器综合状态（在线玩家、世界种子、时间、天气、难度）
- `/mc players` — 查看在线玩家列表
- `/mc servers` — 列出所有配置的服务器
- `/mc use <服务器名>` — 切换默认服务器
- `/mc monitor` — 性能监控（TPS/内存/实体）
- `/mc whitelist` — 白名单管理（查看/添加/移除）
- `/mc ban / unban / banlist / kick` — 封禁与踢人
- `/mc op / deop / op list` — OP 管理
- `/mc gamemode / time / weather / difficulty` — 游戏控制
- `/mc give / tp / kill` — 物品与传送
- `/mc announce <消息>` — 全服公告
- `/mc backup` — 手动备份（save-all）
- `/mc batch give <物品> [数量]` — 批量给所有在线玩家发物品
- `/mc ai <自然语言>` — AI 自然语言执行指令
- `/mc cmd <指令>` — 执行任意服务端指令
- `/mc help` — 完整帮助
- `/mc bridge on|off|status` — QQ 与 MC 聊天桥接开关与状态

## 安装

1. 确保 Minecraft 服务器已启用 RCON：
   ```properties
   # server.properties
   enable-rcon=true
   rcon.password=你的密码
   rcon.port=25575
   ```

2. 将插件文件夹复制到 AstrBot 的 `data/plugins/` 目录。

3. 在 AstrBot WebUI 中启用插件，并填写 RCON 配置。

## 配置说明

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| 启用 RCON 连接 | 是否启用 MC 插件 | `true` |
| RCON 服务器地址 | MC 服务器 IP（兼容旧版） | `127.0.0.1` |
| RCON 端口 | RCON 端口（兼容旧版） | `25575` |
| RCON 密码 | 服务端 RCON 密码（兼容旧版） | 必填 |
| RCON 超时时间 | 连接超时（秒） | `10` |
| 默认服务器名称 | 默认目标服务器 | `default` |
| 仅管理员可执行指令 | 限制使用权限 | `true` |
| 多服务器配置 | 可配置多个服务器 | `[]` |
| 启用自动备份 | 定时执行 save-all | `false` |
| 自动备份间隔 | 备份间隔（分钟） | `60` |
| 启用自动公告 | 定时发送公告 | `false` |
| 公告间隔 | 公告发送间隔（分钟） | `30` |
| 公告内容列表 | 循环发送的公告 | `[]` |
| 启用性能监控 | 允许查看 TPS/内存 | `false` |
| 启用 AI 自然语言控制 | 允许 /mc ai | `true` |
| 启用 QQ ↔ MC 聊天桥接 | 允许 QQ 群与 MC 聊天互通 | `false` |
| QQ -> MC 转发 | 允许 QQ 群消息转发到 MC | `true` |
| MC -> QQ 转发 | 允许 MC 聊天转发到 QQ 群 | `true` |
| 桥接 TCP 监听地址 | MC 插件连接地址 | `127.0.0.1` |
| 桥接 TCP 监听端口 | MC 插件连接端口 | `25576` |
| 目标 QQ 群号 | 转发目标群号，空则使用触发群 | `""` |
| QQ -> MC 消息格式 | 消息格式：{nick} {msg} | `[QQ]{nick}: {msg}` |
| MC -> QQ 消息格式 | 消息格式：{player} {msg} | `[MC]{player}: {msg}` |

### 多服务器配置示例

在 WebUI 的 `多服务器配置` 字段中填写 JSON 数组：

```json
[
  {"name": "survival", "host": "127.0.0.1", "port": 25575, "password": "密码1"},
  {"name": "creative", "host": "192.168.1.100", "port": 25575, "password": "密码2"}
]
```

## 使用

| 指令 | 说明 |
|------|------|
| `/mc help` | 查看完整帮助 |
| `/mc status` | 查看服务器状态 |
| `/mc players` | 查看在线玩家 |
| `/mc servers` | 列出所有服务器 |
| `/mc use survival` | 切换到 survival 服务器 |
| `/mc monitor` | 查看性能监控 |
| `/mc whitelist add Xaunli` | 添加白名单 |
| `/mc ban Xaunli 违规` | 封禁玩家 |
| `/mc kick Xaunli 请文明游戏` | 踢出玩家 |
| `/mc op Xaunli` | 给予 OP |
| `/mc gamemode creative Xaunli` | 切换创造模式 |
| `/mc time set day` | 设置白天 |
| `/mc weather clear 600` | 晴天 10 分钟 |
| `/mc give Xaunli diamond 64` | 给 64 个钻石 |
| `/mc tp Xaunli 100 64 100` | 传送到坐标 |
| `/mc announce 服务器将在 10 分钟后维护` | 全服公告 |
| `/mc backup` | 手动备份 |
| `/mc batch give diamond 1` | 给所有在线玩家 1 个钻石 |
| `/mc ai 把所有在线玩家传送到出生点` | AI 执行指令 |
| `/mc cmd <指令>` | 执行任意指令 |
| `/mc bridge on` | 开启 QQ ↔ MC 聊天桥接 |
| `/mc bridge off` | 关闭 QQ ↔ MC 聊天桥接 |
| `/mc bridge status` | 查看桥接状态 |

## 依赖

- `mcrcon>=0.4.0`

## 注意事项

- RCON 密码明文存储于 AstrBot 配置中，请确保网络环境安全。
- `/mc stop` 会直接停止服务器，请谨慎使用。
- AI 指令执行依赖 LLM 提供商，请确保已配置可用的聊天模型。
- 多服务器模式下，未指定 `use` 时默认使用 `default_server` 配置的服务器。

## License

AGPL-3.0
