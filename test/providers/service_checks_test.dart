import 'dart:async';

import 'package:fl_clash/common/media_unlock_checker.dart';
import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

class _Status extends Notifier<CoreStatus> {
  @override
  CoreStatus build() => CoreStatus.disconnected;
  void set(CoreStatus value) => state = value;
}

class _Selection extends Notifier<Map<String, String>> {
  @override
  Map<String, String> build() => const {};
  void set(String value) => state = {'group': value};
}

class _Suspend extends Notifier<bool> {
  @override
  bool build() => false;
  void set(bool value) => state = value;
}

final _suspend = NotifierProvider<_Suspend, bool>(_Suspend.new);

final _status = NotifierProvider<_Status, CoreStatus>(_Status.new);
final _selection = NotifierProvider<_Selection, Map<String, String>>(
  _Selection.new,
);

class _Call {
  _Call(this.platforms, this.progress);
  final List<MediaPlatform> platforms;
  final void Function(MediaUnlockResult)? progress;
  final completion = Completer<Map<MediaPlatform, MediaUnlockResult>>();

  void finish() {
    if (completion.isCompleted) return;
    final results = {
      for (final platform in platforms)
        platform: MediaUnlockResult(
          platform: platform,
          status: MediaUnlockStatus.unlocked,
          region: 'US',
        ),
    };
    for (final result in results.values) {
      progress?.call(result);
    }
    completion.complete(results);
  }
}

class _Checker extends MediaUnlockChecker {
  final calls = <_Call>[];
  bool completeOnCancel = true;
  int active = 0;
  int maxActive = 0;

  @override
  Future<Map<MediaPlatform, MediaUnlockResult>> checkAll({
    List<MediaPlatform>? platforms,
    void Function(MediaUnlockResult)? onProgress,
  }) async {
    final call = _Call(List.of(platforms!), onProgress);
    calls.add(call);
    active++;
    if (active > maxActive) maxActive = active;
    try {
      return await call.completion.future;
    } finally {
      active--;
    }
  }

  @override
  void cancel() {
    if (completeOnCancel) {
      for (final call in calls) {
        if (!call.completion.isCompleted) call.completion.complete({});
      }
    }
    super.cancel();
  }
}

const _manual = ServiceCheckSettings(
  onConnect: false,
  onRouteChange: false,
  onPanelOpen: false,
);

final _cleanups = <void Function()>[];

void serviceTestWidgets(String name, Future<void> Function(WidgetTester) body) {
  testWidgets(name, (tester) async {
    try {
      await body(tester);
    } finally {
      for (final cleanup in _cleanups) {
        cleanup();
      }
      _cleanups.clear();
      await tester.pump();
    }
  });
}

ProviderContainer _container(
  WidgetTester tester,
  _Checker checker,
  ServiceCheckSettings settings, {
  bool initialized = true,
}) {
  final container = ProviderContainer(
    overrides: [
      initProvider.overrideWithBuild((_, _) => initialized),
      serviceCheckClientProvider.overrideWithValue(checker),
      serviceCheckClockProvider.overrideWithValue(
        () => tester.binding.clock.now(),
      ),
      coreStatusProvider.overrideWithBuild((ref, _) => ref.watch(_status)),
      selectedMapProvider.overrideWith((ref) => ref.watch(_selection)),
      suspendProvider.overrideWith((ref) => ref.watch(_suspend)),
      currentProfileIdProvider.overrideWithBuild((_, _) => 1),
      networkSettingProvider.overrideWithBuild(
        (_, _) => NetworkProps(
          networkFeatures: NetworkFeatureSettings(serviceChecks: settings),
        ),
      ),
    ],
  );
  _cleanups.add(() {
    container.dispose();
    for (final call in checker.calls) {
      if (!call.completion.isCompleted) call.completion.complete({});
    }
  });
  container.listen(serviceCheckControllerProvider, (_, _) {});
  container.read(serviceCheckControllerProvider.notifier).setForeground(true);
  return container;
}

