# 专业团队修复建议

> 针对 `cf-bypass-cli` 在生产环境中对抗 Cloudflare WAF 的优化方案。
>
> 生成日期：2026-07-15

---

## 1. 集成专用 Turnstile 求解器（高优）

**问题**：L4（nodriver）目前仅通过被动等待来处理 `challenge-platform` 这类交互式挑战，无法主动求解 Turnstile。

**现状**（`cf_bypass/strategies/level4_nodriver.py:100-111`）：

```python
if challenge:
    logger.info(f"Challenge detected: '{challenge}' — waiting longer...")
    await page.sleep(10)  # 仅被动等待 10 秒
    html = await page.get_content() or ""
    challenge = _detect_challenge(html)
    if challenge:
        logger.warning(f"Challenge still present...")
```

**建议**：
- 集成专用求解库（如 `cloudflare-solver`），在检测到 Turnstile 时主动调用求解逻辑
- 对接打码平台 API（2captcha / Anti-Captcha / Capsolver），自动完成图片识别类挑战
- 实现 Turnstile token 的自动提取与提交

**参考代码结构**：

```python
# 新增 cf_bypass/solvers/turnstile.py
class TurnstileSolver:
    async def solve(self, page, sitekey: str) -> Optional[str]:
        """Solve Turnstile challenge and return token."""
        ...
```

---

## 2. 升级隐身方案（中优）

**问题**：Playwright 的 `playwright-stealth` 插件在 JavaScript 层面修补指纹，Cloudflare 可通过更底层的检测绕过这些修补。

**现状**（`cf_bypass/strategies/level3_playwright.py:115-116`）：

```python
stealth = Stealth()
await stealth.apply_stealth_async(page)
```

**建议**：
- 考虑将隐身方案升级为更底层的工具，如 **CloakBrowser**（C++ 源码层修改 Chromium 指纹）
- 或使用 **rebrowser-patches** / **undetected-chromedriver** 等经过深度修改的浏览器内核
- 在 L3 和 L4 之间增加差异化隐身层次，避免两条路径使用相同的指纹修改策略
- 长期可探索 **CreepJS** 等指纹检测工具进行隐身效果验证，建立回归测试基线

---

## 3. 配置高质量住宅代理（高优）

**问题**：目标站点（如 `whitepages.com.au`）有地理封锁，数据中心 IP 极易被 Cloudflare 标记。

**现状**（`cf_bypass/config.py`）：仅支持通用代理配置，无代理质量分级。

**建议**：
- 必须使用目标国家（如澳大利亚）的**住宅 IP 代理**
- 对接住宅代理服务商（Bright Data / IPRoyal / Oxylabs / Smartproxy）
- 在配置中区分代理类型，增加代理健康检查（延迟、地域验证、IP 类型检测）

**参考配置扩展**：

```yaml
# ~/.cf-bypass/config.yaml
proxy:
  enabled: true
  url: "http://user:pass@residential-proxy:8080"
  type: "residential"        # residential | datacenter | mobile
  geo_required: "AU"         # 目标国家代码
  health_check: true         # 启动前验证代理可用性
```

---

## 4. 优化 nodriver 等待逻辑（中优）

**问题**：L4 在检测到 `challenge-platform` 后仅硬编码等待 10 秒，对于复杂或慢速挑战不够。

**现状**（`cf_bypass/strategies/level4_nodriver.py:89-105`）：

```python
settle_seconds = max(8, min(timeout // 2, 20))  # 初始等待 8-20s
# ...
if challenge:
    await page.sleep(10)  # 额外等待固定 10s
```

**建议**：
- 将固定等待改为**轮询检测 + 指数退避重试**：

```python
async def _wait_for_challenge_resolution(page, timeout: int = 60):
    """Poll until challenge disappears or timeout."""
    deadline = time.time() + timeout
    interval = 2  # 初始轮询间隔
    while time.time() < deadline:
        html = await page.get_content()
        challenge = _detect_challenge(html)
        if not challenge:
            return True  # 挑战已解除
        await page.sleep(interval)
        interval = min(interval * 1.5, 10)  # 指数退避，上限 10s
    return False
```

- 增加可配置的 `challenge_timeout` 参数，允许用户根据目标站点调整
- 加入重试机制：单次超时后可自动重新加载页面并再次尝试

---

## 5. 增加人工干预接口（低优）

**问题**：当所有自动策略均失败时，需要一种方式让用户手动介入完成验证。

**建议**：
- 在交互模式下，L4 检测到无法自动通过的挑战时：
  1. 暂停自动化流程
  2. 在终端输出提示信息（含剩余超时时间）
  3. 用户手动在浏览器窗口中完成验证（点击、滑动等）
  4. 检测到挑战消失后自动继续提取 Cookie 和 HTML
- 在 HTTP API 模式下返回特定状态码（如 `202` + `challenge_required: true`），由调用方决定是否切换为手动模式

**参考实现**：

```python
# level4_nodriver.py 中的扩展
if challenge and not headless:
    logger.info(
        "⚠️  Challenge requires manual intervention. "
        "Please complete the verification in the browser window. "
        f"Waiting up to {manual_timeout}s..."
    )
    resolved = await _wait_for_challenge_resolution(page, timeout=manual_timeout)
    if resolved:
        logger.info("✅ Challenge resolved manually, continuing...")
    else:
        logger.warning("⏰ Manual intervention timeout, returning partial result")
```

---

## 优先级总览

| 优先级 | 建议 | 影响范围 | 预估工作量 |
|--------|------|----------|-----------|
| 🔴 高优 | 集成专用 Turnstile 求解器 | L4 / 新增 solver 模块 | 3-5 天 |
| 🔴 高优 | 配置高质量住宅代理 | config / proxy 模块 | 1-2 天 |
| 🟡 中优 | 升级隐身方案 | L3 / L4 | 2-4 天 |
| 🟡 中优 | 优化 nodriver 等待逻辑 | L4 | 0.5-1 天 |
| 🟢 低优 | 增加人工干预接口 | L4 / CLI / HTTP API | 1-2 天 |
