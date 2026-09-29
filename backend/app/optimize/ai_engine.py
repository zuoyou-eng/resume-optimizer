"""AI 改写引擎（O-01 的真实模型接入点，OpenAI 兼容 /chat/completions）。

**用户自带模型**：base_url / api_key / model 由前端「模型设置」面板填写，
随改写请求一次性传到服务端，仅用于本次请求构建引擎实例——
不落库、不进日志、不写进任何 reason/model_version。

为什么能"零改造"接进来（设计文档 4.5.1 引擎接口化）：
  引擎仍是 RewriteEngine 的子类，因此基类统一执行的
  ① 前置抽事实 → ④ 后置事实比对 → ⑤ 改动点与风险分级
  对 AI 完全生效，**AI 不可能绕过事实守恒**。

三条必须保留的行为（都是既有链路，不是新逻辑）：
  1. 调用失败（超时 / 网络错误 / 鉴权失败 / 返回不可解析 / 空结果）
     一律返回 None → 基类自动降级为「仅建议」（FR-12 只读展示），
     **不需要新的错误码**，也不会把半成品透给用户；
  2. 改写若改变或新增事实 → 基类判定 rejected，服务层返回 6002，
     违规内容绝不落库；
  3. reproducible 标为 False——相同输入不保证相同输出。
     NFR-08 约束的是确定性引擎；如实标注，不假装可复现。
"""
import re

import httpx

from app.optimize.engine import RewriteEngine, RewriteRequest

# 提示词：把"不许编造"写成可核对的硬约束。
# 约束清单与 facts.py 的抽取器一一对应——抽取器能识别的每一类事实，
# 在这里都有一条对应的禁止条款，避免"提示词说了但校验没管"的错觉。
_SYSTEM_PROMPT = """你是简历改写助手。你会收到一段简历原文、一条诊断问题与一条修改建议，\
任务是按建议优化这段文字的措辞与结构。

硬性约束（违反任意一条即视为失败，请改用更保守的写法）：
1. 不得新增原文没有的任何信息，尤其是：数字与单位（如 30%、10 万、3 年、500 人）、\
时间段、学校名、公司名、职位名、技术名词；
2. 不得新增评价性主张（如"获得一致好评""表现优秀""效果显著""大幅提升""广受认可"）；
3. 不得删除或改写任何既有事实；
4. 保持中文；保持原有信息完整，不要分点、不要解释、不要总结。

只输出改写后的文本本身。不要输出引号、代码块、Markdown 标记、前后缀或任何说明。"""

# 模型偶尔仍会包裹代码块或加"改写后："前缀——这里只做**去包装**，
# 绝不改写内容本身（内容改动会被视为 AI 的产物，必须经事实守恒校验）。
_FENCE_RE = re.compile(r"^\s*```[a-zA-Z]*\s*\n?(?P<body>.*?)\n?\s*```\s*$", re.DOTALL)
_PREFIX_RE = re.compile(
    r"^\s*(?:改写后|修改后|优化后|结果|输出)\s*[:：]\s*", re.MULTILINE
)
_QUOTE_PAIRS = {'"': '"', "“": "”", "'": "'", "‘": "’"}

DEFAULT_TIMEOUT_SECONDS = 60


def _clean_model_output(raw: str) -> str:
    """去掉模型的包装（代码围栏 / 说明前缀 / 整体引号），不改动正文。"""
    text = (raw or "").strip()
    if not text:
        return ""

    fence = _FENCE_RE.match(text)
    if fence:
        text = fence.group("body").strip()

    text = _PREFIX_RE.sub("", text).strip()

    # 整体被一对引号包裹时才剥离（避免误伤正文里的引号）
    if len(text) >= 2 and text[0] in _QUOTE_PAIRS and text[-1] == _QUOTE_PAIRS[text[0]]:
        text = text[1:-1].strip()

    return text


def normalize_base_url(base_url: str) -> str:
    """把用户填的各种写法归一到 `{origin}/chat/completions`。

    接受：https://api.deepseek.com 、https://api.deepseek.com/v1 、
          https://api.deepseek.com/v1/chat/completions 、带尾斜杠的写法。
    """
    url = (base_url or "").strip().rstrip("/")
    if not url:
        return ""
    if url.endswith("/chat/completions"):
        return url
    # 已带 /v1 这类版本段则不再补，避免出现 /v1/v1
    if re.search(r"/v\d+$", url):
        return f"{url}/chat/completions"
    return f"{url}/v1/chat/completions"


