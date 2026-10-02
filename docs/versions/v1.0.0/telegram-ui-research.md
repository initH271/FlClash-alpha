# Telegram Android UI 源码调研（2026-10-03）

本文件属于新 UI 文档里程碑 v1.0.0，与 FlClash 软件版本独立。仅记录调研事实与适配建议，不代表 Flutter 实现或设备验收已完成。

## 结论与证据边界

用户口中的“高斯 / 玻璃悬浮 tab”，准确机制是 **悬浮胶囊底导航 + 背景模糊与饱和度增强 + 可选 SDF 液态折射 + 普通选中胶囊 + 图标/手势动画**。Android 最新源码确有 `LiquidGlassEffect` 与 `liquid_glass_shader.agsl`，不是仅用半透明背景模拟玻璃。选中胶囊自身是强调色 9% 的圆角矩形，并没有独立折射 shader。[AGSL][shader]、[背景 render node][render]、[选中胶囊][tabdraw]

官方 2026-02-09 [Android redesign 公告](https://telegram.org/blog/crafting-android-design-and-more) 明确新 bottom bar 与 Power Saving 效果控制；文中 Liquid Glass 部分主要介绍 iOS。因此 Android 是否折射、如何折射，以下以固定 SHA 源码为准。公告的图片/视频可以辅助视觉参考，不能代替代码参数。

## 来源、版本与取样

- [Telegram 官方应用页](https://telegram.org/apps/) 与 [可复现构建说明](https://core.telegram.org/reproducible-builds) 都指向 `DrKLO/Telegram`；[仓库 README][readme] 声明是官方 Android 源码。
- 本次 live API 与 shallow clone 一致：master HEAD **`f2908b14133bbffbf7ab04f641ecb5bfaf533242`**，提交 `update to 12.10.6 (7112)`，committer 日期 **2026-09-30 17:51:11 UTC**（本地 git 显示 +04:00）。[固定提交](https://github.com/DrKLO/Telegram/commit/f2908b14133bbffbf7ab04f641ecb5bfaf533242)
- 源码构建属性为 `APP_VERSION_NAME=12.10.6`、`APP_VERSION_CODE=7112`。[构建属性][version]
- GitHub latest release API 返回 **release-11.4.2-5469**，published_at **2024-11-20 14:20:11 UTC**；[该 Release](https://github.com/DrKLO/Telegram/releases/tag/release-11.4.2-5469) 与最新 HEAD 不是同一件事。tags API 的首条亦为此旧 tag。不能把它称为当前 Android 商店最新版本。
- 未安装、运行或验签 Telegram APK，未验证商店 rollout 或官网 APK 版本，未访问 Telegram 用户身份/会话；“12.10.6”在本文是最新公开 HEAD 的源码版本，不是独立核验过的分发包版本。
- 本地研究副本：`/Users/aharon/projs/hello/audits/telegram-android-20261003/Telegram/`；同目录 `head.json`、`tags.json`、`latest-release.json`、`tree.json` 保存实际 GitHub 响应。源码 clone 无 submodules，足以读本次 Java/AGSL，未尝试构建官方客户端。

## 1. 现用导航与布局

主调用路径是 `MainTabsActivity.createView → MainTabsLayout → GlassTabView.createMainTab`，背景由 `BlurredBackgroundDrawableViewFactory.create → BlurredBackgroundDrawableRenderNode` 承载。[导航装配][main] `GlassTabsView.java` 只有薄布局/lens bounds 壳，不能把它当作现用主导航的完整实现。

| 参数 | 最新源码事实 | Flutter 适配建议 |
|---|---|---|
| 外形 | 可见主栏 56dp，高度加上下 8dp margin 后72dp；背景 radius28dp | 采用56逻辑像素玻璃实体，外边距8；加 safe area 后不侵占系统手势区 |
| 最大宽度 | MainTabsLayout maxWidth `328 + 8*2 = 344dp`；总 tab 内容最小宽320dp，受可用宽限制 | 手机居中；宽窗口保持胶囊尺寸或换侧导航，不把一条栏拉满 |
| 内部与背景 | tabsView padding12dp；background padding `8-.334dp`，所以 padding包含外 margin 与内4dp间隙 | 不机械叠加两层padding；以可见56dp实体、4dp内间隙复算 |
| 主图标 | 主 tab 图片24×24dp，top4dp | 使用现有应用图标，24尺寸，outline/filled切换；不用Telegram素材 |
| 标签 | 12dp，单行居中省略；top28.33dp；普通bold，选中extra-bold | 保留标签，中文字和文字缩放要单独走查，不能只检验英文 |
| 紧凑策略 | 文字12/12/10dp三次测量，对应水平padding16/8/4dp | 优先减少间距；无障碍文字变大时保留可读性，不盲目缩至10 |
| safe area | wrapper padding加入system left/right/bottom，独立处理底部栏与更新条 | 用真实MediaQuery padding；内容末行留出栏高+margin+safe area |

事实来源：[尺寸常量][dims]、[布局][layout]、[主 tab 装配][main]、[图标标签][tabs]、[主图标尺寸][tabicons]、[安全区][insets]。

## 2. 磨砂与液态折射

背景路径：`MainTabsActivity` 汇集当前 tab fragment 的 `getGlassSource()`；以 Chats 为例，`DialogsActivity.getGlassSource()` 返回 `iBlur3SourceGlass`，该 source 捕获列表并调用 `DownscaleScrollableNoiseSuppressor.DRAW_GLASS`。API31以上建立 RenderNode 捕获，旧平台使用纯主题色 source。[主背景采样][capture]、[Dialogs背景][dialogs]

| 机制 | 最新源码事实 | 适配边界 |
|---|---|---|
| 液玻开启的玻璃分支 | 4×下采样，blur radius6dp，saturation×3 | Flutter sigma不是Android radius；不要直接填sigma6就声称像素等价 |
| frosted分支 | 下采样8，blur `40-1.66=38.34dp` | 这是强磨砂支路，不是主液玻底栏的6dp支路 |
| 液玻关闭simple分支 | 下采样8（allowNoiseSuppress时16），blur40dp，saturation×3 | 可做性能/效果切换；并非所有fallback都无blur |
| 液态折射 | Android API33+ RuntimeShader；圆角SDF，有限差分法线，refract产生采样偏移，最后premultiplied前景色src-over | `BackdropFilter + ImageFilter.blur`只提供模糊；真实边缘折射需要可采样的背景shader/渲染层 |
| 折射默认 | intensity .75，index1.5；thickness默认11dp，限制在短边/5且至少1px | 可借行为/数学结构，不能把Java RenderNode直接照抄成Dart |

源码中的radius/sigma换算是 `sigma=.57735*radius+.5`（radius>0），并在下采样时将sigma除以scale再转回radius；这是Telegram对Android blur的换算，Flutter跨renderer效果仍需截图复核。[换算][sigmaconvert]

源码：[下采样与blur分支][blur]、[饱和度矩阵][sat]、[默认折射参数][defaults]、[厚度边界][render]、[AGSL公式][shader]、[RuntimeShader绑定][effect]。

AGSL核心公式（依据源码归纳，不是完整shader移植）：

1. 令 `p=fragCoord-center`，选择当前象限圆角r，`q=abs(p)-size+r`，圆角SDF为 `length(max(q,0))+min(max(q.x,q.y),0)-r`。
2. 仅 `sd<0` 的内部计算折射。通过 `SDF(p+(1,0))-sd` 与 `SDF(p+(0,1))-sd` 求有限差分，再令 `c=max(thickness+sd,0)/thickness`，构造归一化法线 `(dx*c,dy*c,sqrt(1-c*c))`。
3. 入射 `(0,0,-1)`，折射比 `1/index`。厚度函数 `h=sd<-t?t:sqrt(sd*(-2*t-sd))`，位移长度为 `(h+8*t)/(-refract.z)`，采样偏移乘 `intensity`。
4. 最终以前景premultiplied tint合成采样后的背景。边缘遮罩/裁切由外围RenderNode outline完成，shader自身没有smoothstep edge blend或抗锯齿参数。[公式][shader]、[clip与outline][outline]

Flutter工程建议：片元坐标、size、thickness、1像素有限差分必须处于同一像素单位；devicePixelRatio换算只做一次。保证background sampler矩形覆盖折射偏移范围，边缘采样clamp，防止引入黑色边。若需要额外高光/edge fade，应明确为自己的设计参数；Telegram该shader没有这些参数。先用固定棋盘/高对比条纹背景验证偏移方向，再看真实列表。

shader范围只证明圆角边缘背景折射与色调合成；该shader没有色散、陀螺仪驱动高光或真实物理光学多层散射。把这些第三方“Liquid Glass”库功能归给 Telegram 没有依据。[AGSL全文][shader]

## 3. 色调、轮廓与选中态

mainTabs provider 的背景不只是“白色85%”：`solveSrcColor` 由当前主题背景与目标玻璃色求source color；开启液玻alpha .85，关闭 .76。上下描边与阴影随明暗模式分别设置。[mainTabs provider][provider]

| 参数 | Light | Dark |
|---|---|---|
| 顶部stroke | #11000000 | #06FFFFFF |
| 底部stroke | #20000000 | #11FFFFFF |
| stroke宽 | .4dp | .4dp |
| 阴影 | #20000000 | #04FFFFFF |
| 阴影半径/偏移 | 2.667dp / (0,.85dp) | 同左 |
| 选中胶囊 | 当前主题强调色9% alpha | 同机制 |

`GlassTabView` 的选择因子用320ms decelerate，胶囊scale .6→1、alpha随因子；图标与文字颜色做ARGB插值。图标提供outline/fill动画；选中标签extra-bold。[选择绘制][tabdraw]、[颜色与字重][tabcolors]。强调色来自主题键fallback，未强制Telegram蓝；Flutter应继承应用自己的ColorScheme。[主题fallback][theme]

Flutter建议：主题色玻璃实体+细描边+极轻阴影，先完成稳定可读的磨砂；选中胶囊是玻璃内一层淡强调底，不给每个tab额外堆阴影。玻璃后面需实际可滚动内容，不能仅显示固定渐变假装背景模糊。

## 4. 手势、选择与动画

- 点击tab时，正在手动pager滚动或触摸则返回；点击当前页会请求scroll-to-top；切其他页先select再pager.scrollToPosition。[点击路由][main]
- `MainTabsLayout` 支持长按后拖动，x限制至首末可见tab中心，选择最近可见tab；**长按开始**若命中不是已选tab，会立即 `performClick` 一次；**后续拖动**只更新 `setTabSelected` 视觉状态，不连续 `performClick` 切页；**释放**启动中心吸附，并对最后tab `performClick`。是否真正切页仍受主活动pager状态检查限制。[拖动路由][drag]、[释放][gesture]、[页路由][main]
- 按下先由ClickHelper检查命中，记录startX/startY并预约长按，同时MainTabsLayout继续向child分发原始事件。Chats/Contacts/Calls/Profile在ignore集合内，父ClickHelper不捕获它们的起始按下，交给child专属长按菜单；通用拖动机制不能描述成主栏每个tab都能拖。[按下与move/up][clickflow]、[ignore装配][main]、[分发][dispatch]
- **取消的实际边界**：MainTabsLayout的 `onLongPressCancelled` 不点最后tab，但ClickHelper的 `ACTION_CANCEL → resetTouch` 在已进入 `FLAG_IN_LONG_PRESS` 时调用的是 `onLongPressFinish`，所以仍可能提交最后tab；`onLongPressCancelled` 仅用于 `AWAITING_CUSTOM_LONG_PRESS`。这是追到helper之后的源码事实，不能只读delegate回调名就断言cancel不切页。[resetTouch][clickreset]、[事件路由][clickflow]
- 长按启动阈值是平台longPressTimeout的75%，不是硬编码375ms。`ClickHelper` 默认读 `ViewConfiguration.getLongPressTimeout()`。[手势阈值][gesture]、[默认平台阈值][clickhelper]
- 拖动中心/偏移是SpringAnimation，`STIFFNESS_MEDIUM`与`DAMPING_RATIO_LOW_BOUNCY`；触摸时跟手，释放吸附中心。不是所有选择都用同一个弹簧。[弹簧与中心][spring]
- 整条栏按压scale1→1.019，380ms `EASE_OUT_QUINT`，该曲线控制点(.23,1,.32,1)。scaleX/Y弹簧虽定义了250/.25，但运行调用被注释，不能说按压实际使用它。[按压][gesture]、[曲线定义][curve]
- 主栏 Chats/Contacts/Calls/Profile 还各有专门长按菜单，并加ignore集合；不能把通用长按拖动当作所有主tab毫无冲突的唯一动作。[导航长按装配][main]

Flutter建议：保留点击，长按拖动仅在无冲突区域启用；拖动展示与最终页面切换分开，释放再提交路由，cancel恢复现页（这是相对上面ClickHelper实际取消行为的有意改进）。无障碍Semantics提供label、selected、点击行为；系统disableAnimations时直接选择或短fade，禁用按压放大和弹簧。后者是适配建议，不是本次已证实Telegram严格遵循系统reduce-motion的事实。

## 5. 性能降级与动态背景

工厂仅在允许液玻且API33+、source支持RenderNode时创建液态效果；主活动仅API31+建立背景RenderNode。旧系统退到主题色。效果也受 LiteMode 的 blur/liquid-glass flag 控制。[工厂能力检查][factory]、[主捕获能力检查][capture]

LiteMode根据设备性能等级选择low/medium/high默认preset；旧lite_mode5迁移会清除liquid-glass flag。当前文件列出的三个preset都没有主动包含FLAG_LIQUID_GLASS，因此不能推断“所有高端设备默认都开液玻”；服务器配置或用户设置仍可能影响实际flag，本文没有运行时验证。[preset][presets]、[迁移][lite]

`GlassEngine` 按scroll/edge/位置/主题 generation检查，只更新可见且invalidated drawable；不是无条件每帧重新抓全屏。[失效控制][engine]。Flutter建议限制BackdropFilter裁剪区域、复用背景捕获、避免在ListView每行加blur；低性能或节电模式改为更不透明的纯主题色面板并保留几何、选中态、可读标签。profile frame时间必须单独验证，静态截图证明不了性能。

## Flutter落地参数建议（不是源码事实）

建议第一版采用56高/28圆角/8外边距/24图标/12标签，背景使用ColorScheme surface色调、0.4边缘描边、2.67轻阴影，选中强调色9%胶囊。选择320ms decelerate，按压380ms cubic(.23,1,.32,1)且幅度1.019；reduce-motion禁用位移/放大。Blur用较弱可调sigma，经真实列表滚动截图比较再定，默认上限避免全屏模糊。

如果第一版没有实际背景折射采样，交付名称写“Telegram风格磨砂玻璃导航”，不写“完整Liquid Glass”；新增runtime shader之前先验证Flutter目标renderer支持、采样坐标、截图与低端frame时间。饱和度×3是Telegram事实，FlClash不宜无条件照搬：列表色块更少，设备主题色不同，先用保守色调保可读性。

走查至少含：浅/深主题、首末tab、长标签与大字体、系统三键/手势safe area、滚动内容穿过栏背后、弹出键盘/抽屉、重复快速切页、长按取消、reduce-motion、blur-off。Telegram官方视觉材料只辅证，本次未登录客户端截用户会话。

## 许可与限制

官方仓库根[LICENSE][license]为GPLv2，README要求发布改动源码并约束Telegram名称/标志。[README开发者要求][readme] 本次仅依据参数/行为重新设计Flutter UI；不复制Telegram素材、Java文件或整段shader，也不引入Telegram API/账号/服务器行为。若后续复制或派生代码，需要单独核对原文件及项目许可并保留来源与必要许可，不因“换成Dart”自动免除许可义务。此处仅说明观察到的许可证与工程边界，不给法律结论。

本次深入5个机制：导航布局、背景blur/refraction、颜色与选中态、手势动画、性能降级。未完整审计所有页面、系统reduce-motion链路、运行时服务器flag、GPU不同驱动视觉、官方APK与源代码二进制一致性；这些不能写作已完成验证。

[readme]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/README.md#L1-L16
[version]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/gradle.properties#L16-L17
[shader]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/res/raw/liquid_glass_shader.agsl#L1-L46
[render]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/ui/Components/blur3/drawable/BlurredBackgroundDrawableRenderNode.java#L105-L150
[tabdraw]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/ui/Components/glass/GlassTabView.java#L150-L165
[main]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/ui/MainTabsActivity.java#L308-L368
[dims]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/ui/DialogsActivity.java#L290-L292
[layout]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/ui/MainTabsLayout.java#L46-L130
[tabs]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/ui/Components/glass/GlassTabView.java#L80-L96
[insets]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/ui/MainTabsActivity.java#L913-L950
[capture]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/ui/MainTabsActivity.java#L122-L192
[dialogs]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/ui/DialogsActivity.java#L2757-L2817
[blur]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/ui/Components/blur3/DownscaleScrollableNoiseSuppressor.java#L409-L427
[sat]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/messenger/utils/RenderNodeEffects.java#L28-L35
[defaults]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/ui/Components/blur3/drawable/BlurredBackgroundDrawable.java#L239-L243
[effect]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/ui/Components/blur3/LiquidGlassEffect.java#L13-L102
[provider]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/ui/Components/blur3/drawable/color/impl/BlurredBackgroundProviderImpl.java#L21-L34
[tabcolors]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/ui/Components/glass/GlassTabView.java#L233-L271
[theme]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/ui/ActionBar/Theme.java#L3703-L3707
[drag]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/ui/MainTabsLayout.java#L396-L429
[gesture]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/ui/MainTabsLayout.java#L436-L536
[clickhelper]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/me/vkryl/android/util/ClickHelper.java#L49
[spring]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/ui/MainTabsLayout.java#L328-L429
[curve]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/ui/Components/CubicBezierInterpolator.java#L13
[factory]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/ui/Components/blur3/BlurredBackgroundDrawableViewFactory.java#L96-L104
[presets]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/messenger/LiteMode.java#L52-L90
[lite]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/messenger/LiteMode.java#L202-L217
[engine]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/utils/glass/GlassEngine.java#L130-L189
[license]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/LICENSE#L1-L7

[tabicons]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/ui/Components/glass/GlassTabView.java#L400-L411
[outline]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/ui/Components/blur3/drawable/BlurredBackgroundDrawableRenderNode.java#L36-L85
[clickflow]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/me/vkryl/android/util/ClickHelper.java#L161-L219
[clickreset]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/me/vkryl/android/util/ClickHelper.java#L101-L120
[dispatch]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/ui/MainTabsLayout.java#L606-L609
[sigmaconvert]: https://github.com/DrKLO/Telegram/blob/f2908b14133bbffbf7ab04f641ecb5bfaf533242/TMessagesProj/src/main/java/org/telegram/ui/Components/blur3/DownscaleScrollableNoiseSuppressor.java#L257-L273
