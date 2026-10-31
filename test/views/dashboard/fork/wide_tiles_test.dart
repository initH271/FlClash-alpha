import 'package:fl_clash/core/controller.dart';
import 'package:fl_clash/core/interface.dart';
import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/state.dart';
import 'package:fl_clash/views/dashboard/dashboard.dart';
import 'package:fl_clash/views/dashboard/fork/auto_pause.dart';
import 'package:fl_clash/views/dashboard/fork/push_channel.dart';
import 'package:fl_clash/views/dashboard/fork/route_check.dart';
import 'package:fl_clash/views/dashboard/widgets/card.dart';
import 'package:fl_clash/views/dashboard/widgets/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/misc.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:mocktail/mocktail.dart';

import '../../../helpers/test_app.dart';
import '../../../helpers/test_profiles.dart';

class _MockCore extends Mock implements CoreHandlerInterface {}

const _forkCards = {
  DashboardWidget.forkPushChannel: PushChannelCard,
  DashboardWidget.forkRouteCheck: RouteCheckCard,
  DashboardWidget.forkAutoPause: AutoPauseCard,
};

const _phone = Size(412, 900);
const _landscape = Size(800, 400);
const _narrowestWide = Size(640, 400);
const _tablet = Size(1100, 860);

void main() {
  setUpAll(() {
    registerFallbackValue(const ProbeParams(url: '', timeout: 0));
    registerFallbackValue(const OutboundIpParams(timeout: 0));
  });

  late _MockCore core;
  late ProviderContainer container;

  void useContainer({List<Override> overrides = const []}) {
    container = ProviderContainer(
      overrides: [
        profilesProvider.overrideWith(TestProfiles.new),
        coreHandlerProvider.overrideWithValue(CoreController.scoped(core)),
        ...overrides,
      ],
    );
    globalState.container = container;
  }

  setUp(() {
    core = _MockCore();
    when(() => core.probe(any())).thenAnswer((_) async => null);
    when(() => core.getConnections()).thenAnswer((_) async => const []);
    when(() => core.outboundIp(any())).thenAnswer((_) async => null);
    useContainer();
  });

  tearDown(() => container.dispose());

  Future<void> pumpDashboard(
    WidgetTester tester,
    Size size,
    List<DashboardWidget> forkTiles,
  ) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    container.read(viewSizeProvider.notifier).value = size;
    container
        .read(appSettingProvider.notifier)
        .update(
          (state) => state.copyWith(
            dashboardWidgets: [DashboardWidget.currentOutbound, ...forkTiles],
          ),
        );
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const TestApp(
          child: DashboardView(platform: SupportPlatform.Android),
        ),
      ),
    );
    await tester.pump();
  }

  Future<void> teardown(WidgetTester tester) async {
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pump(const Duration(seconds: 5));
  }

  Finder onDashboard(Type card) =>
      find.byType(card, skipOffstage: false).hitTestable();

  Finder built(Type card) => find.byType(card, skipOffstage: false);

  ScrollPosition scrollOf(WidgetTester tester) =>
      tester.state<ScrollableState>(find.byType(Scrollable).first).position;

  Future<void> scrollToEnd(WidgetTester tester) async {
    final position = scrollOf(tester);
    position.jumpTo(position.maxScrollExtent);
    await tester.pump();
  }

  group('at 640 dp and wider', () {
    for (final size in const [_narrowestWide, _landscape, _tablet]) {
      testWidgets('all saved fork tiles are reachable at $size', (
        tester,
      ) async {
        await pumpDashboard(tester, size, _forkCards.keys.toList());
        for (final card in _forkCards.values) {
          expect(built(card), findsOneWidget, reason: '$card');
        }
        await scrollToEnd(tester);
        expect(onDashboard(RouteCheckCard), findsOneWidget);
        await teardown(tester);
      });
    }

    testWidgets('only the saved fork tiles appear', (tester) async {
      await pumpDashboard(tester, _landscape, const [
        DashboardWidget.forkRouteCheck,
      ]);
      expect(built(RouteCheckCard), findsOneWidget);
      expect(built(PushChannelCard), findsNothing);
      expect(built(AutoPauseCard), findsNothing);
      await teardown(tester);
    });

    testWidgets('no fork tile appears when none is saved', (tester) async {
      await pumpDashboard(tester, _landscape, const []);
      for (final card in _forkCards.values) {
        expect(built(card), findsNothing, reason: '$card');
      }
      await teardown(tester);
    });

    testWidgets('a fork tile in the wide layout still acts', (tester) async {
      container.dispose();
      useContainer(
        overrides: [
          runTimeProvider.overrideWithBuild((_, _) => 1),
          routeTrackerProvider.overrideWithBuild(
            (ref, _) => RouteState(
              coreEpoch: 1,
              routeVersion: 1,
              hostEpoch: 1,
              proxied: ref.watch(isStartProvider),
              synced: true,
              live: true,
            ),
          ),
        ],
      );
      await pumpDashboard(tester, _landscape, const [
        DashboardWidget.forkRouteCheck,
      ]);
      await scrollToEnd(tester);
      await tester.tap(
        find.descendant(
          of: find.byType(RouteCheckCard),
          matching: find.byType(DashboardIconButton),
        ),
      );
      await tester.pump();
      verify(() => core.probe(any())).called(greaterThan(0));
      await teardown(tester);
    });

    testWidgets('two tiles share a row, on the columns of the grid above', (
      tester,
    ) async {
      await pumpDashboard(tester, _landscape, const [
        DashboardWidget.forkPushChannel,
        DashboardWidget.forkAutoPause,
      ]);
      final push = tester.getRect(built(PushChannelCard));
      final pause = tester.getRect(built(AutoPauseCard));
      final grid = tester.getRect(built(CurrentOutboundCard));
      expect(push.top, pause.top);
      expect(push.left, grid.left);
      expect(pause.right, grid.right);
      expect(push.width, pause.width);
      await teardown(tester);
    });

    for (final size in const [_landscape, _tablet]) {
      testWidgets('fork tiles leave the upstream grid in place at $size', (
        tester,
      ) async {
        const upstream = [
          CurrentOutboundCard,
          OutboundModeBar,
          ProfilesCard,
          MemoryInfo,
          ConnectionStatsCard,
        ];
        Map<Type, Rect> gridRects() => {
          for (final card in upstream)
            if (built(card).evaluate().isNotEmpty)
              card: tester.getRect(built(card)),
        };
        await pumpDashboard(tester, size, const []);
        final before = gridRects();
        expect(before, isNotEmpty);

        await pumpDashboard(tester, size, _forkCards.keys.toList());
        expect(gridRects(), before);
        await teardown(tester);
      });
    }
  });

  group('below 640 dp', () {
    testWidgets('tiles keep the single full width column', (tester) async {
      await pumpDashboard(tester, _phone, const [
        DashboardWidget.forkPushChannel,
        DashboardWidget.forkRouteCheck,
      ]);
      final status = tester.getRect(built(CurrentOutboundCard));
      final push = tester.getRect(built(PushChannelCard));
      final route = tester.getRect(built(RouteCheckCard));
      expect(push.left, status.left);
      expect(push.width, status.width);
      expect(route.left, status.left);
      expect(route.width, status.width);
      expect(push.top, greaterThan(status.bottom));
      expect(route.top, greaterThan(push.bottom));
      expect(built(OutboundModeBar), findsNothing);
      await teardown(tester);
    });

    testWidgets('a tile that is not saved stays away', (tester) async {
      await pumpDashboard(tester, _phone, const [
        DashboardWidget.forkPushChannel,
      ]);
      expect(built(PushChannelCard), findsOneWidget);
      expect(built(RouteCheckCard), findsNothing);
      expect(built(AutoPauseCard), findsNothing);
      await teardown(tester);
    });
  });
}
