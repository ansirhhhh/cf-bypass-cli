# 反检测浏览器自动化工具 —— 技术规格说明书（Specification Document）

> **文档版本**：v1.0 | **编制日期**：2026-07-17 | **状态**：Draft


## 一、项目概述

### 1.1 项目背景

现代网站广泛部署 Cloudflare、Google reCAPTCHA 等风控系统，从**网络协议层、浏览器指纹层、自动化特征层、行为分析层、验证码挑战层**五个维度对访问流量进行综合评估。传统的单一解决方案（如 Playwright + Stealth 插件）已难以应对这些多层次检测。

本项目旨在构建一个**多层次的自动化浏览器工具**，通过“伪装为主、求解为辅”的策略，系统性地解决人机检测问题。

### 1.2 项目目标

| 目标 | 描述 |
|------|------|
| **隐身能力** | 通过源码级指纹伪装，使浏览器在30+检测网站上无异常标记 |
| **行为真实** | 模拟人类鼠标曲线、键盘节奏和滚动模式 |
| **验证码求解** | 集成多种求解渠道（2Captcha、CapSolver、AI模型） |
| **LLM驱动** | 支持自然语言指令驱动的自动化任务编排 |
| **可扩展** | 模块化设计，支持插件式扩展 |

### 1.3 目标用户

- 自动化测试工程师
- 数据采集与爬虫开发者
- AI Agent 开发者
- 合规性安全研究人员


## 二、系统架构

### 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                        用户接口层 (User Interface)                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐    │
│  │  CLI 命令行  │  │  REST API   │  │  LLM 自然语言接口       │    │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     编排层 (Orchestration Layer)                    │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              任务调度器 / 工作流引擎                         │   │
│  │   (支持并发、重试、超时、回调、批处理)                       │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      核心引擎层 (Core Engine)                       │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────────────┐  │
│  │   指纹伪装引擎  │  │  行为模拟引擎  │  │   验证码求解引擎      │  │
│  │ (CloakBrowser) │  │ (Humanize)    │  │ (2Captcha/CapSolver)  │  │
│  └───────────────┘  └───────────────┘  └───────────────────────┘  │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────────────┐  │
│  │  Cloudflare    │  │  reCAPTCHA    │  │   LLM 推理引擎        │  │
│  │  Solver        │  │  Solver       │  │   (视觉/决策)         │  │
│  └───────────────┘  └───────────────┘  └───────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     浏览器层 (Browser Layer)                        │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │      Chromium (源码级C++补丁, 66+ patches)                  │   │
│  │   Canvas / WebGL / Audio / Fonts / GPU / WebRTC / TLS       │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     网络层 (Network Layer)                          │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │         住宅代理池 + IP轮换 + 地域感知                       │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 核心设计原则

1. **分层解耦**：各引擎独立，可插拔组合
2. **渐进式策略**：优先伪装，触发验证码后再求解
3. **可观测性**：全链路日志、指标采集、会话回放
4. **安全合规**：仅限合法测试与内部自动化场景


## 三、核心模块规格

### 3.1 指纹伪装引擎 (Fingerprint Stealth Engine)

**定位**：解决第2-3层防御（浏览器指纹层 + 自动化特征层）

**实现方案**：基于 CloakBrowser 封装，提供 Drop-in Playwright 替代

**核心特性**：

| 特性 | 说明 |
|------|------|
| **源码级补丁** | 66个C++源码级补丁，修改Canvas、WebGL、音频、字体、GPU、屏幕、WebRTC、网络时序、自动化信号、CDP输入行为 |
| **指纹一致性** | 所有指纹在C++层统一修改，非JS注入，检测网站视为真实浏览器 |
| **自动下载** | 首次运行时自动下载定制Chromium二进制（~200MB，缓存于`~/.cloakbrowser/`） |
| **跨平台** | 支持 Python、JavaScript/Node.js、.NET |

**API 规格**：

```python
from cloakbrowser import launch

# 基础用法（完全兼容 Playwright API）
browser = launch(
    headless=False,           # 某些网站检测无头模式
    proxy="http://user:pass@residential-proxy:port",  # 住宅代理
    geoip=True,               # 自动匹配时区和语言环境到代理IP
    humanize=True,            # 人类化鼠标曲线、键盘节奏、滚动模式
    # 以下为扩展参数
    fingerprint_os=["windows"],  # 操作系统指纹
    viewport={"width": 1920, "height": 1080},
)
page = browser.new_page()
page.goto("https://example.com")
# ... 完全兼容 Playwright API
browser.close()
```

