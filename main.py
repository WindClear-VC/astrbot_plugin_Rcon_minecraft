"""
Xaunli Spark Bot Minecraft 插件
通过 RCON 协议连接 Minecraft 服务器，实现状态查询、玩家管理和指令执行。
支持多服务器、AI 自然语言控制、定时任务、性能监控、QQ↔MC 聊天桥接。
"""

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger


@dataclass
class MCConfig:
    """单个服务器配置"""
    name: str
    host: str = "127.0.0.1"
    port: int = 25575
    password: str = ""


class MinecraftPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

        # 兼容新旧版 Context API
        def _cfg(key, default=None):
            ctx = context or {}
            if hasattr(ctx, "get") and callable(getattr(ctx, "get")):
                return ctx.get(key, default)
            cfg = {}
            if hasattr(ctx, "config") and isinstance(ctx.config, dict):
                cfg = ctx.config
            elif hasattr(ctx, "api") and hasattr(ctx.api, "get_config"):
                cfg = ctx.api.get_config("minecraft") or {}
            return cfg.get(key, default)

        # 基础开关
        self.rcon_enabled = _cfg("rcon_enabled", True)
        self.admin_only = _cfg("admin_only_commands", True)
        self.rcon_timeout = int(_cfg("rcon_timeout", 10))

        # 多服务器配置（兼容旧版单服务器格式）
        self.servers: Dict[str, MCConfig] = {}
        self.default_server: str = ""
        servers_cfg = _cfg("servers", None)
        if servers_cfg and isinstance(servers_cfg, list):
            for s in servers_cfg:
                if isinstance(s, dict):
                    name = s.get("name", s.get("host", "default"))
                    self.servers[name] = MCConfig(
                        name=name,
                        host=s.get("host", "127.0.0.1"),
                        port=int(s.get("port", 25575)),
                        password=s.get("password", ""),
                    )
            self.default_server = _cfg("default_server", "")
            if not self.default_server and self.servers:
                self.default_server = next(iter(self.servers))
        else:
            # 旧版兼容：单服务器字段
            host = _cfg("rcon_host", "127.0.0.1")
            port = int(_cfg("rcon_port", 25575))
            password = _cfg("rcon_password", "")
            name = _cfg("default_server", "default") or "default"
            self.servers[name] = MCConfig(name=name, host=host, port=port, password=password)
            self.default_server = name

        # 定时任务配置
        self.enable_auto_backup = _cfg("auto_backup", False)
        self.backup_interval = int(_cfg("backup_interval_minutes", 60))
        self.enable_announce = _cfg("enable_announce", False)
        self.announce_interval = int(_cfg("announce_interval_minutes", 30))
        self.announcements: List[str] = _cfg("announcements", []) or []
        self.enable_monitor = _cfg("enable_monitor", False)
        self.monitor_interval = int(_cfg("monitor_interval_seconds", 60))
        self.enable_llm_tool = _cfg("enable_llm_tool", True)

        # MC -> QQ 聊天桥接配置
        self.enable_chat_bridge = _cfg("enable_chat_bridge", False)
        self.bridge_listen_host = _cfg("bridge_listen_host", "127.0.0.1")
        self.bridge_listen_port = int(_cfg("bridge_listen_port", 25576))
        self.bridge_mc_to_qq = _cfg("bridge_mc_to_qq", True)
        self.bridge_qq_group = _cfg("bridge_qq_group", "")
        self.bridge_format_mc = _cfg(
            "bridge_format_mc", "[MC]{player}: {msg}"
        )

        # 运行时状态
        self._tasks: List[asyncio.Task] = []
        self._last_player_set: Set[str] = set()
        self._bridge_server: Optional[asyncio.base_events.Server] = None
        self._bridge_writers: Set[Any] = set()

        if not self.servers:
            logger.warning("MC 插件：未配置任何服务器")
        else:
            logger.info(
                f"MC 插件已加载 | 服务器: {list(self.servers.keys())} | 默认: {self.default_server}"
            )

    # ------------------------------------------------------------------
    # 服务器配置
    # ------------------------------------------------------------------
    def _get_server(self, name: Optional[str] = None) -> Optional[MCConfig]:
        name = name or self.default_server
        return self.servers.get(name)

    def _all_servers(self) -> List[MCConfig]:
        return list(self.servers.values())

    # ------------------------------------------------------------------
    # RCON 执行（带连接缓存与线程池）
    # ------------------------------------------------------------------
    async def _rcon_command(self, command: str, server_name: Optional[str] = None) -> str:
        if not self.rcon_enabled:
            return "RCON 功能未启用"

        srv = self._get_server(server_name)
        if not srv:
            return f"服务器未配置: {server_name or self.default_server}"

        if not srv.password:
            return f"服务器 [{srv.name}] 未配置 RCON 密码"

        def _sync_rcon():
            from mcrcon import MCRcon
            with MCRcon(srv.host, srv.password, srv.port) as mcr:
                return mcr.command(command)

        try:
            result = await asyncio.to_thread(_sync_rcon)
            return result.strip() if result else "（空响应）"
        except Exception as e:
            logger.error(f"RCON 执行失败 [{srv.name}] [{command}]: {e}")
            return f"[{srv.name}] 连接失败: {e}"

    # ------------------------------------------------------------------
    # 服务器信息
    # ------------------------------------------------------------------
    async def _get_status(self, server_name: Optional[str] = None) -> str:
        srv = self._get_server(server_name)
        name = srv.name if srv else (server_name or self.default_server)
        lines = [f"📊 服务器状态 [{name}]", ""]

        # 列表
        try:
            list_resp = await self._rcon_command("list", name)
            lines.append(f"👥 {list_resp}")
        except Exception as e:
            lines.append(f"👥 玩家列表: 获取失败 ({e})")

        # 种子
        try:
            seed_resp = await self._rcon_command("seed", name)
            lines.append(f"🌱 {seed_resp}")
        except Exception as e:
            lines.append(f"🌱 种子: 获取失败 ({e})")

        # 时间
        try:
            time_resp = await self._rcon_command("time query daytime", name)
            lines.append(f"🕐 {time_resp}")
        except Exception as e:
            lines.append(f"🕐 时间: 获取失败 ({e})")

        # 天气
        try:
            weather_resp = await self._rcon_command("weather query", name)
            lines.append(f"🌤️ {weather_resp}")
        except Exception as e:
            lines.append(f"🌤️ 天气: 获取失败 ({e})")

        # 难度
        try:
            diff_resp = await self._rcon_command("difficulty", name)
            lines.append(f"⚔️ {diff_resp}")
        except Exception as e:
            lines.append(f"⚔️ 难度: 获取失败 ({e})")

        # 详细状态（1.21+）
        try:
            status_resp = await self._rcon_command("server status", name)
            if status_resp and "{" in status_resp:
                lines.append("")
                lines.append("📋 详细状态 (server status):")
                lines.append(status_resp[:600])
        except Exception:
            pass

        return "\n".join(lines)

    async def _get_players(self, server_name: Optional[str] = None) -> str:
        name = server_name or self.default_server
        result = await self._rcon_command("list", name)
        if not result or "no players" in result.lower() or "can't keep up" in result.lower():
            return f"[{name}] 当前没有在线玩家"
        return f"👥 [{name}] 在线玩家：\n{result}"

    async def _get_whitelist(self, server_name: Optional[str] = None) -> str:
        name = server_name or self.default_server
        result = await self._rcon_command("whitelist list", name)
        if not result or "whitelist is empty" in result.lower():
            return f"[{name}] 白名单为空"
        return f"📋 [{name}] 白名单：\n{result}"

    async def _get_banlist(self, server_name: Optional[str] = None) -> str:
        name = server_name or self.default_server
        result = await self._rcon_command("banlist", name)
        if not result or "ban list is empty" in result.lower():
            return f"[{name}] 封禁列表为空"
        return f"🚫 [{name}] 封禁列表：\n{result}"

    async def _get_op_list(self, server_name: Optional[str] = None) -> str:
        name = server_name or self.default_server
        result = await self._rcon_command("op list", name)
        if not result or "there are no operators" in result.lower():
            return f"[{name}] 当前没有 OP"
        return f"👑 [{name}] OP 列表：\n{result}"

    # ------------------------------------------------------------------
    # 性能监控
    # ------------------------------------------------------------------
    async def _get_performance(self, server_name: Optional[str] = None) -> str:
        name = server_name or self.default_server
        lines = [f"📈 服务器性能 [{name}]", ""]

        # TPS（1.17+ 用 tick 查询，旧版本 fallback）
        try:
            tps_resp = await self._rcon_command("tps", name)
            lines.append(f"⚡ {tps_resp}")
        except Exception:
            try:
                tps_resp = await self._rcon_command("debug start", name)
                await asyncio.sleep(1)
                tps_resp = await self._rcon_command("debug stop", name)
                lines.append(f"⚡ debug: {tps_resp[:200]}")
            except Exception as e:
                lines.append(f"⚡ TPS: 获取失败 ({e})")

        # 内存
        try:
            mem_resp = await self._rcon_command("memory", name)
            lines.append(f"💾 {mem_resp}")
        except Exception as e:
            lines.append(f"💾 内存: 获取失败 ({e})")

        # 实体数量
        try:
            entity_resp = await self._rcon_command("entity", name)
            lines.append(f"🧍 实体: {entity_resp}")
        except Exception as e:
            lines.append(f"🧍 实体: 获取失败 ({e})")

        # 区块
        try:
            chunk_resp = await self._rcon_command("forge chunks", name)
            if chunk_resp:
                lines.append(f"🧊 区块: {chunk_resp[:200]}")
        except Exception:
            pass

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 定时任务
    # ------------------------------------------------------------------
    async def _auto_backup_loop(self):
        """自动备份循环"""
        while True:
            try:
                await asyncio.sleep(self.backup_interval * 60)
                for srv in self._all_servers():
                    result = await self._rcon_command("save-all", srv.name)
                    logger.info(f"自动备份 [{srv.name}]: {result}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"自动备份异常: {e}")

    async def _auto_announce_loop(self):
        """自动公告循环"""
        idx = 0
        while True:
            try:
                await asyncio.sleep(self.announce_interval * 60)
                if not self.announcements:
                    continue
                msg = self.announcements[idx % len(self.announcements)]
                idx += 1
                for srv in self._all_servers():
                    await self._rcon_command(f'say [系统公告] {msg}', srv.name)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"自动公告异常: {e}")

    async def _player_tracker_loop(self):
        """玩家进出发送群消息（简单轮询版）"""
        while True:
            try:
                await asyncio.sleep(10)
                for srv in self._all_servers():
                    result = await self._rcon_command("list", srv.name)
                    current: Set[str] = set()
                    if result and "no players" not in result.lower():
                        # list 返回格式: "There are 2 of a max of 20 players online: Alice, Bob"
                        parts = result.split(":")
                        if len(parts) >= 2:
                            names = parts[1].strip()
                            if names:
                                current = {n.strip() for n in names.split(",") if n.strip()}

                    prev = self._last_player_set
                    joined = current - prev
                    left = prev - current

                    for p in joined:
                        logger.info(f"[{srv.name}] 玩家加入: {p}")
                    for p in left:
                        logger.info(f"[{srv.name}] 玩家离开: {p}")

                    self._last_player_set = current
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"玩家追踪异常: {e}")

    # ------------------------------------------------------------------
    # MC -> QQ 聊天桥接
    # ------------------------------------------------------------------
    async def _start_bridge_server(self):
        """启动 TCP 服务器，接收 MC 服务端 mod 推送的聊天消息"""
        if not self.bridge_mc_to_qq:
            return

        async def handle_connection(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ):
            peer = writer.get_extra_info("peername")
            logger.info(f"MC 桥接连接来自: {peer}")
            self._bridge_writers.add(writer)
            try:
                while True:
                    data = await reader.readline()
                    if not data:
                        break
                    text = data.decode("utf-8", errors="ignore").strip()
                    if not text:
                        continue
                    try:
                        payload = json.loads(text)
                        player = payload.get("player", "Unknown")
                        message = payload.get("message", "")
                        server_name = payload.get("server", "")
                        if message:
                            await self._handle_mc_chat(player, message, server_name)
                    except json.JSONDecodeError:
                        # 兼容纯文本格式: PlayerName: message
                        if ": " in text:
                            player, message = text.split(": ", 1)
                            await self._handle_mc_chat(player.strip(), message.strip(), "")
            except Exception as e:
                logger.error(f"MC 桥接连接异常 {peer}: {e}")
            finally:
                self._bridge_writers.discard(writer)
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

        try:
            self._bridge_server = await asyncio.start_server(
                handle_connection,
                self.bridge_listen_host,
                self.bridge_listen_port,
            )
            logger.info(
                f"MC 聊天桥接 TCP 服务器已启动 | {self.bridge_listen_host}:{self.bridge_listen_port}"
            )
        except Exception as e:
            logger.error(f"MC 聊天桥接启动失败: {e}")

    async def _handle_mc_chat(self, player: str, message: str, server_name: str = ""):
        """处理从 MC 服务端收到的聊天消息，转发到 QQ"""
        srv = self._get_server(server_name) if server_name else self._get_server()
        name = srv.name if srv else (server_name or self.default_server)

        try:
            formatted = self.bridge_format_mc.format(player=player, msg=message)
        except Exception:
            formatted = f"[MC] {player}: {message}"

        target_group = self.bridge_qq_group or ""

        if hasattr(self.context, "send_message"):
            try:
                await self.context.send_message(target_group, formatted)
            except Exception as e:
                logger.error(f"MC 聊天转发到 QQ 失败: {e}")

    # ------------------------------------------------------------------
    # 帮助信息
    # ------------------------------------------------------------------
    def _get_help_text(self) -> str:
        return (
            "⛏️ Minecraft 插件使用帮助\n"
            "\n"
            "指令格式：/mc <子指令> [参数]\n"
            "\n"
            "📊 服务器信息：\n"
            "  status              - 查看综合状态\n"
            "  players / list      - 在线玩家\n"
            "  monitor             - 性能监控 (TPS/内存/实体)\n"
            "  version             - 服务器版本\n"
            "  servers             - 列出所有配置的服务器\n"
            "  use <服务器名>       - 切换默认服务器\n"
            "\n"
            "👥 玩家管理：\n"
            "  whitelist           - 白名单\n"
            "  ban / unban / banlist / kick\n"
            "  op / deop / op list\n"
            "\n"
            "🎮 游戏控制：\n"
            "  gamemode / time / weather / difficulty\n"
            "  save-all / stop\n"
            "\n"
            "📦 物品与传送：\n"
            "  give / tp / kill\n"
            "\n"
            "💬 聊天桥接：\n"
            "  bridge status       - 查看桥接状态\n"
            "  bridge on/off       - 开启/关闭桥接\n"
            "  (群消息自动转发到 MC，MC 消息通过 mod 推送)\n"
            "\n"
            "🤖 AI 与自动化：\n"
            "  ai <自然语言>        - AI 帮你执行指令\n"
            "  announce <消息>      - 全服公告\n"
            "  backup               - 手动备份\n"
            "  batch give <物品> [数量] - 给所有在线玩家发物品\n"
            "  cmd <指令>           - 执行任意指令\n"
            "  help                 - 显示此帮助\n"
            "\n"
            "⚠️  需要服务器启用 RCON"
        )

    # ------------------------------------------------------------------
    # 主指令入口
    # ------------------------------------------------------------------
    @filter.command("mc")
    async def minecraft_cmd(self, event: AstrMessageEvent, sub: str = "help", args: str = ""):
        '''Minecraft 服务器管理插件'''
        if self.admin_only and not event.is_admin():
            yield event.plain_result("⛔ 仅管理员可使用 MC 指令")
            return

        if not self.rcon_enabled:
            yield event.plain_result("RCON 功能未启用，请在插件设置中开启")
            return

        if not self.servers:
            yield event.plain_result("未配置任何 MC 服务器，请在插件设置中添加")
            return

        sub = sub.lower()
        parts = args.split() if args else []

        # 帮助
        if sub == "help":
            yield event.plain_result(self._get_help_text())
            return

        # 服务器列表
        if sub == "servers":
            lines = ["📡 已配置服务器：", ""]
            for srv in self._all_servers():
                mark = "👈 默认" if srv.name == self.default_server else ""
                lines.append(f"  • {srv.name} ({srv.host}:{srv.port}) {mark}")
            yield event.plain_result("\n".join(lines))
            return

        # 切换默认服务器
        if sub == "use":
            if not parts:
                yield event.plain_result(f"用法：/mc use <服务器名>\n当前默认: {self.default_server}")
                return
            target = parts[0]
            if target not in self.servers:
                yield event.plain_result(f"未知服务器: {target}\n可用: {list(self.servers.keys())}")
                return
            self.default_server = target
            yield event.plain_result(f"✅ 默认服务器已切换为: {target}")
            return

        # 性能监控
        if sub == "monitor":
            if not self.enable_monitor:
                yield event.plain_result("性能监控未启用，请在插件设置中开启")
                return
            yield event.plain_result(await self._get_performance())
            return

        # AI 自然语言执行
        if sub == "ai":
            if not self.enable_llm_tool:
                yield event.plain_result("AI 功能未启用，请在插件设置中开启")
                return
            if not parts:
                yield event.plain_result("用法：/mc ai <你想对服务器做什么>")
                return
            query = " ".join(parts)
            yield event.plain_result(await self._ai_execute(query))
            return

        # 手动备份
        if sub == "backup":
            results = []
            for srv in self._all_servers():
                r = await self._rcon_command("save-all", srv.name)
                results.append(f"[{srv.name}] {r}")
            yield event.plain_result("💾 备份完成：\n" + "\n".join(results))
            return

        # 全服公告
        if sub == "announce":
            if not parts:
                yield event.plain_result("用法：/mc announce <消息内容>")
                return
            msg = " ".join(parts)
            for srv in self._all_servers():
                await self._rcon_command(f'say [Bot公告] {msg}', srv.name)
            yield event.plain_result(f"📢 已向 {len(self.servers)} 个服务器发送公告")
            return

        # 批量给物品
        if sub == "batch":
            if not parts or parts[0].lower() != "give":
                yield event.plain_result("用法：/mc batch give <物品> [数量]")
                return
            if len(parts) < 2:
                yield event.plain_result("用法：/mc batch give <物品> [数量]")
                return
            item = parts[1]
            count = parts[2] if len(parts) >= 3 else "1"
            players_resp = await self._rcon_command("list", self.default_server)
            names = []
            if players_resp and ":" in players_resp:
                names = [n.strip() for n in players_resp.split(":")[1].split(",") if n.strip()]
            if not names:
                yield event.plain_result("当前没有在线玩家")
                return
            results = []
            for p in names:
                r = await self._rcon_command(f"give {p} {item} {count}", self.default_server)
                results.append(f"{p}: {r}")
            yield event.plain_result(f"📦 批量给予 {item} x{count}：\n" + "\n".join(results))
            return

        # 聊天桥接状态与控制
        if sub == "bridge":
            if not parts:
                yield event.plain_result(
                    f"💬 MC -> QQ 聊天桥接状态：\n"
                    f"  启用: {self.enable_chat_bridge}\n"
                    f"  MC→QQ: {self.bridge_mc_to_qq}\n"
                    f"  监听: {self.bridge_listen_host}:{self.bridge_listen_port}\n"
                    f"  目标群: {self.bridge_qq_group or '当前群'}"
                )
                return
            action = parts[0].lower()
            if action == "on":
                self.enable_chat_bridge = True
                yield event.plain_result("✅ 聊天桥接已开启")
                return
            if action == "off":
                self.enable_chat_bridge = False
                yield event.plain_result("🛑 聊天桥接已关闭")
                return
            if action == "status":
                yield event.plain_result(
                    f"💬 桥接状态：\n"
                    f"  启用: {self.enable_chat_bridge}\n"
                    f"  MC→QQ: {self.bridge_mc_to_qq}"
                )
                return
            yield event.plain_result("用法：/mc bridge [on/off/status]")
            return

        # 服务器信息子指令（兼容旧版）
        if sub == "status":
            yield event.plain_result(await self._get_status())
            return
        if sub in ("players", "list"):
            yield event.plain_result(await self._get_players())
            return
        if sub == "version":
            result = await self._rcon_command("version")
            yield event.plain_result(f"ℹ️ 服务器版本：\n{result}")
            return
        if sub == "whitelist":
            if not parts:
                yield event.plain_result(await self._get_whitelist())
                return
            action = parts[0].lower()
            if action == "add" and len(parts) >= 2:
                result = await self._rcon_command(f"whitelist add {parts[1]}", self.default_server)
                yield event.plain_result(f"✅ {result}")
            elif action == "remove" and len(parts) >= 2:
                result = await self._rcon_command(f"whitelist remove {parts[1]}", self.default_server)
                yield event.plain_result(f"✅ {result}")
            else:
                yield event.plain_result("用法：/mc whitelist [add/remove <玩家>] 或 /mc whitelist（查看）")
            return
        if sub == "banlist":
            yield event.plain_result(await self._get_banlist())
            return
        if sub == "op":
            if not parts:
                yield event.plain_result("用法：/mc op <玩家> 或 /mc op list")
                return
            if parts[0].lower() == "list":
                yield event.plain_result(await self._get_op_list())
                return
            result = await self._rcon_command(f"op {parts[0]}", self.default_server)
            yield event.plain_result(f"✅ {result}")
            return
        if sub == "deop":
            if not parts:
                yield event.plain_result("用法：/mc deop <玩家>")
                return
            result = await self._rcon_command(f"deop {parts[0]}", self.default_server)
            yield event.plain_result(f"✅ {result}")
            return
        if sub == "ban":
            if not parts:
                yield event.plain_result("用法：/mc ban <玩家> [原因]")
                return
            reason = " ".join(parts[1:]) if len(parts) > 1 else "违规操作"
            result = await self._rcon_command(f"ban {parts[0]} {reason}", self.default_server)
            yield event.plain_result(f"🚫 {result}")
            return
        if sub == "unban":
            if not parts:
                yield event.plain_result("用法：/mc unban <玩家>")
                return
            result = await self._rcon_command(f"pardon {parts[0]}", self.default_server)
            yield event.plain_result(f"✅ 已解封 {parts[0]}")
            return
        if sub == "kick":
            if not parts:
                yield event.plain_result("用法：/mc kick <玩家> [原因]")
                return
            reason = " ".join(parts[1:]) if len(parts) > 1 else "被管理员踢出"
            result = await self._rcon_command(f"kick {parts[0]} {reason}", self.default_server)
            yield event.plain_result(f"👢 {result}")
            return
        if sub == "gamemode":
            if not parts:
                yield event.plain_result("用法：/mc gamemode <模式> [玩家]")
                return
            mode = parts[0].lower()
            valid = {"survival": "survival", "creative": "creative", "adventure": "adventure", "spectator": "spectator", "s": "survival", "c": "creative", "a": "adventure", "sp": "spectator"}
            if mode not in valid:
                yield event.plain_result("未知模式，请使用 survival / creative / adventure / spectator")
                return
            if len(parts) >= 2:
                result = await self._rcon_command(f"gamemode {valid[mode]} {parts[1]}", self.default_server)
            else:
                result = await self._rcon_command(f"gamemode {valid[mode]}", self.default_server)
            yield event.plain_result(f"🎮 {result}")
            return
        if sub == "time":
            if not parts:
                yield event.plain_result("用法：/mc time <set/day/night/query> [数值]")
                return
            action = parts[0].lower()
            if action in ("day", "night"):
                result = await self._rcon_command(f"time set {action}", self.default_server)
            elif action == "set" and len(parts) >= 2:
                result = await self._rcon_command(f"time set {parts[1]}", self.default_server)
            elif action == "query":
                result = await self._rcon_command("time query daytime", self.default_server)
            else:
                yield event.plain_result("用法：/mc time <set <数值> / day / night / query>")
                return
            yield event.plain_result(f"🕐 {result}")
            return
        if sub == "weather":
            if not parts:
                yield event.plain_result("用法：/mc weather <clear/rain/thunder> [持续时间秒]")
                return
            action = parts[0].lower()
            if action not in ("clear", "rain", "thunder"):
                yield event.plain_result("未知天气，请使用 clear / rain / thunder")
                return
            if len(parts) >= 2 and parts[1].isdigit():
                result = await self._rcon_command(f"weather {action} {parts[1]}", self.default_server)
            else:
                result = await self._rcon_command(f"weather {action}", self.default_server)
            yield event.plain_result(f"🌤️ {result}")
            return
        if sub == "difficulty":
            if not parts:
                yield event.plain_result("用法：/mc difficulty <peaceful/easy/normal/hard>")
                return
            diff = parts[0].lower()
            valid = {"peaceful": "peaceful", "easy": "easy", "normal": "normal", "hard": "hard", "p": "peaceful", "e": "easy", "n": "normal", "h": "hard"}
            if diff not in valid:
                yield event.plain_result("未知难度，请使用 peaceful / easy / normal / hard")
                return
            result = await self._rcon_command(f"difficulty {valid[diff]}", self.default_server)
            yield event.plain_result(f"⚔️ {result}")
            return
        if sub == "save-all":
            result = await self._rcon_command("save-all", self.default_server)
            yield event.plain_result(f"💾 {result}")
            return
        if sub == "stop":
            result = await self._rcon_command("stop", self.default_server)
            yield event.plain_result(f"🛑 服务器正在关闭：{result}")
            return
        if sub == "give":
            if len(parts) < 2:
                yield event.plain_result("用法：/mc give <玩家> <物品> [数量]")
                return
            target = parts[0]
            item = parts[1]
            count = parts[2] if len(parts) >= 3 else "1"
            result = await self._rcon_command(f"give {target} {item} {count}", self.default_server)
            yield event.plain_result(f"📦 {result}")
            return
        if sub == "tp":
            if len(parts) < 2:
                yield event.plain_result("用法：/mc tp <玩家> <目标玩家> 或 /mc tp <玩家> <x> <y> <z>")
                return
            target = parts[0]
            if len(parts) == 2:
                result = await self._rcon_command(f"tp {target} {parts[1]}", self.default_server)
            else:
                coords = " ".join(parts[1:])
                result = await self._rcon_command(f"tp {target} {coords}", self.default_server)
            yield event.plain_result(f"🌀 {result}")
            return
        if sub == "kill":
            if not parts:
                yield event.plain_result("用法：/mc kill <玩家>")
                return
            result = await self._rcon_command(f"kill {parts[0]}", self.default_server)
            yield event.plain_result(f"💀 {result}")
            return
        if sub == "cmd":
            if not parts:
                yield event.plain_result("用法：/mc cmd <Minecraft 指令>")
                return
            cmd = " ".join(parts)
            result = await self._rcon_command(cmd, self.default_server)
            yield event.plain_result(f"⚡ 执行: /{cmd}\n📤 返回:\n{result}")
            return

        yield event.plain_result(f"未知子指令: {sub}\n使用 /mc help 查看完整帮助")

    # ------------------------------------------------------------------
    # AI 自然语言控制
    # ------------------------------------------------------------------
    async def _ai_execute(self, query: str) -> str:
        srv_name = self.default_server
        srv = self._get_server(srv_name)
        if not srv or not srv.password:
            return "默认服务器未配置 RCON 密码，无法执行"

        system_prompt = (
            "你是一个 Minecraft 服务器管理助手。"
            "根据用户的自然语言请求，生成最合适的 Minecraft 服务端指令。"
            "只输出指令本身，不要有多余解释。"
            "如果请求不明确，输出: 无法理解"
        )
        user_prompt = f"服务器: {srv_name}\n用户请求: {query}\n请输出指令:"

        try:
            # 尝试通过 AstrBot LLM 执行
            if hasattr(self.context, "llm_generate"):
                provider_id = await self.context.get_current_chat_provider_id(umo="")
                resp = await self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=f"{system_prompt}\n\n{user_prompt}",
                )
                cmd = (resp.completion_text or "").strip()
            else:
                # fallback：简单关键词映射
                cmd = self._simple_nlp(query)
        except Exception as e:
            logger.error(f"AI 执行失败: {e}")
            return f"AI 处理失败: {e}"

        if not cmd or cmd == "无法理解":
            return "🤔 我不确定该怎么执行，请尝试更具体的指令"

        # 执行指令
        result = await self._rcon_command(cmd, srv_name)
        return f"🤖 AI 执行: /{cmd}\n📤 返回:\n{result}"

    def _simple_nlp(self, query: str) -> str:
        """极简关键词 fallback（无 LLM 时使用）"""
        q = query.lower()
        if "几点" in q or "时间" in q:
            return "time query daytime"
        if "天气" in q:
            return "weather query"
        if "难度" in q:
            return "difficulty"
        if "玩家" in q or "在线" in q:
            return "list"
        if "备份" in q:
            return "save-all"
        if "公告" in q or "say" in q:
            return f"say [Bot] {query}"
        return ""

    # ------------------------------------------------------------------
    # LLM 工具注册（让大模型直接调用 MC 能力）
    # ------------------------------------------------------------------
    async def initialize(self):
        """插件初始化：启动定时任务、桥接服务器与 LLM 工具"""
        # 启动自动备份
        if self.enable_auto_backup and self.backup_interval > 0:
            task = asyncio.create_task(self._auto_backup_loop())
            self._tasks.append(task)
            logger.info(f"自动备份任务已启动 | 间隔: {self.backup_interval} 分钟")

        # 启动自动公告
        if self.enable_announce and self.announcements and self.announce_interval > 0:
            task = asyncio.create_task(self._auto_announce_loop())
            self._tasks.append(task)
            logger.info(f"自动公告任务已启动 | 间隔: {self.announce_interval} 分钟")

        # 启动玩家追踪
        task = asyncio.create_task(self._player_tracker_loop())
        self._tasks.append(task)
        logger.info("玩家追踪任务已启动")

        # 启动 MC 聊天桥接 TCP 服务器
        if self.enable_chat_bridge and self.bridge_mc_to_qq:
            task = asyncio.create_task(self._start_bridge_server())
            self._tasks.append(task)

        # 注册 LLM 工具
        if self.enable_llm_tool:
            self.context.add_llm_tools(self)

        logger.info("Minecraft 插件初始化完成")

    async def terminate(self):
        """插件卸载：取消所有任务"""
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

        if self._bridge_server:
            self._bridge_server.close()
            try:
                await self._bridge_server.wait_closed()
            except Exception:
                pass

        logger.info("Minecraft 插件已卸载，所有后台任务已停止")
