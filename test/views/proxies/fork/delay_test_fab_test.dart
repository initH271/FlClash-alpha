import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/pages/home.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/state.dart';
import 'package:fl_clash/ui/icons/icons.dart';
import 'package:fl_clash/views/proxies/card.dart';
import 'package:fl_clash/views/proxies/fork/delay_test_fab.dart';
import 'package:fl_clash/views/proxies/proxies.dart';
import 'package:fl_clash/widgets/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';

import '../../../helpers/glyph_finders.dart';
import '../../../helpers/test_app.dart';
import '../../../helpers/test_profiles.dart';

const _phone = Size(393, 852);
const _safeBottom = 34.0;

final _fab = find.byType(FloatingActionButton);
final _charging = find.descendant(of: _fab, matching: find.byType(ShaderMask));

class _SpyProxiesAction extends ProxiesAction {
  static final tested = <String>[];

  @override
  Future<void> delayTestPageGroup(
    String groupName, {
    bool matchSearch = true,
  }) async {
    tested.add(groupName);
  }
}

Group _group(String name, {int count = 40}) => Group(
  type: GroupType.Selector,
  name: name,
  all: [
    for (var i = 0; i < count; i++) Proxy(name: '$name $i', type: 'Direct'),
  ],
);

ProviderContainer _container(
  WidgetTester tester, {
  ProxiesType type = ProxiesType.tab,
  List<Group>? groups,
  bool floatingNavigation = true,
}) {
  tester.view.physicalSize = _phone;
  tester.view.devicePixelRatio = 1;
  tester.view.padding = const FakeViewPadding(bottom: _safeBottom);
  addTearDown(tester.view.reset);
  _SpyProxiesAction.tested.clear();
  final profile = Profile.normal().copyWith(currentGroupName: 'A');
  final container = ProviderContainer(
    overrides: [
      currentProfileIdProvider.overrideWithBuild((_, _) => profile.id),
      profilesProvider.overrideWith(() => TestProfiles([profile])),
      currentGroupsStateProvider.overrideWithValue(
        GroupsState(value: groups ?? [_group('A'), _group('B')]),
      ),
      proxiesActionProvider.overrideWith(_SpyProxiesAction.new),
      navigationItemsStateProvider.overrideWithValue(
        NavigationItemsState(
          value: [
            NavigationItem(
              glyph: AppGlyphs.proxies,
              label: PageLabel.proxies,
              builder: (_) => const ProxiesView(),
            ),
            NavigationItem(
              glyph: AppGlyphs.tools,
              label: PageLabel.tools,
              builder: (_) => const SizedBox.shrink(),
            ),
          ],
        ),
      ),
    ],
  );
  addTearDown(container.dispose);
  globalState.container = container;
  for (final provider in <ProviderListenable<Object?>>[
    currentProfileProvider,
    proxiesStyleSettingProvider,
    appSettingProvider,
  ]) {
    addTearDown(container.listen(provider, (_, _) {}).close);
  }
  container
      .read(proxiesStyleSettingProvider.notifier)
      .update((state) => state.copyWith(type: type));
  container
      .read(appSettingProvider.notifier)
      .update(
        (state) => state.copyWith(floatingNavigationBar: floatingNavigation),
      );
  return container;
}

Future<void> _pumpView(
  WidgetTester tester,
  ProviderContainer container, {
  bool picker = false,
  TextDirection? direction,
}) async {
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: TestApp(
        homeBuilder: (child) => direction == null
            ? child
            : Directionality(textDirection: direction, child: child),
        child: ProxiesView(picker: picker),
      ),
    ),
  );
  await tester.pump();
}

