import asyncio
import aiohttp
import json
import os
from pathlib import Path
from urllib.parse import quote
from typing import Optional, Dict, Tuple

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

# 插件数据目录（用于缓存题目图片）
PLUGIN_DATA_DIR = Path("data", "plugins_data", "astrbot_plugin_gengtu")
PLUGIN_DATA_DIR.mkdir(parents=True, exist_ok=True)


@register(
    "astrbot_plugin_gengtu",
    "柠柚",
    "这是 AstrBot 的一个梗图抽象猜词插件，发送图片题目并校验答案",
    "1.0.3",
)
class GengtuPlugin(Star):
    """
    AstrBot 梗图抽象猜词插件。
    - /梗图 或 /gengtu 命令：获取最新题目并发送图片
    - /答案 <你的答案>：提交答案并验证
    """

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        # 接口与配置
        self.api_url = getattr(self.config, "api_url", "https://api.nycnm.cn/api/v2/gengtu")
        # 注意：API KEY 如需变更请在插件配置中修改
        self.api_key = getattr(
            self.config,
            "api_key",
            "",
        )
        self.timeout = getattr(self.config, "timeout", 10)

        # 待作答题目映射：以发送者名称为键，保存最近题目的 ID
        self.pending_questions: Dict[str, int] = {}
        logger.info("梗图抽象猜词插件初始化完成")

    @filter.command("gengtu", alias={"梗图", "抽象猜词", "猜词"})
    async def get_question(self, event: AstrMessageEvent):
        """
        获取梗图题目并发送图片。
        用法：/梗图 或 /gengtu
        """
        img_path = None
        try:
            q = await self._fetch_question()
            if not q:
                yield event.plain_result("❌ 获取题目失败，请稍后重试")
                return

            qid, image_url = q
            key = self._get_sender_key(event)
            self.pending_questions[key] = qid

            from astrbot.api.message_components import Plain, Image
            guide_text = "📝 使用 /答案 你的答案 作答\n💡 查看提示：/提示 或 /hint"
            
            img_path = await self._download_image(image_url, qid)
            if img_path:
                chain = [Image.fromFileSystem(img_path), Plain(text=guide_text)]
            else:
                # 备选方案，万一图片下载失败尝试直接发URL
                chain = [Image.fromURL(image_url), Plain(text=guide_text)]
                
            yield event.chain_result(chain)
        except Exception as e:
            logger.error(f"获取梗图题目时发生错误: {e}")
            yield event.plain_result("❌ 获取梗图题目时发生错误，请稍后重试")
        finally:
            pass

    @filter.command("answer", alias={"答案", "gengtu_answer", "猜词答案"})
    async def check_answer(self, event: AstrMessageEvent):
        """
        校验用户答案。
        用法：/答案 你的答案
        """
        message_text = event.get_message_str().strip()
        parts = message_text.split()
        if len(parts) < 2:
            yield event.plain_result("❌ 用法错误！请使用：/答案 你的答案")
            return

        # 支持包含空格的答案
        user_answer = " ".join(parts[1:])
        key = self._get_sender_key(event)
        qid = self.pending_questions.get(key)
        if not qid:
            yield event.plain_result("ℹ️ 当前没有待作答的题目，请先使用 /梗图 获取题目")
            return

        try:
            result_msg, correct, correct_answer = await self._verify_answer(qid, user_answer)
            # 根据返回结果提示
            tip_lines = []
            if correct is not None:
                if correct:
                    tip_lines.append("✅ 回答正确！")
                    # 回答正确后清理待作答状态
                    self.pending_questions.pop(key, None)
                    # 只有回答正确时才显示正确答案
                    if correct_answer:
                        tip_lines.append(f"📘 正确答案：{correct_answer}")
                else:
                    tip_lines.append("❌ 回答不正确！")
                    tip_lines.append("💡 如需查看正确答案，请使用 /提示 命令")
            else:
                # 如果无法判断正确性，显示服务端返回的消息
                tip_lines.append(result_msg)

            yield event.plain_result("\n".join(tip_lines))
        except Exception as e:
            logger.error(f"校验答案时发生错误: {e}")
            yield event.plain_result("❌ 校验失败，请稍后重试")

    @filter.command("hint", alias={"提示", "答案提示", "正确答案"})
    async def show_hint(self, event: AstrMessageEvent):
        """
        显示当前题目的正确答案。
        用法：/提示 或 /hint
        """
        key = self._get_sender_key(event)
        qid = self.pending_questions.get(key)
        if not qid:
            yield event.plain_result("ℹ️ 当前没有待作答的题目，请先使用 /梗图 获取题目")
            return

        try:
            # 获取正确答案（不校验用户答案）
            url = f"{self.api_url}?check={qid}&answer=&apikey={self.api_key}"
            logger.info("请求题目提示接口")
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=self.timeout)) as resp:
                    if resp.status != 200:
                        yield event.plain_result("❌ 获取提示失败，请稍后重试")
                        return
                    
                    data = await resp.json()
                    if not isinstance(data, dict):
                        yield event.plain_result("❌ 获取提示失败，请稍后重试")
                        return
                    
                    pdata = data.get("data", {}) if isinstance(data.get("data", {}), dict) else {}
                    correct_answer = pdata.get("correct_answer") if isinstance(pdata.get("correct_answer"), str) else None
                    
                    if correct_answer:
                        yield event.plain_result(f"💡 正确答案：{correct_answer}\n📝 请使用 /答案 {correct_answer} 来完成此题目")
                        # 不清除待作答状态，让用户仍需要正确回答
                        # self.pending_questions.pop(key, None)  # 注释掉这行
                    else:
                        yield event.plain_result("❌ 无法获取正确答案，请稍后重试")
                        
        except Exception as e:
            logger.error(f"获取提示时发生错误: {e}")
            yield event.plain_result("❌ 获取提示失败，请稍后重试")

    @filter.command("help_gengtu", alias={"梗图帮助", "猜词帮助", "使用说明"})
    async def show_help(self, event: AstrMessageEvent):
        """显示梗图抽象猜词插件帮助信息"""
        help_text = """
🎯 梗图抽象猜词插件使用说明

🖼️ 获取题目：
• /梗图 或 /gengtu

📝 提交答案：
• /答案 你的答案
  例如：/答案 六六大顺

💡 获取提示：
• /提示 或 /hint
  显示当前题目的正确答案，但仍需要正确回答才能完成题目

💡 说明：
• 发送图片后，会在当前会话记录题目编号
• 使用 /答案 命令提交你的回答，系统会返回正确与否
• 回答错误时不会显示正确答案，需要使用 /提示 命令查看
• 使用 /提示 查看答案后，仍需要通过 /答案 命令正确回答才能完成题目
• 如需新的题目，直接再次输入 /梗图
        """
        yield event.plain_result(help_text.strip())

    def _get_sender_key(self, event: AstrMessageEvent) -> str:
        """获取映射键，优先使用发送者名称。"""
        try:
            return event.get_sender_name() or "unknown"
        except Exception:
            return "unknown"

    async def _fetch_question(self) -> Optional[Tuple[int, str]]:
        """
        获取题目 ID 与图片 URL。
        返回 (question_id, image_url) 或 None
        """
        url = f"{self.api_url}?apikey={self.api_key}"
        # 避免日志泄露密钥，仅显示接口地址
        logger.info("请求梗图题目接口")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=self.timeout)) as resp:
                    if resp.status != 200:
                        logger.error(f"接口返回状态码错误: {resp.status}")
                        return None
                    data = await resp.json()
                    # 期望结构：{ data: { question: { id, image, answer }, show_answer: true, ... } }
                    if not isinstance(data, dict):
                        return None
                    payload = data.get("data", {})
                    q = payload.get("question", {})
                    qid = q.get("id")
                    img = q.get("image")
                    if isinstance(qid, int) and isinstance(img, str) and img:
                        return qid, img
                    return None
        except asyncio.TimeoutError:
            logger.error("请求题目接口超时")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"网络错误: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析错误: {e}")
            return None
        except Exception as e:
            logger.error(f"获取题目发生未知错误: {e}")
            return None

    async def _download_image(self, image_url: str, qid: int) -> Optional[str]:
        """下载题目图片到本地并返回文件路径。"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.xiaohongshu.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url, headers=headers, timeout=aiohttp.ClientTimeout(total=self.timeout)) as resp:
                    if resp.status != 200:
                        logger.error(f"图片下载失败，状态码: {resp.status}")
                        return None
                    img_bytes = await resp.read()
                    img_path = PLUGIN_DATA_DIR / f"gengtu_{qid}.jpg"
                    with open(img_path, "wb") as f:
                        f.write(img_bytes)
                    return str(img_path)
        except asyncio.TimeoutError:
            logger.error("图片下载超时")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"图片下载网络错误: {e}")
            return None
        except Exception as e:
            logger.error(f"图片下载发生未知错误: {e}")
            return None

    async def _verify_answer(self, qid: int, answer: str) -> Tuple[str, Optional[bool], Optional[str]]:
        """
        校验答案。
        返回 (message, correct, correct_answer)
        """
        encoded_answer = quote(answer, encoding="utf-8")
        url = f"{self.api_url}?check={qid}&answer={encoded_answer}&apikey={self.api_key}"
        # 避免日志泄露密钥，仅显示接口地址
        logger.info("校验答案接口")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=self.timeout)) as resp:
                    if resp.status != 200:
                        raise Exception(f"接口返回错误代码: {resp.status}")
                    data = await resp.json()
                    # 期望结构：{ success, code, message, data: { correct, correct_answer } }
                    if not isinstance(data, dict):
                        return "❓ 未知返回格式", None, None
                    message = str(data.get("message", "")) or ""
                    pdata = data.get("data", {}) if isinstance(data.get("data", {}), dict) else {}
                    correct = pdata.get("correct") if isinstance(pdata.get("correct"), bool) else None
                    correct_answer = pdata.get("correct_answer") if isinstance(pdata.get("correct_answer"), str) else None
                    # 如果服务端没有 message，兜底提示
                    if not message:
                        message = "✅ 回答正确！" if correct else "❌ 回答不正确！"
                    return message, correct, correct_answer
        except asyncio.TimeoutError:
            logger.error("校验接口请求超时")
            return "⏱️ 请求超时，请稍后重试", None, None
        except aiohttp.ClientError as e:
            logger.error(f"网络错误: {e}")
            return "🌐 网络错误，请稍后重试", None, None
        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析错误: {e}")
            return "📄 返回格式错误，请稍后重试", None, None
        except Exception as e:
            logger.error(f"校验答案未知错误: {e}")
            return "❌ 校验失败，请稍后重试", None, None

    async def terminate(self):
        """插件终止时的清理工作"""
        logger.info("梗图抽象猜词插件已终止")