class AIRewriteEngine(RewriteEngine):
    """调用用户配置的 OpenAI 兼容模型做改写。

    与规则引擎的分工：规则引擎只做确定性、不改变语义的修正（产物恒为
    auto_safe）；本引擎做**措辞与结构**优化，产物通常为 needs_review，
    必须逐条人工确认后才能应用。
    """

    name = "ai_rewrite"
    reproducible = False  # 相同输入不保证相同输出（NFR-08 只约束确定性引擎）

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        temperature: float = 0.2,
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        # 版本号带模型名，使改写记录可追溯"这条是谁产出的"；
        # 刻意不含 base_url 与 api_key。
        self.version = f"ai-{model}" if model else "ai-unknown-model"

    # ---------- 请求装配（可单独测试，不发网络） ----------

    def build_payload(self, req: RewriteRequest) -> dict:
        user = (
            f"【诊断问题】{req.issue.get('problem') or ''}\n"
            f"【修改建议】{req.issue.get('suggestion') or ''}\n"
            f"【简历原文】\n{req.field_text or ''}"
        )
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            # 低温换取稳定：仍不保证可复现，但减少无谓波动
            "temperature": self.temperature,
            "stream": False,
        }

    def _endpoint(self) -> str:
        return normalize_base_url(self.base_url)

    def ping(self) -> tuple[bool, str]:
        """连接自检：发一个最小请求，用于前端「测试连接」按钮。

        返回 (是否可用, 说明)。同样遵守"Key 不进说明"的约束。
        """
        try:
            with httpx.Client(timeout=min(self.timeout, 30)) as client:
                resp = client.post(
                    self._endpoint(),
                    headers=self._headers(),
                    json={
                        "model": self.model,
                        "messages": [{"role": "user", "content": "ping"}],
                        "max_tokens": 1,
                        "stream": False,
                    },
                )
        except httpx.TimeoutException:
            return False, "连接超时，请检查接口地址或网络"
        except httpx.HTTPError as exc:
            # 只用异常类型名，避免异常串里可能带的 URL/头信息
            return False, f"无法连接到接口（{type(exc).__name__}），请检查接口地址"
        if resp.status_code in (401, 403):
            return False, "鉴权失败，请检查 API Key"
        if resp.status_code == 404:
            return False, "接口地址不存在，请检查 base_url 与模型名称"
        if resp.status_code >= 400:
            return False, f"接口返回错误状态 {resp.status_code}"
        return True, f"连接成功（模型 {self.model}）"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # ---------- 引擎钩子 ----------

    def _generate(self, req: RewriteRequest) -> tuple[str | None, str]:
        """调用模型生成候选文本。

        任何失败都返回 (None, 说明)——由基类降级为「仅建议」。
        说明文案只描述失败原因，**绝不包含 API Key**。
        """
        if not self.model:
            return None, "未配置模型名称，无法调用"
        endpoint = self._endpoint()
        if not endpoint.startswith(("http://", "https://")):
            return None, "模型接口地址无效，应为 http(s):// 开头的地址"

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    endpoint,
                    headers=self._headers(),
                    json=self.build_payload(req),
                )
        except httpx.TimeoutException:
            return None, f"模型调用超时（{self.timeout}s），已降级为仅建议"
        except httpx.HTTPError as exc:
            return None, f"模型调用网络失败（{type(exc).__name__}），已降级为仅建议"

        if resp.status_code in (401, 403):
            return None, "模型鉴权失败，请检查 API Key"
        if resp.status_code == 404:
            return None, "模型接口或模型名称不存在，请检查配置"
        if resp.status_code == 429:
            return None, "模型调用次数超限，请稍后重试"
        if resp.status_code >= 400:
            # 只报状态码：响应体可能回显请求内容，不宜透出
            return None, f"模型接口返回错误状态 {resp.status_code}，已降级为仅建议"

        try:
            payload = resp.json()
            content = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            return None, "模型返回格式无法解析，已降级为仅建议"

        text = _clean_model_output(content if isinstance(content, str) else "")
        if not text:
            return None, "模型未返回有效内容，已降级为仅建议"
        return text, f"由模型 {self.model} 生成"


def build_engine(
    base_url: str,
    api_key: str,
    model: str,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> AIRewriteEngine:
    """按用户配置构建引擎实例；配置不成立时抛 ValueError。

    放在类定义之后：返回注解在 Python 3.13 及更早版本是**定义时求值**的，
    写在类之前会直接 NameError（本项目曾因此在 3.13 下无法导入）。
    刻意不 import 业务异常：app/optimize/ 是纯逻辑层（设计文档 4.1），
    由调用方（服务层 / 路由层）决定转成哪个错误码。
    """
    normalized = normalize_base_url(base_url or "")
    if not normalized.startswith(("http://", "https://")) or not (model or "").strip():
        raise ValueError("模型配置无效：接口地址需为 http(s):// 开头，且需填写模型名称")
    return AIRewriteEngine(
        base_url=normalized,
        api_key=api_key or "",
        model=(model or "").strip(),
        timeout=timeout,
    )