void _connect(ProviderContainer container) {
  container.read(_status.notifier).set(CoreStatus.connected);
  container.read(coreStatusProvider);
  container.read(runTimeProvider.notifier).value = 0;
}

void _settings(ProviderContainer container, ServiceCheckSettings settings) {
  container
      .read(networkFeaturesProvider.notifier)
      .update((value) => value.copyWith(serviceChecks: settings));
  container.read(networkFeaturesProvider);
}

void main() {
  serviceTestWidgets('connect waits for routing to settle and debounces once', (
    tester,
  ) async {
    final checker = _Checker();
    final container = _container(tester, checker, const ServiceCheckSettings());
    final routing = container.read(serviceCheckRoutingProvider.notifier);
    final token = routing.begin();
    _connect(container);
    await tester.pump(const Duration(seconds: 10));
    expect(checker.calls, isEmpty);
    routing.end(token, applied: true);
    await tester.pump(const Duration(seconds: 2));
    expect(checker.calls, isEmpty);
    await tester.pump(const Duration(seconds: 1));
    expect(checker.calls, hasLength(1));
    expect(checker.calls.single.platforms, hasLength(30));
    checker.calls.single.finish();
    await tester.pump();
    expect(container.read(serviceCheckControllerProvider).running, isFalse);
  });

  serviceTestWidgets(
    'automatic checks wait until application initialization completes',
    (tester) async {
      final checker = _Checker();
      final container = _container(
        tester,
        checker,
        const ServiceCheckSettings(),
        initialized: false,
      );
      _connect(container);
      await tester.pump(const Duration(seconds: 10));
      expect(checker.calls, isEmpty);
      container.read(initProvider.notifier).value = true;
      await tester.pump(const Duration(seconds: 3));
      expect(checker.calls, hasLength(1));
    },
  );

  serviceTestWidgets('rapid route changes check only the final settled route', (
    tester,
  ) async {
    final checker = _Checker();
    final container = _container(
      tester,
      checker,
      _manual.copyWith(onRouteChange: true),
    );
    _connect(container);
    container.read(_selection.notifier).set('A');
    container.read(selectedMapProvider);
    await tester.pump(Duration.zero);
    await tester.pump(const Duration(seconds: 2));
    container.read(_selection.notifier).set('B');
    container.read(selectedMapProvider);
    await tester.pump(Duration.zero);
    await tester.pump(const Duration(seconds: 2));
    container.read(_selection.notifier).set('C');
    container.read(selectedMapProvider);
    await tester.pump(Duration.zero);
    await tester.pump(const Duration(seconds: 2));
    expect(checker.calls, isEmpty);
    await tester.pump(const Duration(seconds: 1));
    expect(checker.calls, hasLength(1));
    expect(container.read(selectedMapProvider)['group'], 'C');
  });

  serviceTestWidgets(
    'effective automatic group changes refresh but group-list updates do not',
    (tester) async {
      final checker = _Checker();
      final container = _container(
        tester,
        checker,
        _manual.copyWith(onRouteChange: true),
      );
      _connect(container);
      const first = Group(name: 'auto', type: GroupType.URLTest, now: 'A');
      container.read(groupsProvider.notifier).value = [first];
      await tester.pump(const Duration(seconds: 4));
      expect(checker.calls, isEmpty);
      container.read(groupsProvider.notifier).value = [
        first.copyWith(now: 'B'),
      ];
      await tester.pump(const Duration(seconds: 3));
      expect(checker.calls, hasLength(1));
      checker.calls.single.finish();
      await tester.pump();
      container.read(groupsProvider.notifier).value = [
        first.copyWith(
          now: 'B',
          all: const [Proxy(name: 'B', type: 'VLESS')],
        ),
      ];
      await tester.pump(const Duration(seconds: 4));
      expect(checker.calls, hasLength(1));
    },
  );

  serviceTestWidgets(
    'route refresh survives a temporarily empty group list during application',
    (tester) async {
      final checker = _Checker();
      final container = _container(
        tester,
        checker,
        _manual.copyWith(onRouteChange: true),
      );
      _connect(container);
      const group = Group(name: 'auto', type: GroupType.URLTest, now: 'A');
      container.read(groupsProvider.notifier).value = [group];
      await tester.pump();
      container.read(_selection.notifier).set('new');
      container.read(selectedMapProvider);
      final routing = container.read(serviceCheckRoutingProvider.notifier);
      final token = routing.begin();
      container.read(groupsProvider.notifier).value = [];
      await tester.pump(const Duration(seconds: 5));
      expect(checker.calls, isEmpty);
      container.read(groupsProvider.notifier).value = [
        group.copyWith(now: 'B'),
      ];
      routing.end(token, applied: true);
      await tester.pump(const Duration(seconds: 3));
      expect(checker.calls, hasLength(1));
    },
  );

  serviceTestWidgets(
    'callbacks from a completed batch cannot overwrite a manual refresh',
    (tester) async {
      final checker = _Checker();
      final container = _container(tester, checker, _manual);
      final controller = container.read(
        serviceCheckControllerProvider.notifier,
      );
      controller.toggleManual();
      final old = checker.calls.single;
      old.finish();
      await tester.pump();
      controller.toggleManual();
      old.progress?.call(
        const MediaUnlockResult(
          platform: MediaPlatform.openai,
          status: MediaUnlockStatus.unlocked,
          region: 'OLD',
        ),
      );
      expect(container.read(serviceCheckResultsProvider), isEmpty);
      checker.calls.last.finish();
      await tester.pump();
      expect(
        container
            .read(serviceCheckResultsProvider)[MediaPlatform.openai]
            ?.region,
        'US',
      );
    },
  );

  serviceTestWidgets(
    'connection and route switches are independently enabled',
    (tester) async {
      final checker = _Checker();
      final container = _container(
        tester,
        checker,
        _manual.copyWith(onRouteChange: true),
      );
      final routing = container.read(serviceCheckRoutingProvider.notifier);
      final token = routing.begin();
      _connect(container);
      routing.end(token, applied: true);
      await tester.pump(const Duration(seconds: 5));
      expect(checker.calls, isEmpty);
      container.read(_selection.notifier).set('new');
      container.read(selectedMapProvider);
      await tester.pump(const Duration(seconds: 3));
      expect(checker.calls, hasLength(1));
    },
  );

  serviceTestWidgets(
    'profile changes invalidate results and trigger fresh checks',
    (tester) async {
      final checker = _Checker();
      final container = _container(
        tester,
        checker,
        _manual.copyWith(onRouteChange: true),
      );
      _connect(container);
      final controller = container.read(
        serviceCheckControllerProvider.notifier,
      );
      controller.toggleManual();
      checker.calls.single.finish();
      await tester.pump();
      expect(container.read(serviceCheckResultsProvider), isNotEmpty);
      container.read(currentProfileIdProvider.notifier).value = 2;
      expect(container.read(serviceCheckResultsProvider), isEmpty);
      await tester.pump(const Duration(seconds: 3));
      expect(checker.calls, hasLength(2));
    },
  );

  serviceTestWidgets(
    'manual and panel triggers do not duplicate an active batch',
    (tester) async {
      final checker = _Checker();
      final container = _container(
        tester,
        checker,
        const ServiceCheckSettings(),
      );
      _connect(container);
      final controller = container.read(
        serviceCheckControllerProvider.notifier,
      );
      controller.toggleManual();
      controller.panelOpened();
      await tester.pump(const Duration(seconds: 4));
      expect(checker.calls, hasLength(1));
      expect(checker.maxActive, 1);
    },
  );

  serviceTestWidgets(
    'cancelled route batch drains before the next batch and ignores late data',
    (tester) async {
      final checker = _Checker()..completeOnCancel = false;
      final container = _container(
        tester,
        checker,
        _manual.copyWith(onRouteChange: true),
      );
      _connect(container);
      container.read(serviceCheckControllerProvider.notifier).toggleManual();
      final old = checker.calls.single;
      container.read(_selection.notifier).set('new');
      container.read(selectedMapProvider);
      await tester.pump(const Duration(seconds: 3));
      expect(checker.calls, hasLength(1));
      old.progress?.call(
        const MediaUnlockResult(
          platform: MediaPlatform.openai,
          status: MediaUnlockStatus.unlocked,
          region: 'OLD',
        ),
      );
      expect(container.read(serviceCheckResultsProvider), isEmpty);
      old.completion.completeError(StateError('obsolete'));
      await tester.pump();
      expect(checker.calls, hasLength(2));
      expect(checker.maxActive, 1);
      expect(container.read(serviceCheckControllerProvider).failed, isFalse);
      checker.calls.last.finish();
      await tester.pump();
      expect(
        container
            .read(serviceCheckResultsProvider)[MediaPlatform.openai]
            ?.region,
        'US',
      );
    },
  );

  serviceTestWidgets(
    'opening the panel reuses fresh results and refreshes expired ones',
    (tester) async {
      final checker = _Checker();
      final container = _container(
        tester,
        checker,
        _manual.copyWith(onPanelOpen: true),
      );
      _connect(container);
      final controller = container.read(
        serviceCheckControllerProvider.notifier,
      );
      controller.panelOpened();
      checker.calls.single.finish();
      await tester.pump();
      controller.panelClosed();
      await tester.pump(const Duration(minutes: 9));
      controller.panelOpened();
      expect(checker.calls, hasLength(1));
      controller.panelClosed();
      await tester.pump(const Duration(minutes: 1));
      controller.panelOpened();
      expect(checker.calls, hasLength(2));
    },
  );

  serviceTestWidgets('cache validity accounts for changed service selections', (
    tester,
  ) async {
    final checker = _Checker();
    final original = _manual.copyWith(
      onPanelOpen: true,
      platforms: [MediaPlatform.github],
    );
    final container = _container(tester, checker, original);
    _connect(container);
    final controller = container.read(serviceCheckControllerProvider.notifier);
    controller.panelOpened();
    checker.calls.single.finish();
    await tester.pump();
    _settings(
      container,
      original.copyWith(
        platforms: [MediaPlatform.github, MediaPlatform.coinbase],
      ),
    );
    expect(controller.hasFreshResults, isFalse);
    controller.panelOpened();
    expect(checker.calls, hasLength(2));
    checker.calls.last.finish();
    await tester.pump();
    _settings(container, original);
    expect(controller.hasFreshResults, isTrue);
  });

  serviceTestWidgets(
    'periodic checks are opt-in, pause in background and catch up on resume',
    (tester) async {
      final checker = _Checker();
      final container = _container(tester, checker, _manual);
      _connect(container);
      final controller = container.read(
        serviceCheckControllerProvider.notifier,
      );
      await tester.pump(const Duration(minutes: 20));
      expect(checker.calls, isEmpty);
      _settings(
        container,
        _manual.copyWith(periodic: true, intervalMinutes: 5),
      );
      await tester.pump(const Duration(minutes: 4, seconds: 59));
      expect(checker.calls, isEmpty);
      await tester.pump(const Duration(seconds: 1));
      expect(checker.calls, hasLength(1));
      checker.calls.single.finish();
      await tester.pump();
      controller.setForeground(false);
      await tester.pump(const Duration(minutes: 30));
      expect(checker.calls, hasLength(1));
      controller.setForeground(true);
      await tester.pump(Duration.zero);
      expect(checker.calls, hasLength(2));
      _settings(container, _manual);
      await tester.pump(const Duration(minutes: 30));
      expect(checker.calls, hasLength(2));
    },
  );

  serviceTestWidgets('disconnect clears results and stops automatic work', (
    tester,
  ) async {
    final checker = _Checker();
    final container = _container(
      tester,
      checker,
      const ServiceCheckSettings(periodic: true),
    );
    _connect(container);
    await tester.pump(const Duration(seconds: 3));
    checker.calls.single.finish();
    await tester.pump();
    container.read(runTimeProvider.notifier).value = null;
    container.read(_status.notifier).set(CoreStatus.disconnected);
    expect(container.read(serviceCheckResultsProvider), isEmpty);
    await tester.pump(const Duration(hours: 1));
    expect(checker.calls, hasLength(1));
  });

  serviceTestWidgets(
    'excluded-network suspension prevents probes until the proxy can resume',
    (tester) async {
      final checker = _Checker();
      final container = _container(
        tester,
        checker,
        const ServiceCheckSettings(),
      );
      container.read(_suspend.notifier).set(true);
      container.read(suspendProvider);
      _connect(container);
      await tester.pump(const Duration(seconds: 10));
      expect(checker.calls, isEmpty);
      container.read(_suspend.notifier).set(false);
      container.read(suspendProvider);
      await tester.pump(const Duration(seconds: 3));
      expect(checker.calls, hasLength(1));
    },
  );

  serviceTestWidgets(
    'turning off a pending automatic trigger prevents it from firing',
    (tester) async {
      final checker = _Checker();
      final container = _container(
        tester,
        checker,
        const ServiceCheckSettings(),
      );
      _connect(container);
      await tester.pump(const Duration(seconds: 2));
      _settings(container, _manual);
      await tester.pump(const Duration(seconds: 10));
      expect(checker.calls, isEmpty);
    },
  );

  serviceTestWidgets(
    'failed routing blocks automatic checks without overriding manual intent',
    (tester) async {
      final checker = _Checker();
      final container = _container(
        tester,
        checker,
        const ServiceCheckSettings(),
      );
      final routing = container.read(serviceCheckRoutingProvider.notifier);
      final profile = routing.begin();
      _connect(container);
      final listener = routing.begin(primary: false);
      routing.end(listener, applied: true);
      routing.end(profile, applied: false);
      await tester.pump(const Duration(seconds: 10));
      expect(checker.calls, isEmpty);
      container.read(serviceCheckControllerProvider.notifier).toggleManual();
      expect(checker.calls, hasLength(1));
    },
  );

  serviceTestWidgets(
    'an older route completion cannot override the latest route outcome',
    (tester) async {
      final checker = _Checker();
      final container = _container(tester, checker, _manual);
      final routing = container.read(serviceCheckRoutingProvider.notifier);
      final old = routing.begin();
      final latest = routing.begin();
      routing.end(latest, applied: true);
      routing.end(old, applied: false);
      expect(container.read(serviceCheckRoutingProvider).failed, isFalse);
      expect(container.read(serviceCheckRoutingProvider).pending, 0);
    },
  );

  serviceTestWidgets(
    'disposal cancels timers and rejects late errors without touching disposed state',
    (tester) async {
      final checker = _Checker()..completeOnCancel = false;
      final container = _container(
        tester,
        checker,
        const ServiceCheckSettings(periodic: true),
      );
      _connect(container);
      await tester.pump(const Duration(seconds: 3));
      final old = checker.calls.single;
      _cleanups.removeAt(0);
      container.dispose();
      old.progress?.call(
        const MediaUnlockResult(
          platform: MediaPlatform.openai,
          status: MediaUnlockStatus.unlocked,
        ),
      );
      old.completion.completeError(StateError('late after dispose'));
      await tester.pump(const Duration(hours: 1));
      expect(checker.calls, hasLength(1));
      expect(tester.takeException(), isNull);
    },
  );

  serviceTestWidgets('empty selection never probes automatically', (
    tester,
  ) async {
    final checker = _Checker();
    final container = _container(
      tester,
      checker,
      const ServiceCheckSettings(periodic: true, platforms: []),
    );
    _connect(container);
    container.read(serviceCheckControllerProvider.notifier).panelOpened();
    await tester.pump(const Duration(hours: 1));
    expect(checker.calls, isEmpty);
  });
}
