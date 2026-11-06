"""MyFinance App 渠道：把定时研究结果写进 App 的「研报」。

这个渠道只有出站方向。App 用户在手机上看研报，不会在这个渠道里跟 agent
对话，所以没有入站消息、没有长连接，``start()`` 只是把状态标成 running，
真正的动作全在 ``send()``：把结果 POST 到 MyFinance 后端的
``/research-reports``，落库后 App 的研报列表和后台通知就能看到。

定时任务的投递目标来自 ``job.config["channels"]``。其他渠道靠「用户先给
bot 发过消息」在 channel runtime 的 session map 里留下 ``渠道:chat_id``
绑定，而这个渠道永远没有入站消息，因此额外实现 ``scheduled_targets()``，
让投递逻辑在没有会话绑定时用配置里的固定目标补上。
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections import OrderedDict
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from pydantic import AliasChoices, BaseModel, Field

from src.channels.base import BaseChannel
from src.channels.bus.events import OutboundMessage
from src.channels.bus.queue import MessageBus

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:18889/api/v1"
DEFAULT_TARGET = "app"
DEFAULT_SOURCE = "trading_claw"
DEFAULT_TAGS = "定时研报"

TITLE_MAX_LEN = 60
SUMMARY_MAX_LEN = 160
# 报告标题通常在前几行（模型会先写一句寒暄），只在开头这些行里找
_TITLE_SCAN_LINES = 8
# 发送失败时 ChannelManager 会重试，重试窗口内用内容指纹去重，避免同一份
# 研报在 App 里出现多条。
DEDUPE_TTL_S = 300
DEDUPE_MAX_ENTRIES = 64

# 定时任务的投递前缀由 scheduled_routes 统一加，形如：
#   📊 定时研究结果 · 盘前扫描：按昨日异常成交量排名…
_SCHEDULED_PREFIX_RE = re.compile(r"^📊\s*定时研究结果\s*·\s*(?P<label>[^\n]*)\n*")
# 只认一级/二级标题：正文里的 ### 小标题是章节，不当研报标题
_TITLE_HEADING_RE = re.compile(r"^#{1,2}\s+(?P<title>.+?)\s*#*$")
# 任务名按这些标点取第一段，如「盘前扫描：按昨日异常成交量…」→「盘前扫描」
_LABEL_SPLIT_RE = re.compile(r"[：:，,。；;|｜]")
_SUMMARY_HINTS = ("一句话", "定调", "结论", "摘要", "核心观点")
# 列表项（- / * / 1.），区别于以 * 开头的加粗正文（**结论**：…）
_BULLET_RE = re.compile(r"^(?:[-*+]|\d+\.)\s")
_MARKDOWN_NOISE_RE = re.compile(r"(\*\*|__|`{1,3}|^[>\-*+]\s+|!?\[[^\]]*\]\([^)]*\))")


class MyFinanceConfig(BaseModel):
    """``channels.myfinance`` 段的配置。"""

    enabled: bool = False
    base_url: str = Field(
        default=DEFAULT_BASE_URL,
        validation_alias=AliasChoices("base_url", "baseUrl"),
    )
    api_token: str = Field(
        default="",
        validation_alias=AliasChoices("api_token", "apiToken"),
    )
    timeout_s: float = Field(
        default=30.0,
        validation_alias=AliasChoices("timeout_s", "timeoutS"),
    )
    source: str = DEFAULT_SOURCE
    default_tags: str = Field(
        default=DEFAULT_TAGS,
        validation_alias=AliasChoices("default_tags", "defaultTags"),
    )
    # 无入站会话时，定时结果投递到这些固定目标（只用于日志与去重，不涉及用户鉴权）。
    targets: list[str] = Field(default_factory=lambda: [DEFAULT_TARGET])

    model_config = {"populate_by_name": True, "extra": "ignore"}


def extract_title_and_body(text: str) -> tuple[str, str]:
    """从定时任务结果里拆出标题与正文。

    优先级：正文开头的 markdown 一级/二级标题 > 投递前缀里的任务名 + 日期。
    投递前缀（``📊 定时研究结果 · <任务名>``）只是渠道层的排版，不该当成
    研报标题，所以命中前缀时先剥掉再找标题。

    标题往往不在第一行：模型常先写一句「数据已经全部到位。以下是完整报告。」
    再给 ``# 盘前扫描 | 2026-11-09``，所以在前几行里找标题；命中后把标题行
    之前的寒暄一并丢掉，避免 App 详情页出现「大标题 + 正文重复一遍」。
    """
    body = text.strip()
    label = ""
    prefix = _SCHEDULED_PREFIX_RE.match(body)
    if prefix:
        label = (prefix.group("label") or "").strip()
        body = body[prefix.end():].strip()

    lines = body.splitlines()
    for index, line in enumerate(lines[:_TITLE_SCAN_LINES]):
        heading = _TITLE_HEADING_RE.match(line.strip())
        if heading:
            rest = "\n".join(lines[index + 1:]).strip()
            return _clip(heading.group("title"), TITLE_MAX_LEN), rest or body

    return _fallback_title(label or _first_text_line(lines)), body


def _fallback_title(label: str) -> str:
    """没有 markdown 标题时，用任务名里最像标题的一段 + 当天日期。"""
    short = _LABEL_SPLIT_RE.split(label.strip(), maxsplit=1)[0].strip()
    return f"{_clip(short or '定时研报', TITLE_MAX_LEN - 8)} · {_today_suffix()}"


def _today_suffix() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%m-%d")


def _first_text_line(lines: list[str]) -> str:
    for line in lines:
        stripped = line.strip()
        if stripped and stripped[0] not in "#>|!-*":
            return stripped
    return ""


def summarize(body: str) -> str:
    """给列表页用的纯文本摘要。

    优先取报告里的「一句话定调 / 结论」式引用块——那通常是整篇里信息密度最高
    的一行；没有就退回第一个普通段落。标题、分隔线、表格与列表一律跳过。
    """
    lines = [line.strip() for line in body.splitlines()]

    for line in lines:
        if line.startswith(">") and any(hint in line for hint in _SUMMARY_HINTS):
            return _clip(_MARKDOWN_NOISE_RE.sub("", line.lstrip("> ")), SUMMARY_MAX_LEN)

    for line in lines:
        if not line or line.startswith(("#", ">", "|", "!")):
            continue
        if _BULLET_RE.match(line) or set(line) <= {"-", " "}:
            continue
        return _clip(_MARKDOWN_NOISE_RE.sub("", line), SUMMARY_MAX_LEN)
    return ""


def _clip(value: str, limit: int) -> str:
    text = " ".join((value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class MyFinanceChannel(BaseChannel):
    """只出站的渠道：定时结果 → MyFinance 后端研报库。"""

    name = "myfinance"
    display_name = "App"
    # 研报是终态产物，过程性输出没有意义，且每次 send 都是一次写库。
    send_progress = False
    send_tool_hints = False
    show_reasoning = False

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return MyFinanceConfig().model_dump(by_alias=True)

    def __init__(self, config: Any, bus: MessageBus) -> None:
        if isinstance(config, dict):
            config = MyFinanceConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: MyFinanceConfig = config
        self._sent: OrderedDict[str, float] = OrderedDict()

    async def start(self) -> None:
        """没有入站监听，只校验配置并标记就绪。"""
        if not self.config.api_token:
            self.logger.warning(
                "MyFinance channel not started: channels.myfinance.apiToken is empty"
            )
            return
        self._running = True
        self.logger.info(
            "MyFinance channel ready: base_url=%s targets=%s",
            self.config.base_url,
            self.config.targets,
        )

    async def stop(self) -> None:
        self._running = False

    def scheduled_targets(self) -> list[str]:
        """定时结果在没有会话绑定时的固定投递目标。"""
        return [target for target in self.config.targets if target] or [DEFAULT_TARGET]

    async def send(self, msg: OutboundMessage) -> None:
        """把一条结果写进研报库。

        失败直接抛异常：由 ChannelManager 统一重试，重试用内容指纹去重，
        不会在 App 里产生重复研报。
        """
        if not self.config.api_token:
            raise RuntimeError("MyFinance channel: apiToken is not configured")

        content = (msg.content or "").strip()
        if not content:
            return

        fingerprint = hashlib.sha1(content.encode("utf-8")).hexdigest()
        if self._recently_sent(fingerprint):
            self.logger.info("MyFinance: duplicate scheduled result skipped")
            return

        title, body = extract_title_and_body(content)
        payload = {
            "title": title,
            # 正文只留内容：投递前缀与重复的标题行都已经抽到 title 里了
            "content": body or content,
            "summary": summarize(body),
            "tags": self.config.default_tags,
            "source": self.config.source,
        }
        url = f"{self.config.base_url.rstrip('/')}/research-reports"
        try:
            # 目标是同机后端，trust_env=False：生产环境配了 HTTP_PROXY，
            # 让 loopback 请求绕过代理判定更可靠。
            async with httpx.AsyncClient(
                timeout=self.config.timeout_s, trust_env=False
            ) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={"X-API-Token": self.config.api_token},
                )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"MyFinance: report push failed: {exc}") from exc

        if response.status_code >= 300:
            raise RuntimeError(
                f"MyFinance: report push rejected ({response.status_code}): "
                f"{response.text[:200]}"
            )

        self._remember(fingerprint)
        report_id = ""
        try:
            report_id = str(response.json().get("id", ""))
        except ValueError:
            pass
        self.logger.info(
            "MyFinance: scheduled report delivered (id=%s title=%s)",
            report_id or "?",
            title,
        )

    def _recently_sent(self, fingerprint: str) -> bool:
        expires_at = self._sent.get(fingerprint)
        if expires_at is None:
            return False
        if expires_at <= time.monotonic():
            self._sent.pop(fingerprint, None)
            return False
        return True

    def _remember(self, fingerprint: str) -> None:
        now = time.monotonic()
        self._sent[fingerprint] = now + DEDUPE_TTL_S
        self._sent.move_to_end(fingerprint)
        while len(self._sent) > DEDUPE_MAX_ENTRIES:
            self._sent.popitem(last=False)