### 3.2 行为模拟引擎 (Human Behavior Engine)

**定位**：解决第4层防御（行为分析层）

**实现方案**：集成 `humanize` 能力 + 自定义行为合成

**核心能力**：

| 行为类型 | 模拟方式 |
|----------|----------|
| **鼠标移动** | 贝塞尔曲线轨迹，非线性速度变化 |
| **键盘输入** | 可变延迟（模拟打字速度波动） |
| **页面滚动** | 自然滚动节奏，带停顿和加速 |
| **点击操作** | 带微偏移动画，非精确像素点击 |
| **疲劳模拟** | 长时间操作后行为节奏变慢 |

**API 规格**：

```python
from core.behavior import HumanBehavior

class HumanBehavior:
    def __init__(self, 
                 mouse_speed: float = 1.0,      # 鼠标速度倍率
                 typing_delay_min: int = 50,    # 最小打字延迟(ms)
                 typing_delay_max: int = 250,   # 最大打字延迟(ms)
                 fatigue_enabled: bool = True,  # 启用疲劳模拟
                 scroll_interval: float = 0.5): # 滚动间隔(秒)
        pass
    
    async def move_to(self, page, selector: str, offset: tuple = (0, 0)):
        """贝塞尔曲线移动到目标元素"""
        pass
    
    async def type_text(self, page, selector: str, text: str):
        """模拟人类打字节奏"""
        pass
    
    async def scroll_natural(self, page, target_y: int):
        """自然滚动到目标位置"""
        pass
```

### 3.3 Cloudflare 求解引擎 (Cloudflare Solver)

**定位**：解决 Cloudflare 的 Challenge（Cookie）和 Turnstile（Token）验证

**实现方案**：基于 `cloudflare-solver` 封装

**核心特性**：

| 特性 | 说明 |
|------|------|
| **双模式支持** | Challenge（`cf_clearance` Cookie）和 Turnstile（Token） |
| **异步高性能** | 基于 `asyncio` + Playwright |
| **浏览器池** | 预热的浏览器池消除冷启动开销 |
| **智能缓存** | TTL感知的结果缓存，按域名自动派生过期时间 |
| **批处理** | `solve_batch()` 支持多URL并行求解 |
| **回调钩子** | `on_success` / `on_failure` 钩子 |

**API 规格**：

```python
from cloudflare_solver import CloudflareSolver, ChallengeType, BrowserPool

# 基础用法 - Challenge类型
solver = CloudflareSolver(
    challenge_type=ChallengeType.CHALLENGE,
    headless=True,
    os=["windows"],           # 操作系统指纹伪装
    proxy="http://user:pass@proxy:port",  # 代理支持
)
result = await solver.solve("https://nopecha.com/demo/cloudflare")
# result 包含 cf_clearance cookie

# 基础用法 - Turnstile类型
solver = CloudflareSolver(
    challenge_type=ChallengeType.TURNSTILE,
    headless=True,
)
result = await solver.solve("https://nopecha.com/captcha/turnstile")
# result.token 包含 Turnstile token

# 浏览器池模式（高吞吐场景）
async with BrowserPool(size=3, headless=True, os=["windows"]) as pool:
    solver = CloudflareSolver(
        challenge_type=ChallengeType.TURNSTILE,
        pool=pool,             # 复用预热浏览器
    )
    result = await solver.solve("https://example.com")
```

### 3.4 reCAPTCHA 求解引擎 (reCAPTCHA Solver)

**定位**：解决 Google reCAPTCHA v2/v3 验证

**实现方案**：支持多种求解渠道

#### 3.4.1 免费方案：Audio Challenge Solver

基于 `playwright-recaptcha-solver`，利用 `wit.ai` 语音转文字服务求解音频挑战

```python
# 参考实现（Node.js）
import { solve } from 'playwright-recaptcha-solver';

# 传入URL，自动管理浏览器生命周期
const token = await solve('https://www.google.com/recaptcha/api2/demo');

# 传入已有Page对象
const token = await solve(page, {
    headless: true,
    proxy: 'socks5://127.0.0.1:9060',
    verbose: true,
});
# token 自动填入 g-recaptcha-response
```

#### 3.4.2 付费方案：2Captcha API

