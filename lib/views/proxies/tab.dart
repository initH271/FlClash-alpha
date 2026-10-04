import 'dart:async';
import 'dart:math';
import 'dart:ui' as ui;

import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/models/common.dart';
import 'package:fl_clash/state.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/widgets/widgets.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'card.dart';
import 'common.dart';

typedef ProxyGroupViewKeyMap =
    Map<String, GlobalObjectKey<_ProxyGroupViewState>>;

class ProxiesTabView extends ConsumerStatefulWidget {
  const ProxiesTabView({super.key});

  static Map<String, PageStorageKey> pageListStoreMap = {};

  @override
  ConsumerState<ProxiesTabView> createState() => ProxiesTabViewState();
}

class ProxiesTabViewState extends ConsumerState<ProxiesTabView>
    with TickerProviderStateMixin {
  TabController? _tabController;
  final _hasMoreButtonNotifier = ValueNotifier<bool>(false);
  ProxyGroupViewKeyMap _keyMap = {};

  @override
  void initState() {
    super.initState();
    ref.listenManual(proxiesTabControllerStateProvider, (prev, next) {
      if (prev == next) {
        return;
      }
      if (!stringListEquality.equals(prev?.groupNames, next.groupNames)) {
        final groupNames = next.groupNames;
        final currentGroupName = next.currentGroupName;
        final index = groupNames.indexWhere((item) => item == currentGroupName);
        _updateTabController(groupNames.length, index);
      }
    }, fireImmediately: true);
  }

  @override
  void dispose() {
    _destroyTabController();
    _hasMoreButtonNotifier.dispose();
    super.dispose();
  }

  void scrollToGroupSelected() {
    final group = currentGroup;
    if (group == null) {
      return;
    }
    _keyMap[group.name]?.currentState?.scrollToSelected();
  }

  Future<void> delayTestCurrentGroup() async {
    final group = currentGroup;
    if (group == null) {
      return;
    }
    await ref
        .read(proxiesActionProvider.notifier)
        .delayTest(group.all, group.testUrl);
  }

  Group? get currentGroup {
    return _getGroup(_tabController?.index);
  }

  Group? _getGroup(int? index) {
    final groups = ref.read(proxiesTabStateProvider).groups;
    if (index == null || index < 0 || index >= groups.length) {
      return null;
    }
    return groups[index];
  }

  Widget _buildMoreButton() {
    return Consumer(
      builder: (_, ref, _) {
        final isMobileView = ref.watch(isMobileViewProvider);
        return IconButton(
          tooltip: context.appLocalizations.more,
          onPressed: _showMoreMenu,
          icon: isMobileView
              ? const Icon(Icons.expand_more)
              : const Icon(Icons.chevron_right),
        );
      },
    );
  }

  void _showMoreMenu() {
    showSheet(
      context: context,
      props: const SheetProps(isScrollControlled: false),
      builder: (_) {
        return AdaptiveSheetScaffold(
          body: SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: Consumer(
              builder: (_, ref, _) {
                final state = ref.watch(proxiesTabControllerStateProvider);
                final groupNames = state.groupNames;
                final currentGroupName = state.currentGroupName;
                return SizedBox(
                  width: double.infinity,
                  child: Wrap(
                    alignment: WrapAlignment.center,
                    runSpacing: 8,
                    spacing: 8,
                    children: [
                      for (final groupName in groupNames)
                        SettingTextCard(
                          groupName,
                          onPressed: () {
                            final index = groupNames.indexWhere(
                              (item) => item == groupName,
                            );
                            if (index == -1) return;
                            _tabController?.animateTo(index);
                            ref
                                .read(proxiesActionProvider.notifier)
                                .updateCurrentGroupName(groupName);
                            Navigator.of(context).pop();
                          },
                          isSelected: groupName == currentGroupName,
                        ),
                    ],
                  ),
                );
              },
            ),
          ),
          title: context.appLocalizations.proxyGroup,
        );
      },
    );
  }

  void _tabControllerListener([int? index]) {
    final group = _getGroup(index ?? _tabController?.index);
    if (group == null) {
      return;
    }
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) {
        return;
      }
      ref
          .read(proxiesActionProvider.notifier)
          .updateCurrentGroupName(group.name);
    });
  }

  void _destroyTabController() {
    _tabController?.removeListener(_tabControllerListener);
    _tabController?.dispose();
    _tabController = null;
  }

  // An empty group list keeps the previous controller: the outgoing tab bar
  // still drives it while the empty state animates in.
  void _updateTabController(int length, int index) {
    if (length == 0) {
      return;
    }
    _destroyTabController();
    final realIndex = index == -1 ? 0 : index;
    final controller = TabController(
      length: length,
      initialIndex: realIndex,
      vsync: this,
    );
    _tabController = controller;
    _tabControllerListener(realIndex);
    controller.addListener(_tabControllerListener);
  }

  @override
  Widget build(BuildContext context) {
    final appLocalizations = context.appLocalizations;
    ref.watch(themeSettingProvider.select((state) => state.textScale));
    final state = ref.watch(proxiesTabStateProvider.select((state) => state));
    final proxiesLayout = ref.watch(
      proxiesStyleSettingProvider.select((state) => state.layout),
    );
    final groups = state.groups;
    _keyMap = {};
    final scope = ContentStyleScope.of(context);
    final enhanced = scope != null;
    final tabHeight = max(44.0, globalState.measure.titleSmallHeight + 16);
    final header = NotificationListener<ScrollMetricsNotification>(
      onNotification: (scrollNotification) {
        _hasMoreButtonNotifier.value =
            scrollNotification.metrics.maxScrollExtent > 0;
        return false;
      },
      child: ValueListenableBuilder(
        valueListenable: _hasMoreButtonNotifier,
        builder: (_, value, child) {
          return Stack(
            alignment: AlignmentDirectional.centerStart,
            children: [
              TabBar(
                controller: _tabController,
                padding: EdgeInsets.only(
                  left: enhanced ? 0 : 16,
                  right: 16 + (value ? 40 : 0),
                ),
                dividerColor: Colors.transparent,
                labelColor: context.colorScheme.primary,
                unselectedLabelColor: context.colorScheme.onSurfaceVariant,
                labelStyle: context.textTheme.titleSmall?.copyWith(
                  fontWeight: FontWeight.w600,
                ),
                unselectedLabelStyle: context.textTheme.titleSmall?.copyWith(
                  fontWeight: FontWeight.w500,
                ),
                indicatorSize: TabBarIndicatorSize.label,
                indicatorWeight: 2,
                indicatorPadding: const EdgeInsets.symmetric(horizontal: 4),
                labelPadding: const EdgeInsets.symmetric(horizontal: 12),
                isScrollable: true,
                tabAlignment: TabAlignment.start,
                tabs: [
                  for (final group in groups)
                    Tab(
                      height: tabHeight,
                      child: Builder(
                        builder: (context) {
                          return Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              EmojiText(
                                group.name,
                                style: DefaultTextStyle.of(context).style,
                              ),
                              const SizedBox(width: 8),
                              Text(
                                '${group.all.length}',
                                style: context.textTheme.labelSmall?.copyWith(
                                  color: context.colorScheme.onSurfaceVariant,
                                ),
                              ),
                            ],
                          );
                        },
                      ),
                    ),
                ],
              ),
              if (value) Positioned(right: 0, child: child!),
            ],
          );
        },
        child: Container(
          decoration: BoxDecoration(
            gradient: LinearGradient(
              begin: Alignment.centerLeft,
              end: Alignment.centerRight,
              colors: [
                context.colorScheme.surface.opacity10,
                context.colorScheme.surface,
              ],
              stops: const [0.0, 0.1],
            ),
          ),
          child: _buildMoreButton(),
        ),
      ),
    );
    final views = LayoutBuilder(
      builder: (_, constraints) {
        final columns = getProxiesColumns(
          max(constraints.maxWidth - 32, 0),
          proxiesLayout,
        );
        return TabBarView(
          controller: _tabController,
          children: [
            for (final group in groups)
              ProxyGroupView(
                key: _keyMap.updateCacheValue(
                  group.name,
                  () => GlobalObjectKey<_ProxyGroupViewState>(group.name),
                ),
                group: group,
                columns: columns,
                cardType: state.proxyCardType,
                topInset: enhanced ? scope.topInset + tabHeight + 12 : 0,
              ),
          ],
        );
      },
    );
    return NullStatusSwitcher(
      isEmpty: groups.isEmpty || _tabController == null,
      nullStatus: NullStatus(
        illustration: NullStatusIllustration.proxies,
        label: appLocalizations.nullTip(appLocalizations.proxies),
      ),
      child: enhanced
          ? Stack(
              children: [
                Positioned.fill(child: views),
                Positioned(
                  left: 16,
                  right: 16,
                  top: scope.topInset + 8,
                  child: ClipRect(
                    child: BackdropFilter(
                      enabled:
                          scope.effectsEnabled &&
                          !MediaQuery.highContrastOf(context),
                      filter: ui.ImageFilter.blur(sigmaX: 12, sigmaY: 12),
                      child: ColoredBox(
                        color: context.colorScheme.surface.withValues(
                          alpha: .94,
                        ),
                        child: header,
                      ),
                    ),
                  ),
                ),
              ],
            )
          : Column(
              children: [
                header,
                Expanded(child: views),
              ],
            ),
    );
  }
}

