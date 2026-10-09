FlClash-alpha 0.8.98-alpha.16

<!-- flclash:changelog:begin -->
### Bug Fixes
- **android** Fix Android log exports losing the selected document URI

<!-- flclash:changelog:end -->

<!-- flclash:changelog:json
{"schemaVersion":2,"versions":[{"version":"0.8.98-alpha.16","tag":"v0.8.98-alpha.16","date":"","prerelease":false,"groups":[{"type":"fix","entries":[{"id":"ec5a51f","scope":"android","text":"Fix Android log exports losing the selected document URI"}]}]}]}
-->

---

FlClash-alpha 0.8.98-alpha.15

<!-- flclash:changelog:begin -->
### Bug Fixes
- **core,logs** Fix VPN startup with large retained logs and stream complete log exports

<!-- flclash:changelog:end -->

<!-- flclash:changelog:json
{"schemaVersion":2,"versions":[{"version":"0.8.98-alpha.15","tag":"v0.8.98-alpha.15","date":"","prerelease":false,"groups":[{"type":"fix","entries":[{"id":"56f5a2f","scope":"core,logs","text":"Fix VPN startup with large retained logs and stream complete log exports"}]}]}]}
-->

---

FlClash-alpha 0.8.98（构建 2026094010）

- 首页新增 Bettbox v1.19.4 的一组可选组件，可在编辑器中选择并保存，原有默认布局保持不变。
- 新增手动服务解锁检测，可随时取消；切换路由、配置或连接状态会清除上一次结果。
- 按 IP、CIDR 或网关自动暂停并恢复，仅恢复由策略暂停的会话，手动启停会撤销自动恢复资格。
- 禁用 QUIC 改为运行时下发 UDP/443 拒绝规则，不改动订阅文件本身。
- 嗅探、NTP 覆盖和桌面防休眠均默认关闭，需要时手动开启。
- 修复仪表盘布局与功能反馈：恢复紧凑的速率和分服务显示，避免内容被裁切，
  运行控件改为内联排布；网络规则保存明确反馈，服务与面板失败可恢复提示，
  面板连点做了防抖，浏览器在准备完成后再打开。
- 新增 Telegram 风格玻璃导航：手机悬浮导航栏与桌面侧栏，局部纹理 SDF 折射，
  不支持着色器时回退为磨砂；长按预览、释放提交、取消/路由打断/目标替换均按源码行为保留，
  同时保留原有键盘语义、减少动画、安全区和末行留白处理。
- 统一四个主页面（首页、代理、配置、工具）的内容层与操作层：悬浮磨砂顶部工具栏与主操作，
  轻量内容面板，工具按业务分组呈现，服务结果统一状态与地区标签，代理组、节点、配置带一致选中标记。
- 配置了启动组件时不再重复显示浮动启动按钮，编辑时隐藏浮动启动操作；原有 provider、Core 与 ServiceState 生命周期不变。
- 折射 shader 使用实际四角半径与物理尺寸，不再把卡片当作胶囊；退出页面停止背景采样，返回时恢复。
- 细化导航与紧凑页面：手机底栏图标、文案与选中块／外框圆角比例更协调，底栏为与几何匹配的超椭圆磨砂面；
  大字体下适度增高，导航语义、拖动预览与自定义图标保持不变。
- 首页启动卡内联呈现状态与运行时间，速率卡补充上下行，连接摘要占整行并显示实际 TCP／UDP 数量。
- 配置页按 URL／文件分类，显示来源图标与域名，原有订阅用量、到期与更新时间保留。
- 工具快捷卡图标与标题同行、说明一行，标准字号高度 160dp → 80dp；原有入口与设置分组不变。
- 代理卡类型／当前线路说明与延迟同行，标准字号展开档约 106dp → 78dp；三种密度与 tab／列表布局保留。
- 分组 tab 改为文字选中态、淡色数量与细下划线，去掉外层大圆角框与数量徽章；
  长分组名在列表中单行省略并提示完整名称，修复固定标题高度下的换行溢出。
- 跟随上游 v0.8.98，保留滚动日志、双渠道更新、应用内下载安装和固定个人签名。
- 使用相同包名和签名证书，可覆盖升级并保留配置与数据。

验收边界

- Flutter 3.47.1：flutter analyze 无问题；完整 flutter test 1938 通过、1 项可选在线测试跳过，既有测试未改。
- 本轮在受控数据下的页面与交互走查覆盖明暗、320/390/1100、中英俄日、1.4/2.8 字体、滚动、键盘／弹层与效果关闭，
  并覆盖三种密度、tab／列表布局、7 分组 × 每组 18 条长名称线路；长分组名溢出修复后已重跑。
- 独立 Android profile UI 包（生产页面组件加可控 provider 数据）已在无窗口 Android34／Impeller OpenGLES／host GPU 上
  验证明暗四页、底栏拖动、工具连接页、服务检测面板、配置排序／菜单、分组直接切换与更多菜单，日志无未处理异常。
- 工具 160dp → 80dp、代理展开档约 106dp → 78dp 来自独占 Android34 模拟器的 UI XML 实测，不承诺所有设备固定尺寸。
- 截图中的流量、线路与服务结果为可控数据，未初始化真实代理核心。
  本次未对完整签名 APK 的真机首次启动、系统权限与真实代理做验收。