```python
from twocaptcha import TwoCaptcha
from playwright.sync_api import sync_playwright

solver = TwoCaptcha('YOUR_API_KEY')

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto('https://example.com')
    
    # 获取 sitekey
    sitekey = page.get_attribute('.g-recaptcha', 'data-sitekey')
    
    # 提交给2Captcha求解
    result = solver.recaptcha(
        sitekey=sitekey,
        url=page.url
    )
    
    # 注入 token
    page.evaluate(f"""
        document.getElementById('g-recaptcha-response').innerHTML = '{result["code"]}';
        callback('{result["code"]}');
    """)
```

#### 3.4.3 付费方案：CapSolver API

CapSolver 提供统一的 `solve()` 方法，组合 `createTask` 和 `getTaskResult`

```python
import requests

# 创建任务
response = requests.post(
    "https://api.capsolver.com/createTask",
    json={
        "clientKey": "YOUR_API_KEY",
        "task": {
            "type": "ReCaptchaV2TaskProxyLess",
            "websiteURL": "https://www.google.com/recaptcha/api2/demo",
            "websiteKey": "6Le-wvkSAAAAAPBMRTvw0Q4Muexq9bi0DJwx_mJ-"
        }
    }
)
task_id = response.json()["taskId"]  # 

# 获取结果（1-10秒后）
result = requests.post(
    "https://api.capsolver.com/getTaskResult",
    json={
        "clientKey": "YOUR_API_KEY",
        "taskId": task_id
    }
)
token = result.json()["solution"]["gRecaptchaResponse"]  # 
```

### 3.5 统一验证码调度器 (Unified CAPTCHA Dispatcher)

**设计目标**：统一管理多种验证码求解渠道，支持 fallback 和优先级策略

**API 规格**：

```python
from core.captcha import CaptchaDispatcher, Provider, CaptchaType

dispatcher = CaptchaDispatcher(
    providers={
        Provider.TWOCAPTCHA: {"api_key": "xxx", "priority": 1},
        Provider.CAPSOLVER: {"api_key": "xxx", "priority": 2},
        Provider.AUDIO_SOLVER: {"priority": 3},
        Provider.LLM_VISION: {"model": "gpt-4-vision", "priority": 4},
    },
    fallback_strategy="next",   # 失败后自动切换到下一个provider
    timeout=120,                # 单次求解超时(秒)
    max_retries=3,
)

# 自动检测并求解
result = await dispatcher.solve(
    page=page,
    captcha_type=CaptchaType.RECAPTCHA_V2,
    context={"sitekey": "xxx", "url": page.url}
)

# 支持的验证码类型
# - RECAPTCHA_V2, RECAPTCHA_V3
# - HCAPTCHA
# - TURNSTILE
# - IMAGE_TO_TEXT
# - GEETEST
```

### 3.6 LLM 推理引擎 (LLM Inference Engine)

**定位**：利用大语言模型实现智能决策、验证码视觉识别和自然语言驱动自动化

#### 3.6.1 视觉验证码识别

利用多模态 LLM（如 GPT-4V、Claude Vision、豆包视觉模型）识别图形验证码。

```python
from core.llm import LLMCaptchaSolver

solver = LLMCaptchaSolver(
    provider="openai",          # 或 "anthropic", "doubao"
    model="gpt-4-vision-preview",
    api_key="YOUR_API_KEY",
)

# 截取验证码区域，调用LLM识别
captcha_image = await page.screenshot(
    selector=".captcha-image"
)
result = await solver.solve_image(
    image_base64=captcha_image,
    instruction="请识别图片中的字符，只返回结果",
)
# result = "ABCD1234"
await page.fill(".captcha-input", result)
```

#### 3.6.2 自然语言驱动的浏览器自动化

用户通过自然语言描述任务，LLM 解析后生成 Playwright 操作序列。

```python
from core.llm import LLMAgent

agent = LLMAgent(
    provider="openai",
    model="gpt-4",
    browser=stealth_browser,
)

# 自然语言指令
await agent.execute(
    "打开 example.com，找到登录按钮，点击后输入用户名 admin，密码 123456，然后提交"
)

# 内部流程：
# 1. LLM 解析指令 → 生成操作序列
# 2. 通过 Playwright 执行操作
# 3. 遇到验证码 → 调用 CaptchaDispatcher
# 4. 遇到风控 → 调整行为策略
```

#### 3.6.3 智能决策与自适应策略

LLM 根据页面反馈动态调整策略：

