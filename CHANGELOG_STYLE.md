# 更新日志风格指南

更新弹窗里的文字来自提交说明的 `Changelog:` trailer。这份指南规定它怎么写。

## 写给谁

读者是普通用户：不看代码，也不关心我们怎么发版，只想知道这次更新对自己有什么用。

## 怎么写

- 用中文，一条一句话，尽量不超过 30 个字。
- 讲用户能感受到的变化，不讲实现。
- 不出现技术名词：core、tun、socket、OSV、controller、provider、hook 等。VPN、节点、配置这类用户在界面上见过的词可以用。
- 可以诙谐、抽象、有点网感，让人读完笑一下。
- 不玩烂梗，不阴阳怪气，不拿用户或上一版的自己开涮。
- 说实话：用户没有感知的改动，再好笑也不写，直接 `Changelog: skip`。

## 正反例

| 技术写法 | 推荐写法 |
|---|---|
| protect sockets opened while no tun handler is active | VPN 重启后不再自己绕自己，流量终于学会出门了 |
| Large profiles no longer crash | 配置文件再大，也不会把 App 撑趴下了 |
| Opening the app no longer reloads a running VPN | 打开 App 就只是打开 App，跑着的 VPN 不会再被惊动 |
| Keep the core running while Windows sleeps | Windows 睡一觉醒来，代理还在岗 |
| Clear the DNS cache by hand or on network change | 换个网络，旧地址记录自动翻篇，想手动清也行 |
| Smoother editor for large files and in sheets | 大文件也能顺滑编辑，手指不用再等屏幕 |
| retain core history by configurable age | 日志留几天，现在你说了算 |

这些写法不要用：

| 写法 | 问题 |
|---|---|
| 修复了若干已知问题，提升了用户体验 | 等于什么都没说 |
| 绝绝子！流量直接起飞 YYDS | 烂梗，过两个月就尴尬 |
| 终于修好了这个某些人天天喊的问题 | 阴阳怪气 |
| 修掉 OSV 超时越过截止时间的边界 | 内部改动，不该写进日志 |

## 怎么落到提交里

```text
fix(core): protect sockets opened while no tun handler is active

Changelog: VPN 重启后不再自己绕自己，流量终于学会出门了
```

- 每个用户可见的提交都要在合并前写好 `Changelog:`。合并后提交说明就改不了，只能靠发版时手写（见下一节）。
- 没写 trailer 的用户可见提交会沿用提交主题进入日志：生成时打印警告，并在发版 Markdown 里留下 `<!-- changelog:needs-copy <id> -->`。发版前看到它，说明有一条文案漏了。
- 内部改动默认不收录，范围见 `tool/src/changelog/parser.dart` 的 `internalChangelogScopes`，以及 feat、fix、perf、revert 以外的提交类型。这些提交写了 `Changelog: <文案>` 依然会收录。
- `Changelog: skip` 一定不收录。
- 整版没有可收录的条目时，日志只显示一句兜底文案，不用手写。

## 发版时手写

发版 PR 可以在 `.github/release-notes.md` 里写当前版本的一节。有这一节时，弹窗和 Release 页面都只显示这一节的内容，自动生成的条目全部不用：

```markdown
## 0.9.2-alpha.18

### 修好了
- VPN 重启后不再自己绕自己，流量终于学会出门了
```

- `## ` 后面写 `.github/release.json` 的 `displayVersion`，和它对不上的节不生效。这样忘了改文件时，上一版的文案不会再发一次，而是退回自动生成，并打印警告。
- 分组标题只有五个：新玩意儿、修好了、更快了、要注意、撤回了。每条一行，以 `- ` 开头。
- 这一节写错（标题不认识、条目不在分组下、有别的文字、分组是空的）时，测试和发版都会直接报错，不会退回自动生成。既然写了就是想覆盖，悄悄发出自动文案才是最难发现的错。不想手写了就删掉这一节。
- 版本标题之前的文字不生效，可以留作备注。
