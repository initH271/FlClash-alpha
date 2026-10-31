# FlClash-alpha fork 补丁清单

这份清单列出 FlClash-alpha 相对上游 [chen08209/FlClash](https://github.com/chen08209/FlClash) 的全部差异，给做升级的人逐条核对。

- **升级上游前先读**：先读「升级时的通用规则」，再读所有写了「上游文件」的条目。这些补丁打在上游文件上，升级时可能冲突。
- **合并后照着核对**：按每条的「核对」看上游这次改了什么，再跑对应的测试。
- **同步更新**：每个在上游文件上打补丁的 PR，都要同时更新这份清单。fork 独有的新文件按目录概括，不用逐个列。清单只记已经合入 main 的内容，分支上的改动不写进来。

| 基线 | 值 |
| --- | --- |
| 上游版本 | `v0.9.2`（`7fd417fb`），同 `.automation/policy.json` 的 `upstream_tag` |
| 正文对应的 fork 提交 | `984799d4` |
| 重新列差异 | `git diff --stat <上游 tag> HEAD` |

仓库文档索引见 [AGENTS.md](AGENTS.md)。相关文档：[AUTOMATION.md](AUTOMATION.md)、[RELEASE_CHANNELS.md](RELEASE_CHANNELS.md)、[ROLLING_LOG_HISTORY.md](ROLLING_LOG_HISTORY.md)、[SECURITY_AUTOMATION.md](SECURITY_AUTOMATION.md)。

## 升级时的通用规则

- **自动流程写的文件不手改**：owner 批准后，`.automation/control.py` 写 `.github/release.json`、`.automation/policy.json`、`.github/release-notes.md` 和 `.automation/candidate.json`。合并有冲突时它会停下，开草稿 PR 并写 `UPSTREAM_REVIEW.md`。
- **整份用 fork 版本**：`.github/workflows/build.yaml`、`README.md`。
- **继续保持删除**：`.github/workflows/pages.yaml`、`site/`、`tool/build_site.sh`、`tool/render_site.mjs`、`README_zh_CN.md`。
- **其他冲突文件**：取上游版本，再按本清单把 fork 补丁打回去。提交 `6a7a5383` 是恢复 fork 功能的样板。
- **生成文件不手工合并**：`lib/**/generated/**` 用 `dart run build_runner build --delete-conflicting-outputs` 重新生成，`lib/l10n/` 用 `dart run intl_utils:generate` 重新生成。
- **锁文件不能直接取上游**：取上游的 `core/go.sum` 和 `Cargo.lock` 会丢掉安全版本，见 G4。
- **全量回归**：有 `.automation/candidate.json` 时，`build.yaml` 跑全量 `flutter test`；日常发版只跑其中的子集。
- **mihomo**：`core/Clash.Meta` 没有 fork 补丁。改动规则见 `.agents/rules.md` 里关于 `core/Clash.Meta` 的预算条目，默认在 FlClash 这一侧解决。
- **受保护路径**：`.automation/`、`.cnb/`、`.cnb.yml`、`.github/` 的改动走 owner 通道（GitHub PR），见 `.agents/rules.md` 的 Automation Changes。

## A. 滚动日志与导出

### A1. Core 历史日志

- **文件**：上游文件 `core/lifecycle.go`、`core/method.go`、`core/protocol.go`；fork 文件 `core/log_history.go`、`core/log_history_test.go`、`core/internal/logstore/`。
- **改了什么**：`handleInitClash` 按 `log-retention-days` 启动记录器，`handleShutdown` 停止记录器；新增 `exportLogHistory`、`setLogHistoryRetention` 两个方法；`InitParams` 加字段。
- **为什么**：实时视图只留 5000 条，fork 要跨重启保留诊断日志（`ROLLING_LOG_HISTORY.md`）；按时间保留的需求见 `docs/versions/v1.4.0/requirements.md`。
- **核对**：上游改初始化或关闭流程、方法注册表、`InitParams` 时重看。兜底：`cd core && CGO_ENABLED=0 go test . ./internal/logstore`、`test/core/protocol_contract_test.dart`。

### A2. 日志保留期限

- **文件**：上游文件 `lib/core/controller.dart`、`lib/core/interface.dart`、`lib/core/method.dart`、`lib/models/core.dart`、`lib/models/config.dart`、`lib/common/constant.dart`、`lib/providers/actions/core.dart`、`lib/manager/core_manager.dart`、`lib/views/config/general.dart`；fork 文件 `lib/views/config/log_retention.dart`。
- **改了什么**：初始化时传入已存期限，重连和改设置时同步给 Core；通用设置加入口；Core 初始化失败时 `actions/core.dart` 抛错。默认值 14 写在 `constant.dart`、`controller.dart`、`models/core.dart` 三处。
- **为什么**：避免选了 30 天却先按 14 天清理（`docs/versions/v1.4.0/requirements.md`）。初始化抛错来自修 VPN 启动的提交 `56f5a2f6`，具体原因未记录。
- **核对**：上游改 `CoreController.init`、`InitParams`、`_CoreContainerState`、日志设置项时重看。兜底：`test/models/log_retention_settings_test.dart`、`test/views/log_retention_test.dart`。

### A3. APP 日志

- **文件**：上游文件 `lib/common/print.dart`；fork 文件 `lib/common/log_history.dart`。
- **改了什么**：`CommonPrint.log` 同时写入 `appLogHistory`。
- **为什么**：APP 日志要跨重启保留，并且在入口记录，不依赖界面的 5000 条（`ROLLING_LOG_HISTORY.md`）。
- **核对**：上游改 `CommonPrint.log` 或换日志入口时重看。兜底：`test/common/log_history_test.dart`。

### A4. 全量导出

- **文件**：上游文件 `lib/providers/app.dart`、`lib/views/logs.dart`、`lib/common/picker.dart`、`lib/plugins/app.dart`。Android 部分见 F1。
- **改了什么**：`exportLogs` 把 Core 历史、APP 历史和近期界面快照打成 ZIP；导出期间禁用按钮；Android 用文档选择器加 `copyFileToUri` 写入，不再整份读进内存；`saveFileWithPath` 在源文件不存在时报错，结束后总是删除临时文件。备份导出也走 `saveFileWithPath`。
- **为什么**：提交 `56f5a2f6`、`9b47564f`、`ec5a51fd` 的 Changelog：修大日志导出，并按选择器返回的完整文档地址保存。
- **核对**：上游改 `saveFileWithPath` 的调用方、`lib/views/backup_and_restore.dart`、日志页按钮时重看。Android 文档类型写死为 `application/zip`，新调用方要是别的格式就得改。兜底：`test/common/file_export_test.dart`、`test/plugins/app_test.dart`、`test/views/logs_view_test.dart`。

## B. 双渠道发布与应用内更新

### B1. 更新来源

- **文件**：上游文件 `lib/common/constant.dart`、`lib/common/request.dart`；fork 文件 `lib/common/app_update.dart`。
- **改了什么**：`repository` 改成 `initH271/FlClash-alpha`；`checkForUpdate` 只在 Android 上工作，并行查 GitHub 和 CNB，按内部构建号比较。
- **为什么**：fork 只发 Android ARM64，两个渠道互为备份（`RELEASE_CHANNELS.md`）。
- **核对**：上游改 `checkForUpdate`、`latestRelease`，或新增用到 `repository` 的地方时重看，它现在指向 fork 仓库。兜底：`test/common/app_update_test.dart`。

### B2. 更新检查调度

- **文件**：上游文件 `lib/application.dart`、`lib/bootstrap.dart`、`lib/providers/action.dart`、`lib/providers/actions/common.dart`；fork 文件 `lib/common/update_check_scheduler.dart`。
- **改了什么**：`autoCheckUpdate` 移到 `markRunning` 之后；启动后检查一次，之后前台每 6 小时检查；前后台状态从 `ApplicationState` 传给调度器；Android 弹 fork 的更新对话框。
- **为什么**：提交 `a23d9596`：启动后再查，定时查，后台结果延后，同一构建不重复提示。
- **核对**：上游改启动顺序、`checkUpdateResultHandle`、`autoCheckUpdate` 时重看。兜底：`test/common/update_check_scheduler_test.dart`、`test/providers/common_action_test.dart`、`test/widgets/update_dialog_test.dart`。

### B3. 下载与安装

- **文件**：fork 文件 `lib/common/update_download.dart`、`lib/widgets/app_update_dialog.dart`。Android 部分见 F2。
- **改了什么**：应用内下载 APK，校验校验和、包名、构建号和证书后，打开系统安装器。
- **为什么**：README 列出的 fork 功能：下载校验后在应用内安装。
- **核对**：基本不冲突。上游改发布说明格式或自己加应用内更新时重看。兜底：`test/common/update_download_test.dart`、`test/widgets/app_update_dialog_test.dart`。

### B4. 关于页

- **文件**：上游文件 `lib/views/about.dart`；fork 文件 `assets/images/avatar/aharon.png`。版本读取见 D4。
- **改了什么**：页面改成有状态组件；标题写死 FlClash-alpha；显示可读版本、上游版本、发布日期和内部构建号；项目链接改成 GitHub、CNB 和上游；加维护者；去掉 Telegram 链接。
- **为什么**：可读版本的需求见 `docs/versions/v1.5.0/requirements.md`。去掉 Telegram 链接的原因未记录（`de664d73`）。
- **核对**：上游改关于页布局时，以上游新结构为准重打。兜底：`test/views/about_view_test.dart`、`test/views/release_version_view_test.dart`、`test/widgets/uncovered_views_test.dart`。

### B5. 更新开关改键

- **文件**：上游文件 `lib/models/config.dart` 和生成文件、`lib/providers/actions/common.dart`；fork 文件 `lib/common/update_check_scheduler.dart`。
- **改了什么**：`autoCheckUpdate` 改存为 `autoCheckAppUpdate`，自动检查加日志。
- **为什么**：旧版「不再提醒」写入的 false 让自动检查永久静默（#106）。
- **核对**：确认 `@JsonKey(name: 'autoCheckAppUpdate')` 还在，生成文件读写的都是新键。

## C. 网络工具

### C1. 配置注入

- **文件**：上游文件 `lib/models/config.dart`、`lib/models/models.dart`、`lib/models/state.dart`、`lib/providers/config.dart`、`lib/providers/providers.dart`、`lib/common/task.dart`、`lib/providers/actions/setup.dart`、`lib/manager/core_manager.dart`；fork 文件 `lib/models/network_features.dart`、`lib/common/network_policy.dart`、`lib/providers/network_features.dart`。
- **改了什么**：`NetworkProps` 加 `networkFeatures`；生成配置的最后一步调用 `applyNetworkFeatures`，加入 UDP/443 拒绝规则和 sniffer、NTP 覆盖；这些选项变化时触发 `fullSetup`。
- **为什么**：代码从 Bettbox 移植（`d3e6e33c`）。选择这些功能的原因未记录。
- **核对**：上游改 `_makeRealProfileTask` 结尾时，确认 YAML、md5 和 counts 都取注入后的配置；上游改 sniffer 或 NTP 配置结构时也要重看。兜底：`test/common/network_policy_test.dart`、`test/models/network_features_test.dart`、`test/views/network_feature_flow_test.dart`。

### C2. 自动停止与恢复、保持唤醒

- **文件**：上游文件 `lib/providers/actions/setup.dart`、`lib/manager/core_manager.dart`、`lib/plugins/app.dart`、`pubspec.yaml`；fork 文件 `lib/manager/network_automation_manager.dart`、`lib/common/network_snapshot.dart`。Android 部分见 F1。
- **改了什么**：`setRunning` 记录用户意图；新增不记录意图的 `setRunningAutomatically`；`_CoreContainerState` 混入 `NetworkAutomationMixin`；用 `wakelock_plus` 保持唤醒。
- **为什么**：提交 `d3e6e33c` 移植的按网络自动暂停和恢复；手动停止优先（`arb/intl_en.arb` 的 `smartAutoStopDesc`）。选择这项功能的原因未记录。
- **核对**：上游改 `setRunning`、`_run`、网络监听时重看，确认手动路径仍记录意图、自动路径不记录。兜底：同 C1。

### C3. zashboard 外部面板

- **文件**：上游文件 `lib/common/task.dart`。
- **改了什么**：外部控制器开启时，把 `external-ui` 和 `external-ui-url` 设成 zashboard v3.29.1 的固定下载地址。上游把这两项清空。
- **为什么**：原因未记录。
- **核对**：上游改 `external-ui` 的处理时重看。没有测试兜底，开启外部控制器后手工确认面板能打开。

### C4. 工具页入口

- **文件**：上游文件 `lib/views/tools.dart`；fork 文件 `lib/views/network_features.dart`。
- **改了什么**：工具页加「网络工具」入口。
- **为什么**：网络工具设置页的入口。
- **核对**：上游改工具页列表结构时重看。兜底：`test/views/network_feature_flow_test.dart`。

## D. 发版与签名

### D1. 发布工作流

- **文件**：上游文件 `.github/workflows/build.yaml`（整份替换）。
- **改了什么**：只构建 Android ARM64，用个人证书签名和校验，发布 GitHub Release 并触发 CNB 镜像；构建可复用已有产物，也可回退到 CNB 编译。
- **为什么**：fork 只发 Android ARM64，用固定个人密钥，两个渠道发相同的 APK（`RELEASE_CHANNELS.md`）。
- **核对**：冲突时保留 fork 版本，再读上游这次的工作流差异。上游升工具链时一起改：`go-version`、`flutter-version`、`RUSTUP_TOOLCHAIN`，以及 `.automation/security_scan.py` 的 `TOOLCHAIN_PINS` 列出的 6 处 Go 版本。

### D2. 上游构建工作流副本

- **文件**：fork 文件 `.github/upstream-build.yaml`。
- **改了什么**：放在 `.github/workflows/` 外面，不会运行。内容来自上游 `build.yaml`，已和 v0.9.2 的版本不同。`.automation/security_scan.py` 从这里读 `GO_VERSION`。
- **为什么**：保留这份副本的原因未记录。
- **核对**：确认 `security_scan.py` 仍能读到版本。上游升 Go 时同步这里的 `GO_VERSION`。

### D3. 签名与发布脚本

- **文件**：fork 文件 `.github/release.json`、`.github/release-notes.md`、`.github/scripts/`、`.github/workflows/sign-existing.yaml`、`.automation/verify_apk.py`、`.cnb/mirror-release.py`。
- **改了什么**：记录发行身份和证书指纹，签名 APK，生成 `update.json` 和校验和，把 Release 镜像到 CNB。
- **为什么**：固定签名让已装版本能原地升级，两个渠道的字节要一致（`RELEASE_CHANNELS.md`）。
- **核对**：基本不冲突。`applicationId` 和 `.dev` 后缀来自未改动的 `android/app/build.gradle.kts`，上游改这里时必须重看，包名或证书一变已装版本就无法升级。兜底：`.cnb/test_mirror_release.py`、`.automation/test_release_identity_wiring.py`。

### D4. 版本身份与发布说明

- **文件**：fork 文件 `lib/common/release_identity.dart`、`tool/release_identity.py`、`tool/test_release_identity.py`、`tool/release_notes.dart`、`tool/src/release_notes/`。
- **改了什么**：对外版本是「上游版本-alpha.序号」，内部构建号单独递增；`build.yaml` 用 `--build-name` 和 `--build-number` 覆盖 `pubspec.yaml` 的版本；按发布范围生成累积说明。
- **为什么**：可读版本和升级兼容的需求见 `docs/versions/v1.5.0/requirements.md`。
- **核对**：内部构建号不能重置。上游改 `tool/src/changelog/` 时跑发布说明测试。兜底：`test/common/release_identity_test.dart`、`test/widgets/release_version_dialog_test.dart`、`test/tool/release_notes_test.dart`、`test/tool/release_version_notes_test.dart`、`python3 tool/test_release_identity.py`。

### D5. 删除上游网站

- **文件**：上游文件 `.github/workflows/pages.yaml`、`site/`、`tool/build_site.sh`、`tool/render_site.mjs`（均已删除）；上游文件 `.agents/commands.md`（去掉 Website 一节）、`.agents/rules.md`（去掉 `site/` 的 px 说明）。
- **改了什么**：不发布上游的 GitHub Pages 站点。
- **为什么**：原因未记录。提交 `1b86dd13` 只记录了删除。
- **核对**：上游改这些文件时，合并会报 modify/delete 冲突，继续删除即可。上游文档新增对 `site/` 的引用时一并去掉。

### D6. 内部提交不进更新说明（#115）

- **文件**：上游文件 `tool/src/changelog/parser.dart`；fork 文件 `tool/src/release_notes/range.dart`。
- **改了什么**：`internalChangelogScopes` 里的内部 scope 默认不进更新说明，除非提交带 `Changelog:` trailer；非内部 scope 缺 trailer 时告警；整版没有任何条目时显示 `alphaEmptyNote` 这句中文兜底。
- **为什么**：更新对话框读起来像 CI 日志，读者不关心构建细节。
- **核对**：上游改 `parser.dart` 的 scope 判断或 trailer 解析时重看。兜底：`test/tool/changelog_parser_test.dart`、`test/tool/release_notes_test.dart`。

### D7. needs-copy 标记（#115）

- **文件**：上游文件 `tool/src/changelog/models.dart`、`tool/src/changelog/render.dart`、`tool/src/changelog/parser.dart`。
- **改了什么**：`ChangelogEntry` 加 `needsCopy`；没有 trailer 的条目，渲染时在后面留一行 `<!-- changelog:needs-copy` 注释（`releaseNeedsCopyMarker`）。
- **为什么**：只靠 stderr 告警容易漏看。
- **核对**：上游改渲染或解析时重看，确认注释不进 JSON。兜底：`test/common/changelog_test.dart`、`test/tool/changelog_render_test.dart`。

### D8. 更新日志规范（#115）

- **文件**：上游文件 `.agents/rules.md`、`.agents/commands.md`、`tool/hooks/commit_msg.sh`、`tool/src/changelog/parser.dart`、`test/widgets/update_dialog_test.dart`；fork 文件 `CHANGELOG_STYLE.md`、`RELEASE_CHANNELS.md`。
- **改了什么**：`Changelog:` trailer 不再限定英文，改按 `CHANGELOG_STYLE.md` 用中文写；hook、parser 警告和规则文字同步改过。
- **为什么**：更新对话框的读者不关心构建细节，文案用中文。
- **核对**：上游改 hook 或这些规则段落时，确认 hook、parser 警告和规则说法一致。兜底：`test/tool/changelog_parser_test.dart`、`test/widgets/update_dialog_test.dart`。

### D9. 手写发版说明（#115）

- **文件**：上游文件 `tool/src/changelog/render.dart`、`.agents/rules.md`；fork 文件 `tool/src/release_notes/manual.dart`、`tool/src/release_notes/range.dart`、`CHANGELOG_STYLE.md`、`test/tool/release_notes_manual_test.dart`。
- **改了什么**：`.github/release-notes.md` 里按版本命名的节（`## <版本>`）覆盖该版本的自动条目。
- **为什么**：已合并的提交没法改写。
- **核对**：上游改 `render.dart` 时重看。兜底：`test/tool/release_notes_manual_test.dart`。

### D10. 中文分组标题（#115）

- **文件**：上游文件 `arb/intl_zh_CN.arb` 和生成文件、`test/widgets/update_dialog_test.dart`。
- **改了什么**：zh_CN 的 `changelogBreaking`、`changelogFeatures`、`changelogFixes`、`changelogPerformance`、`changelogReverts` 等分组标题改成口语（「新玩意儿」「修好了」）。
- **为什么**：和条目语气一致。
- **核对**：上游改这些 key 时保留 fork 的中文，再重新生成 `lib/l10n/`。兜底：`test/widgets/update_dialog_test.dart`。

## E. 自动化控制器

### E1. 控制器与流水线

- **文件**：fork 文件 `.automation/`、`.cnb/`、`.cnb.yml`、`.github/workflows/upstream.yaml`、`.github/workflows/security.yaml`、`AUTOMATION.md`、`CNB_DEVELOPMENT.md`、`SECURITY_AUTOMATION.md`。
- **改了什么**：上游版本追踪和 owner 批准、依赖漏洞扫描、CNB main 同步和国内下载镜像。
- **为什么**：新的上游正式版要经 owner 批准和审查后才合入、发布（`AUTOMATION.md`）；依赖漏洞的处理见 `SECURITY_AUTOMATION.md`。
- **核对**：基本不冲突。上游新增顶层目录或构建输入时，看 `.github/scripts/ci_changes.py` 的 `NEUTRAL`、`RULES`。上游改 CI 或路径时看 `.automation/policy.json` 的 `protected_paths`。兜底：`python3 -m unittest discover -s .automation -p 'test_*.py'`。

### E2. 上游的 agent 文档

- **文件**：上游文件 `AGENTS.md`、`.agents/rules.md`、`.agents/commands.md`。
- **改了什么**：`AGENTS.md` 加一条自动化路径规则；`rules.md` 加 Automation Changes 一节；`commands.md` 加自动化单元测试命令。
- **为什么**：自动化配置走 owner 通道（`.agents/rules.md`）。
- **核对**：这几个文件上游常改，冲突时保留这些段落。没有测试兜底，合并后 `grep -n 'Automation Changes' .agents/rules.md`。

## F. Android 侧改动

### F1. AppPlugin

- **文件**：上游文件 `android/app/src/main/kotlin/com/follow/clash/plugins/AppPlugin.kt`。
- **改了什么**：新增 `getNetworkAddresses`、`createExportDocument`、`copyFileToUri`；请求码 `EXPORT_DOCUMENT_REQUEST_CODE = 1005`；`onActivityResult` 和 detach 时处理待完成的导出。
- **为什么**：分别服务 C2 的网络匹配和 A4 的导出。
- **核对**：上游改 `onMethodCall`、`onActivityResult`，或新增请求码时，确认 1005 不撞、导出分支仍排在 VPN 判断前面。兜底：`test/plugins/app_test.dart`、CNB 的 Android 单元测试。

### F2. 安装器接入

- **文件**：上游文件 `android/app/src/main/AndroidManifest.xml`、`android/app/src/main/kotlin/com/follow/clash/MainActivity.kt`；fork 文件 `android/app/src/main/kotlin/com/follow/clash/plugins/UpdatePlugin.kt`、`android/app/src/main/kotlin/com/follow/clash/plugins/UpdateFileProvider.kt`、`android/app/src/main/res/xml/update_paths.xml`。
- **改了什么**：加 `REQUEST_INSTALL_PACKAGES` 权限和 `UpdateFileProvider`；`MainActivity` 注册 `UpdatePlugin`。
- **为什么**：应用内安装下载的 APK（B3）。
- **核对**：上游改 Manifest 的 application 段或插件注册时，确认这三处还在。上游若引入自己的 FileProvider，确认 authorities 不撞。没有自动兜底，要装一次 APK 验证。

### F3. 停止服务的回复时机

- **文件**：上游文件 `android/app/src/main/kotlin/com/follow/clash/plugins/ServicePlugin.kt`；fork 文件 `android/tests/app/ServicePluginTest.kt`。
- **改了什么**：stop 等拆除完成后才回复 Flutter。
- **为什么**：改访问控制后重启时，「当前出站」磁贴的开关状态不同步（#108）。
- **核对**：上游改 `ServicePlugin` 的 stop 流程时跑 `ServicePluginTest`。

## G. Core 改动

### G1. mihomo 子模块

- **文件**：上游文件 `.gitmodules`。
- **改了什么**：子模块指针 `core/Clash.Meta` 和 v0.9.2 相同（`c5062921`），没有补丁。只把子模块地址从 SSH 改成 HTTPS。
- **为什么**：原因未记录（`be6eeb74`）。`.cnb.yml` 直接跑 `git submodule update --init --recursive`，没有配置 SSH 或 `insteadOf`。
- **核对**：确认地址还是 HTTPS。上游换子模块仓库或分支时重看。

### G2. Socket 保护

- **文件**：上游文件 `core/lib.go`；fork 文件 `core/socket_guard.go`、`core/socket_guard_test.go`、`core/lib_protect_test.go`。
- **改了什么**：钩子在加载时安装；没有活动 TUN handler 时打开的 socket 先保留，下一个 handler 启动时再保护；TUN 启动过程中打开的 socket 也保护。
- **为什么**：VPN 重启时，健康检查的 QUIC socket 没被保护，流量回环进 TUN（`53b11ce2`）。
- **核对**：上游改 `TunHandler`、`installHooks`、`DefaultSocketHook`、`handleProtect` 时重看。兜底：`cd core && CGO_ENABLED=0 go test -run 'TestSocketHook|TestSocketGuard' .`。

### G3. 启动顺序门禁（#202）

- **文件**：上游文件 `core/lib.go`、`core/lifecycle.go`、`lib/core/controller.dart`、`lib/providers/actions/setup.dart`；fork 文件 `core/listener_start_test.go`。
- **改了什么**：`handleStartListener` 拒绝未初始化或没配置的 Core；`handleStartTun` 要求 Core 已就绪；`StartTun` 不再自己启动监听；`setupConfig` 配置成功后才启动监听；`_run` 先应用配置再启动，配置失败就回滚。
- **为什么**：监听抢在配置应用之前会让 mihomo 崩溃（#202）；迟到的 TUN 回调不能重启已停止的运行（`c6a00787`、`61d4d694`）。
- **核对**：上游改 `_run`、`setupConfig`、`StartTun`、`handleStartListener` 时逐行重看，这条最容易被合并冲掉。兜底：`core/listener_start_test.go`、`core/route_test.go`、`test/core/controller_test.dart`、`test/providers/action_test.dart`。

### G4. 依赖安全版本

- **文件**：上游文件 `core/go.mod`、`core/go.sum`、`services/helper/Cargo.toml`、`services/helper/Cargo.lock`、`services/helper/src/service/hub.rs`、`services/helper/src/service/linux.rs`、`plugins/rust_api/rust/Cargo.lock`。
- **改了什么**：Go 固定 cilium/ebpf、insomniacslk/dhcp、klauspost/compress、goldmark、grpc、go-jose、otel/sdk、x/net 等的修复版本，并把 logrus 变成直接依赖（A1 使用）；helper 升到 warp 0.4，`linux.rs` 自己实现带鉴权的连接服务循环；两个 Rust 锁文件固定 tokio 1.53.3。
- **为什么**：清除依赖漏洞告警（`8097e29c`、`4021b38d`）。
- **核对**：合并后对照 `git diff v0.9.2 HEAD -- core/go.mod`，版本不能回退。上游自己升到 warp 0.4 时比较服务循环，保留连接鉴权。兜底：`.github/workflows/security.yaml`、CNB 的 Go 和 Rust 依赖回归流水线、`services/helper` 的 `cargo test`。

## H. 测试与 lint 调整

### H1. design_package lint

- **文件**：上游文件 `test/lint/design_package_test.dart`。
- **改了什么**：相对路径的分隔符统一成 `/`。
- **为什么**：原因未记录（`256f03f6`）。
- **核对**：冲突时可以直接取上游版本，见文末「可以考虑去掉的补丁」。

### H2. 上游测试随 fork 行为调整

- **文件**：上游文件 `core/route_test.go`、`core/ownership_test.go`、`test/core/controller_test.dart`、`test/providers/action_test.dart`、`test/providers/setup_action_test.dart`、`test/providers/common_action_test.dart`、`test/widgets/uncovered_views_test.dart`、`test/pages/scan_test.dart`、`test/common/link_test.dart`、`test/plugins/app_test.dart`。
- **改了什么**：`route_test`、`controller_test`、`action_test`、`setup_action_test` 改成 G3 的启动顺序；`ownership_test` 按 euid 分支，兼容 root 运行器；`common_action_test` 覆盖 B2 的调度器重建；`uncovered_views_test` 改成 B4 的关于页和桌面端不查更新；`link_test` 和 `scan_test` 覆盖 I1；`app_test` 覆盖 F1。
- **为什么**：这些测试断言的是上游行为，要跟 fork 补丁保持一致。`ownership_test` 的原因是 CI 运行器以 root 执行（`065d947c`）。
- **核对**：冲突时取上游新测试，再按 fork 行为改预期，不要放宽断言。fork 新增的测试在 `test/common/`、`test/models/`、`test/tool/`、`test/views/`、`test/widgets/` 下，一般不冲突，升级后跟全量回归一起跑。

## I. 其他

### I1. 吞掉平台路由推送

- **文件**：上游文件 `lib/common/link.dart`、`lib/application.dart`。
- **改了什么**：新增 `RoutePushSink` 回答 `didPushRouteInformation`，并排在 `MaterialApp` 的 observer 前面注册。
- **为什么**：`MaterialApp` 只有 home，平台推来的路由会失败或叠出第二个首页；链接已由 `app_links` 交给 `LinkManager`（`731020c8`）。
- **核对**：上游加命名路由或改深链接处理时重看，那时这个补丁可能要去掉。兜底：`test/common/link_test.dart`。

### I2. rust_api 构建钩子

- **文件**：上游文件 `plugins/rust_api/hook/build.dart`。
- **改了什么**：优先用环境变量 `LIBCLANG_PATH`；在 NDK 里多找一个 `bin` 目录。
- **为什么**：原因未记录（`be6eeb74`）。
- **核对**：上游改 `_bindgenEnvironment` 时可以先取上游版本，再构建 APK 验证。

### I3. AnimatedVisibility 跟随减少动画

- **文件**：上游文件 `lib/ui/animated_visibility.dart`。
- **改了什么**：系统关闭动画时，把时长设为 0 并直接跳到结果值。
- **为什么**：原因未记录。这段代码是合并提交 `5bd6efd0` 带进来的，两个父提交都没有。
- **核对**：上游改这个组件时可以先取上游版本。没有针对这段行为的测试，`test/widgets/animated_visibility_test.dart` 不覆盖它。

### I4. README

- **文件**：上游文件 `README.md`（整份替换）、`README_zh_CN.md`（移到 `translations/README_zh_CN.md`）。
- **改了什么**：先讲 fork 的功能和下载渠道，默认英文。
- **为什么**：提交 `8af4836d` 的标题：突出项目功能，默认英文。
- **核对**：冲突时保留 fork 版本。上游新增的功能说明按需挑进来。

### I5. 界面文案

- **文件**：上游文件 `arb/intl_en.arb`、`arb/intl_es.arb`、`arb/intl_fr.arb`、`arb/intl_ja.arb`、`arb/intl_ko.arb`、`arb/intl_ru.arb`、`arb/intl_zh_CN.arb`。
- **改了什么**：7 种语言都在文件末尾加了 fork 文案（更新、网络工具、日志保留、版本信息）；en、ja、ru、zh_CN 把 `exportLogs` 改成「导出全部日志」的意思。
- **为什么**：A、B、C 组功能的界面文案。
- **核对**：冲突时两边的 key 都保留，再重新生成 `lib/l10n/`。兜底：`test/l10n`。

### I6. 依赖与生成文件

- **文件**：上游文件 `pubspec.yaml`、`pubspec.lock`、`macos/Flutter/GeneratedPluginRegistrant.swift`、`lib/l10n/`、`lib/models/generated/`、`lib/providers/generated/`、`.gitignore`。
- **改了什么**：`wakelock_plus`（C2）；dev 依赖 `path_provider_platform_interface`（`test/common/file_export_test.dart` 用）；其余是生成结果；`.gitignore` 忽略 `/android/.kotlin/`。
- **为什么**：跟随上面各条功能。
- **核对**：确认 `pubspec.yaml` 的两个依赖还在；生成文件按通用规则重新生成，不手工合并。

### I7. fork 独有文档

- **文件**：fork 文件 `docs/README.md`、`docs/versions/`、`CNB_DEVELOPMENT.md`、`RELEASE_CHANNELS.md`、`ROLLING_LOG_HISTORY.md`。
- **改了什么**：记录 fork 的里程碑、发布渠道和日志设计。
- **为什么**：fork 自己的文档。
- **核对**：不冲突。升级后更新里面写到的上游版本。

### I8. 免责声明只确认一次

- **文件**：上游文件 `lib/models/config.dart` 和生成文件、`lib/common/constant.dart`、`lib/bootstrap.dart`。
- **改了什么**：迁移旧字段，判定放宽为接受过任意版本。
- **为什么**：owner 要求只确认一次，不随版本重弹（#105）。
- **核对**：确认 `_handlerDisclaimer` 仍调用 `disclaimerNeeded`，`readValue` 还在。

### I9. 服务状态显示节点名

- **文件**：上游文件 `lib/views/dashboard/widgets/service_status.dart`、`test/views/dashboard/service_status_test.dart`。
- **改了什么**：`_OutboundIpLine` 显示 IP 和节点名。
- **为什么**：owner 要看每次检查走的节点（#109）。
- **核对**：上游改 `_OutboundIpLine`、`_ServiceRow` 副标题或 `ServiceCheck.node` 时重新核对。兜底："a sheet row puts the node after its address"。

### I10. 服务状态：新增服务（#113）

- **文件**：上游文件 `core/service_check.go`、`lib/common/service_probe.dart`、`lib/views/dashboard/widgets/service_status.dart`、`test/views/dashboard/service_status_test.dart`、`test/common/service_probe_test.dart`；fork 文件 `core/service_rules_extra.go`、`core/service_rules_extra_test.go`。
- **改了什么**：新增 7 个 checker；`ServiceTarget` 加 `mark`；`_ServiceBadge` 画字母标记。
- **为什么**：覆盖 owner 用的交易所和社交应用。
- **核对**：上游改 `serviceCheckers`、`ServiceTarget` 字段或 `_ServiceBadge` 时重看。兜底：测试 "every service has a check registered in the Core"、`cd core && CGO_ENABLED=0 go test -run 'TestBinance|TestBybit' .`。

### I11. 服务状态：分类文案（#113）

- **文件**：上游文件 `arb/intl_en.arb`、`arb/intl_es.arb`、`arb/intl_fr.arb`、`arb/intl_ja.arb`、`arb/intl_ko.arb`、`arb/intl_ru.arb`、`arb/intl_zh_CN.arb` 和 `lib/l10n/` 生成文件。
- **改了什么**：6 个 `serviceCategory*` key（Ai、Streaming、Social、Finance、Developer、Gaming），7 种语言。
- **为什么**：面板分类标题（I12）。
- **核对**：上游 arb 冲突时保留这些 key，再重新生成 `lib/l10n/`。兜底：`test/l10n`。

### I12. 服务状态：面板分类（#113）

- **文件**：上游文件 `lib/views/dashboard/widgets/service_status.dart`、`test/views/dashboard/service_status_test.dart`；fork 文件 `lib/common/service_category.dart`、`test/common/service_category_test.dart`。
- **改了什么**：`ServiceStatusSheet` 按类别列出服务，组顺序按每组第一个服务的已存顺序。
- **为什么**：owner 要分组。
- **核对**：上游新增服务没有分类时会编译失败（穷举 switch）；面板列表结构变化时重看。兜底：`test/common/service_category_test.dart`。

### I13. 服务状态：手机卡片横向滚动（#113）

- **文件**：上游文件 `lib/views/dashboard/widgets/service_status.dart`、`test/views/dashboard/service_status_test.dart`。
- **改了什么**：`_ServiceStrip` 取代手机上的网格；只检测可见的格子。
- **为什么**：手机上显示全部服务。
- **核对**：上游改 `ServiceStatusCard.build`、`_syncShown`、`shownServiceCountProvider`、`_ServiceGrid` 时重看。兜底："a phone card scrolls sideways through every service"、"a vertical drag on the phone card scrolls the page"。

## J. 仪表盘磁贴

### J1. 磁贴扩展机制（#116）

- **文件**：上游文件 `lib/enum/enum.dart`、`lib/views/dashboard/widget_registry.dart`；fork 文件 `lib/views/dashboard/fork/fork_tiles.dart`、`test/views/dashboard/fork/fork_tiles_test.dart`。
- **改了什么**：`DashboardWidget` 开头留一段 fork 磁贴（`fork*`）；`widget_registry.dart` 的三个 switch 各加一行 `_ => forkTileOf(this)...` 兜底，分发给 `forkTiles`。
- **为什么**：让升级上游时冲突最少。
- **核对**：上游改 enum 位置或 switch 结构（比如改成 Map）时，确认兜底还在、fork 段还在上游值前面。删掉兜底会直接编译失败。fork 磁贴名定下后不能改，`fork_tiles_test.dart` 的 `shippedForkTileNames` 守着。宽度 ≥640dp 时用桌面布局（`lib/views/dashboard/layout.dart` 的 `_minDesktopWidth`），fork 磁贴不出现。兜底：`test/views/dashboard/fork/fork_tiles_test.dart`。

### J2. 推送通道磁贴（#116）

- **文件**：上游文件 `arb/intl_en.arb`、`arb/intl_es.arb`、`arb/intl_fr.arb`、`arb/intl_ja.arb`、`arb/intl_ko.arb`、`arb/intl_ru.arb`、`arb/intl_zh_CN.arb`、`lib/models/generated/config.g.dart`、`lib/enum/enum.dart`；fork 文件 `lib/views/dashboard/fork/push_channel.dart`、`test/views/dashboard/fork/push_channel_test.dart`。
- **改了什么**：新增 `forkPushChannel` 磁贴。
- **为什么**：一眼看出 FCM 有没有走代理。
- **核对**：上游改 `ConnectionsPolling`（`lib/views/dashboard/widgets/connections_table.dart`）、`TrackerInfo`、`DashboardCard` 的接口时重看。`config.g.dart` 冲突时重新生成，不要手动合。兜底：`test/views/dashboard/fork/push_channel_test.dart`。

### J3. 分流自检磁贴（#116）

- **文件**：上游文件 `arb/intl_en.arb`、`arb/intl_es.arb`、`arb/intl_fr.arb`、`arb/intl_ja.arb`、`arb/intl_ko.arb`、`arb/intl_ru.arb`、`arb/intl_zh_CN.arb`、`lib/models/generated/config.g.dart`、`lib/enum/enum.dart`、`test/views/dashboard/edit_test.dart`（一行：视图高度 1400 改 1800）；fork 文件 `lib/providers/fork/route_check.dart`、`lib/views/dashboard/fork/route_check.dart`、`test/providers/fork/route_check_test.dart`、`test/views/dashboard/fork/route_check_test.dart`。
- **改了什么**：新增 `forkRouteCheck` 磁贴，数据层和界面分开。
- **为什么**：排查规则分流。
- **核对**：上游改 `RoutedProbe`（`lib/providers/routed_probe.dart`）、`ProbeParams`（`lib/models/core.dart`）、`outboundIpProbeProvider` 时重看。上游改 `edit_test.dart` 时确认那一行加高还在；上游改 dashboard 布局分支时确认 fork 磁贴在手机布局还能出现。兜底：`test/providers/fork/route_check_test.dart`、`test/views/dashboard/fork/route_check_test.dart`。

### J4. 手动覆盖修复（#116）

- **文件**：fork 文件 `lib/common/network_policy.dart`、`lib/manager/network_automation_manager.dart`、`lib/providers/network_features.dart`、`test/common/network_policy_test.dart`。
- **改了什么**：策略增加覆盖状态；自动化状态对外发布；增加恢复请求（`networkResumeRequestProvider`）和网络读取的替换点（`networkSnapshotReaderProvider`）。
- **为什么**：命中规则时手动启动，会被下一次检查停掉。
- **核对**：跑 `test/common/network_policy_test.dart`，并核对 `setRunning` 仍记录用户意图（C2）。这几个文件都是 fork 自己的，一般不冲突。

### J5. 自动暂停磁贴（#116）

- **文件**：上游文件 `lib/enum/enum.dart`、`test/views/dashboard/edit_test.dart`、7 个 arb、`lib/l10n/` 和 `lib/models/generated/config.g.dart` 等生成文件；fork 文件 `lib/views/dashboard/fork/fork_tiles.dart`、`lib/views/dashboard/fork/auto_pause.dart`、`test/views/dashboard/fork/auto_pause_test.dart`、`test/views/dashboard/fork/fork_tiles_test.dart`。
- **改了什么**：新增 `forkAutoPause` 磁贴。
- **为什么**：区分规则停止和手动停止，并提供覆盖和恢复（J4）。
- **核对**：跑 `test/views/dashboard`，核对 `edit_test.dart` 的 `seed` 和 `maxScrollExtent - 330` 偏移；`lib/l10n/` 重新生成。

## 可以考虑去掉的补丁

这些补丁看起来可以不打，但都没有实测过。去掉前先跑全量回归。

- **H1**：只有 Windows 上分隔符才不是 `/`，而 fork 的 CI 跑在 Linux 上，只发布 Android。
- **I2**：仓库里没有地方设置 `LIBCLANG_PATH`；上游只找 `lib` 和 `lib64`。去掉后要构建一次 APK。
- **I3**：没有提交说明，也没有测试。
- **B2 里 `lib/providers/actions/common.dart` 的非 Android 分支**：`checkForUpdate` 在非 Android 上直接返回 null，线上走不到这里读 `source` 和 `download_url` 的两行，可以恢复成上游写法。