```python
from core.llm import AdaptiveStrategy

class AdaptiveStrategy:
    async def analyze_page(self, page) -> dict:
        """LLM分析页面状态，返回风险等级和建议策略"""
        screenshot = await page.screenshot()
        html = await page.content()
        
        response = await self.llm.chat([
            {"role": "system", "content": "你是反检测专家，分析页面是否触发了风控"},
            {"role": "user", "content": [
                {"type": "image", "image": screenshot},
                {"type": "text", "text": f"页面HTML片段: {html[:2000]}... 请判断是否触发验证码或风控"}
            ]}
        ])
        return {
            "has_captcha": True/False,
            "captcha_type": "recaptcha/turnstile/hcaptcha",
            "risk_level": "low/medium/high",
            "suggested_action": "retry/change_proxy/use_humanize"
        }
```

### 3.7 网络与代理层 (Network & Proxy Layer)

**API 规格**：

```python
from core.proxy import ProxyManager, ProxyType

proxy_manager = ProxyManager(
    providers=[
        {"type": "residential", "url": "http://user:pass@res-proxy:port"},
        # 支持轮换池
    ],
    rotation_strategy="round_robin",  # 或 "random", "least_used"
    health_check_interval=60,          # 健康检查间隔(秒)
    geo_preference="US",               # 地域偏好
)

# 自动获取可用代理
proxy = await proxy_manager.get_proxy(geo="US")

# 在浏览器中使用
browser = launch(proxy=proxy.url, geoip=True)
```


## 四、API 接口设计

### 4.1 REST API

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/v1/session` | POST | 创建隐身浏览器会话 |
| `/api/v1/session/{id}` | DELETE | 销毁会话 |
| `/api/v1/session/{id}/navigate` | POST | 导航到URL（自动处理风控） |
| `/api/v1/session/{id}/screenshot` | GET | 截取当前页面 |
| `/api/v1/session/{id}/execute` | POST | 执行Playwright操作脚本 |
| `/api/v1/captcha/solve` | POST | 独立验证码求解API |
| `/api/v1/agent/execute` | POST | LLM自然语言指令执行 |
| `/api/v1/health` | GET | 服务健康检查 |

### 4.2 请求/响应示例

**创建会话**：

```json
POST /api/v1/session
{
    "headless": false,
    "proxy": {
        "url": "http://user:pass@proxy:8080",
        "geoip": true
    },
    "humanize": true,
    "fingerprint": {
        "os": "windows",
        "viewport": {"width": 1920, "height": 1080}
    },
    "captcha": {
        "providers": ["twocaptcha", "capsolver"],
        "fallback": true
    }
}

Response:
{
    "session_id": "sess_abc123",
    "ws_endpoint": "ws://localhost:9222/devtools/browser/xxx",
    "status": "ready",
    "fingerprint_score": 0.95
}
```

**LLM指令执行**：

```json
POST /api/v1/agent/execute
{
    "session_id": "sess_abc123",
    "instruction": "访问 https://example.com，如果出现验证码就自动处理，然后提取页面标题",
    "llm_config": {
        "provider": "openai",
        "model": "gpt-4"
    }
}

Response:
{
    "task_id": "task_xyz789",
    "status": "completed",
    "result": {
        "title": "Example Domain",
        "captcha_solved": true,
        "execution_time_ms": 3450
    },
    "steps": [
        {"action": "navigate", "url": "https://example.com"},
        {"action": "captcha_solve", "provider": "twocaptcha", "duration_ms": 2300},
        {"action": "extract", "selector": "title", "value": "Example Domain"}
    ]
}
```


## 五、技术选型

| 组件 | 技术选型 | 说明 |
|------|----------|------|
| **浏览器引擎** | Chromium (CloakBuilder定制版) | 源码级C++补丁 |
| **自动化框架** | Playwright (兼容层) | CloakBrowser提供完全兼容的API |
| **指纹伪装** | CloakBrowser (66 C++ patches) | Canvas/WebGL/Audio/WebRTC等 |
| **行为模拟** | 自研 + CloakBrowser humanize | 贝塞尔曲线、打字节奏 |
| **Cloudflare求解** | cloudflare-solver | 异步Python，支持Challenge+Turnstile |
| **reCAPTCHA求解** | playwright-recaptcha-solver (免费) | wit.ai语音转文字 |
| **付费求解** | 2Captcha / CapSolver API | 支持多种验证码类型 |
| **LLM集成** | OpenAI API / Anthropic / 豆包 | 视觉识别、自然语言驱动 |
| **编程语言** | Python 3.10+ / Node.js 18+ | 双语言支持 |
| **代理支持** | 住宅代理 (BrightData/oxylabs等) | 自带或自带 |


## 六、部署与运维

### 6.1 部署架构

```
┌────────────────────────────────────────────────────────┐
│                   负载均衡 (Nginx/ALB)                  │
└────────────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│  API Server 1 │ │  API Server 2 │ │  API Server 3 │
│  (CloakBrowser│ │  (CloakBrowser│ │  (CloakBrowser│
│   + Engines)  │ │   + Engines)  │ │   + Engines)  │
└───────────────┘ └───────────────┘ └───────────────┘
        │                   │                   │
        └───────────────────┼───────────────────┘
                            ▼
              ┌─────────────────────────┐
              │   Redis (会话缓存/队列)   │
              └─────────────────────────┘
                            │
                            ▼
              ┌─────────────────────────┐
              │   代理池 (住宅代理)       │
              └─────────────────────────┘
