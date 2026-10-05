# 阶段报告 — 需求 #177 / 分支 automation/req-177

生成时间：2026-10-05
head 基线：`bc028531fa15178a3394a3d631921a21161e3dc7`（= main）

本轮目标：直接应用主会话已验证的增量发布说明补丁，完成受保护发布入口接线。
结果：**补丁附件无法下载，未应用补丁，未产生函数性源码改动。**

## 已核实的事实

### 1. 附件下载失败，SHA256 无法校验

- 需求给定链接：
  `https://cnb.cool/507space/FlClash-alpha/-/files/issues/2107100893051641856/c6iG46QFN7Tud4vecorE0F/fa8f5234-e4bc-431b-b224-abce94e89b1a/verified-incremental-notes.patch`
- 直接请求返回 `HTTP 404`，body `{"errcode":404,"errmsg":"Not Found"}`，仅 39 字节。
- 期望 SHA256：`2b049afd9cf50e865cda7de9a94094954f96af482422ffb507a9f940356da69f`
- 实际取回 SHA256：`c124149a2028d57049175663202b5cfd0d9b8c9ae3ad969179074ebfd8740a0b`（内容为 404 JSON，非补丁）

### 2. 已穷举平台取件通道，均失败

| 通道 | 结果 |
|---|---|
| `cnb issues get-files` | 404 `资源不存在` |
| `cnb issues get-issue-files --repo 507space/FlClash-alpha` | 404 `资源不存在` |
| `cnb assets get-files --repo 507space/FlClash-alpha` | 404 `Resource not found.` |
| `cnb assets list-assets --slug 507space/FlClash-alpha`（33 条） | 列表内无该 patch |
| `api.cnb.cool/507space/FlClash-alpha/-/files/issues/<path>`（Token + JSON Accept） | 404 |
| `cnb.cool/.../-/files/issues/<path>` | 400 `Invalid argument` |

URL 中的 `2107100893051641856` 既不是 #173/#177 的评论 ID，也不是 issue number，无法定位任何 asset 组。

### 3. 当前 main 仍是补丁要修复的缺陷状态

- `.github/scripts/prepare-release.py` 第 41 行与第 44 行**连续调用两次**
  `release_notes.generate(...)`；第二次不传 `args.base`，会覆盖第一次结果（即需求描述的真实 bug）。
- 旧的 `.github/scripts/release_notes.py`（Python 生成器）仍存在，未被删除。
- `tool/release_notes.dart` 与 `tool/src/release_notes/range.dart` 尚不存在。
- `test/tool/release_notes_test.dart` 现有 19 项测试。

### 4. 基线验证（补丁未应用状态）

| 命令 | 结果 | 退出码 |
|---|---|---|
| `dart format --output=none --set-exit-if-changed tool/ test/tool/` | 15 files, 0 changed | 0 |
| `flutter analyze --no-fatal-infos` | No issues found | 0 |
| `env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=commit.gpgsign GIT_CONFIG_VALUE_0=false flutter test test/tool/release_notes_test.dart --reporter expanded` | All tests passed! 19 项 | 0 |

既有 19 项在旧 Python 生成器下通过，符合“补丁未应用”的预期。

## 已改文件

**函数性源码改动：无。** 本分支唯一提交内容为本报告文件 `STAGE-REPORT-req-177.md`。
未修改 `.automation/`、`.cnb/`、`.github/`、Flutter 客户端、Core/ServiceState、依赖、版本号。

按需求禁止擅自重写实现，故未以手工方式重建补丁内容。

## 未完成项

1. 补丁附件未取回，未执行 `git apply --check`，**未应用补丁**。
2. 5 个目标文件未变更：
   - 新增 `tool/release_notes.dart` — 未创建
   - 新增 `tool/src/release_notes/range.dart` — 未创建
   - 更新 `test/tool/release_notes_test.dart` — 未更新
   - 更新 `.github/scripts/prepare-release.py` — 未更新
   - 删除 `.github/scripts/release_notes.py` — 未删除
3. 22 项测试（19 迁移 + 3 新增）未产生；`prepare-release.py` 双重 `generate()` 缺陷仍存在于 main。
4. 退役 2026094010 只读预演（base=`alpha-0.8.98-2026094009`）未执行——依赖新 `tool/release_notes.dart`。

## 需要的支持

请确认附件链接 / asset 组 ID 是否已失效，或重新上传补丁到可下载位置，并提供可用链接与新的 SHA256。
附件可下载后，本分支 `automation/req-177` 可直接续做：应用补丁 → 22 项测试 + formatter/analyze → 完整测试 → 提交。
