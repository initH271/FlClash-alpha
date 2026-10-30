import 'dart:async';

import 'package:fl_clash/core/controller.dart';
import 'package:fl_clash/core/interface.dart';
import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/providers/fork/route_check.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/providers/routed_probe.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

class _MockCore extends Mock implements CoreHandlerInterface {}

const _ok = ProbeResult(statusCode: 204, delay: 85, chains: ['HK 01', 'Proxy']);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUpAll(() => registerFallbackValue(const ProbeParams(url: '', timeout: 0)));

  late _MockCore core;
  late Map<String, Completer<ProbeResult?>> pending;
  late List<ProbeParams> asked;

  setUp(() {
    core = _MockCore();
    pending = {};
    asked = [];
    when(() => core.probe(any())).thenAnswer((invocation) {
      final params = invocation.positionalArguments.single as ProbeParams;
      asked.add(params);
      return (pending[params.url] = Completer<ProbeResult?>()).future;
    });
  });

  ProviderContainer containerOf({bool proxied = true}) {
    final container = ProviderContainer(
      overrides: [
        routeTrackerProvider.overrideWithBuild(
          (_, _) => RouteState(
            coreEpoch: 1,
            routeVersion: 1,
            hostEpoch: 1,
            proxied: proxied,
            synced: true,
            live: true,
          ),
        ),
        coreHandlerProvider.overrideWithValue(CoreController.scoped(core)),
      ],
    );
    addTearDown(container.dispose);
    container.listen(routeCheckProvider, (_, _) {});
    return container;
  }

  Future<void> settle() => Future<void>.delayed(Duration.zero);

  ProbeEntry<ProbeResult> entryOf(ProviderContainer container, String label) =>
      container
          .read(routeCheckProvider)
          .entryOf(routeCheckTargets.firstWhere((t) => t.label == label));

  Future<ProviderContainer> ask(ProviderContainer container) async {
    container.read(routeCheckProvider.notifier).refresh(routeCheckTargets);
    await settle();
    return container;
  }

  test('reads each outcome off the probe result', () {
    expect(routeCheckOutcomeOf(_ok), RouteCheckOutcome.ok);
    expect(
      routeCheckOutcomeOf(const ProbeResult(error: 'timeout')),
      RouteCheckOutcome.timeout,
    );
    expect(
      routeCheckOutcomeOf(const ProbeResult(error: 'failed')),
      RouteCheckOutcome.failed,
    );
    expect(routeCheckOutcomeOf(const ProbeResult()), RouteCheckOutcome.failed);
  });

  test('every target is an http(s) url with its own label', () {
    expect(routeCheckTargets.map((t) => t.label).toSet(), hasLength(5));
    for (final target in routeCheckTargets) {
      expect(Uri.parse(target.url).scheme, 'https', reason: target.label);
    }
  });

  test(
    'probes nothing until asked, then routes every target by rule',
    () async {
      final container = containerOf();
      await settle();
      expect(asked, isEmpty);
      expect(entryOf(container, 'Google').phase, ProbePhase.empty);

      await ask(container);
      expect(asked.map((p) => p.url), routeCheckTargets.map((t) => t.url));
      expect(asked.map((p) => p.proxyName).toSet(), {''});
      expect(entryOf(container, 'Google').phase, ProbePhase.probing);
    },
  );

  test('stopped, every target goes out direct', () async {
    await ask(containerOf(proxied: false));
    expect(asked.map((p) => p.proxyName).toSet(), {'DIRECT'});
  });

  test('an answer settles fresh or failed and keeps the outcome', () async {
    final container = await ask(containerOf());
    void answer(String label, ProbeResult? result) =>
        pending[routeCheckTargets.firstWhere((t) => t.label == label).url]!
            .complete(result);

    answer('Google', _ok);
    answer('GitHub', const ProbeResult(error: 'timeout'));
    answer('OKX', const ProbeResult(error: 'failed'));
    answer('FCM', null);
    pending[routeCheckTargets.last.url]!.completeError(StateError('core gone'));
    await settle();

    expect(entryOf(container, 'Google').phase, ProbePhase.fresh);
    expect(entryOf(container, 'Google').value, _ok);
    expect(entryOf(container, 'GitHub').phase, ProbePhase.failed);
    expect(entryOf(container, 'GitHub').value?.error, 'timeout');
    expect(entryOf(container, 'OKX').phase, ProbePhase.failed);
    expect(entryOf(container, 'FCM').phase, ProbePhase.failed);
    expect(entryOf(container, 'FCM').value, isNull);
    expect(entryOf(container, 'Baidu').phase, ProbePhase.failed);
  });

  test('a moved route drops the answers it made stale', () async {
    final container = await ask(containerOf());
    for (final completer in pending.values) {
      completer.complete(_ok);
    }
    await settle();
    expect(entryOf(container, 'Google').phase, ProbePhase.fresh);

    container.read(routeTrackerProvider.notifier).bumpHostEpoch();
    await settle();
    expect(entryOf(container, 'Google').phase, ProbePhase.empty);
  });
}