class ProxyGroupView extends ConsumerStatefulWidget {
  final Group group;
  final int columns;
  final ProxyCardType cardType;
  final double topInset;

  const ProxyGroupView({
    super.key,
    required this.group,
    required this.columns,
    required this.cardType,
    this.topInset = 0,
  });

  @override
  ConsumerState<ProxyGroupView> createState() => _ProxyGroupViewState();
}

class _ProxyGroupViewState extends ConsumerState<ProxyGroupView> {
  late final ScrollController _controller;

  @override
  void initState() {
    super.initState();
    _controller = ScrollController();
  }

  PageStorageKey _getPageStorageKey() {
    final profile = ref.read(currentProfileProvider);
    final key =
        '${profile?.id}_${ScrollPositionCacheKey.proxiesTabList.name}_${widget.group.name}';
    return ProxiesTabView.pageListStoreMap.updateCacheValue(
      key,
      () => PageStorageKey(key),
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void scrollToSelected() {
    if (_controller.position.maxScrollExtent == 0) {
      return;
    }
    _controller.animateTo(
      min(
        16 +
            getScrollToSelectedOffset(
              ref: ref,
              groupName: widget.group.name,
              proxies: widget.group.all,
              columns: widget.columns,
            ),
        _controller.position.maxScrollExtent,
      ),
      duration: const Duration(milliseconds: 300),
      curve: Curves.easeIn,
    );
  }

  @override
  Widget build(BuildContext context) {
    final group = widget.group;
    final proxies = group.all;
    return CommonScrollBar(
      controller: _controller,
      child: GridView.builder(
        key: _getPageStorageKey(),
        controller: _controller,
        padding: EdgeInsets.only(
          top: 16 + widget.topInset,
          left: 16,
          right: 16,
          bottom: 16 + BottomInsetScope.of(context),
        ),
        gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
          crossAxisCount: widget.columns,
          mainAxisSpacing: 8,
          crossAxisSpacing: 8,
          mainAxisExtent: getItemHeight(widget.cardType),
        ),
        itemCount: proxies.length,
        itemBuilder: (_, index) {
          final proxy = proxies[index];
          return ProxyCard(
            testUrl: group.testUrl,
            groupType: group.type,
            type: widget.cardType,
            proxy: proxy,
            groupName: group.name,
          );
        },
      ),
    );
  }
}

class DelayTestButton extends StatefulWidget {
  final Future Function() onClick;

  const DelayTestButton({super.key, required this.onClick});

  @override
  State<DelayTestButton> createState() => _DelayTestButtonState();
}

class _DelayTestButtonState extends State<DelayTestButton>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;
  late Animation<double> _animation;

  bool _running = false;

  Future<void> _healthcheck() async {
    if (_running) {
      return;
    }
    _running = true;
    unawaited(_controller.forward());
    try {
      await widget.onClick();
    } finally {
      _running = false;
      if (mounted) {
        unawaited(_controller.reverse());
      }
    }
  }

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 400),
    );
    _animation = Tween<double>(begin: 1.0, end: 0.0).animate(
      CurvedAnimation(parent: _controller, curve: Curves.easeInOutBack),
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final appLocalizations = context.appLocalizations;
    return AnimatedBuilder(
      animation: _controller.view,
      builder: (_, child) {
        return FadeTransition(
          opacity: _animation,
          child: ScaleTransition(scale: _animation, child: child),
        );
      },
      child: CommonFloatingActionButton(
        onPressed: _healthcheck,
        label: appLocalizations.delayTest,
        icon: const Icon(Icons.network_ping),
      ),
    );
  }
}