```

### 6.2 环境要求

| 要求 | 规格 |
|------|------|
| **操作系统** | Linux (Ubuntu 20.04+) / macOS / Windows |
| **CPU** | 2核+ (推荐4核) |
| **内存** | 4GB+ (推荐8GB) |
| **磁盘** | 2GB+ (CloakBrowser binary ~200MB) |
| **Python** | 3.10+ |
| **Node.js** | 18+ (JavaScript版本) |

### 6.3 环境变量

```bash
# API Keys
TWOCAPTCHA_API_KEY=your_2captcha_key
CAPSOLVER_API_KEY=your_capsolver_key
OPENAI_API_KEY=your_openai_key
ANTHROPIC_API_KEY=your_anthropic_key
DOUBAO_API_KEY=your_doubao_key

# 代理配置
PROXY_POOL_URL=http://proxy-provider:port
PROXY_USERNAME=user
PROXY_PASSWORD=pass

# 服务配置
API_PORT=8080
MAX_CONCURRENT_SESSIONS=10
SESSION_TIMEOUT=300
LOG_LEVEL=INFO
```


## 七、安全与合规声明

> ⚠️ **重要提示**：
>
> 1. 本工具**仅供合法的自动化测试、安全研究、内部工作流自动化**使用。
> 2. 绕过人机验证可能违反目标网站的服务条款（ToS），使用者需自行承担法律风险。
> 3. 禁止将本工具用于：
>    - 非法数据采集或爬取
>    - 账号批量注册或撞库攻击
>    - 任何违反当地法律法规的行为
> 4. CloakBrowser 项目本身明确声明：**不提供验证码破解服务**，目标是**减少验证码出现的概率**。本工具的验证码求解模块仅作为兜底方案。


## 八、版本规划

| 版本 | 里程碑 | 核心功能 |
|------|--------|----------|
| **v0.1** | MVP | CloakBrowser封装 + 基础Playwright兼容 |
| **v0.2** | Alpha | 行为模拟引擎 + 住宅代理集成 |
| **v0.3** | Beta | Cloudflare Solver + reCAPTCHA Solver (2Captcha) |
| **v0.4** | RC | CapSolver集成 + 统一验证码调度器 |
| **v1.0** | GA | LLM推理引擎 + REST API + 完整文档 |
| **v1.1** | 后续 | MCP (Model Context Protocol) 服务化 |


## 九、参考资料

| 项目 | 说明 |
|------|------|
| [CloakBrowser](https://github.com/CloakHQ/CloakBrowser) | 源码级指纹伪装的Chromium |
| [cloudflare-solver](https://github.com/art3m4ik3/cloudflare-solver) | Cloudflare Challenge/Turnstile求解 |
| [playwright-recaptcha-solver](https://www.npmjs.com/package/playwright-recaptcha-solver) | reCAPTCHA音频挑战免费求解 |
| [agentic-stealth-browser](https://github.com/shanewas/agentic-stealth-browser) | 人类行为模拟框架 |
| [2Captcha](https://2captcha.com) | 付费验证码求解服务 |
| [CapSolver](https://docs.capsolver.com) | 付费验证码求解服务 |
| [fingerprint-suite](https://www.npmjs.com/package/fingerprint-suite) | 浏览器指纹生成与注入工具 |

---

