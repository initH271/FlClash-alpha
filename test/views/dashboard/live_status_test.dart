import 'package:drift/native.dart';
import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/common/mitm_module.dart';
import 'package:fl_clash/database/database.dart';
import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/providers/mitm.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/state.dart';
import 'package:fl_clash/ui/icons/icons.dart';
import 'package:fl_clash/views/dashboard/widgets/live_status.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:package_info_plus/package_info_plus.dart';

import '../../helpers/glyph_finders.dart';
import '../../helpers/host_scaffold.dart';
import '../../helpers/test_app.dart';
import '../../helpers/test_profiles.dart';

final _profile = Profile.normal(label: 'My subscription');

void main() {
  late ProviderContainer container;
  var toAgree = <MitmModule>[];

  setUp(() {
    toAgree = [];
    container = ProviderContainer(
      overrides: [
        profilesProvider.overrideWith(() => TestProfiles([_profile])),
        mitmModulesToAgreeProvider.overrideWith((ref) => toAgree),
      ],
    );
    globalState.container = container;
    globalState.packageInfo = PackageInfo(
      appName: 'FlClash',
      packageName: 'com.follow.clash',
      version: '0.9.3',
      buildNumber: '1',
    );
    container.read(coreStatusProvider.notifier).value = CoreStatus.connected;
  });

  tearDown(() => container.dispose());

  // A starting core spins, so the deck never settles on its own.
  Future<void> settle(WidgetTester tester) async {
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 600));
  }

  Future<void> pumpButton(
    WidgetTester tester, {
    bool separateCore = false,
    Size size = const Size(800, 900),
  }) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: TestApp(
          locale: const Locale('en'),
          child: HostScaffold(
            body: Padding(
              padding: const EdgeInsets.only(left: 400, top: 40),
              child: Align(
                alignment: Alignment.topLeft,
                child: SizedBox(
                  height: 44,
                  child: LiveStatusButton(separateCore: separateCore),
                ),
              ),
            ),
          ),
        ),
      ),
    );
    await settle(tester);
  }

  Future<void> open(WidgetTester tester) async {
    await tester.tap(find.byTooltip('Live status'));
    await settle(tester);
  }

  Finder front(String text) => find.text(text).hitTestable();

  Finder badge(String label) => find.byWidgetPredicate(
    (widget) => widget is Semantics && widget.properties.label == label,
  );

  testWidgets('is gone while nothing is happening', (tester) async {
    await pumpButton(tester);

    expect(find.byTooltip('Live status'), findsNothing);
  });

  testWidgets('names the modules an update turned off', (tester) async {
    MitmModule module(int id, String name) => MitmModule(
      id: id,
      name: name,
      enabled: false,
      lastUpdateTime: DateTime(2026, 11, 17),
    );
    toAgree = [module(1, 'Ads')];
    await pumpButton(tester);

    expect(badge('Modules turned off'), findsOneWidget);
    await open(tester);

    expect(front('Ads'), findsOneWidget);
    expect(
      find.text(
        'An update to Ads brought scripts or network changes you have not '
        'agreed to',
      ),
      findsOneWidget,
    );
    expect(front('View'), findsOneWidget);

    toAgree = [module(1, 'Ads'), module(2, 'Tracker'), module(3, 'Video')];
    container.invalidate(mitmModulesToAgreeProvider);
    await settle(tester);

    expect(front('+1'), findsOneWidget);
    expect(
      find.text(
        '3 modules got updates with scripts or network changes you have not '
        'agreed to',
      ),
      findsOneWidget,
    );
  });

  group('with modules stored', () {
    late Database testDatabase;

    setUp(() {
      testDatabase = Database(NativeDatabase.memory());
      database = testDatabase;
    });

    // The modules provider holds a query open until its container goes.
    tearDown(() {
      container.dispose();
      return testDatabase.close();
    });

    testWidgets('the module card asks about each module in turn', (
      tester,
    ) async {
      MitmModule module(int id, String name) => MitmModule(
        id: id,
        name: name,
        enabled: false,
        scripts: 1,
        order: id,
        lastUpdateTime: DateTime(2026, 11, 17),
      );
      await testDatabase.mitmModulesDao.putAll([
        module(1, 'Ads').toCompanion(),
        module(2, 'Tracker').toCompanion(),
      ]);
      container.dispose();
      container = ProviderContainer(
        overrides: [
          profilesProvider.overrideWith(() => TestProfiles([_profile])),
          for (final id in [1, 2])
            mitmModuleContentProvider(
              id,
            ).overrideWith((ref) async => MitmModuleContent()),
        ],
      );
      globalState.container = container;
      container.read(coreStatusProvider.notifier).value = CoreStatus.connected;
      await pumpButton(tester);
      await open(tester);

      await tester.tap(front('View'));
      for (final _ in [1, 2]) {
        await settle(tester);
        expect(
          find.text(currentAppLocalizations.mitmScriptRiskTitle),
          findsOneWidget,
        );
        await tester.tap(find.text(currentAppLocalizations.cancel));
      }
      await settle(tester);

      final stored = await testDatabase.mitmModulesDao.query().get();
      expect([for (final item in stored) item.accepted], [false, false]);
      expect(container.read(mitmModulesToAgreeProvider), isEmpty);
      expect(
        find.text(currentAppLocalizations.mitmScriptRiskTitle),
        findsNothing,
      );
      expect(badge('Modules turned off'), findsNothing);
    });
  });

  testWidgets('leaves updating resources out', (tester) async {
    container.read(updatingKeysProvider.notifier)
      ..start(_profile.updatingKey)
      ..start(GeoResource.GEOIP.updatingKey);
    await pumpButton(tester);

    expect(find.byTooltip('Live status'), findsNothing);
  });

  testWidgets('drops a desktop deck under the bar at the right edge', (
    tester,
  ) async {
    container.read(viewSizeProvider.notifier).value = const Size(1200, 900);
    container.read(coreStatusProvider.notifier).value = CoreStatus.disconnected;
    await pumpButton(tester, size: const Size(1200, 900));
    final anchor = tester.getRect(find.byType(LiveStatusButton));
    await open(tester);

    final card = tester.getRect(
      find.byKey(const ValueKey<Object>(CoreLiveStatus)).last,
    );
    expect(card.right, 1200 - 16 - 24);
    expect(card.top, anchor.bottom + 56);
  });

  testWidgets('closes once nothing is left', (tester) async {
    container.read(coreStatusProvider.notifier).value = CoreStatus.disconnected;
    await pumpButton(tester);
    await open(tester);

    expect(find.text('The app lost its connection to the core'), findsOne);

    container.read(coreStatusProvider.notifier).value = CoreStatus.connected;
    await settle(tester);

    expect(find.text('The app lost its connection to the core'), findsNothing);
  });

  testWidgets('a tap outside the deck closes it', (tester) async {
    container.read(coreStatusProvider.notifier).value = CoreStatus.disconnected;
    await pumpButton(tester);
    await open(tester);

    await tester.tapAt(const Offset(20, 880));
    await settle(tester);

    expect(find.text('Restart core'), findsNothing);
  });

  testWidgets('centers the front card where an alert sits', (tester) async {
    container.read(coreStatusProvider.notifier).value = CoreStatus.disconnected;
    await pumpButton(tester);
    await open(tester);

    expect(
      tester.getCenter(find.byKey(const ValueKey<Object>(CoreLiveStatus)).last),
      const Offset(400, 450),
    );
  });

  group('a separate core', () {
    testWidgets('alone shrinks the button to a check that opens its card', (
      tester,
    ) async {
      await pumpButton(tester, separateCore: true);

      expect(find.byGlyph(AppGlyphs.check), findsOneWidget);

      await open(tester);

      expect(find.text('Core running'), findsOneWidget);
      expect(front('Force restart'), findsOneWidget);
    });

    testWidgets('asks before a force restart', (tester) async {
      await pumpButton(tester, separateCore: true);
      await open(tester);

      await tester.tap(front('Force restart'));
      await settle(tester);

      expect(find.text('Force restart the core?'), findsOneWidget);
      expect(front('Restart'), findsOneWidget);
      expect(find.byType(LiveStatusButton), findsOneWidget);
      expect(
        find.text('Are you sure you want to force restart the core?'),
        findsNothing,
      );
    });

    testWidgets('holds starting for the minimum after a fast restart', (
      tester,
    ) async {
      await pumpButton(tester, separateCore: true);
      final status = container.read(coreStatusProvider.notifier);
      const step = Duration(milliseconds: 400);
      final rest = HeldCoreStatus.minimumStart - step;

      status.value = CoreStatus.connecting;
      await tester.pump();
      await tester.pump(step);
      expect(badge('Connecting…'), findsOneWidget);

      status.value = CoreStatus.connected;
      await tester.pump();
      await tester.pump(rest - const Duration(milliseconds: 1));
      expect(badge('Connecting…'), findsOneWidget);

      await tester.pump(const Duration(milliseconds: 1));
      await tester.pump(step);
      expect(badge('Connecting…'), findsNothing);
      expect(find.byGlyph(AppGlyphs.check), findsOneWidget);
    });

    testWidgets('an open deck shows a fast restart for the minimum', (
      tester,
    ) async {
      final status = container.read(coreStatusProvider.notifier);
      await pumpButton(tester, separateCore: true);
      await open(tester);

      status.value = CoreStatus.connecting;
      await tester.pump();
      status.value = CoreStatus.connected;
      await tester.pump();
      await tester.pump(HeldCoreStatus.minimumStart ~/ 2);

      expect(find.text('Starting core'), findsOneWidget);

      await tester.pump(HeldCoreStatus.minimumStart);
      await settle(tester);

      expect(find.text('Starting core'), findsNothing);
      expect(front('Force restart'), findsOneWidget);
    });

    testWidgets('shows a failed start at once', (tester) async {
      await pumpButton(tester, separateCore: true);
      final status = container.read(coreStatusProvider.notifier);

      status.value = CoreStatus.connecting;
      await tester.pump();
      status.value = CoreStatus.disconnected;
      await tester.pump();

      expect(badge('Core stopped'), findsOneWidget);
    });

    testWidgets('the stopped card says why the core stopped', (tester) async {
      container.read(coreStatusProvider.notifier).value =
          CoreStatus.disconnected;
      container.read(coreStopReasonProvider.notifier).value =
          'The core could not be launched';
      await pumpButton(tester, separateCore: true);

      await open(tester);

      expect(front('The core could not be launched'), findsOneWidget);
      expect(
        find.text('The app lost its connection to the core'),
        findsNothing,
      );
    });
  });
}
