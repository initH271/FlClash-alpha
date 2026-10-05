import 'package:fl_clash/common/media_unlock_checker.dart';
import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/manager/service_check_manager.dart';
import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/views/service_checks.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_test/flutter_test.dart';

import '../helpers/test_app.dart';

class _Checker extends MediaUnlockChecker {
  int calls = 0;

  @override
  Future<Map<MediaPlatform, MediaUnlockResult>> checkAll({
    List<MediaPlatform>? platforms,
    void Function(MediaUnlockResult)? onProgress,
  }) async {
    calls++;
    final results = {
      for (final platform in platforms!)
        platform: MediaUnlockResult(
          platform: platform,
          status: MediaUnlockStatus.unlocked,
        ),
    };
    for (final result in results.values) {
      onProgress?.call(result);
    }
    return results;
  }
}

void main() {
  testWidgets(
    'application lifecycle pauses periodic work and resumes overdue checks',
    (tester) async {
      final checker = _Checker();
      try {
        await tester.pumpWidget(
          TestApp(
            wrapInProviderScope: true,
            overrides: [
              initProvider.overrideWithBuild((_, _) => true),
              coreStatusProvider.overrideWithValue(CoreStatus.connected),
              runTimeProvider.overrideWithBuild((_, _) => 0),
              selectedMapProvider.overrideWith((_) => const {}),
              serviceCheckClientProvider.overrideWithValue(checker),
              serviceCheckClockProvider.overrideWithValue(
                () => tester.binding.clock.now(),
              ),
              networkSettingProvider.overrideWithBuild(
                (_, _) => const NetworkProps(
                  networkFeatures: NetworkFeatureSettings(
                    serviceChecks: ServiceCheckSettings(
                      onConnect: false,
                      onRouteChange: false,
                      onPanelOpen: false,
                      periodic: true,
                      intervalMinutes: 1,
                    ),
                  ),
                ),
              ),
            ],
            child: const ServiceCheckManager(child: SizedBox()),
          ),
        );
        await tester.pump();
        tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
        await tester.pump(const Duration(minutes: 2));
        expect(checker.calls, 0);
        tester.binding.handleAppLifecycleStateChanged(
          AppLifecycleState.resumed,
        );
        await tester.pump(Duration.zero);
        await tester.pump();
        expect(checker.calls, 1);
        await tester.pumpWidget(const SizedBox());
        await tester.pump(const Duration(minutes: 5));
        expect(checker.calls, 1);
        expect(tester.takeException(), isNull);
      } finally {
        tester.binding.handleAppLifecycleStateChanged(
          AppLifecycleState.resumed,
        );
        await tester.pumpWidget(const SizedBox());
        await tester.pump();
      }
    },
  );

  testWidgets(
    'opening the real panel checks once and reuses fresh results on reopening',
    (tester) async {
      final checker = _Checker();
      final visible = ValueNotifier(true);
      addTearDown(visible.dispose);
      await tester.pumpWidget(
        TestApp(
          wrapInProviderScope: true,
          overrides: [
            initProvider.overrideWithBuild((_, _) => true),
            coreStatusProvider.overrideWithValue(CoreStatus.connected),
            runTimeProvider.overrideWithBuild((_, _) => 0),
            selectedMapProvider.overrideWith((_) => const {}),
            serviceCheckClientProvider.overrideWithValue(checker),
            serviceCheckClockProvider.overrideWithValue(
              () => tester.binding.clock.now(),
            ),
            networkSettingProvider.overrideWithBuild(
              (_, _) => const NetworkProps(
                networkFeatures: NetworkFeatureSettings(
                  serviceChecks: ServiceCheckSettings(
                    onConnect: false,
                    onRouteChange: false,
                  ),
                ),
              ),
            ),
          ],
          homeBuilder: (child) => Scaffold(body: child),
          child: ServiceCheckManager(
            child: ValueListenableBuilder<bool>(
              valueListenable: visible,
              builder: (_, show, _) =>
                  show ? const ServiceChecksView() : const SizedBox(),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(checker.calls, 1);
      visible.value = false;
      await tester.pumpAndSettle();
      visible.value = true;
      await tester.pumpAndSettle();
      expect(checker.calls, 1);
      visible.value = false;
      await tester.pumpAndSettle();
      await tester.pump(const Duration(minutes: 11));
      visible.value = true;
      await tester.pumpAndSettle();
      expect(checker.calls, 2);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      await tester.pump();
    },
  );
}
