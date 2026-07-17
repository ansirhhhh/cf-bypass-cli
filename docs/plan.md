# cf-bypass-cli 实施计划（Implementation Plan）

> **文档版本**：v1.0 | **编制日期**：2026-07-17 | **适用版本**：v0.1.0 → v2.0
>
> **配套文档**：
> - [project-overview-and-enhancement.md](project-overview-and-enhancement.md) —— 项目解读与增强总览
> - [tasks.md](tasks.md) —— 详细任务清单（按 ID 追踪）
> - [updatespec.md](updatespec.md) —— 原始远期愿景 spec
>
> **本文档定位**：将"提升到 98% 成功率"的总览拆解为**可执行、可追踪、可验收**的阶段计划。

---

## 目录

1. [项目愿景与目标](#1-愿景与目标)
2. [北极星指标（North Star）](#2-北极星指标)
3. [阶段规划总览](#3-阶段规划总览)
4. [阶段 1：基础强化（Week 1-2）](#4-阶段-1)
5. [阶段 2：行为层 L5（Week 3-4）](#5-阶段-2)
6. [阶段 3：指纹层 L6（Week 5-6）](#6-阶段-3)
7. [阶段 4：代理池 X2（Week 7-8）](#7-阶段-4)
8. [阶段 5：智能路由 + 重试（Week 9-10）](#8-阶段-5)
9. [阶段 6：可观测性（Week 11-12）](#9-阶段-6)
10. [阶段 7：验证码补全（Week 13-14）](#10-阶段-7)
11. [阶段 8：集成测试与调优（Week 15-16）](#11-阶段-8)
12. [资源需求与团队分工](#12-资源需求)
13. [关键决策记录（ADR 摘要）](#13-adr)
14. [风险登记册（Risk Register）](#14-风险)
15. [发布策略](#15-发布策略)

---

<a id="1-愿景与目标"></a>
## 1. 项目愿景与目标

### 1.1 愿景陈述

> 将 `cf-bypass-cli` 从"单一 Cloudflare 绕过工具"升级为"**生产级反检测 WAF 绕过框架**"，在**混合真实场景**下达到 **98%+ 端到端成功率**，同时保持轻量、可配置、合规。

### 1.2 SMART 目标

| 维度 | 当前基线 | M1 目标 | M2 目标 | 最终目标（v2.0）|
|------|---------|---------|---------|----------------|
| 端到端成功率 | ~85% | 90% | 95% | **98%** |
| 平均响应时间（p50） | 8s | 10s | 12s | ≤15s |
| CAPTCHA 求解成功率 | 0%（无求解器）| 70% | 85% | 95% |
| 代理池支持 | 单 URL | 3 节点 | 10 节点 | 100+ 节点 |
| 单元测试覆盖率 | ~70% | 75% | 80% | **85%** |
| 公开文档完整度 | 70% | 80% | 90% | **100%** |
| CI/CD 可用性 | 无 | PR check | 完整 | 完整 + 性能门禁 |

### 1.3 非目标（明确不做）

为避免范围蔓延，明确**不做**：

- ❌ 不实施 CloakBrowser C++ 源码级修改（不可控）
- ❌ 不引入 Node.js / .NET 多语言 SDK
- ❌ 不做浏览器二进制打包/分发
- ❌ 不内置商业代理（用户自配）
- ❌ 不做"AI Agent 自动编排"等 LLM 驱动（spec §3.6 暂缓）

---

<a id="2-北极星指标"></a>
## 2. 北极星指标（North Star Metric）

> **核心指标**：**混合场景端到端成功率（MSR, Mixed Scenario Success Rate）**

### 2.1 MSR 定义

```
MSR = (成功绕过数 / 总尝试数) × 100%

成功 = 拿到 cf_clearance cookie + 200 OK + HTML 中无 challenge 关键词
```

### 2.2 测量方法

**目标站点池（每日测试集）**：30 个站点，分 4 类：

| 类别 | 数量 | 例子 |
|------|------|------|
| 简单 CF | 8 | example.com, simple-blog.com |
| Managed Challenge | 14 | nopecha.com/demo/cloudflare, medium-fansite.com |
| Bot Manager | 6 | discord.com 部分路径, demoboard 等 |
| 强检测（DataDome/HCaptcha） | 2 | niche-forum-with-datadome.com |

**测试方法**：
- 每日 CI 跑 3 轮（每轮 30 个站点）
- 记录 strategy_used、duration、success
- 输出到 `metrics.db`（阶段 6 引入）
- 仪表盘可视化

### 2.3 关键子指标

| 子指标 | 目标 | 用途 |
|--------|------|------|
| L1 命中率 | 30% | 防止 L1 退化 |
| L4 命中率 | 90% | 防止 L4 退化 |
| 缓存命中率 | 60% | 衡量快速通道价值 |
| CAPTCHA 求解率 | 95% | 阶段 7 目标 |
| p99 响应时间 | ≤60s | 用户体验底线 |
| 代理池健康度 | 95% | 阶段 4 目标 |

---

<a id="3-阶段规划总览"></a>
## 3. 阶段规划总览

### 3.1 时间线

```
Week:  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16
       ├──┴──┤  ├──┴──┤  ├──┴──┤  ├──┴──┤  ├──┴──┤  ├──┴──┤  ├──┴──┤
       │ P1  │  │ P2  │  │ P3  │  │ P4  │  │ P5  │  │ P6  │  │ P7  │  │ P8  │
       基础   行为   指纹   代理   路由+   可观测  验证   调优
       强化   L5     L6     池     重试    性            码
```

### 3.2 阶段交付物清单

| 阶段 | 时长 | 主要交付 | 累计 MSR |
|------|------|----------|---------|
| **P1 基础强化** | 2 周 | CaptchaDispatcher 骨架 + reCAPTCHA v2 | 87% |
| **P2 行为层 L5** | 2 周 | `cf_bypass/humanize/` 完整包 | 90% |
| **P3 指纹层 L6** | 2 周 | `cf_bypass/fingerprint/` 完整包 | 93% |
| **P4 代理池 X2** | 2 周 | `cf_bypass/proxy/` 完整包 | 95% |
| **P5 智能路由** | 2 周 | quick_probe + RetryPolicy | 97% |
| **P6 可观测性** | 2 周 | `cf_bypass/observability/` + dashboard | 97% |
| **P7 验证码补全** | 2 周 | reCAPTCHA v3 + hCaptcha + 视觉 LLM | 97.5% |
| **P8 集成调优** | 2 周 | 端到端测试 + 调优 + 文档 | **98%+** |

### 3.3 阶段退出条件（Gate Criteria）

每个阶段结束必须满足：

1. ✅ 所有任务（tasks.md 中该阶段条目）**完成**
2. ✅ 单元测试覆盖率**达标**（本阶段增量 ≥80%）
3. ✅ 集成测试通过（不破坏现有 L1-L4）
4. ✅ 文档同步更新（README/CHANGELOG）
5. ✅ MSR 不低于阶段目标
6. ✅ 代码 review 通过
7. ✅ CI 流水线全绿

未达到退出条件**不得**进入下一阶段。

---

<a id="4-阶段-1"></a>
## 4. 阶段 1：基础强化（Week 1-2）

### 4.1 目标

建立后续工作的基础设施，并补上最急缺的 reCAPTCHA v2 求解能力。

### 4.2 范围

**In Scope**：
- CaptchaDispatcher 抽象
- Turnstile 求解器重构（接入 dispatcher）
- reCAPTCHA v2 求解器（图像 + 音频双路）
- 配置扩展（`captcha` 配置块）
- 单点 CLI 验证：`cf-bypass captcha solve <url>`

**Out of Scope**：
- reCAPTCHA v3（推迟到 P7）
- hCaptcha（推迟到 P7）
- LLM 视觉（推迟到 P7）

### 4.3 交付物

| 编号 | 交付物 | 验收标准 |
|------|--------|----------|
| P1-D1 | `cf_bypass/solvers/dispatcher.py` | 单元测试覆盖 ≥90%，支持 fallback 链 |
| P1-D2 | `cf_bypass/solvers/recaptcha_v2.py` | 在 nopecha.com/demo 成功率 ≥90% |
| P1-D3 | `cf_bypass/solvers/providers/twocaptcha.py` | API 封装完整 + 单元测试 |
| P1-D4 | 配置文件 `captcha.yaml` 解析 | 单元测试 + 示例 |
| P1-D5 | CLI `cf-bypass captcha solve` | 可手动测试 + 集成测试 |
| P1-D6 | 文档更新（README） | 包含新命令、新配置说明 |

### 4.4 风险

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| Capsolver 接口变更 | 中 | 高 | 适配层 + 版本固定 |
| reCAPTCHA 升级 | 中 | 高 | 多个 provider fallback |
| 单元测试 mocks 困难 | 中 | 中 | 用 HTML 夹具 |

### 4.5 退出条件

- [x] P1-D1 ~ P1-D6 全部完成
- [x] `cf-bypass captcha solve https://www.google.com/recaptcha/api2/demo` 成功
- [x] 现有所有测试通过
- [x] MSR ≥ 87%

---

<a id="5-阶段-2"></a>
## 5. 阶段 2：行为层 L5（Week 3-4）

### 5.1 目标

让 L3/L4 浏览器在执行任务时表现出"真人"行为模式，弥补"瞬时出现"特征。

### 5.2 范围

**In Scope**：
- `cf_bypass/humanize/` 包完整实现
- 鼠标轨迹生成（贝塞尔 + 最小急动度）
- 键盘节奏（含大写字母/标点特殊处理）
- 滚动行为（含停顿）
- 集成到 L3 启动前后
- 单元测试 + 行为可视化工具

**Out of Scope**：
- 长时间预热（warm-up 推迟到 P8）
- LLM 驱动行为（不做）

### 5.3 交付物

| 编号 | 交付物 | 验收标准 |
|------|--------|----------|
| P2-D1 | `humanize/trajectory.py` | 单元测试，轨迹图像对比 |
| P2-D2 | `humanize/mouse.py` | Fitts' law 验证 |
| P2-D3 | `humanize/keyboard.py` | 大写/标点节奏测试 |
| P2-D4 | `humanize/scroll.py` | 自然停顿模拟 |
| P2-D5 | 集成到 `level3_playwright.py` | 测试站点 MSR +3pp |
| P2-D6 | 集成到 `level4_nodriver.py` | 测试站点 MSR +3pp |
| P2-D7 | 行为可视化工具（CLI + HTML 输出） | 命令 `cf-bypass visualize-mouse` |

### 5.4 算法验收标准

**鼠标轨迹**：
- 起终点 Fitts' law 减速区符合理论（误差 ≤10%）
- 中段速度峰值 0.5-1.5× 起始速度
- 包含 1-3 个微停顿（30-100ms）

**键盘节奏**：
- 打字间隔均值 ±15% 内可配置
- 包含 1-2% 的错误修正
- 标点/大写后停顿 ≥200ms

### 5.5 风险

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 行为被检测为"模板化" | 中 | 高 | 引入随机种子 + 多种 profile |
| 鼠标移动引入卡顿 | 中 | 中 | 优化轨迹插值算法 |
| 单元测试难写 | 高 | 中 | 引入可视化对照测试 |

### 5.6 退出条件

- [x] P2-D1 ~ P2-D7 全部完成
- [x] L3 启动时自动应用行为层
- [x] L4 启动时自动应用行为层
- [x] 单元测试覆盖率 ≥85%
- [x] MSR ≥ 90%

---

<a id="6-阶段-3"></a>
## 6. 阶段 3：指纹层 L6（Week 5-6）

### 6.1 目标

让每次会话的浏览器指纹具有"真实分布 + 内部一致性"，对抗 FingerprintJS Pro 级别的检测。

### 6.2 范围

**In Scope**：
- `cf_bypass/fingerprint/` 包
- Profile 生成器（真实分布采样）
- Canvas 指纹噪声
- AudioContext 指纹噪声
- 内部一致性校验
- 集成到 L3/L4 启动

**Out of Scope**：
- 字体指纹探测欺骗（推迟 P8）
- 硬件层（GPU）指纹（推迟 P8）

### 6.3 交付物

| 编号 | 交付物 | 验收标准 |
|------|--------|----------|
| P3-D1 | `fingerprint/profile.py` 数据类 | 单元测试 |
| P3-D2 | `fingerprint/generator.py` 采样器 | 分布测试（chi-square） |
| P3-D3 | `fingerprint/canvas.py` 噪声 | 在 fingerprintjs demo 上 hash 变化 |
| P3-D4 | `fingerprint/audio.py` 噪声 | 单元测试 + 浏览器实测 |
| P3-D3 | `fingerprint/consistency.py` 一致性校验 | 100% 规则覆盖 |
| P3-D6 | 集成到 L3 启动 | 自动注入 |
| P3-D7 | 集成到 L4 启动 | 自动注入 |
| P3-D8 | 指纹持久化（per-session 模式） | 单元测试 |

### 6.4 关键算法

**分布采样**（generator.py）：
- OS 分布：Windows 60% / macOS 30% / Linux 10%
- Browser version：从 5 个稳定版本随机（避免太新被检测）
- Locale：从 5 个主用 locale 采样
- Hardware：按真实装机量分布采样

**一致性规则**（consistency.py）：
- `ua_string` 中的 Chrome 版本 = `userAgentData.brands` 中的版本
- `webgl_renderer` 与 `os` 匹配（Apple M1 只在 macOS）
- `viewport` ≤ `screen_resolution`
- `timezone` 与 `locale.region` 匹配

### 6.5 风险

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| Canvas 噪声被识别 | 中 | 高 | 算法可配置（3 种模式） |
| 采样分布与真实不符 | 中 | 中 | 定期用真实设备数据校准 |
| 一致性规则不完整 | 高 | 中 | 用 FingerprintJS 探测清单反推 |

### 6.6 退出条件

- [x] P3-D1 ~ P3-D8 全部完成
- [x] 在 fingerprintjs.com/demo 上 canvas hash 每次不同
- [x] 在 bot.sannysoft.com 上全部检查通过
- [x] MSR ≥ 93%

---

<a id="7-阶段-4"></a>
## 7. 阶段 4：代理池 X2（Week 7-8）

### 7.1 目标

替代单 URL 代理为完整代理池，支持轮换 + 健康检查 + 地域感知。

### 7.2 范围

**In Scope**：
- `cf_bypass/proxy/` 包
- 池化 + 多种轮换策略
- 健康检查 + 自动冷却
- 3 个 provider 适配（BrightData, Oxylabs, 本地文件）
- 配置向后兼容
- CLI 子命令 `cf-bypass proxy list/test`

**Out of Scope**：
- 移动代理（推迟）
- ISP 代理（推迟）

### 7.3 交付物

| 编号 | 交付物 | 验收标准 |
|------|--------|----------|
| P4-D1 | `proxy/pool.py` | 单元测试覆盖 ≥85% |
| P4-D2 | `proxy/rotation.py` 4 种策略 | 单元测试 + 分布验证 |
| P4-D3 | `proxy/quality.py` 评分 | 算法测试 |
| P4-D4 | `proxy/providers/brightdata.py` | 集成测试 |
| P4-D5 | `proxy/providers/oxylabs.py` | 集成测试 |
| P4-D6 | `proxy/providers/file.py` | 单元测试 |
| P4-D7 | 集成到 Orchestrator | MSR +2pp |
| P4-D8 | CLI `cf-bypass proxy list` | 手动测试 |
| P4-D9 | CLI `cf-bypass proxy test` | 手动测试 |
| P4-D10 | 配置文件向后兼容 | 旧 `proxy.url` 仍可用 |

### 7.4 轮换策略

| 策略 | 算法 | 适用场景 |
|------|------|----------|
| `round_robin` | 严格顺序 | 调试、压测 |
| `random` | 均匀随机 | 默认 |
| `weighted` | 按 quality_score 加权 | 生产 |
| `least_used` | 选最久未用 | 长会话 |

### 7.5 风险

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| BrightData 接口变更 | 中 | 中 | 适配层抽象 |
| 代理被 CF 封禁 | 高 | 高 | 池化 + 自动冷却 |
| 成本失控 | 中 | 中 | 成本监控 + 告警 |

### 7.6 退出条件

- [x] P4-D1 ~ P4-D10 全部完成
- [x] 旧配置文件无需修改即可运行
- [x] 池中 50% 节点健康时整体仍可用
- [x] MSR ≥ 95%

---

<a id="8-阶段-5"></a>
## 8. 阶段 5：智能路由 + 重试（Week 9-10）

### 8.1 目标

让 Orchestrator 从"按 level 硬 fallback"升级为"按页面响应智能路由"。

### 8.2 范围

**In Scope**：
- Orchestrator 引入 `quick_probe()` 阶段
- RetryPolicy 智能重试
- 错误分类（硬失败/软失败）
- 兼容默认行为（开关控制）

**Out of Scope**：
- ML 模型预测（不做）
- 自适应策略学习（不做）

### 8.3 交付物

| 编号 | 交付物 | 验收标准 |
|------|--------|----------|
| P5-D1 | `orchestrator.py` 增加 `quick_probe()` | 单元测试 |
| P5-D2 | `cf_bypass/retry.py` RetryPolicy | 单元测试 |
| P5-D3 | 错误分类器（软/硬） | 分类规则文档化 |
| P5-D4 | Orchestrator 集成 RetryPolicy | 配置开关 |
| P5-D5 | 性能对比报告（开关前后） | 文档化 |
| P5-D6 | 文档：路由决策表 | README + 注释 |

### 8.4 quick_probe 决策表

| 探测结果 | 起始 Level | 理由 |
|----------|----------|------|
| 200 + cf_clearance | 1 | 缓存已生效 |
| 200 + challenge 关键词 | 3 | JS 挑战，跳 L3 |
| 200 + turnstile 标识 | 4 | 需浏览器内交互 |
| 403 | 3 | UA/IP 问题，升级浏览器 |
| 503 | 2 | 暂时限流，重试 |
| timeout | 1 | 网络问题 |

### 8.5 风险

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 探测本身被检测 | 中 | 中 | 探测请求伪装为正常 |
| 重试触发更多封禁 | 中 | 高 | 退避 + 熔断 |
| 决策表不准确 | 中 | 中 | 持续观察 + 调优 |

### 8.6 退出条件

- [x] P5-D1 ~ P5-D6 全部完成
- [x] 默认行为不变（向后兼容）
- [x] 启用 smart routing 后 p50 降低
- [x] MSR ≥ 97%

---

<a id="9-阶段-6"></a>
## 9. 阶段 6：可观测性（Week 11-12）

### 9.1 目标

每次 bypass 全链路可观测、可回放、可分析。

### 9.2 范围

**In Scope**：
- `cf_bypass/observability/` 包
- 指标持久化（SQLite）
- 简单 HTML dashboard（端口 8192）
- `cf-bypass stats` CLI

**Out of Scope**：
- 完整 Grafana 集成（不做）
- 远程 telemetry（不做，**合规考虑**）

### 9.3 交付物

| 编号 | 交付物 | 验收标准 |
|------|--------|----------|
| P6-D1 | `observability/metrics.py` 数据类 | 单元测试 |
| P6-D2 | `observability/storage.py` SQLite 持久化 | 单元测试 |
| P6-D3 | `observability/dashboard.py` FastAPI | 集成测试 |
| P6-D4 | 集成到 Orchestrator 自动记录 | 不阻塞主流程 |
| P6-D5 | CLI `cf-bypass stats` | 手动测试 |
| P6-D6 | Dashboard 页面（趋势图 + 表格） | 可视化验证 |

### 9.4 仪表盘核心指标

- MSR 趋势（按天 / 按域 / 按策略）
- 缓存命中率
- 代理池健康度
- 验证码求解率
- 响应时间分布（p50/p95/p99）
- 失败原因分类（top 10）

### 9.5 风险

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| SQLite 写入阻塞 | 低 | 中 | 异步 + 批量 |
| Dashboard 暴露敏感信息 | 中 | 中 | 默认仅 127.0.0.1 监听 |
| 数据量爆炸 | 中 | 低 | 自动归档 30 天前数据 |

### 9.6 退出条件

- [x] P6-D1 ~ P6-D6 全部完成
- [x] 每日 1000 次 bypass 仍能流畅查询
- [x] Dashboard 可视化所有核心指标
- [x] MSR 不退化（仍 ≥97%）

---

<a id="10-阶段-7"></a>
## 10. 阶段 7：验证码补全（Week 13-14）

### 10.1 目标

把 reCAPTCHA v3、hCaptcha 接入 dispatcher，可选 LLM 视觉兜底。

### 10.2 范围

**In Scope**：
- reCAPTCHA v3 求解（基于 score）
- hCaptcha 求解
- LLM 视觉求解器（OpenAI 兼容）
- 集成到 dispatcher 链

**Out of Scope**：
- Geetest（不做）
- FunCaptcha（不做）

### 10.3 交付物

| 编号 | 交付物 | 验收标准 |
|------|--------|----------|
| P7-D1 | `solvers/recaptcha_v3.py` | 集成测试 |
| P7-D2 | `solvers/hcaptcha.py` | 集成测试 |
| P7-D3 | `solvers/image_captcha.py` | 集成测试 |
| P7-D4 | `solvers/providers/llm_vision.py` | 单元测试 + 集成 |
| P7-D5 | 集成到 dispatcher 链 | 配置驱动 |
| P7-D6 | `image` 类型 fallback 到 LLM | 验证 |

### 10.4 风险

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| reCAPTCHA v3 score 不可控 | 中 | 中 | 默认 0.9，可配置 |
| LLM 成本 | 中 | 低 | 仅作 fallback |
| hCaptcha 难度上升 | 中 | 中 | 多 provider |

### 10.5 退出条件

- [x] P7-D1 ~ P7-D6 全部完成
- [x] CAPTCHA 求解率 ≥95%
- [x] 单元测试 + 集成测试通过
- [x] MSR ≥ 97.5%

---

<a id="11-阶段-8"></a>
## 11. 阶段 8：集成测试与调优（Week 15-16）

### 11.1 目标

端到端压测、调优达到 98% 目标，文档齐全。

### 11.2 范围

**In Scope**：
- 100+ 目标站点压测
- 指纹分布调优
- 性能调优（响应时间）
- 完整文档
- 发布 v2.0

**Out of Scope**：
- 多语言 SDK
- 商业化打包

### 11.3 交付物

| 编号 | 交付物 | 验收标准 |
|------|--------|----------|
| P8-D1 | 100 站点测试集 | 每日 CI 跑通 |
| P8-D2 | 调优报告 | MSR ≥ 98% |
| P8-D3 | 完整 README 改写 | 与代码同步 |
| P8-D4 | CHANGELOG.md | 完整变更记录 |
| P8-D5 | 性能基准报告 | p50 ≤15s |
| P8-D6 | v2.0 发布（GitHub release） | 公开 |

### 11.4 调优方向

1. **指纹分布** —— 用真实设备统计调权重
2. **行为参数** —— 用成功率反推最优
3. **路由决策** —— 用历史数据训练决策表
4. **代理权重** —— 持续淘汰低质量节点

### 11.5 退出条件

- [x] P8-D1 ~ P8-D6 全部完成
- [x] 7 天连续 MSR ≥ 98%
- [x] 公开文档完整
- [x] v2.0 发布

---

<a id="12-资源需求"></a>
## 12. 资源需求与团队分工

### 12.1 人力

> 注：以下假设为**单人**主开发 + 兼职协作。若团队更大可并行多个阶段。

| 角色 | 投入 | 阶段 |
|------|------|------|
| 主开发（Python + 浏览器自动化）| 100% | 全程 |
| 兼职（CAPTCHA 供应商对接）| 20% | P1, P7 |
| 测试协助 | 20% | P2-P8 |
| 文档 | 10% | P6, P8 |

### 12.2 第三方服务

| 服务 | 用途 | 阶段 | 预估月成本 |
|------|------|------|----------|
| Capsolver | CAPTCHA 求解 | P1-P8 | $50-200 |
| 2Captcha | CAPTCHA 备用 | P1-P8 | $50-200 |
| BrightData 代理 | 测试代理池 | P4-P8 | $100-500 |
| OpenAI API | LLM 视觉（仅 fallback）| P7-P8 | $20-50 |
| GitHub Actions | CI | 全程 | 免费层 |
| 测试 VPS | 端到端测试 | P6-P8 | $20 |

**总月成本预算**：$240-970（与代理/CAPTCHA 用量正相关）

### 12.3 基础设施

- GitHub Actions（CI）：免费
- 1 台测试 VPS（Ubuntu 22.04）：2 核 4GB
- 本地开发机：Windows + WSL2（已有）

---

<a id="13-adr"></a>
## 13. 关键决策记录（ADR 摘要）

> 完整 ADR 见 [docs/adr/](adr/)（后续补充）。此处仅列摘要。

| 编号 | 决策 | 理由 | 替代方案 | 状态 |
|------|------|------|----------|------|
| ADR-001 | 不实施 CloakBrowser C++ 修改 | 不可控 + 维护成本极高 | JS 层增强 + 商业服务 | ✅ 采纳 |
| ADR-002 | L5 行为层使用贝塞尔 + 最小急动度 | 学术最优 + 业界主流 | 简单线性 + 抖动 | ✅ 采纳 |
| ADR-003 | L6 指纹用"真实分布采样" | 避免硬编码被反指纹 | 固定档案 | ✅ 采纳 |
| ADR-004 | 代理池存储用内存 + 持久化到 JSON | 简单 + 可读 | Redis | ✅ 采纳（v2.0） |
| ADR-005 | 可观测性用 SQLite | 零依赖 | Postgres/InfluxDB | ✅ 采纳 |
| ADR-006 | 不内置商业代理 | 合规 + 灵活性 | 内置 | ✅ 采纳 |
| ADR-007 | 不实施多语言 SDK | 资源限制 + 需求不明 | Node.js / Go | ✅ 采纳 |
| ADR-008 | LLM 仅作 CAPTCHA fallback | 成本 + 不确定 | 全 LLM 驱动 | ✅ 采纳 |
| ADR-009 | 默认不启用 smart routing | 向后兼容 | 默认启用 | ✅ 采纳 |
| ADR-010 | reCAPTCHA v3 score 目标 0.9 | 大多数站点接受 | 0.7 / 0.8 | ✅ 采纳 |

---

<a id="14-风险"></a>
## 14. 风险登记册（Risk Register）

### 14.1 高级风险（需主动管理）

| ID | 风险 | 概率 | 影响 | 缓解策略 | 责任人 | 触发条件 |
|----|------|------|------|----------|--------|----------|
| R-01 | Cloudflare 升级签名（误判激增） | 高 | 高 | 持续监控 + 快速回滚 + 渐进式发布 | 主开发 | MSR 单日下降 >5pp |
| R-02 | 主流 CAPTCHA 服务涨价 | 中 | 中 | 多 provider + 成本监控 | 主开发 | 月成本 >$500 |
| R-03 | 代理 IP 池被大规模封禁 | 中 | 高 | 健康检查 + 冷却 + 多 provider | 主开发 | 池健康度 <70% |
| R-04 | 法律/合规风险 | 低 | 高 | 文档声明 + 不内置商业代理 | 主开发 | 收到投诉 |
| R-05 | 指纹噪声被检测算法升级 | 中 | 中 | 3 种噪声算法可切换 | 主开发 | fingerprintjs 检测率上升 |
| R-06 | 浏览器升级破坏 stealth | 中 | 中 | 锁版本 + 灰度升级 | 主开发 | Playwright/Chrome 大版本 |
| R-07 | 单元测试覆盖率不足 | 中 | 中 | 阶段门禁 | 主开发 | 覆盖率 <80% |
| R-08 | 性能回退（响应时间变长） | 中 | 中 | 性能基准 CI | 主开发 | p50 >20s |

### 14.2 风险评审节奏

- **每周一**：站会评审当前阶段风险
- **每阶段结束**：完整风险评审 + 更新登记册
- **每月**：第三方服务成本 + 稳定性评审

---

<a id="15-发布策略"></a>
## 15. 发布策略

### 15.1 版本号约定

遵循语义化版本：

- **v0.x** —— 当前阶段（小特性迭代）
- **v1.0** —— v1 GA（基础可用）
- **v1.x** —— 维护版本（小幅特性）
- **v2.0** —— **本文档目标版本**（98% MSR）

### 15.2 发布节奏

| 版本 | 时间 | 范围 |
|------|------|------|
| v0.2.0 | P1 完成 | + CaptchaDispatcher + reCAPTCHA v2 |
| v0.3.0 | P2 完成 | + L5 行为层 |
| v0.4.0 | P3 完成 | + L6 指纹层 |
| v0.5.0 | P4 完成 | + 代理池 |
| v0.6.0 | P5 完成 | + 智能路由 |
| v0.7.0 | P6 完成 | + 可观测性 |
| v0.8.0 | P7 完成 | + 验证码补全 |
| **v2.0.0** | P8 完成 | 98% MSR 目标达成 |

### 15.3 发布门禁

每个版本发布前必须：

1. ✅ 所有阶段任务完成
2. ✅ 单元测试覆盖率 ≥85%
3. ✅ 集成测试通过
4. ✅ 7 天连续 MSR 达标
5. ✅ 文档同步更新
6. ✅ CHANGELOG 完整
7. ✅ 性能基准无回退

### 15.4 回滚策略

- **快速回滚**：保留旧版本分支（`release/v1.x`）
- **灰度发布**：先发布 `v0.x.0-beta` → 1 周观察 → 稳定后 `v0.x.0`
- **特性开关**：P5 的 smart routing、P6 的可观测性默认关闭，需用户显式启用

### 15.5 沟通计划

| 事件 | 渠道 | 频率 |
|------|------|------|
| 阶段完成 | GitHub release + Discord | 每 2 周 |
| 重大风险 | Email 通知 | 实时 |
| 月度报告 | 博客 | 每月 |
| 路线图更新 | README + 文档 | 每月 |

---

## 附录 A：阶段依赖图

```
P1 ─┐
    ├─→ P2 ─┐
P1 ─┘      ├─→ P3 ─┐
           P2 ─┘    ├─→ P4 ─┐
                    P3 ─┘    ├─→ P5 ─┐
                             P4 ─┘    ├─→ P6 ─┐
                                      P5 ─┘    ├─→ P7 ─┐
                                                P6 ─┘    ├─→ P8 → v2.0
                                                          P7 ─┘
```

P1 必先；P2-P4 可有限并行（但建议串行以减少冲突）；P5-P8 严格串行。

## 附录 B：成功定义（DoD）

> "v2.0 完成" = 满足**所有**以下条件：

- [ ] MSR ≥ 98%（7 天滚动平均）
- [ ] p50 ≤ 15s，p99 ≤ 60s
- [ ] 单元测试覆盖率 ≥ 85%
- [ ] 公开文档完整（README + CHANGELOG + 增强文档 + tasks.md）
- [ ] 100 站点测试集纳入 CI
- [ ] 至少 2 个 CAPTCHA provider
- [ ] 至少 1 个代理 provider
- [ ] Dashboard 可视化全部核心指标
- [ ] 合规声明完整

---

**下一步**：

1. 把本文档（`plan.md`）和 [tasks.md](tasks.md) 发给团队评审
2. 启动 P1 任务分配
3. 建立 `metrics.db` 跟踪 MSR
4. 设置 CI 流水线
