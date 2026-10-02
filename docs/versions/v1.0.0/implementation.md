# Telegram 源码机制与 Flutter 适配

基线为官方 Android 源码 `f2908b14133bbffbf7ab04f641ecb5bfaf533242`（源码版本12.10.6），具体原始文件、参数和交互路径见 [调研](telegram-ui-research.md)。本次采用现有 Flutter/Material UI 技术栈，没有复制 Telegram 界面文件、账号能力或品牌素材。

## 迁移范围

| Telegram 机制 | 本次实现 | 适配差异 |
|---|---|---|
| 56dp高的悬浮胶囊、周边8dp空间 | 手机导航位于内容上方，最大胶囊宽344，列表可实际经过背景 | 比原始约328dp胶囊稍宽，兼容本项目标签；大字体增加栏高 |
| 主题求色与半透明背景 | 保留用户当前 Material 色系；液态 tint .85，磨砂 .76 | 不强制 Telegram 蓝色，避免高饱和度滤镜改变用户主题 |
| 弱模糊和圆角 SDF 折射 | 高斯sigma4，加独立 GLSL 折射；厚度约短边19.64%、折射率1.5、强度.75 | Flutter与Android参数单位不能一一当作像素等价；原生图单独验收 |
| 普通强调色选中胶囊 | 当前主题主色9%透明度，选中图标及标签强化 | 避免额外的选中态折射和重复背景捕获 |
| 320ms减速、轻按压、弹簧吸附 | 选中320ms；1.019缩放380ms；拖动预览弹簧1500/.75 | 按压过程中重绘材质尺寸，避免缩放后shader边界过期 |
| 紧凑字体12/10 | 测量翻译后标签，窄屏采用10；保留完整语义及鼠标提示 | 极长翻译仍可能省略；导航语义不省略 |
| 拖动中的显示选择与最终页面选择分开 | 长按只移动预览，合法释放提交一次；取消、外部切页、目标变化均恢复 | 有意不沿用源码ACTION_CANCEL可能提交的行为；也不在拖动开始时先切页 |
| 活动页面状态与平台导航 | 保留实际NavigationBar、NavigationRail、原有PageView和FocusTraversal | 当前页面重复点击保持本项目原行为；没有统一移植Telegram滚回顶部能力 |

桌面侧栏和已有透明弹层工具栏使用同一套磨砂背景及圆角；没有给每一行或每个首页卡片叠加滤镜。高对比度、关闭页面动画时改为更实色的材质；系统减少动画时取消胶囊、页面和导航显隐运动。

## 渲染边界

`GlassSurface` 缓存一次 FragmentProgram，每个实例拥有独立 FragmentShader，离开时释放。Skia及不支持shader图片滤镜的渲染器使用磨砂回退。源码资产通过pubspec的shaders注册；不会每帧将整个页面截图回CPU。

原生验收纠正了一个只有截图才能发现的问题：单一组合滤镜和嵌套滤镜的采样纹理坐标不是同一拓扑。当前外层模糊先生成裁剪后的subpass，内层shader采样该纹理，所以距离场必须以局部纹理中心计算；浮点uniform使用真实物理表面尺寸。不能直接减去屏幕全局位置。

Flutter固定引擎证据：[subpass分配](https://github.com/flutter/flutter/blob/5d531788691ec3404cac0cee66ead4007b177363/engine/src/flutter/impeller/display_list/canvas.cc#L1900-L1937)、[纹理选择](https://github.com/flutter/flutter/blob/5d531788691ec3404cac0cee66ead4007b177363/engine/src/flutter/impeller/display_list/canvas.cc#L2446-L2447)、[未变换的片段坐标](https://github.com/flutter/flutter/blob/5d531788691ec3404cac0cee66ead4007b177363/engine/src/flutter/impeller/entity/shaders/runtime_effect.vert#L18-L20)。

图片滤镜会[复制uniform数据](https://github.com/flutter/flutter/blob/5d531788691ec3404cac0cee66ead4007b177363/engine/src/flutter/lib/ui/painting/fragment_shader.cc#L97-L107)，因此自定义渲染层在绘制时先提交尺寸、再创建滤镜。GLES采样翻转Y轴按[官方API约定](https://api.flutter.dev/flutter/dart-ui/ImageFilter/ImageFilter.shader.html)处理。两维棋盘格比单纯竖条纹更适合验证边缘折射。

## 导航与业务边界

页面末行和FAB使用BottomInsetScope保留导航与系统安全区；键盘出现时收起手机栏，恢复后重新出现。工具页从原来的固定20底部空白改为随导航高度留白。原有页面保活、动态代理页面、搜索退出和键盘焦点规则保持，新增测试覆盖取消、迟到释放、RTL、目标替换、减少动画、高对比度和底部安全区。

没有增加核心生命周期所有者，没有改订阅、代理节点、服务检测或自动启停的数据模型；表面交互不替代真实域状态。
