# FlClash-alpha

[English](README.md) · **简体中文**

由 **Aharon（GitHub: [initH271](https://github.com/initH271)，CNB: [Aharon](https://cnb.cool/u/Aharon)）** 维护的 FlClash 个人增强版，基于 [chen08209/FlClash](https://github.com/chen08209/FlClash)。保留上游代理客户端能力，重点改进日志回顾、应用更新和个人维护流程。

这是独立维护的派生项目，并非上游官方发行版。目前本项目提供 **Android ARM64** 安装包。

## 下载与项目地址

| 渠道 | 源码 | 安装包 |
| --- | --- | --- |
| GitHub | [FlClash-alpha](https://github.com/initH271/FlClash-alpha) | [最新版本](https://github.com/initH271/FlClash-alpha/releases/latest) |
| CNB | [FlClash-alpha](https://cnb.cool/507space/FlClash-alpha) | [最新 APK](https://cnb.cool/507space/FlClash-alpha/-/releases/latest/download/FlClash-alpha-arm64-v8a.apk) |

两端发布的是同一份固定签名 APK，可用 Release 中的 `SHA256SUMS.txt` 核对。

## 本项目增强了什么

- **滚动日志文件**：核心与 APP 日志分别保留最多 10 × 5 MiB，跨重启保留。界面仍显示最近 5000 条，磁盘记录独立运行。
- **统一导出**：一次导出当前保留的全部核心日志、APP 日志及界面快照，便于回顾排障。过期轮转文件和安装前的记录无法恢复。
- **双渠道更新**：并行检查 GitHub、CNB，优先最新构建，同版本选择响应更快且可用的下载地址；下载失败可切换镜像。
- **应用内下载与安装**：发现新版后自动显示下载进度，校验文件摘要、包名、构建号和固定证书；下载完成后点击“安装更新”，由 Android 系统确认安装。
- **受控跟随上游**：上游正式版先生成决策 Issue 和 NPC 分析，你批准后再合并、测试、构建、发版。

## 安装和升级

本项目包名为 `com.follow.clash.dev`，使用固定个人签名。修改版之间直接覆盖安装即可保留配置和数据；它与上游官方安装包具有不同身份。

第一次使用，或从尚不支持应用内安装的旧版本升级时，请先下载 APK 并覆盖安装一次。之后可在“关于 → 检查更新”中完成下载和安装。开启自动检查更新时，启动检查发现新版也会自动下载。

首次点击安装时，Android 可能要求允许本应用“安装未知应用”。授权后返回应用继续，由系统安装界面确认；本项目不绕过系统确认进行静默安装。关闭更新窗口会取消未完成下载，已校验的安装包会保留供下次使用。

备份格式沿用上游。首次从官方版迁移时通过备份导入配置，VPN 等系统授权需要重新确认。卸载或清除应用数据会删除私有日志，重要记录请先导出。

## 维护与开发

- [日志实现与保留策略](ROLLING_LOG_HISTORY.md)
- [双渠道发布和更新机制](RELEASE_CHANNELS.md)
- [上游批准、NPC 和构建调度](AUTOMATION.md)
- [CNB 开发环境](CNB_DEVELOPMENT.md)
- [构建与测试命令](.agents/commands.md)

正式包由 GitHub 优先构建和签名，CNB 同步同一份产物；故障恢复优先复用产物。签名私钥与自动化令牌不包含在源码中。

欢迎通过 [CNB Issue](https://cnb.cool/507space/FlClash-alpha/-/issues) 提交问题。提交日志前请自行检查并移除订阅地址、凭据和其他个人信息。

## 来源、贡献与协议

原项目：[chen08209/FlClash](https://github.com/chen08209/FlClash)。感谢原作者、June2、Arue 及全部上游贡献者。本派生项目的日志、更新和维护流程增强由 Aharon（initH271）维护。

本项目沿用 **GNU GPL v3（GPL-3.0）** 开源协议，完整条款见 [LICENSE](LICENSE)。使用、修改与分发时请遵守许可证要求，保留必要的版权及许可证声明。项目按许可证规定提供，不附带保证。

## 使用声明

本项目面向网络技术、应用开发与自动化构建的**学习和研究**，不提供代理节点或订阅服务。请遵守适用法律法规，**禁止用于违法行为，维护者拒绝提供违法用途的支持**。

上述用途声明不替代 GPL-3.0 许可证，也不缩减该许可证授予的权利。
