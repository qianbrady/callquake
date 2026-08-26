# callquake

[![CI](https://github.com/qianbrady/callquake/actions/workflows/ci.yml/badge.svg)](https://github.com/qianbrady/callquake/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
> **Know the blast radius before you edit the fuse.**
> A zero-dependency CLI that tells you who calls a function and how battle-scarred its file is — before you change a single line.

## 这是什么

**callquake（改动余震仪）回答一个改码前的问题：我要动的这个函数，波及面有多大？**

输入一个函数/方法名，它做两件事：

1. **AST 调用链**：解析仓库里所有 `.py` 文件，建立"谁调用谁"的反向索引，
   列出每个调用点的 `文件:行号`；
2. **git 历史热度**：统计该函数所在文件近 180 天的改动次数、
   提交信息含 `fix`/`bug` 的占比。

两者合成一个 **0-100 风险分**，并给出一句话建议：
低分 → "低风险，放心改"；高分 → "有 X 个调用方 + Y 次 fix 历史，建议补测试再动"。

纯 Python 标准库实现，**零第三方依赖**，Python ≥ 3.10 即可运行。

## 快速开始

```bash
# 无需安装：把本仓库 clone 下来后，在仓库根目录直接用模块方式运行
python -m callquake --help
python -m callquake --version
```

三条核心命令（以下输出均在真实演示仓库上实测）：

### ① impact — 谁在调用它

```bash
python -m callquake impact apply_discount --path path/to/repo
```

```text
函数 'apply_discount' 的波及面（扫描 3 个 .py 文件）
定义 1 处:
  shop/cart.py:4  apply_discount
调用方 2 处:
  shop/cart.py:12  apply_discount(...)
  shop/cart.py:13  apply_discount(...)
注: 动态调用（getattr/exec/字符串反射）对 AST 不可见，不计入。
```

### ② risk — 改它有多危险

```bash
python -m callquake risk apply_discount --path path/to/repo
```

```text
函数 'apply_discount' 风险分: 37/100
  调用广度: 10/50（2 个调用点）
  历史热度: 27/50（近 180 天改动 5 次；fix/bug 提交 3 次，占 60%）
建议: 有 2 个调用方 + 3 次 fix 历史，建议补测试再动
```

### ③ report — 全仓 Top-10 高风险函数

```bash
python -m callquake report --path path/to/repo
```

```markdown
# 高风险函数 Top 10

共评估 6 个函数名；风险分 = 调用广度(0-50) + 历史热度(0-50)。

| 排名 | 函数 | 风险分 | 调用点 | 近180天改动 | fix占比 | 建议 |
|---:|---|---:|---:|---:|---:|---|
| 1 | `apply_discount` | 37 | 2 | 5 | 60% | 有 2 个调用方 + 3 次 fix 历史，建议补测试再动 |
| 2 | `checkout` | 32 | 1 | 5 | 60% | 有 1 个调用方 + 3 次 fix 历史，建议补测试再动 |
| 3 | `add` | 27 | 0 | 5 | 60% | 低风险，放心改 |
| 4 | `handle_request` | 5 | 1 | 0 | 0% | 低风险，放心改 |
| 5 | `entry` | 0 | 0 | 0 | 0% | 低风险，放心改 |
| 6 | `healthcheck` | 0 | 0 | 0 | 0% | 低风险，放心改 |
```

## 与依赖图工具的差异

jdeps / pydeps 这类工具画的是**依赖图**；callquake 回答的是**"这一刀下去会震到谁"**。
以 pydeps 为例——其 README 自述为 *"Python module dependency visualization"*，
通过命令行 `pydeps` 使用，基于 Python 字节码里的 import 操作码找依赖关系
（因此只会统计被 import 到的文件），配合 Graphviz 渲染 svg/png 依赖图，
并提供 import 环检测、聚类与 bacon 跳数过滤等能力。
jdeps 则是 JDK 自带的 Java 类/包级依赖分析工具。

| 维度 | jdeps / pydeps 等依赖图工具 | callquake |
|---|---|---|
| 分析粒度 | 模块 / 包级 import 关系 | **函数/方法级**调用点（文件:行号） |
| 回答的问题 | "这个模块依赖谁？" | "**谁在调用这个函数？改它会波及多大范围？**" |
| 数据来源 | 静态 import 关系（pydeps 只看被 import 的文件） | 全量 AST 解析所有 `.py` + **git log 历史** |
| 历史信号 | 无 | 近 180 天改动次数 + fix/bug 提交占比 → **0-100 风险分** |
| 输出形态 | 可视化依赖图（svg/png） | 纯文本列表 / Markdown 表格（可直接贴 PR 描述） |
| 外部依赖 | 需要 Graphviz（`dot`）等外部二进制 | **零依赖**，Python ≥ 3.10 标准库即可 |

一句话总结：依赖图工具帮你**看结构**，callquake 帮你**决策敢不敢改**。

## 风险分公式（确定性，整数运算）

```
调用广度 = min(50, 5 × 该函数名的 AST 调用点数)          # 0-50
改动频次 = min(30, 3 × 定义所在文件近180天提交数)         # ─┐
fix 占比 = round_half_up(20 × fix类提交占比)              # ─┴→ 历史热度 0-50
总 分   = min(100, 调用广度 + 改动频次 + fix占比)
```

- 总分 ≤ 29：`低风险，放心改`
- 总分 ≥ 30：`有 X 个调用方 + Y 次 fix 历史，建议补测试再动`
- 同一输出对同一仓库**永远逐字节一致**（全排序、无时间戳），便于 diff 与缓存。

## 设计边界（如实相告）

- **动态调用不可见**：`getattr(obj, "name")`、`exec`/`eval`、`registry[name]()`
  等字符串反射调用无法被纯 AST 看到，不计入调用点（输出中已标注）。
- 按函数**简单名**聚合：不同类的同名方法会合并统计（v0.1 取可用性优先）。
- git 不可用时（非仓库/git 未安装）自动降级：历史热度按 0 计并明确提示，不崩溃。
- 语法错误的文件会被跳过并列出，不影响其余文件的分析。

## 退出码

| 退出码 | 含义 |
|---:|---|
| 0 | 正常 |
| 1 | 数据错误（路径不存在 / 没有 .py 文件 / 函数未找到） |
| 2 | 用法错误（未知参数、缺少子命令或参数） |

Windows 控制台（GBK 等遗留代码页）下输出强制 UTF-8 并容错替换，不会因编码崩溃。

## 开发与测试

```bash
python -m unittest discover -s tests -q     # 34 个测试全绿
```

测试覆盖：AST 解析边界（嵌套类 / 装饰器 / 动态调用不可见）、git 维度计算
（窗口过滤 / fix 占比 / 边界日期）、风险分公式与封顶、同仓库双跑确定性、
GBK 子进程冒烟、空目录与非 Python 目录的友好降级。CI 在
ubuntu + windows × Python 3.10/3.12 四个组合上跑同一套测试。

## License

[MIT](LICENSE) © 2025 ox-alpha

## Install

```bash
pip install -e .
```

## Usage

```text
$ python -m callquake --help
usage: callquake [-h] [--version] {impact,risk,report} ...
改一行代码前先看波及面：AST 调用链 + git 历史 = 0-100 风险分。
positional arguments:
  {impact,risk,report}
    impact              列出调用某函数的所有位置（AST 反向索引）
    risk                输出某函数的 0-100 风险分与分项建议
    report              全仓 Top-10 高风险函数（Markdown 表格）
```

## Contributing

Issues and PRs welcome - run `pytest` locally before submitting.
