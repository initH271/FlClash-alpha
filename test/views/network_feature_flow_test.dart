import 'dart:async';

import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/common/media_unlock_checker.dart';
import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/views/dashboard/widgets/extended_widgets.dart';
import 'package:fl_clash/views/network_features.dart';
import 'package:fl_clash/views/service_checks.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';
import 'package:url_launcher_platform_interface/link.dart';
import 'package:url_launcher_platform_interface/url_launcher_platform_interface.dart';

import '../helpers/test_app.dart';

class _Checker extends MediaUnlockChecker {
  int calls = 0;
  bool cancelled = false;
  bool completeOnCancel = true;
  Completer<Map<MediaPlatform, MediaUnlockResult>>? pending;
  void Function(MediaUnlockResult)? progress;

  @override
  Future<Map<MediaPlatform, MediaUnlockResult>> checkAll({
    List<MediaPlatform>? platforms,
    void Function(MediaUnlockResult result)? onProgress,
  }) {
    calls++;
    progress = onProgress;
    pending = Completer();
    return pending!.future;
  }

  @override
  void cancel() {
    cancelled = true;
    if (completeOnCancel && pending?.isCompleted == false) {
      pending!.complete({});
    }
    super.cancel();
  }
}

class _Setup extends SetupAction {
  int calls = 0;
  Completer<bool>? pending;

  @override
  void build() {}

  @override
  Future<bool> fullSetup() {
    calls++;
    pending = Completer();
    return pending!.future;
  }
}

class _Launcher extends UrlLauncherPlatform {
  final urls = <String>[];
  bool success = true;

  @override
  LinkDelegate? get linkDelegate => null;

  @override
  Future<bool> launchUrl(String url, LaunchOptions options) async {
    urls.add(url);
    return success;
  }
}

Future<ProviderContainer> _service(
  WidgetTester tester,
  _Checker checker,
) async {
  await tester.pumpWidget(
    TestApp(
      locale: const Locale('zh', 'CN'),
      wrapInProviderScope: true,
      overrides: [
        selectedMapProvider.overrideWith((_) => const {}),
        serviceCheckClientProvider.overrideWithValue(checker),
      ],
      homeBuilder: (child) => Scaffold(body: child),
      child: const ServiceChecksView(),
    ),
  );
  await tester.pumpAndSettle();
  return ProviderScope.containerOf(
    tester.element(find.byType(ServiceChecksView)),
  );
}

Future<void> _run(WidgetTester tester) async {
  await tester.tap(find.byKey(const ValueKey('run-service-checks')));
  await tester.pump();
}

Future<void> _panel(WidgetTester tester, _Setup setup) async {
  await tester.pumpWidget(
    TestApp(
      locale: const Locale('zh', 'CN'),
      wrapInProviderScope: true,
      overrides: [
        viewSizeProvider.overrideWithValue(const Size(390, 844)),
        setupActionProvider.overrideWith(() => setup),
      ],
      homeBuilder: (child) => Scaffold(body: child),
      child: const Center(child: SizedBox(width: 220, child: OnlinePanel())),
    ),
  );
  await tester.pumpAndSettle();
}

