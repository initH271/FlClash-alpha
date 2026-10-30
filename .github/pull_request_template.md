## 改动摘要


## 关联的需求或 issue
CNB 需求 / issue：

## CI 证据
- 本 head 在 CNB `owner/<分支>` 上的流水线链接：
- 四条流水线结论（Automation、Go、Flutter and Android、Rust，逐条写通过 / 失败 / 未跑）：
  1.
  2.
  3.
  4.
- 依赖扫描：以本 PR 上 GitHub 的 Dependency vulnerability scan 为准。

合并前必须对「合进当前 main 之后的结果」跑过对应的流水线。

## 用户可见的界面变化
- [ ] 本 PR 有用户看得见的界面变化（含上游升级带来的变化）
勾选后必须附上前后对比截图（模拟器截图即可）和改动清单，并等 owner 确认后才能合并。没有变化也请保持不勾选。

## 本地测试
命令与结果：

## 风险与回滚
风险：
回滚方式：

## 自动化配置
- [ ] 本 PR 改动了 `.github/workflows` 或 `.automation`（这类改动走 owner 通道）
