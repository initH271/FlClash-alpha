# FlClash-alpha

[English](../README.md) · **简体中文**

FlClash-alpha 是 [chen08209/FlClash](https://github.com/chen08209/FlClash) 的独立维护分支，并非上游官方发行版。提供 **Android ARM64** 安装包，跟随上游正式版。

## 和官方版的区别

- **持久化诊断日志**：日志跨重启保存在本地，排查问题时可以一键导出。
- **双渠道发布**：版本同时发布到 GitHub 和 CNB，使用固定签名。应用会检查两个渠道，校验安装包和签名后在应用内更新。
- **按网络环境自动化**：可根据所在网络自动暂停、恢复代理。

## 下载

| 渠道 | 源码 | 安装包 |
| --- | --- | --- |
| GitHub | [FlClash-alpha](https://github.com/initH271/FlClash-alpha) | [最新版本](https://github.com/initH271/FlClash-alpha/releases/latest) |
| CNB | [FlClash-alpha](https://cnb.cool/507space/FlClash-alpha) | [最新 APK](https://cnb.cool/507space/FlClash-alpha/-/releases/latest/download/FlClash-alpha-arm64-v8a.apk) |

两个渠道发布的是字节一致、同一签名的 APK，Release 中附有 `SHA256SUMS.txt` 供核对。

## 安装与升级

- 包名为 `com.follow.clash.dev`，与官方安装包身份不同，两者不能互相覆盖。
- 版本使用固定签名，新版可直接覆盖旧版安装，数据保留。
- 第一次请手动安装 APK，之后在应用内检查更新即可。Android 会要求授权“安装未知应用”。
- 从官方版迁移时，通过备份导入配置，并重新授予 VPN 等系统权限。

## 反馈问题

请到 [CNB Issues](https://cnb.cool/507space/FlClash-alpha/-/issues) 提交，使用 Bug 表单。贴日志前，先删掉订阅链接、令牌、节点地址等个人信息。

## 开发与维护

- [日志实现与保留策略](../ROLLING_LOG_HISTORY.md)
- [双渠道发布和更新机制](../RELEASE_CHANNELS.md)
- [上游批准、NPC 和构建调度](../AUTOMATION.md)
- [CNB 开发环境](../CNB_DEVELOPMENT.md)
- [构建与测试命令](../.agents/commands.md)

正式包由 GitHub 构建和签名，CNB 镜像同一份产物。签名密钥和自动化凭据不入库。

## 来源、贡献与协议

原项目：[chen08209/FlClash](https://github.com/chen08209/FlClash)。感谢原作者、June2、Arue 及全部上游贡献者。本分支由 Aharon（initH271）维护。

本项目沿用 **GNU GPL v3（GPL-3.0）** 开源协议，完整条款见 [LICENSE](../LICENSE)。使用、修改与分发时请遵守许可证要求，保留必要的版权及许可证声明。项目按许可证规定提供，不附带保证。

## 使用声明

本项目面向网络技术、应用开发与自动化构建的**学习和研究**，不提供代理节点或订阅服务。请遵守适用法律法规，**禁止用于违法行为，维护者拒绝提供违法用途的支持**。

上述用途声明不替代 GPL-3.0 许可证，也不缩减该许可证授予的权利。
