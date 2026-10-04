# UI 演进记录

FlClash-alpha 是基于 Flutter/Mihomo 的跨平台代理客户端。本目录记录 Telegram Android 风格改造的文档里程碑；文档 v1.0.0 不等于软件发布版本 0.8.98，也不改写此前项目历史。

当前最新 v1.2.0 UI 优化已获用户确认并进入提交／发布流程；此前功能与交互修复提交为 `2c0f7ec`，通过 CNB 需求 #144 推进正式合并。

| 里程碑 | 状态 | 需求 | 完成与验证 | 调研 |
|---|---|---|---|---|
| v1.0.0 Telegram 风格玻璃 UI | 本地验收完成 | [需求](versions/v1.0.0/requirements.md) | [完成情况](versions/v1.0.0/completion.md) | [Telegram 源码调研](versions/v1.0.0/telegram-ui-research.md) |
| v1.1.0 内容与操作 UI | 本地验收完成 | [需求](versions/v1.1.0/requirements.md) | [完成情况](versions/v1.1.0/completion.md) | 延续固定 Telegram 源码依据 |
| v1.2.0 导航细节与紧凑页面 | 本地验收完成，待 CI／发布 | [需求](versions/v1.2.0/requirements.md) | [完成情况与截图](versions/v1.2.0/completion.md) | 延续固定 Telegram 源码依据 |

需求与实测结果分开记录；截图中的模拟数据和渲染器降级应明确标注。研究使用固定源码 SHA，后续新增证据只更新对应阶段。