// Alone, since the top action's spinner never stops running animations.
Future<void> _pumpButton(
  WidgetTester tester,
  ProviderContainer container,
) async {
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: TestApp(
        child: ProxiesDelayTestFab(
          onPressed: () {},
          child: const SizedBox.shrink(),
        ),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

Future<void> _pumpHome(WidgetTester tester, ProviderContainer container) async {
  container.read(viewSizeProvider.notifier).value = _phone;
  container.read(currentPageLabelProvider.notifier).toPage(PageLabel.proxies);
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: const TestApp(includeNavigatorKey: false, child: HomePage()),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('the tab page floats the delay test as an icon', (tester) async {
    await _pumpView(tester, _container(tester));

    expect(_fab, findsOneWidget);
    expect(
      find.descendant(of: _fab, matching: find.byGlyph(AppGlyphs.bolt)),
      findsOneWidget,
    );
    expect(
      find.descendant(of: _fab, matching: find.byType(Text)),
      findsNothing,
    );
    expect(find.text('Delay test'), findsNothing);
    expect(tester.widget<FloatingActionButton>(_fab).tooltip, 'Delay test');
    expect(tester.getSize(_fab), const Size.square(56));
  });

  testWidgets('the list page tests from its group headers instead', (
    tester,
  ) async {
    await _pumpView(tester, _container(tester, type: ProxiesType.list));

    expect(_fab, findsNothing);
  });

  testWidgets('the dashboard picker leaves its foot to the docked search', (
    tester,
  ) async {
    await _pumpView(tester, _container(tester), picker: true);

    expect(find.byType(ProxyCard), findsWidgets);
    expect(_fab, findsNothing);
  });

  testWidgets('no groups leave nothing to test', (tester) async {
    await _pumpView(tester, _container(tester, groups: const []));

    expect(_fab, findsNothing);
  });

  testWidgets('it follows the reading direction', (tester) async {
    await _pumpView(tester, _container(tester), direction: TextDirection.rtl);

    expect(tester.getRect(_fab).left, BottomInsetScope.dockedSearchMargin);
  });

  testWidgets('a tap tests the current group', (tester) async {
    await _pumpView(tester, _container(tester));

    await tester.tap(_fab);
    await tester.pump();
    expect(_SpyProxiesAction.tested, ['A']);

    await tester.tap(find.text('B'));
    await tester.pumpAndSettle();
    await tester.tap(_fab);
    await tester.pump();
    expect(_SpyProxiesAction.tested, ['A', 'B']);
  });

  testWidgets('while the current group tests it charges and ignores taps', (
    tester,
  ) async {
    final container = _container(tester);
    await _pumpView(tester, container);
    final testing = container.read(delayTestingGroupsProvider.notifier);
    bool enabled() =>
        tester.widget<FloatingActionButton>(_fab).onPressed != null;

    testing.start('B');
    await tester.pump();
    expect(enabled(), isTrue);
    expect(_charging, findsNothing);

    testing.start('A');
    await tester.pump();
    expect(enabled(), isFalse);
    expect(_charging, findsOneWidget);
    expect(tester.widget<FloatingActionButton>(_fab).tooltip, 'Delay test');
    await tester.tap(_fab, warnIfMissed: false);
    await tester.pump();
    expect(_SpyProxiesAction.tested, isEmpty);

    testing.stop('A');
    await tester.pump();
    expect(enabled(), isTrue);
    expect(_charging, findsNothing);
    await tester.pumpAndSettle();
  });

  testWidgets('the bolt charges in place and comes back when testing ends', (
    tester,
  ) async {
    final container = _container(tester);
    await _pumpButton(tester, container);
    final testing = container.read(delayTestingGroupsProvider.notifier);
    final bolt = find.descendant(
      of: _fab,
      matching: find.byGlyph(AppGlyphs.bolt),
    );
    final idle = tester.getRect(bolt);

    testing.start('A');
    await tester.pump();
    expect(_charging, findsOneWidget);
    expect(tester.getRect(bolt), idle);
    await tester.pump(const Duration(milliseconds: 600));
    expect(tester.hasRunningAnimations, isTrue);

    testing.stop('A');
    await tester.pump();
    expect(_charging, findsNothing);
    expect(tester.getRect(bolt), idle);
    await tester.pumpAndSettle();
    expect(tester.hasRunningAnimations, isFalse);
  });

  testWidgets('with animations off the bolt holds still', (tester) async {
    tester.platformDispatcher.accessibilityFeaturesTestValue =
        const FakeAccessibilityFeatures(disableAnimations: true);
    addTearDown(tester.platformDispatcher.clearAccessibilityFeaturesTestValue);
    final container = _container(tester);
    await _pumpButton(tester, container);

    container.read(delayTestingGroupsProvider.notifier).start('A');
    await tester.pump();

    expect(_charging, findsOneWidget);
    expect(tester.hasRunningAnimations, isFalse);
  });

  testWidgets('the last row scrolls clear of it', (tester) async {
    await _pumpHome(tester, _container(tester));

    final position = tester
        .state<ScrollableState>(
          find
              .descendant(
                of: find.byType(GridView),
                matching: find.byType(Scrollable),
              )
              .first,
        )
        .position;
    position.jumpTo(position.maxScrollExtent);
    await tester.pumpAndSettle();

    final last = tester.getRect(find.byType(ProxyCard).last);
    expect(last.bottom, lessThanOrEqualTo(tester.getRect(_fab).top));
  });

  testWidgets('it stands above the floating navigation bar', (tester) async {
    await _pumpHome(tester, _container(tester));

    final fab = tester.getRect(_fab);
    final dock = tester.getRect(find.byType(FloatingNavigationBar));
    expect(fab.bottom, lessThanOrEqualTo(dock.top));
    expect(fab.bottom, lessThan(_phone.height - _safeBottom));
  });

  testWidgets('it stands above the docked navigation bar', (tester) async {
    await _pumpHome(tester, _container(tester, floatingNavigation: false));

    final fab = tester.getRect(_fab);
    final bar = tester.getRect(find.byType(NavigationBar));
    expect(fab.bottom, lessThanOrEqualTo(bar.top));
  });

  testWidgets('it stays put under the keyboard', (tester) async {
    await _pumpHome(tester, _container(tester));
    final resting = tester.getRect(_fab);

    tester.view.viewInsets = const FakeViewPadding(bottom: 300);
    await tester.pumpAndSettle();

    expect(tester.getRect(_fab), resting);
  });
}
