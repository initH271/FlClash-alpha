import 'dart:async';

import 'package:fl_clash/common/media_unlock_checker.dart';
import 'package:fl_clash/models/media_unlock.dart';
import 'package:fl_clash/providers/network_features.dart';
import 'package:fl_clash/providers/config.dart';
import 'package:fl_clash/providers/app.dart';
import 'package:fl_clash/providers/service_checks.dart';
import 'package:fl_clash/providers/state.dart';
import 'package:fl_clash/views/service_checks.dart';
import 'package:fl_clash/views/service_check_settings.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../helpers/test_app.dart';

class _Checker extends MediaUnlockChecker {
  int calls = 0;
  bool cancelled = false;
  List<MediaPlatform>? requestedPlatforms;
  Completer<Map<MediaPlatform, MediaUnlockResult>>? pending;

  @override
  Future<Map<MediaPlatform, MediaUnlockResult>> checkAll({
    List<MediaPlatform>? platforms,
    void Function(MediaUnlockResult result)? onProgress,
  }) async {
    calls++;
    requestedPlatforms = platforms == null ? null : List.of(platforms);
    const result = MediaUnlockResult(
      platform: MediaPlatform.netflix,
      status: MediaUnlockStatus.unlocked,
      region: 'US',
    );
    onProgress?.call(result);
    final pending = this.pending;
    if (pending != null) return pending.future;
    return {MediaPlatform.netflix: result};
  }

  @override
  void cancel() {
    cancelled = true;
    if (pending?.isCompleted == false) pending!.complete({});
    super.cancel();
  }
}

