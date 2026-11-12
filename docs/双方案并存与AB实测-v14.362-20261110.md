# 双方案并存 + A/B 实测（v14.362）

日期：2026-11-10
构建：`minimax-h3-extender-v14.362-viggle-tier+upscaler-probe+os-route-standby`

## 一、用户提议与我的判断

用户提议「两套都做保留，用开关切换」。结论：**代码两套都保留（已做），但不建议做成环境变量/档位开关**，理由如下。

| 维度 | 环境变量开关 | 守卫式组合（推荐） |
|---|---|---|
| 参数位置 | 不动 widget ✓ | 不动 widget ✓ |
| 需要人工切换 | 是（每次要想着切） | 否（按文本自动选） |
| 主流程改动量 | 要把一镜到底段复制成两条分支常驻 | 只加一层 if，两条路径各用所长 |
| 维护成本 | 以后每次改一镜到底都要同步两条路 | 单一路径 |
| 真机验证 | 两条路径都要跑 | 一条路径 |

关键原因：v14.339 那 290 行不是「一个函数返回一段文本」，而是嵌在一镜到底主流程的 10 个挂接点里（`_os_scene_routes.append`、`_os_transit_site` 判定、`[段首承接]` / `[One Continuous Take]` 注入等）。做成双分支等于把主流程复制一遍。

## 二、本次实际动作

把 v14.339 独有的两套实现**原样搬入** v14.362，**当前无任何调用点**，运行行为零变化：

| 符号 | 行数 | 说明 |
|---|---|---|
| `_OS_TIMECODE_RE` + `_one_shot_normalize_timecodes` | 58 | v14.341 正文时间码「平移归一」（对现有 v14.300「直接剥离」的替代方案） |
| `_OS_EMPTY_PAREN_RE` / `_OS_ROUTE_TAG_RE` / `_OS_ROUTE_NAME_CUT_RE` | 3 | 行程解析用正则 |
| `_one_shot_scene_route(text, catalog)` | 60 | 解析「起行空间 → 过渡物 → 终止空间」，返回 start/end/transit/cross/route |
| `_one_shot_transit_mid_rule(start, end, transit)` | 86 | 段中换场规则（v14.343→v14.344→v14.347 三轮实机修正后的版本） |
| `_one_shot_scene_anchor_mid_rule(start, end, transit)` | 11 | 场景锚定 |
| `_one_shot_space_decision(routes, i, names)` | 25 | 接缝优先的空间判定，输出 (scene, prev, kind, site) |

合计 252 行，全部为自包含纯函数（只依赖 `re` 与入参，不读全局状态）。

验证：`py_compile rc=0`；离线加载 `required 65 + optional 29 = 94`、`render_pipeline 37 项`、`viggle_faceswap` widget 残留 False、8 个新符号全部 OK；写回 1,035,346 B。

## 三、A/B 实测（用工作流里的真实文本）

样本取自 v15 工作流的真实节点（不是造数据）：

1. **样本 node=75**《BSAI_H3_Film_Factory_分镜脚本》493 字 —— 当前 V2V 替换档的脚本（纯描述，无 S/T 行程）
2. **样本 node=152**《ShowText》154 字 —— 含行程写法 `S20 故宫·午门城台拱门@图22(黎明)…`
3. **样本 node=149**《ShowText》137 字 —— 场景描述片段，无标签

### 结果

| 样本 | A 现役 `_one_shot_scene_name` | B `_one_shot_scene_route` |
|---|---|---|
| node=152（行程文本） | `"S20 故宫·午门城台拱门"` ✓ | `start="S20 故宫·午门城台拱门"`, `end` 同, `transit=None`, `cross=False` ✓ |
| node=75（纯描述） | `None` ✓（正确拒识） | `start="把 @视频1 里那位人物换成"` ✗ **误解析** |
| node=149（片段） | `None` ✓ | `start=None` ✓ |

### 三条结论

1. **单场景/多场景行程上两套解析结果一致** —— 样本 2 两边都得到 `S20 故宫·午门城台拱门`。B 并不比 A 更准。
2. **B 的真实增量是结构化信息** —— `transit`（段中要跨过的过渡物）与 `cross`（是否真跨场景），A 只给一个场景名，给不出这两项。
3. **B 有两个必须加的守卫**：
   - 对**非行程文本会误解析**：node=75 里把普通句子 `把 @视频1 里那位人物换成` 当成了场景名（正则 `[ST]\d` 在长句里碰巧命中）。所以 B 只能用于判定为「行程写法」的文本，不能对任意提示词调用。
   - `transit_mid_rule` 在 `start == end`（不跨场景）时输出**自相矛盾的文本**：实测生成「…与`S20 故宫·午门城台拱门`明显不同，一眼就看得出画幅里此刻是`S20 故宫·午门城台拱门`」。所以它只能在 `cross=True` 时调用。

## 四、推荐的接入形态（待确认后动）

```python
_rt = _one_shot_scene_route(text)                 # B 先解析
if _rt.get("cross"):                              # 只有真跨场景才用 B 的换场规则
    _rule = _one_shot_transit_mid_rule(_rt["start"], _rt["end"], _rt["transit"])
else:                                             # 单场景 / 解析失败 → A 兜底
    _rule = None
    _scene = _one_shot_scene_name(text)
```

即：**B 负责「跨场景」这一新能力，A 负责其余所有情况**。两套并存、各用所长、不需要人工开关，也不会互相覆盖。

时间码那套则仍需二选一（剥离 vs 平移），因为两套会处理同一段文本；建议保留现役剥离，等真机能验收一镜到底档后再切。

## 五、未做与受阻

- 上面的接入形态**尚未接线**：它要改一镜到底主流程的挂接点，属于行为变更，必须真机跑一镜到底档验收（对比「段中换场是否不塌缩、是否不倒走」）后才能定稿。
- 8181 实例未运行，GPU 被 8183 占约 23.8/24.4 GB，当前无法真机验证。
- v14.346 假倍率二采拦截（约 50 行）仍未合并：属替换型，且对第 36 档无影响。
