#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import os
import time
import tomllib
import hashlib
import hmac
import json
import random
import string
import re
from datetime import datetime
from typing import Dict, List, Set
import aiohttp
from loguru import logger

from WechatAPI import WechatAPIClient
from utils.decorators import on_text_message, on_image_message, scheduler
from utils.plugin_base import PluginBase

class SMSNotifier(PluginBase):
    description = "通过PushPlus通知微信离线用户"
    author = "老夏的金库"
    version = "1.1.0"

    def __init__(self):
        super().__init__()
        self.name = "SMSNotifier"
        self.description = "PushPlus通知插件"
        self.help = "发送PushPlus通知"
        
        # 基础样式模板
        self._base_style = """
            font-family: Microsoft YaHei, Arial;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            margin: 10px;
        """
        
        # 警告样式模板
        self._warning_style = self._base_style + """
            background: #fff5f5;
            border-left: 5px solid #ff4757;
        """
        
        # 信息样式模板
        self._info_style = self._base_style + """
            background: #f0f7ff;
            border-left: 5px solid #2196f3;
        """
        
        # 签名样式
        self._signature_style = """
            margin-top: 20px;
            padding-top: 15px;
            border-top: 1px dashed #ddd;
            color: #666;
            font-size: 14px;
        """

        # 默认通知文字内容
        self._default_notification_text = {
            "title": "⚠️ 微信离线通知",
            "content": "您的微信账号 <b>{wxid}</b> 已于 <span style=\"color:#ff4757;font-weight:bold;\">{time}</span> 离线",
            "note": "请尽快检查您的设备连接状态或重新登录。"
        }

        # 默认测试文字内容
        self._default_test_text = {
            "title": "📱 测试通知",
            "content": "这是一条测试消息，验证通知功能是否正常。",
            "account": "监控账号: <b>{wxid}</b>",
            "time": "发送时间: <span style=\"color:#2196f3;\">{time}</span>"
        }
        
        self.enable = False
        self.debug = False
        
        # PushPlus配置
        self.pushplus_token = ""
        self.pushplus_channel = "wechat"  # 默认为微信公众号，也可以是"sms"短信
        self.pushplus_template = "html"   # 默认模板
        self.pushplus_topic = ""          # 群组编码，不填仅发送给自己
        
        # 通知配置
        self.check_interval = 300  # 检查间隔，单位:秒
        self.retry_times = 3      # 短信发送失败重试次数
        self.retry_interval = 60  # 重试间隔，单位:秒
        
        # 用户配置
        self.users: Dict[str, str] = {}  # wxid -> phone_number/微信令牌
        self.current_wxid = ""  # 当前微信ID
        
        # 状态记录
        self.offline_users: Set[str] = set()  # 记录已经离线的用户wxid
        self.notification_sent: Dict[str, float] = {}  # wxid -> 上次发送短信的时间戳
        self.heartbeat_failures: Dict[str, List[float]] = {}  # wxid -> 列表[失败时间戳]
        self.heartbeat_threshold = 3  # 连续心跳失败次数阈值
        self.last_log_position = 0  # 上次读取日志的位置
        self.last_detected_wxid = None  # 用于保存最近检测到的wxid
        
        # 加载配置
        self._load_config()
        
        # 检查和发送线程
        self.check_task = None
    
    def _format_notification_template(self, text_config):
        """格式化通知模板"""
        return f"""
        <div style="{self._warning_style}">
            <h2 style="color:#ff4757;margin:0 0 15px 0;">{text_config["title"]}</h2>
            <p style="font-size:16px;line-height:1.6;color:#333;">
                {text_config["content"]}
            </p>
            <p style="font-size:16px;color:#333;margin-top:10px;">
                {text_config["note"]}
            </p>
            <div style="{self._signature_style}">老夏的金库提醒您</div>
        </div>
        """

    def _format_test_template(self, text_config):
        """格式化测试模板"""
        return f"""
        <div style="{self._info_style}">
            <h2 style="color:#2196f3;margin:0 0 15px 0;">{text_config["title"]}</h2>
            <p style="font-size:16px;line-height:1.6;color:#333;">
                {text_config["content"]}
            </p>
            <p style="font-size:16px;color:#333;">
                {text_config["account"]}
            </p>
            <p style="font-size:16px;color:#333;">
                {text_config["time"]}
            </p>
            <div style="{self._signature_style}">老夏的金库提醒您</div>
        </div>
        """

    def _load_config(self):
        """加载配置"""
        config_path = os.path.join(os.path.dirname(__file__), "config.toml")
        
        # 默认配置
        self.enable = False
        self.debug = False
        self.users = {}
        self.current_wxid = ""
        
        # 默认消息模板
        self.title_template = "微信离线通知 - {time}"
        self.notification_text = self._default_notification_text.copy()
        self.test_title_template = "测试通知 - {time}"
        self.test_text = self._default_test_text.copy()
        
        if not os.path.exists(config_path):
            logger.warning(f"配置文件不存在: {config_path}")
            return
            
        try:
            with open(config_path, "rb") as f:
                config = tomllib.load(f)
            
            # 基础配置
            basic_config = config.get("basic", {})
            self.enable = basic_config.get("enable", False)
            self.debug = basic_config.get("debug", False)
            self.current_wxid = basic_config.get("current_wxid", "")
            
            # PushPlus配置
            pushplus_config = config.get("pushplus", {})
            self.pushplus_token = pushplus_config.get("token", "")
            self.pushplus_channel = pushplus_config.get("channel", "wechat")
            self.pushplus_template = pushplus_config.get("template", "html")
            self.pushplus_topic = pushplus_config.get("topic", "")
            
            # 通知配置
            notification_config = config.get("notification", {})
            self.check_interval = notification_config.get("check_interval", 2)
            self.retry_times = notification_config.get("retry_times", 3)
            self.retry_interval = notification_config.get("retry_interval", 60)
            self.heartbeat_threshold = notification_config.get("heartbeat_threshold", 3)
            
            # 消息模板配置
            message_config = config.get("message", {})
            
            # 加载标题模板
            if "title_template" in message_config:
                self.title_template = message_config["title_template"]
            if "test_title_template" in message_config:
                self.test_title_template = message_config["test_title_template"]
            
            # 加载通知文字内容
            notification_text = message_config.get("notification_text", {})
            for key in self.notification_text:
                if key in notification_text:
                    self.notification_text[key] = notification_text[key]
            
            # 加载测试文字内容
            test_text = message_config.get("test_text", {})
            for key in self.test_text:
                if key in test_text:
                    self.test_text[key] = test_text[key]
            
            # 生成完整的HTML模板
            self.content_template = self._format_notification_template(self.notification_text)
            self.test_content_template = self._format_test_template(self.test_text)
            
            # 用户配置
            if self.current_wxid:
                self.users = {self.current_wxid: ""}
                logger.info(f"已添加当前微信ID {self.current_wxid} 到监控列表")
            else:
                logger.warning("未设置current_wxid，无法监控用户")
            
            if self.enable:
                if not self.pushplus_token:
                    logger.error("PushPlus配置不完整，请先配置token")
                    self.enable = False
                elif not self.users:
                    logger.warning("用户列表为空，没有需要监控的用户")
                else:
                    logger.info(f"SMSNotifier插件已启用，监控{len(self.users)}个用户")
            
        except Exception as e:
            logger.error(f"加载SMSNotifier配置文件失败: {str(e)}")
            self.enable = False

    def _format_message_template(self, template, wxid):
        """格式化消息模板，替换变量"""
        now = datetime.now()
        
        # 准备替换变量
        replacements = {
            "{wxid}": wxid,
            "{time}": now.strftime("%Y-%m-%d %H:%M:%S"),
            "{date}": now.strftime("%Y-%m-%d"),
            "{hour}": now.strftime("%H:%M"),
            "{bot_name}": getattr(self, "bot_name", "微信机器人"),
            "{bot_wxid}": self.current_wxid
        }
        
        # 替换所有变量
        result = template
        for key, value in replacements.items():
            result = result.replace(key, value)
            
        return result

    async def async_init(self):
        """获取当前机器人ID并启动监控"""
        logger.info("SMSNotifier插件开始初始化")
        
        # 创建心跳错误文件
        error_path = os.path.join(os.path.dirname(__file__), "heartbeat_errors.txt")
        with open(error_path, "w") as f:
            f.write(f"初始化心跳错误日志: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        logger.info(f"创建心跳错误文件: {error_path}")
        
        # 创建异步任务
        tasks = []
        
        # 获取机器人ID任务
        async def _get_bot_id():
            try:
                # 等待几秒钟，确保bot已经完全初始化
                await asyncio.sleep(5)
                
                # 尝试获取bot实例
                if hasattr(self, 'bot') and self.bot:
                    try:
                        bot_info = await self.bot.get_login_info()
                        if bot_info and "wxid" in bot_info:
                            self.current_wxid = bot_info["wxid"]
                            logger.info(f"成功获取到当前微信ID: {self.current_wxid}")
                            
                            # 添加到监控列表
                            self.users[self.current_wxid] = ""  # 接收者留空表示发送给token拥有者
                            logger.info(f"已将当前微信ID {self.current_wxid} 添加到监控列表")
                            return True
                        else:
                            logger.warning("未能从get_login_info获取到wxid")
                    except Exception as e:
                        logger.error(f"获取login_info时出错: {e}")
                
                # 尝试获取当前聊天信息
                wxid = None
                try:
                    # 注册消息回调
                    async def message_callback(message):
                        if not self.current_wxid and message.get("SenderWxid", "").startswith("wxid_"):
                            logger.info(f"从消息中识别到可能的当前wxid: {message.get('SenderWxid')}")
                            self.current_wxid = message.get("SenderWxid")
                            self.users[self.current_wxid] = ""
                            logger.info(f"已通过消息回调将 {self.current_wxid} 添加到监控列表")
                            return True
                        return False
                    
                    # 最多等待30秒来获取wxid
                    start_time = time.time()
                    while not self.current_wxid and time.time() - start_time < 30:
                        await asyncio.sleep(1)
                    
                    if self.current_wxid:
                        logger.info(f"通过消息回调成功获取到当前wxid: {self.current_wxid}")
                        return True
                    
                except Exception as e:
                    logger.error(f"尝试从消息获取wxid时出错: {e}")
            
                # 如果以上方法都失败，尝试从配置文件中获取
                if self.current_wxid:
                    logger.info(f"使用配置文件中的wxid: {self.current_wxid}")
                    self.users[self.current_wxid] = ""  # 确保在用户列表中
                    return True
                else:
                    # 如果仍然无法获取wxid，记录警告
                    logger.warning("无法自动获取当前微信ID，请手动设置")
                    return False
            except Exception as e:
                logger.error(f"获取机器人ID时出错: {e}")
                return False
        
        # 创建获取ID的任务
        id_task = asyncio.create_task(_get_bot_id())
        tasks.append(id_task)
        
        # 启动API检查任务
        if self.enable:
            logger.info("启动API状态检查任务")
            api_task = asyncio.create_task(self._check_api_heartbeat())
            tasks.append(api_task)
        
        return tasks

    @on_text_message(priority=1)
    async def capture_bot_id(self, bot: WechatAPIClient, message: dict):
        """捕获机器人ID"""
        # 保存bot引用
        self.bot = bot
        
        # 如果尚未获取到微信ID，尝试从消息中获取
        if not self.current_wxid:
            # 如果消息中包含自己的信息，尝试获取
            if message.get("SenderWxid", "").startswith("wxid_"):
                self.current_wxid = message.get("SenderWxid")
                # 添加到监控列表
                self.users[self.current_wxid] = ""  # 接收者留空表示发送给token拥有者
                logger.info(f"从消息中捕获到当前微信ID: {self.current_wxid}")
        
        return True  # 继续处理消息

    @on_text_message(priority=20)
    async def handle_test_command(self, bot: WechatAPIClient, message: dict):
        """处理测试发送通知命令"""
        # 保存bot引用
        self.bot = bot
        
        if not self.enable:
            return
            
        content = message.get("Content", "").strip()
        if not content.startswith("sms_test"):
            return
            
        # 检查发送者是否为管理员
        sender = message.get("SenderWxid", "")
        if not await self.is_admin(bot, sender):
            await bot.send_text_message(message["FromWxid"], "您没有权限执行此命令")
            return
        
        # 尝试获取wxid（如果尚未获取）
        if not self.current_wxid:
            # 尝试直接使用发送者的ID
            self.current_wxid = sender
            logger.info(f"使用测试命令发送者的ID作为微信ID: {self.current_wxid}")
            self.users[self.current_wxid] = ""
        
        # 使用当前设置的微信ID
        wxid = self.current_wxid
        if not wxid:
            await bot.send_text_message(message["FromWxid"], "未能获取当前微信ID，请在配置文件中手动设置current_wxid")
            return
        
        success = await self._send_test_message(wxid)
        
        if success:
            await bot.send_text_message(message["FromWxid"], f"测试通知已成功发送，wxid={wxid}，渠道: {self.pushplus_channel}")
        else:
            await bot.send_text_message(message["FromWxid"], f"发送测试通知失败，wxid={wxid}")
            
    @on_text_message(priority=20)
    async def handle_set_wxid_command(self, bot: WechatAPIClient, message: dict):
        """手动设置当前微信ID"""
        # 保存bot引用
        self.bot = bot
        
        if not self.enable:
            return
            
        content = message.get("Content", "").strip()
        if not content.startswith("sms_set_wxid "):
            return
            
        # 检查发送者是否为管理员
        sender = message.get("SenderWxid", "")
        if not await self.is_admin(bot, sender):
            await bot.send_text_message(message["FromWxid"], "您没有权限执行此命令")
            return
        
        parts = content.split()
        
        if len(parts) < 2:
            await bot.send_text_message(message["FromWxid"], "用法: sms_set_wxid <wxid>")
            return
        
        wxid = parts[1]
        
        # 设置当前微信ID
        old_wxid = self.current_wxid
        self.current_wxid = wxid
        
        # 更新监控列表
        if old_wxid in self.users:
            del self.users[old_wxid]
        self.users[wxid] = ""  # 接收者留空表示发送给token拥有者
        
        # 更新配置文件
        try:
            config_path = os.path.join(os.path.dirname(__file__), "config.toml")
            if os.path.exists(config_path):
                with open(config_path, "rb") as f:
                    config_data = tomllib.load(f)
                
                # 更新current_wxid
                if "basic" not in config_data:
                    config_data["basic"] = {}
                config_data["basic"]["current_wxid"] = wxid
                
                # 写回配置文件
                with open(config_path, "w", encoding="utf-8") as f:
                    # 手动构建TOML格式，因为Python的tomllib只支持读取
                    # 基础部分
                    f.write("[basic]\n")
                    for key, value in config_data["basic"].items():
                        if isinstance(value, bool):
                            f.write(f'{key} = {str(value).lower()}\n')
                        elif isinstance(value, (int, float)):
                            f.write(f'{key} = {value}\n')
                        else:
                            f.write(f'{key} = "{value}"\n')
                    f.write("\n")
                    
                    # PushPlus部分
                    if "pushplus" in config_data:
                        f.write("[pushplus]\n")
                        for key, value in config_data["pushplus"].items():
                            if isinstance(value, bool):
                                f.write(f'{key} = {str(value).lower()}\n')
                            elif isinstance(value, (int, float)):
                                f.write(f'{key} = {value}\n')
                            else:
                                f.write(f'{key} = "{value}"\n')
                        f.write("\n")
                    
                    # 通知配置部分
                    if "notification" in config_data:
                        f.write("[notification]\n")
                        for key, value in config_data["notification"].items():
                            if isinstance(value, bool):
                                f.write(f'{key} = {str(value).lower()}\n')
                            elif isinstance(value, (int, float)):
                                f.write(f'{key} = {value}\n')
                            else:
                                f.write(f'{key} = "{value}"\n')
                        f.write("\n")
                    
                    # 消息模板部分
                    if "message" in config_data:
                        f.write("[message]\n")
                        for key, value in config_data["message"].items():
                            if isinstance(value, bool):
                                f.write(f'{key} = {str(value).lower()}\n')
                            elif isinstance(value, (int, float)):
                                f.write(f'{key} = {value}\n')
                            else:
                                f.write(f'{key} = "{value}"\n')
                        f.write("\n")
        except Exception as e:
            logger.error(f"更新配置文件时出错: {e}")
        
        await bot.send_text_message(message["FromWxid"], f"已成功将当前微信ID从 {old_wxid or '未设置'} 更改为 {wxid}")
        
        # 发送一次测试通知
        await bot.send_text_message(message["FromWxid"], "正在发送测试通知...")
        success = await self._send_test_message(wxid)
        if success:
            await bot.send_text_message(message["FromWxid"], "测试通知发送成功")
        else:
            await bot.send_text_message(message["FromWxid"], "测试通知发送失败")

    async def _check_loop(self):
        """定期检查用户在线状态的循环"""
        while self.enable:
            try:
                # 简化检查条件，不再尝试创建XYBot实例
                if hasattr(self, 'bot') and self.bot:
                    await self._check_users(self.bot)
                else:
                    logger.warning("无法获取机器人实例，跳过本次检查")
                    
            except Exception as e:
                logger.error(f"检查用户在线状态出错: {str(e)}")
            
            # 等待下一次检查
            await asyncio.sleep(self.check_interval)
    
    async def _check_users(self, bot: WechatAPIClient):
        """检查用户在线状态，并向离线用户发送短信通知"""
        try:
            # 不再尝试获取好友列表，直接通过心跳检测和错误日志来判断状态
            current_time = time.time()
            
            # 检查心跳错误文件
            error_path = os.path.join(os.path.dirname(__file__), "heartbeat_errors.txt")
            if os.path.exists(error_path):
                try:
                    with open(error_path, "r", encoding='utf-8') as f:
                        recent_errors = f.readlines()[-10:]  # 只读取最后10行
                        for error_line in recent_errors:
                            if "心跳失败" in error_line or "Heartbeat failed" in error_line or "用户可能退出" in error_line:
                                # 提取时间戳
                                try:
                                    error_time_str = error_line.split()[0]
                                    error_time = datetime.strptime(error_time_str, "%Y/%m/%d %H:%M:%S")
                                    error_timestamp = error_time.timestamp()
                                    
                                    # 只处理最近5分钟内的错误
                                    if current_time - error_timestamp <= 300:
                                        # 提取wxid
                                        wxid_match = re.search(r'wxid_\w+', error_line)
                                        if wxid_match:
                                            wxid = wxid_match.group(0)
                                            if wxid in self.users:
                                                logger.warning(f"从错误日志检测到用户 {wxid} 的心跳失败")
                                                await self._process_heartbeat_failure(wxid)
                                except Exception as e:
                                    logger.error(f"处理错误日志时间戳出错: {e}")
                except Exception as e:
                    logger.error(f"读取心跳错误文件失败: {e}")
            
            # 检查每个配置的用户
            for wxid in self.users.keys():
                # 检查是否在离线列表中
                if wxid in self.offline_users:
                    # 已知离线的用户，检查是否需要再次通知
                    last_sent = self.notification_sent.get(wxid, 0)
                    if current_time - last_sent > 3600:  # 至少间隔1小时
                        success = await self._send_sms_notification(wxid)
                        if success:
                            self.notification_sent[wxid] = current_time
                            logger.info(f"已向持续离线的用户 {wxid} 发送提醒")
                    continue
                
                # 尝试发送心跳包
                try:
                    heartbeat_result = await bot.heartbeat()
                    if not heartbeat_result:
                        logger.warning(f"用户 {wxid} 心跳检测失败")
                        await self._process_heartbeat_failure(wxid)
                except Exception as e:
                    logger.error(f"发送心跳包时出错: {e}")
                    await self._process_heartbeat_failure(wxid)
        
        except Exception as e:
            logger.error(f"检查用户状态时出错: {str(e)}")
            # 发生错误时，通过心跳失败检测来处理
            logger.info("将依赖心跳失败日志检测来进行通知")
    
    async def _send_sms_notification(self, wxid: str, to: str = "") -> bool:
        """发送通知（通过PushPlus）"""
        # 重命名为更清晰的名称
        return await self._send_pushplus_notification(wxid, to)
        
    async def _send_pushplus_notification(self, wxid: str, to: str = "") -> bool:
        """发送通知（通过PushPlus）"""
        if not self.pushplus_token:
            logger.error(f"发送通知所需参数不完整: pushplus_token={bool(self.pushplus_token)}")
            return False
        
        # 请求地址
        url = 'http://www.pushplus.plus/send'
        
        # 消息标题和内容
        title = self._format_message_template(self.title_template, wxid)
        content = self._format_message_template(self.content_template, wxid)
        
        # 请求数据 - 直接发送给token拥有者
        data = {
            "token": self.pushplus_token,
            "title": title,
            "content": content,
            "template": self.pushplus_template,
            "channel": self.pushplus_channel
        }
        
        # 可选的topic参数
        if self.pushplus_topic:
            data["topic"] = self.pushplus_topic
            
        logger.info(f"准备发送通知，渠道: {self.pushplus_channel}，发送给token拥有者")
        
        for retry in range(self.retry_times):
            try:
                logger.info(f"尝试发送通知 (第 {retry+1}/{self.retry_times} 次)")
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=data) as response:
                        result = await response.json()
                        logger.info(f"PushPlus API响应: {result}")
                        
                        if result.get('code') == 200:
                            logger.info(f"通知发送成功: {result}")
                            return True
                        else:
                            error_msg = result.get('msg', '')
                            if "token" in error_msg.lower() and "用户" in error_msg:
                                logger.error(f"PushPlus token验证失败: {error_msg}")
                                logger.warning("请确保：\n1. 使用了正确的token\n2. 使用token对应的微信账号登录了PushPlus网站")
                                # 对于token错误，直接返回，不需要重试
                                return False
                            else:
                                logger.error(f"通知发送失败: {result}")
            except Exception as e:
                logger.error(f"发送通知出错: {str(e)}")
            
            # 如果失败，重试
            if retry < self.retry_times - 1:
                logger.info(f"将在 {self.retry_interval} 秒后重试")
                await asyncio.sleep(self.retry_interval)
        
        return False

    @on_text_message(priority=20)
    async def handle_reload_command(self, bot: WechatAPIClient, message: dict):
        """处理重新加载配置命令"""
        # 保存bot引用
        self.bot = bot
        
        if not self.enable:
            return
            
        content = message.get("Content", "").strip()
        if content != "sms_reload":
            return
            
        # 检查发送者是否为管理员
        sender = message.get("SenderWxid", "")
        if not await self.is_admin(bot, sender):
            await bot.send_text_message(message["FromWxid"], "您没有权限执行此命令")
            return
        
        was_enabled = self.enable
        self._load_config()
        
        if was_enabled and not self.enable:
            if self.check_task:
                self.check_task.cancel()
                self.check_task = None
        elif not was_enabled and self.enable:
            self.check_task = asyncio.create_task(self._check_loop())
        
        await bot.send_text_message(message["FromWxid"], f"SMSNotifier配置已重新加载，插件现在{'已启用' if self.enable else '已禁用'}")

    @on_text_message(priority=20)
    async def handle_status_command(self, bot: WechatAPIClient, message: dict):
        """处理查询状态命令"""
        # 保存bot引用
        self.bot = bot
        
        if not self.enable:
            return
            
        content = message.get("Content", "").strip()
        if content != "sms_status":
            return
            
        # 检查发送者是否为管理员
        sender = message.get("SenderWxid", "")
        if not await self.is_admin(bot, sender):
            await bot.send_text_message(message["FromWxid"], "您没有权限执行此命令")
            return
        
        status_text = "SMSNotifier状态报告：\n"
        status_text += f"启用状态: {'已启用' if self.enable else '已禁用'}\n"
        status_text += f"通知渠道: {self.pushplus_channel}\n"
        status_text += f"监控用户数: {len(self.users)}\n"
        status_text += f"离线用户数: {len(self.offline_users)}\n"
        status_text += f"已发送通知用户数: {len(self.notification_sent)}\n"
        status_text += "\n离线用户列表:\n"
        
        if not self.offline_users:
            status_text += "无离线用户\n"
        else:
            for wxid in self.offline_users:
                status_text += f"- {wxid}"
                if wxid in self.notification_sent:
                    timestamp = self.notification_sent[wxid]
                    notify_time = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
                    status_text += f" (已通知于 {notify_time})"
                status_text += "\n"
        
        await bot.send_text_message(message["FromWxid"], status_text)

    @on_text_message(priority=20)
    async def handle_test_heartbeat_command(self, bot: WechatAPIClient, message: dict):
        """处理测试心跳状态命令"""
        # 保存bot引用
        self.bot = bot
        
        if not self.enable:
            return
            
        content = message.get("Content", "").strip()
        if not content.startswith("sms_heartbeat"):
            return
            
        # 检查发送者是否为管理员
        sender = message.get("SenderWxid", "")
        if not await self.is_admin(bot, sender):
            await bot.send_text_message(message["FromWxid"], "您没有权限执行此命令")
            return
            
        parts = content.split()
        wxid = None
        
        if len(parts) > 1:
            wxid = parts[1]
        elif self.current_wxid:
            wxid = self.current_wxid
        elif len(self.users) == 1:
            wxid = list(self.users.keys())[0]
            
        if not wxid:
            await bot.send_text_message(message["FromWxid"], "请指定要测试的wxid，例如: sms_heartbeat wxid_123456")
            return
            
        # 使用IsRunning端点检查服务运行状态
        api_base_url = "http://127.0.0.1:9000"
        is_running_url = f"{api_base_url}/IsRunning"
        
        is_running_result = "未知"
        
        try:
            # 检查服务运行状态
            async with aiohttp.ClientSession() as session:
                async with session.get(is_running_url) as response:
                    if response.status == 200:
                        is_running_result = await response.text()
                        logger.info(f"API运行状态检查结果: {is_running_result}")
                    else:
                        logger.warning(f"API服务状态检查失败，状态码: {response.status}")
        except Exception as e:
            logger.error(f"API状态检查出错: {e}")
            
        # 再尝试直接发送心跳包（如果可用）
        direct_result = await self._test_heartbeat(wxid)
        
        # 构建响应消息
        response_text = f"微信服务状态测试结果 (wxid: {wxid}):\n\n"
        
        # IsRunning API结果
        response_text += f"API服务运行状态检查:\n"
        response_text += f"- 服务是否运行: {'是' if 'true' in is_running_result.lower() else '否'}\n"
        response_text += f"- 原始返回: {is_running_result}\n"
        
        # SDK直接心跳测试
        response_text += f"\n直接心跳测试: {'成功' if direct_result else '失败'}\n"
        
        # 添加自动心跳状态（如果可用）
        try:
            heartbeat_status = await bot.get_auto_heartbeat_status()
            response_text += f"\n自动心跳状态: {'已开启' if heartbeat_status else '已关闭'}"
        except Exception as e:
            response_text += f"\n获取自动心跳状态失败: {e}"
            
        # 添加监控状态
        response_text += f"\n\n当前监控状态:"
        response_text += f"\n- 监控用户数: {len(self.users)}"
        response_text += f"\n- 离线用户数: {len(self.offline_users)}"
        response_text += f"\n- 心跳失败阈值: {self.heartbeat_threshold}次"
        
        # 发送响应
        await bot.send_text_message(message["FromWxid"], response_text)

    async def _send_test_message(self, wxid: str):
        """发送测试通知"""
        # 获取接收者，留空表示发送给token拥有者
        to = self.users.get(wxid, "")
        
        # 构建测试消息内容
        title = self._format_message_template(self.test_title_template, wxid)
        content = self._format_message_template(self.test_content_template, wxid)
        
        # 请求地址
        url = 'http://www.pushplus.plus/send'
        
        # 请求数据
        data = {
            "token": self.pushplus_token,
            "title": title,
            "content": content,
            "template": self.pushplus_template,
            "channel": self.pushplus_channel
        }
        
        # 如果有指定接收者并且channel是wechat，添加to参数
        if to and self.pushplus_channel == "wechat":
            data["to"] = to
            
        # 可选的topic参数
        if self.pushplus_topic:
            data["topic"] = self.pushplus_topic
            
        logger.info(f"准备发送测试通知，渠道: {self.pushplus_channel}" + (f", 接收者: {to}" if to else ""))
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=data) as response:
                    result = await response.json()
                    logger.info(f"PushPlus API响应: {result}")
                    if result.get('code') == 200:
                        logger.info(f"测试通知发送成功: {result}")
                        return True
                    else:
                        logger.error(f"测试通知发送失败: {result}")
                        return False
        except Exception as e:
            logger.error(f"发送测试通知出错: {str(e)}")
            return False

    @on_text_message(priority=20)
    async def handle_monitor_command(self, bot: WechatAPIClient, message: dict):
        """处理添加监控用户命令"""
        # 保存bot引用
        self.bot = bot
        
        if not self.enable:
            return
            
        content = message.get("Content", "").strip()
        if not content.startswith("sms_monitor "):
            return
            
        # 检查发送者是否为管理员
        sender = message.get("SenderWxid", "")
        if not await self.is_admin(bot, sender):
            await bot.send_text_message(message["FromWxid"], "您没有权限执行此命令")
            return
        
        parts = content.split()
        
        if len(parts) < 2:
            await bot.send_text_message(message["FromWxid"], "用法: sms_monitor <wxid> <to>")
            return
        
        wxid = parts[1]
        to = parts[2]
        
        if wxid in self.users:
            await bot.send_text_message(message["FromWxid"], f"用户 {wxid} 已存在于监控列表中")
            return
        
        self.users[wxid] = to
        await bot.send_text_message(message["FromWxid"], f"已成功将用户 {wxid} 添加到监控列表，使用接收者 {to}，渠道: {self.pushplus_channel}")
        
    @on_text_message(priority=20)
    async def handle_channel_command(self, bot: WechatAPIClient, message: dict):
        """处理更改通知渠道命令"""
        # 保存bot引用
        self.bot = bot
        
        if not self.enable:
            return
            
        content = message.get("Content", "").strip()
        if not content.startswith("sms_channel "):
            return
            
        # 检查发送者是否为管理员
        sender = message.get("SenderWxid", "")
        if not await self.is_admin(bot, sender):
            await bot.send_text_message(message["FromWxid"], "您没有权限执行此命令")
            return
        
        parts = content.split()
        
        if len(parts) < 2:
            await bot.send_text_message(message["FromWxid"], "用法: sms_channel <channel>\n支持的渠道: wechat, sms, mail, webhook, cp")
            return
        
        channel = parts[1]
        old_channel = self.pushplus_channel
        
        valid_channels = ["wechat", "sms", "mail", "webhook", "cp"]
        if channel not in valid_channels:
            await bot.send_text_message(message["FromWxid"], f"不支持的渠道: {channel}\n支持的渠道: wechat, sms, mail, webhook, cp")
            return
        
        self.pushplus_channel = channel
        await bot.send_text_message(message["FromWxid"], f"已成功将通知渠道从 {old_channel} 更改为 {channel}")

    @on_text_message(priority=1)  # 使用最高优先级确保捕获所有消息
    async def capture_error_messages(self, bot: WechatAPIClient, message: dict):
        """直接捕获错误信息，不依赖日志文件"""
        # 保存bot引用
        self.bot = bot
        
        if not self.enable:
            return True
            
        # 如果系统消息含有错误信息，则处理
        try:
            if message and isinstance(message, dict):
                # 检查是否是日志转发的消息
                if message.get("MsgType") == 1 and message.get("FromWxid") in ["admin", "system", "log"]:
                    content = message.get("Content", "")
                    if "心跳失败" in content or "Heartbeat failed" in content or "用户可能退出" in content:
                        # 这可能是系统转发的错误日志
                        logger.warning(f"从转发日志消息捕获心跳失败: {content}")
                        
                        # 尝试提取wxid
                        wxid_match = re.search(r'wxid_\w+', content)
                        wxid = None
                        if wxid_match:
                            wxid = wxid_match.group(0)
                            logger.info(f"从日志消息提取到wxid: {wxid}")
                        elif message.get("ToWxid") and "wxid_" in message.get("ToWxid"):
                            wxid = message.get("ToWxid")
                            logger.info(f"使用ToWxid作为目标: {wxid}")
                        elif hasattr(self, 'current_wxid') and self.current_wxid:
                            wxid = self.current_wxid
                            
                        if wxid:
                            await self._process_heartbeat_failure(wxid)
                        
                        # 写入到心跳错误文件
                        try:
                            error_path = os.path.join(os.path.dirname(__file__), "heartbeat_errors.txt")
                            with open(error_path, "a") as f:
                                f.write(f"日志消息心跳失败: {time.strftime('%Y-%m-%d %H:%M:%S')} - wxid:{wxid or '未知'} - {content}\n")
                        except Exception as e:
                            logger.error(f"写入心跳错误文件失败: {e}")
                
                # 处理系统消息
                if message.get("MsgType") == 10000:  # 系统消息
                    content = message.get("Content", "")
                    if "用户可能退出" in content or "心跳失败" in content:
                        logger.warning(f"直接从系统消息捕获心跳失败: {content}")
                        
                        # 尝试提取wxid
                        wxid_match = re.search(r'wxid_\w+', content)
                        if wxid_match:
                            wxid = wxid_match.group(0)
                            logger.info(f"从系统消息提取到wxid: {wxid}")
                            await self._process_heartbeat_failure(wxid)
                        elif hasattr(self, 'current_wxid') and self.current_wxid:
                            # 使用配置的wxid
                            logger.info(f"使用当前配置的wxid: {self.current_wxid}")
                            await self._process_heartbeat_failure(self.current_wxid)
                        elif len(self.users) == 1:
                            # 如果只有一个用户，使用该用户
                            wxid = list(self.users.keys())[0]
                            logger.info(f"仅有一个配置的用户，使用该用户: {wxid}")
                            await self._process_heartbeat_failure(wxid)
        except Exception as e:
            logger.error(f"处理可能的错误消息时发生异常: {e}")
        
        # 将错误信息保存到特殊文件，以便直接监控检测到
        try:
            # 检查是否包含错误信息
            msg_str = str(message)
            if "心跳失败" in msg_str or "heartbeat failed" in msg_str.lower() or "用户可能退出" in msg_str:
                error_path = os.path.join(os.path.dirname(__file__), "heartbeat_errors.txt")
                with open(error_path, "a") as f:
                    f.write(f"错误消息: {time.strftime('%Y-%m-%d %H:%M:%S')} - {msg_str[:200]}...\n")
                logger.info(f"记录心跳失败信息到错误文件")
                
                # 从整个消息字符串中提取wxid
                wxid_match = re.search(r'wxid_\w+', msg_str)
                if wxid_match:
                    wxid = wxid_match.group(0)
                    logger.info(f"从消息字符串提取到wxid: {wxid}")
                    # 检查是否与监控用户匹配
                    if wxid in self.users or wxid == self.current_wxid:
                        logger.warning(f"检测到监控用户 {wxid} 的心跳失败")
                        await self._process_heartbeat_failure(wxid)
                    else:
                        logger.info(f"提取的wxid {wxid} 不在监控列表中")
        except Exception as e:
            logger.error(f"写入错误信息到文件时出错: {e}")
        
        # 监听所有消息是否有退出或离线提示    
        try:
            # 监听系统消息和错误报告
            content = str(message)
            if isinstance(message, dict):
                content_field = message.get("Content", "")
                if isinstance(content_field, str) and (
                    "已退出" in content_field or 
                    "离线" in content_field or 
                    "不在线" in content_field or
                    "登录异常" in content_field
                ):
                    # 记录到错误文件
                    error_path = os.path.join(os.path.dirname(__file__), "heartbeat_errors.txt")
                    with open(error_path, "a") as f:
                        f.write(f"系统消息提示离线: {time.strftime('%Y-%m-%d %H:%M:%S')} - {content_field}\n")
                    
                    # 尝试提取wxid
                    wxid = None
                    wxid_match = re.search(r'wxid_\w+', content_field)
                    if wxid_match:
                        wxid = wxid_match.group(0)
                    elif self.current_wxid:
                        wxid = self.current_wxid
                        
                    if wxid:
                        logger.warning(f"从系统消息中检测到用户离线: {wxid}")
                        await self._process_heartbeat_failure(wxid)
            
            # 检查是否包含"获取新消息失败"字眼
            if "获取新消息失败" in content or "error" in content.lower():
                error_path = os.path.join(os.path.dirname(__file__), "heartbeat_errors.txt")
                with open(error_path, "a") as f:
                    f.write(f"检测到消息失败: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                logger.info("检测到获取消息失败")
                
                # 如果我们监控的是当前登录账号，则直接处理此失败
                if self.current_wxid and self.current_wxid in self.users:
                    logger.warning(f"检测到当前账号 {self.current_wxid} 可能离线，处理心跳失败")
                    await self._process_heartbeat_failure(self.current_wxid)
                elif len(self.users) == 1:
                    # 如果只有一个用户，默认处理
                    wxid = list(self.users.keys())[0]
                    logger.warning(f"检测到心跳失败，默认处理唯一监控用户: {wxid}")
                    await self._process_heartbeat_failure(wxid)
        except Exception as e:
            logger.error(f"分析消息出错: {e}")
            
        return True  # 继续处理其他插件

    async def _process_heartbeat_failure(self, wxid):
        """处理心跳失败记录"""
        logger.info(f"处理心跳失败: wxid={wxid}")
        
        if wxid in self.users:
            # 发送通知
            success = await self._send_pushplus_notification(wxid)
            if success:
                logger.info(f"已向心跳检测失败的用户 {wxid} 发送离线通知")
            else:
                logger.error(f"向心跳检测失败的用户 {wxid} 发送通知失败")
        else:
            logger.warning(f"忽略非监控用户 {wxid} 的心跳失败")

    async def _send_heartbeat_notification(self, wxid: str, to: str):
        """发送心跳失败通知"""
        logger.info(f"开始发送心跳失败通知: wxid={wxid}, to={to}")
        
        # 如果PushPlus配置不完整，使用备用方式记录
        if not self.pushplus_token:
            logger.error("PushPlus配置不完整，无法发送通知")
            # 仍然记录这次通知尝试，避免重复触发
            self.notification_sent[wxid] = time.time()
            logger.warning(f"已记录对用户 {wxid} 的通知尝试，但由于配置问题未能发送通知")
            return False
        
        # 直接等待发送结果，不创建新任务
        success = await self._send_pushplus_notification(wxid, to)
        if success:
            self.notification_sent[wxid] = time.time()
            logger.info(f"已向心跳检测失败的用户 {wxid} 发送离线通知")
            return True
        else:
            logger.error(f"向心跳检测失败的用户 {wxid} 发送通知失败")
            return False

    async def is_admin(self, bot: WechatAPIClient, wxid: str) -> bool:
        """检查用户是否为管理员"""
        try:
            # 获取主配置中的admin列表
            config_path = "main_config.toml"
            if os.path.exists(config_path):
                with open(config_path, "rb") as f:
                    config = tomllib.load(f)
                admins = config.get("XYBot", {}).get("admins", [])
                return wxid in admins
        except Exception as e:
            logger.error(f"检查管理员权限失败: {e}")

    async def _check_api_heartbeat(self):
        """检查API状态并直接监听日志"""
        logger.info("启动API状态检查和日志监控")
        
        # API服务器地址
        api_base_url = "http://127.0.0.1:9000"
        
        # 记录上次通知时间
        last_notification_time = {}
        
        # 心跳失败计数
        failure_count = {}
        
        # 使用自定义日志处理器捕获相关日志
        class HeartbeatLogHandler:
            def __init__(self, callback):
                self.callback = callback
                # 存储心跳失败情况
                self.heartbeat_failures = {}
                # 注册到loguru
                self.handler_id = None
                
            def __call__(self, message):
                # 直接使用传入的消息字符串 - message已经是字符串而不是字典
                try:
                    # 检查是否包含心跳失败信息
                    if "Heartbeat failed for wxid" in message:
                        # 提取wxid
                        wxid_match = re.search(r'Heartbeat failed for wxid (wxid_\w+)', message)
                        if wxid_match:
                            wxid = wxid_match.group(1)
                            # 回调处理心跳失败
                            asyncio.create_task(self.callback(wxid))
                    
                    # 检查是否包含消息获取失败信息
                    elif "获取新消息失败" in message and "用户可能退出" in message:
                        # 使用当前微信ID (如果可用)
                        if self.callback.current_wxid:
                            asyncio.create_task(self.callback(self.callback.current_wxid))
                except Exception as e:
                    print(f"处理日志消息出错: {e}")
                
                # 返回True表示消息继续传递给其他处理器
                return True
            
            def register(self):
                # 注册日志处理器
                self.handler_id = logger.add(self, level="INFO")
                logger.info("已注册心跳失败日志处理器")
                
            def unregister(self):
                # 移除日志处理器
                if self.handler_id is not None:
                    logger.remove(self.handler_id)
                    # 不需要输出日志处理器移除的消息
                    # logger.info("已移除心跳失败日志处理器")
        
        # 创建日志处理器
        # 处理心跳失败的回调函数
        async def heartbeat_failure_callback(wxid):
            current_time = time.time()
            
            # 只处理在监控列表中的用户
            if wxid not in self.users:
                return
                
            # 初始化失败计数
            if wxid not in failure_count:
                failure_count[wxid] = []
            
            # 添加失败记录
            failure_count[wxid].append(current_time)
            
            # 清理过时的记录（5分钟前）
            failure_count[wxid] = [t for t in failure_count[wxid] if current_time - t <= 300]
            
            # 不打印正常的失败计数日志，只有达到阈值时才输出
            if len(failure_count[wxid]) >= self.heartbeat_threshold:
                logger.warning(f"检测到用户 {wxid} 的心跳失败，当前失败次数: {len(failure_count[wxid])}/{self.heartbeat_threshold}")
            
            # 检查是否达到阈值
            if len(failure_count[wxid]) >= self.heartbeat_threshold:
                # 检查上次通知时间
                if wxid not in last_notification_time or current_time - last_notification_time[wxid] >= 3600:
                    logger.warning(f"用户 {wxid} 心跳失败次数达到阈值，发送通知")
                    
                    # 发送通知
                    success = await self._send_pushplus_notification(wxid)
                    if success:
                        last_notification_time[wxid] = current_time
                        logger.info(f"已向用户 {wxid} 发送离线通知")
                        # 重置失败计数
                        failure_count[wxid] = []
                    else:
                        logger.error(f"向用户 {wxid} 发送通知失败")
                else:
                    time_diff = current_time - last_notification_time[wxid]
                    logger.info(f"用户 {wxid} 距离上次通知仅 {time_diff/60:.1f} 分钟，暂不重复发送")
        
        # 给回调函数添加对current_wxid的访问
        heartbeat_failure_callback.current_wxid = self.current_wxid
        
        # 创建并注册日志处理器
        log_handler = HeartbeatLogHandler(heartbeat_failure_callback)
        log_handler.register()
        
        try:
            # 主循环
            while self.enable:
                try:
                    # 更新回调函数的current_wxid（可能已更改）
                    heartbeat_failure_callback.current_wxid = self.current_wxid
                    
                    # 检查API服务状态
                    try:
                        async with aiohttp.ClientSession() as session:
                            async with session.get(f"{api_base_url}/IsRunning", timeout=5) as response:
                                if response.status == 200:
                                    result_text = await response.text()
                                    # 不输出正常的API状态检查结果
                                    # logger.info(f"API运行状态检查结果: {result_text}")
                                    
                                    # 服务不在运行时发送通知
                                    if result_text.strip().lower() != "ok":
                                        current_time = time.time()
                                        logger.warning("API服务异常，状态检查返回非OK")
                                        
                                        for wxid in self.users:
                                            if wxid not in last_notification_time or current_time - last_notification_time[wxid] >= 3600:
                                                logger.warning(f"API异常，发送通知给用户 {wxid}")
                                                await self._process_heartbeat_failure(wxid)
                                                last_notification_time[wxid] = current_time
                                else:
                                    logger.warning(f"API服务状态检查失败，状态码: {response.status}")
                                    current_time = time.time()
                                    
                                    # 服务不可用时发送通知
                                    for wxid in self.users:
                                        if wxid not in last_notification_time or current_time - last_notification_time[wxid] >= 3600:
                                            logger.warning(f"API服务不可用，发送通知给用户 {wxid}")
                                            await self._process_heartbeat_failure(wxid)
                                            last_notification_time[wxid] = current_time
                    except Exception as e:
                        logger.error(f"API状态检查请求失败: {e}")
                        
                except Exception as e:
                    logger.error(f"API状态检查循环出错: {e}")
                
                # 每2秒检查一次
                await asyncio.sleep(2)
        finally:
            # 确保日志处理器被移除
            log_handler.unregister()

    # 发送一次心跳包进行测试
    async def _test_heartbeat(self, wxid):
        """测试发送心跳包"""
        if hasattr(self, 'bot') and self.bot:
            try:
                logger.info(f"尝试为用户 {wxid} 发送心跳包")
                result = await self.bot.heartbeat()
                logger.info(f"心跳包发送结果: {result}")
                return result
            except Exception as e:
                logger.error(f"发送心跳包出错: {e}")
                return False
        return False

    @on_text_message(priority=20)
    async def handle_unmonitor_command(self, bot: WechatAPIClient, message: dict):
        """处理移除监控用户命令"""
        # 保存bot引用
        self.bot = bot
        
        if not self.enable:
            return
            
        content = message.get("Content", "").strip()
        if not content.startswith("sms_unmonitor "):
            return
            
        # 检查发送者是否为管理员
        sender = message.get("SenderWxid", "")
        if not await self.is_admin(bot, sender):
            await bot.send_text_message(message["FromWxid"], "您没有权限执行此命令")
            return
        
        parts = content.split()
        
        if len(parts) < 2:
            await bot.send_text_message(message["FromWxid"], "用法: sms_unmonitor <wxid>")
            return
        
        wxid = parts[1]
        
        if wxid not in self.users:
            await bot.send_text_message(message["FromWxid"], f"用户 {wxid} 不存在于监控列表中")
            return
        
        del self.users[wxid]
        # 如果用户在离线列表中，也一同移除
        if wxid in self.offline_users:
            self.offline_users.remove(wxid)
        
        await bot.send_text_message(message["FromWxid"], f"已成功将用户 {wxid} 从监控列表中移除")

    @on_text_message(priority=20)
    async def handle_message_template_command(self, bot: WechatAPIClient, message: dict):
        """处理设置消息模板命令"""
        # 保存bot引用
        self.bot = bot
        
        if not self.enable:
            return
            
        content = message.get("Content", "").strip()
        if not content.startswith("sms_template "):
            return
            
        # 检查发送者是否为管理员
        sender = message.get("SenderWxid", "")
        if not await self.is_admin(bot, sender):
            await bot.send_text_message(message["FromWxid"], "您没有权限执行此命令")
            return
        
        # 分析命令部分
        try:
            # 解析命令参数
            parts = content.split(maxsplit=2)  # 最多分成3部分
            
            if len(parts) < 3:
                await bot.send_text_message(message["FromWxid"], "用法: \nsms_template title 新标题模板\nsms_template content 新内容模板\n\n可用变量: {wxid}, {time}, {date}, {hour}, {bot_name}, {bot_wxid}")
                return
            
            template_type = parts[1].lower()
            template_content = parts[2]
            
            # 根据类型设置不同的模板
            if template_type == "title":
                self.title_template = template_content
                await bot.send_text_message(message["FromWxid"], f"已更新通知标题模板为:\n{template_content}")
            elif template_type == "content":
                self.content_template = template_content
                await bot.send_text_message(message["FromWxid"], f"已更新通知内容模板为:\n{template_content}")
            elif template_type == "test_title":
                self.test_title_template = template_content
                await bot.send_text_message(message["FromWxid"], f"已更新测试通知标题模板为:\n{template_content}")
            elif template_type == "test_content":
                self.test_content_template = template_content
                await bot.send_text_message(message["FromWxid"], f"已更新测试通知内容模板为:\n{template_content}")
            else:
                await bot.send_text_message(message["FromWxid"], f"未知的模板类型: {template_type}\n支持的类型: title, content, test_title, test_content")
            
            # 显示示例效果
            example = self._format_message_template(template_content, self.current_wxid)
            await bot.send_text_message(message["FromWxid"], f"模板示例效果:\n{example}")
            
            # 保存到配置文件
            self._save_message_templates()
            
        except Exception as e:
            logger.error(f"处理消息模板命令出错: {str(e)}")
            await bot.send_text_message(message["FromWxid"], f"设置消息模板失败: {str(e)}")
    
    def _save_message_templates(self):
        """保存消息模板到配置文件"""
        try:
            config_path = os.path.join(os.path.dirname(__file__), "config.toml")
            
            # 如果配置文件不存在，无法保存
            if not os.path.exists(config_path):
                logger.error("配置文件不存在，无法保存消息模板")
                return False
                
            # 读取现有配置
            with open(config_path, "rb") as f:
                config_data = tomllib.load(f)
            
            # 更新消息模板部分
            if "message" not in config_data:
                config_data["message"] = {}
                
            config_data["message"]["title_template"] = self.title_template
            config_data["message"]["content_template"] = self.content_template
            config_data["message"]["test_title_template"] = self.test_title_template
            config_data["message"]["test_content_template"] = self.test_content_template
            
            # 写回配置文件
            with open(config_path, "w", encoding="utf-8") as f:
                # 手动构建TOML格式，因为Python的tomllib只支持读取
                # 基础部分
                if "basic" in config_data:
                    f.write("[basic]\n")
                    for key, value in config_data["basic"].items():
                        if isinstance(value, bool):
                            f.write(f'{key} = {str(value).lower()}\n')
                        elif isinstance(value, (int, float)):
                            f.write(f'{key} = {value}\n')
                        else:
                            f.write(f'{key} = "{value}"\n')
                    f.write("\n")
                
                # PushPlus部分
                if "pushplus" in config_data:
                    f.write("[pushplus]\n")
                    for key, value in config_data["pushplus"].items():
                        if isinstance(value, bool):
                            f.write(f'{key} = {str(value).lower()}\n')
                        elif isinstance(value, (int, float)):
                            f.write(f'{key} = {value}\n')
                        else:
                            f.write(f'{key} = "{value}"\n')
                    f.write("\n")
                
                # 通知配置部分
                if "notification" in config_data:
                    f.write("[notification]\n")
                    for key, value in config_data["notification"].items():
                        if isinstance(value, bool):
                            f.write(f'{key} = {str(value).lower()}\n')
                        elif isinstance(value, (int, float)):
                            f.write(f'{key} = {value}\n')
                        else:
                            f.write(f'{key} = "{value}"\n')
                    f.write("\n")
                
                # 消息模板部分
                f.write("[message]\n")
                f.write(f'title_template = "{self.title_template}"\n')
                f.write(f'content_template = "{self.content_template}"\n')
                f.write(f'test_title_template = "{self.test_title_template}"\n')
                f.write(f'test_content_template = "{self.test_content_template}"\n')
                f.write("\n")
                
                # 用户配置部分
                if "users" in config_data:
                    f.write("[users]\n")
                    for user, value in config_data["users"].items():
                        f.write(f'"{user}" = "{value}"\n')
                
            logger.info("已保存消息模板到配置文件")
            return True
            
        except Exception as e:
            logger.error(f"保存消息模板到配置文件失败: {str(e)}")
            return False

# 创建插件实例（供XYBot加载）
plugin_instance = SMSNotifier()