void main() {
  testWidgets('does not probe until requested and publishes results', (
    tester,
  ) async {
    final checker = _Checker();
    await tester.pumpWidget(
      TestApp(
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
    expect(checker.calls, 0);
    await tester.tap(find.byKey(const ValueKey('run-service-checks')));
    await tester.pumpAndSettle();
    final container = ProviderScope.containerOf(
      tester.element(find.byType(ServiceChecksView)),
    );
    expect(checker.calls, 1);
    expect(
      container
          .read(serviceCheckResultsProvider)[MediaPlatform.netflix]
          ?.region,
      'US',
    );
  });

  testWidgets('defaults include developer, trading and social services', (
    tester,
  ) async {
    final checker = _Checker();
    await tester.pumpWidget(
      TestApp(
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
    expect(checker.calls, 0);
    await tester.tap(find.byKey(const ValueKey('run-service-checks')));
    await tester.pumpAndSettle();
    expect(
      checker.requestedPlatforms,
      unorderedEquals([
        MediaPlatform.openai,
        MediaPlatform.claude,
        MediaPlatform.gemini,
        MediaPlatform.netflix,
        MediaPlatform.disney,
        MediaPlatform.youtube,
        MediaPlatform.spotify,
        MediaPlatform.github,
        MediaPlatform.gitlab,
        MediaPlatform.npm,
        MediaPlatform.cdnjs,
        MediaPlatform.unpkg,
        MediaPlatform.nodejs,
        MediaPlatform.wikipedia,
        MediaPlatform.apple,
        MediaPlatform.onetrust,
        MediaPlatform.coinbase,
        MediaPlatform.okx,
        MediaPlatform.kraken,
        MediaPlatform.cryptocom,
        MediaPlatform.phantom,
        MediaPlatform.paypal,
        MediaPlatform.reddit,
        MediaPlatform.x,
        MediaPlatform.discord,
        MediaPlatform.v2ex,
        MediaPlatform.medium,
        MediaPlatform.stackoverflow,
        MediaPlatform.quora,
        MediaPlatform.telegram,
      ]),
    );
  });

  testWidgets('a default developer service can be deselected before probing', (
    tester,
  ) async {
    final checker = _Checker();
    await tester.pumpWidget(
      TestApp(
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
    final tile = find.widgetWithText(CheckboxListTile, 'GitHub');
    await tester.scrollUntilVisible(tile, 150);
    expect(tester.widget<CheckboxListTile>(tile).value, isTrue);
    await tester.tap(tile);
    await tester.pump();
    expect(tester.widget<CheckboxListTile>(tile).value, isFalse);
    expect(checker.calls, 0);
    await tester.tap(find.byKey(const ValueKey('run-service-checks')));
    await tester.pumpAndSettle();
    expect(checker.requestedPlatforms, isNot(contains(MediaPlatform.github)));
    expect(checker.requestedPlatforms, contains(MediaPlatform.coinbase));
    expect(checker.requestedPlatforms, contains(MediaPlatform.telegram));
  });

  testWidgets('selected services are preserved when the panel is reopened', (
    tester,
  ) async {
    final checker = _Checker();
    final visible = ValueNotifier(true);
    addTearDown(visible.dispose);
    await tester.pumpWidget(
      TestApp(
        wrapInProviderScope: true,
        overrides: [
          selectedMapProvider.overrideWith((_) => const {}),
          serviceCheckClientProvider.overrideWithValue(checker),
        ],
        homeBuilder: (child) => Scaffold(body: child),
        child: ValueListenableBuilder<bool>(
          valueListenable: visible,
          builder: (_, show, _) =>
              show ? const ServiceChecksView() : const SizedBox(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    final github = find.widgetWithText(CheckboxListTile, 'GitHub');
    await tester.scrollUntilVisible(github, 150);
    await tester.tap(github);
    await tester.pump();
    final container = ProviderScope.containerOf(
      tester.element(find.byType(ServiceChecksView)),
    );
    expect(
      container.read(networkFeaturesProvider).serviceChecks.platforms,
      isNot(contains(MediaPlatform.github)),
    );
    visible.value = false;
    await tester.pumpAndSettle();
    visible.value = true;
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(github, 150);
    expect(tester.widget<CheckboxListTile>(github).value, isFalse);
    expect(checker.calls, 0);
  });

  testWidgets(
    'automatic settings expose independent switches and saved durations',
    (tester) async {
      final checker = _Checker();
      await tester.pumpWidget(
        TestApp(
          wrapInProviderScope: true,
          locale: const Locale('zh', 'CN'),
          overrides: [
            selectedMapProvider.overrideWith((_) => const {}),
            serviceCheckClientProvider.overrideWithValue(checker),
            viewSizeProvider.overrideWithValue(const Size(800, 600)),
          ],
          homeBuilder: (child) => Scaffold(body: child),
          child: const ServiceChecksView(),
        ),
      );
      await tester.pumpAndSettle();
      final container = ProviderScope.containerOf(
        tester.element(find.byType(ServiceChecksView)),
      );
      await tester.tap(find.byKey(const ValueKey('service-check-options')));
      await tester.pumpAndSettle();
      expect(find.byType(ServiceCheckSettingsView), findsOneWidget);
      final scrollable = find.descendant(
        of: find.byType(ServiceCheckSettingsView),
        matching: find.byType(Scrollable),
      );
      for (final key in [
        'service-check-on-connect',
        'service-check-on-route',
        'service-check-on-panel',
      ]) {
        final toggle = find.byKey(ValueKey(key));
        await tester.scrollUntilVisible(toggle, 150, scrollable: scrollable);
        expect(tester.widget<SwitchListTile>(toggle).value, isTrue);
        await tester.tap(toggle);
        await tester.pumpAndSettle();
      }
      final periodic = find.byKey(const ValueKey('service-check-periodic'));
      await tester.scrollUntilVisible(periodic, 150, scrollable: scrollable);
      expect(tester.widget<SwitchListTile>(periodic).value, isFalse);
      await tester.tap(periodic);
      await tester.pumpAndSettle();
      final interval = find
          .byKey(const ValueKey('service-check-interval'))
          .last;
      await tester.scrollUntilVisible(interval, 150, scrollable: scrollable);
      await tester.tap(interval);
      await tester.pumpAndSettle();
      await tester.tap(find.text('5 分钟').last);
      await tester.pumpAndSettle();
      final settings = container.read(networkFeaturesProvider).serviceChecks;
      expect(settings.onConnect, isFalse);
      expect(settings.onRouteChange, isFalse);
      expect(settings.onPanelOpen, isFalse);
      expect(settings.periodic, isTrue);
      expect(settings.intervalMinutes, 5);
      expect(checker.calls, 0);
    },
  );

  testWidgets('closing the view cancels pending checks', (tester) async {
    final checker = _Checker()..pending = Completer();
    await tester.pumpWidget(
      TestApp(
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
    await tester.tap(find.byKey(const ValueKey('run-service-checks')));
    await tester.pump();
    expect(checker.calls, 1);
    await tester.pumpWidget(const SizedBox());
    await tester.pump();
    expect(checker.cancelled, true);
    expect(tester.takeException(), isNull);
  });
}
