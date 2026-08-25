# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 风格。

## [0.1.0] - 2026-08-25

首个公开版本。

### Added
- `impact <函数名> [--path 仓库]`：AST 反向索引，输出"谁在调用它"（定义处 + 每个
  调用点的 文件:行号），动态调用（getattr/exec/字符串反射）标注为不可见。
- `risk <函数名> [--path 仓库]`：叠加 git 维度（近 180 天改动次数、fix/bug 提交
  占比），输出 0-100 风险分分项与一句话行动建议。
- `report [--path 仓库]`：全仓 Top-10 高风险函数 Markdown 表格。
- 确定性输出：同一仓库多次运行结果逐字节一致；退出码 0/1/2 三级约定。
- GBK 等遗留控制台兼容：stdio 强制 UTF-8 容错；subprocess 显式 UTF-8 解码。
- 测试套件 34 例：AST 边界（嵌套类/装饰器/异步）、git 维度、评分公式、双跑
  确定性、GBK 冒烟、空目录/非 Python 目录友好降级。
- CI：ubuntu + windows × Python 3.10/3.12 矩阵。

[0.1.0]: https://github.com/ox-alpha/callquake/releases/tag/v0.1.0