Future<void> _confirmPanel(WidgetTester tester) async {
  await tester.tap(find.byType(OnlinePanel));
  await tester.pumpAndSettle();
  expect(find.textContaining('127.0.0.1'), findsOneWidget);
  await tester.tap(find.text('确定'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('batch error is visible and a retry clears it', (tester) async {
    final checker = _Checker();
    await _service(tester, checker);
    expect(checker.calls, 0);
    await _run(tester);
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
    expect(
      tester
          .widgetList<CheckboxListTile>(find.byType(CheckboxListTile))
          .every((tile) => tile.onChanged == null),
      isTrue,
    );
    checker.pending!.completeError(StateError('transport failed'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.byKey(const ValueKey('service-check-error')), findsOneWidget);
    expect(find.byType(LinearProgressIndicator), findsNothing);
    await _run(tester);
    expect(checker.calls, 2);
    expect(find.byKey(const ValueKey('service-check-error')), findsNothing);
    await _run(tester);
    await tester.pumpAndSettle();
    expect(checker.cancelled, isTrue);
  });

  testWidgets(
    'route changes clear results and ignore late callbacks and errors',
    (tester) async {
      final checker = _Checker()..completeOnCancel = false;
      final container = await _service(tester, checker);
      await _run(tester);
      const result = MediaUnlockResult(
        platform: MediaPlatform.openai,
        status: MediaUnlockStatus.unlocked,
        region: 'US',
      );
      checker.progress!(result);
      await tester.pump();
      expect(container.read(serviceCheckResultsProvider), isNotEmpty);
      container.read(currentProfileIdProvider.notifier).value = 2;
      await tester.pump();
      expect(checker.cancelled, isTrue);
      expect(container.read(serviceCheckResultsProvider), isEmpty);
      checker.progress!(result);
      checker.pending!.completeError(StateError('late failure'));
      await tester.pumpAndSettle();
      expect(container.read(serviceCheckResultsProvider), isEmpty);
      expect(find.byKey(const ValueKey('service-check-error')), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('no selected services disables the start button', (tester) async {
    final checker = _Checker();
    final container = await _service(tester, checker);
    final selected = container
        .read(networkFeaturesProvider)
        .serviceChecks
        .platforms;
    for (final platform in MediaPlatform.values.where(selected.contains)) {
      final finder = find.widgetWithText(
        CheckboxListTile,
        platform.defaultName,
      );
      await tester.scrollUntilVisible(finder, 150);
      await Scrollable.ensureVisible(tester.element(finder), alignment: 0.5);
      await tester.pumpAndSettle();
      if (tester.widget<CheckboxListTile>(finder).value == true) {
        await tester.tap(finder);
        await tester.pump();
      }
    }
    expect(
      container.read(networkFeaturesProvider).serviceChecks.platforms,
      isEmpty,
    );
    expect(
      tester
          .widget<FilledButton>(
            find.byKey(const ValueKey('run-service-checks')),
          )
          .onPressed,
      isNull,
    );
    expect(checker.calls, 0);
  });

  testWidgets(
    'network settings validate and save their input and dependent toggles',
    (tester) async {
      await tester.pumpWidget(
        TestApp(
          locale: const Locale('zh', 'CN'),
          wrapInProviderScope: true,
          homeBuilder: (child) => Scaffold(body: child),
          child: const NetworkFeaturesView(),
        ),
      );
      await tester.pumpAndSettle();
      final container = ProviderScope.containerOf(
        tester.element(find.byType(NetworkFeaturesView)),
      );
      final l = tester
          .element(find.byType(NetworkFeaturesView))
          .appLocalizations;
      await tester.enterText(find.byType(TextFormField).first, 'invalid');
      await tester.testTextInput.receiveAction(TextInputAction.done);
      await tester.pump();
      expect(
        container.read(networkFeaturesProvider).smartAutoStopNetworks,
        isEmpty,
      );
      expect(find.textContaining('请输入有效'), findsOneWidget);
      const rules = '192.168.1.0/24,\ngateway:192.168.1.1';
      await tester.enterText(find.byType(TextFormField).first, rules);
      await tester.testTextInput.receiveAction(TextInputAction.done);
      await tester.pump();
      expect(
        container.read(networkFeaturesProvider).smartAutoStopNetworks,
        rules,
      );
      Future<void> toggle(String label) async {
        final tile = find.widgetWithText(SwitchListTile, label);
        await tester.ensureVisible(tile);
        await tester.pumpAndSettle();
        await tester.tap(tile);
        await tester.pumpAndSettle();
      }

      expect(
        tester
            .widget<SwitchListTile>(
              find.widgetWithText(SwitchListTile, l.sniffer),
            )
            .onChanged,
        isNull,
      );
      await toggle(l.smartAutoStop);
      await toggle(l.disableQuic);
      await toggle(l.snifferOverride);
      await toggle(l.sniffer);
      await toggle(l.ntpOverride);
      await toggle('NTP');
      final ntp = find.byType(TextFormField).last;
      await tester.ensureVisible(ntp);
      await tester.enterText(ntp, 'pool.ntp.org');
      await tester.testTextInput.receiveAction(TextInputAction.done);
      await tester.pump();
      final settings = container.read(networkFeaturesProvider);
      expect(settings.smartAutoStop, isTrue);
      expect(settings.disableQuic, isTrue);
      expect(settings.overrideSniffer, isTrue);
      expect(settings.snifferEnabled, isFalse);
      expect(settings.overrideNtp, isTrue);
      expect(settings.ntpEnabled, isFalse);
      expect(settings.ntpServer, 'pool.ntp.org');
      if (system.isDesktop) {
        await toggle(l.keepAwake);
        expect(container.read(networkFeaturesProvider).keepAwake, isTrue);
      }
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('multiline rules require an explicit save after physical Enter', (
    tester,
  ) async {
    await tester.pumpWidget(
      TestApp(
        locale: const Locale('zh', 'CN'),
        wrapInProviderScope: true,
        homeBuilder: (child) => Scaffold(body: child),
        child: const NetworkFeaturesView(),
      ),
    );
    await tester.pumpAndSettle();
    final container = ProviderScope.containerOf(
      tester.element(find.byType(NetworkFeaturesView)),
    );
    await tester.enterText(find.byType(TextFormField).first, '10.20.0.0/16');
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pump();
    expect(
      container.read(networkFeaturesProvider).smartAutoStopNetworks,
      isEmpty,
    );
    await tester.ensureVisible(
      find.byKey(const ValueKey('save-network-rules')),
    );
    await tester.tap(find.byKey(const ValueKey('save-network-rules')));
    await tester.pumpAndSettle();
    expect(
      container.read(networkFeaturesProvider).smartAutoStopNetworks,
      '10.20.0.0/16',
    );
    await tester.enterText(find.byType(TextFormField).first, 'invalid');
    await tester.tap(find.byKey(const ValueKey('save-network-rules')));
    await tester.pumpAndSettle();
    expect(
      container.read(networkFeaturesProvider).smartAutoStopNetworks,
      '10.20.0.0/16',
    );
    expect(find.textContaining('请输入有效'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  group('online panel', () {
    late _Launcher launcher;
    late UrlLauncherPlatform previous;
    setUp(() {
      previous = UrlLauncherPlatform.instance;
      launcher = _Launcher();
      UrlLauncherPlatform.instance = launcher;
    });
    tearDown(() {
      UrlLauncherPlatform.instance = previous;
    });

    testWidgets('cancel leaves the controller closed and does not launch', (
      tester,
    ) async {
      final setup = _Setup();
      await _panel(tester, setup);
      await tester.tap(find.byType(OnlinePanel));
      await tester.pumpAndSettle();
      await tester.tap(find.text('取消'));
      await tester.pumpAndSettle();
      final container = ProviderScope.containerOf(
        tester.element(find.byType(OnlinePanel)),
      );
      expect(
        container.read(patchClashConfigProvider).externalController,
        ExternalControllerStatus.close,
      );
      expect(setup.calls, 0);
      expect(launcher.urls, isEmpty);
    });
    testWidgets(
      'awaits setup, ignores repeated taps, and retries a setup failure',
      (tester) async {
        final setup = _Setup();
        await _panel(tester, setup);
        await _confirmPanel(tester);
        expect(setup.calls, 1);
        expect(launcher.urls, isEmpty);
        await tester.tap(find.byType(OnlinePanel));
        await tester.pump();
        expect(setup.calls, 1);
        expect(launcher.urls, isEmpty);
        setup.pending!.complete(false);
        await tester.pumpAndSettle();
        expect(find.text('面板打开失败，请重试。'), findsOneWidget);
        await tester.tap(find.byType(OnlinePanel));
        await tester.pump();
        expect(setup.calls, 2);
        setup.pending!.complete(true);
        await tester.pumpAndSettle();
        expect(launcher.urls, ['http://127.0.0.1:9090/ui/']);
        expect(tester.takeException(), isNull);
      },
    );
    testWidgets('launcher failure is visible and permits retry', (
      tester,
    ) async {
      final setup = _Setup();
      launcher.success = false;
      await _panel(tester, setup);
      await _confirmPanel(tester);
      setup.pending!.complete(true);
      await tester.pumpAndSettle();
      expect(find.text('面板打开失败，请重试。'), findsOneWidget);
      launcher.success = true;
      await tester.tap(find.byType(OnlinePanel));
      await tester.pumpAndSettle();
      expect(launcher.urls, hasLength(2));
      expect(setup.calls, 1);
      expect(tester.takeException(), isNull);
    });
    testWidgets('closing a pending panel does not launch afterward', (
      tester,
    ) async {
      final setup = _Setup();
      await _panel(tester, setup);
      await _confirmPanel(tester);
      await tester.pumpWidget(const SizedBox());
      await tester.pump();
      setup.pending!.complete(true);
      await tester.pumpAndSettle();
      expect(launcher.urls, isEmpty);
      expect(tester.takeException(), isNull);
    });
    testWidgets('a later controller close wins over a pending open', (
      tester,
    ) async {
      final setup = _Setup();
      await _panel(tester, setup);
      await _confirmPanel(tester);
      final container = ProviderScope.containerOf(
        tester.element(find.byType(OnlinePanel)),
      );
      container
          .read(patchClashConfigProvider.notifier)
          .update(
            (state) => state.copyWith(
              externalController: ExternalControllerStatus.close,
            ),
          );
      setup.pending!.complete(true);
      await tester.pumpAndSettle();
      expect(launcher.urls, isEmpty);
      expect(tester.takeException(), isNull);
    });
  });
}
