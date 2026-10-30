import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/common/network_policy.dart';
import 'package:fl_clash/l10n/l10n.dart';
import 'package:fl_clash/manager/network_automation_manager.dart';
import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/state.dart';
import 'package:fl_clash/views/dashboard/fork/auto_pause.dart';
import 'package:fl_clash/views/network_features.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';

import '../../../helpers/test_app.dart';

const _rule = 'gateway:192.168.1.1';
const _office = NetworkSnapshot(
  addresses: ['192.168.1.20'],
  gateways: ['192.168.1.1'],
);
const _home = NetworkSnapshot(addresses: ['10.0.0.5'], gateways: ['10.0.0.1']);

/// Stands in for the core only; every running decision stays real.
class _PlatformSetupAction extends SetupAction {
  final coreCalls = <bool>[];

  @override
  Future<bool> setCoreRunning(bool running) async {
    coreCalls.add(running);
    return true;
  }

  @override
  Future<bool> inputsApplied() async => true;

  @override
  void resetCoreTraffic() {}
}

class _NoTraffic extends CommonAction {
  @override
  Future<void> updateTraffic() async {}
}

/// Hosts the real automation mixin the way CoreManager does.
class _AutomationHost extends ConsumerStatefulWidget {
  const _AutomationHost({required this.child});

  final Widget child;

  @override
  ConsumerState<_AutomationHost> createState() => _AutomationHostState();
}

class _AutomationHostState extends ConsumerState<_AutomationHost>
    with WidgetsBindingObserver, NetworkAutomationMixin<_AutomationHost> {
  @override
  Widget build(BuildContext context) => widget.child;
}

NetworkProps _settings({required bool smartAutoStop}) => NetworkProps(
  bypassPrivateRoute: false,
  networkFeatures: NetworkFeatureSettings(
    smartAutoStop: smartAutoStop,
    smartAutoStopNetworks: _rule,
  ),
);

void main() {
  group('display', () {
    Future<ProviderContainer> pump(
      WidgetTester tester, {
      bool enabled = true,
      required bool running,
      NetworkAutomationState automation = const NetworkAutomationState(),
    }) async {
      final container = ProviderContainer(
        overrides: [
          networkSettingProvider.overrideWithBuild(
            (_, _) => _settings(smartAutoStop: enabled),
          ),
          runTimeProvider.overrideWithBuild((_, _) => running ? 1 : null),
        ],
      );
      addTearDown(container.dispose);
      container.read(networkAutomationProvider.notifier).publish(automation);
      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: TestApp(
            child: Scaffold(body: ListView(children: const [AutoPauseCard()])),
          ),
        ),
      );
      await tester.pumpAndSettle();
      return container;
    }

    AppLocalizations l(WidgetTester tester) =>
        tester.element(find.byType(AutoPauseCard)).appLocalizations;

    testWidgets('automation off', (tester) async {
      await pump(tester, enabled: false, running: true);
      expect(find.text(l(tester).forkAutoPauseOff), findsOneWidget);
      expect(find.text(l(tester).forkAutoPauseOffHint), findsOneWidget);
      expect(find.byType(IconButton), findsNothing);
    });

    testWidgets('stopped by a rule names the rule and offers a start', (
      tester,
    ) async {
      await pump(
        tester,
        running: false,
        automation: const NetworkAutomationState(
          pausedByPolicy: true,
          matchedRule: _rule,
        ),
      );
      expect(find.text(l(tester).forkAutoPauseStoppedByRule), findsOneWidget);
      expect(find.text(l(tester).forkAutoPauseMatched(_rule)), findsOneWidget);
      expect(find.byTooltip(l(tester).forkAutoPauseStartAnyway), findsOne);
    });

    testWidgets('a stop no rule made reads as plainly stopped', (tester) async {
      await pump(tester, running: false);
      expect(find.text(l(tester).forkAutoPauseStopped), findsOneWidget);
      expect(find.text(l(tester).forkAutoPauseStoppedByRule), findsNothing);
      expect(find.text(l(tester).forkAutoPauseNoMatch), findsOneWidget);
      expect(find.byType(IconButton), findsNothing);
    });

    testWidgets(
      'a stop on a matching network is only a rule stop if a rule did it',
      (tester) async {
        await pump(
          tester,
          running: false,
          automation: const NetworkAutomationState(matchedRule: _rule),
        );
        expect(find.text(l(tester).forkAutoPauseStopped), findsOneWidget);
        expect(find.text(l(tester).forkAutoPauseStoppedByRule), findsNothing);
      },
    );

    testWidgets('running', (tester) async {
      await pump(tester, running: true);
      expect(find.text(l(tester).forkAutoPauseRunning), findsOneWidget);
      expect(find.byType(IconButton), findsNothing);
    });

    testWidgets('overridden shows the rule and offers a hand-back', (
      tester,
    ) async {
      await pump(
        tester,
        running: true,
        automation: const NetworkAutomationState(
          overridden: true,
          matchedRule: _rule,
        ),
      );
      expect(find.text(l(tester).forkAutoPauseOverridden), findsOneWidget);
      expect(find.text(l(tester).forkAutoPauseMatched(_rule)), findsOneWidget);
      expect(find.byTooltip(l(tester).forkAutoPauseResume), findsOne);
    });

    testWidgets('a tap opens Network tools', (tester) async {
      await pump(tester, running: true);
      await tester.tap(find.byType(AutoPauseCard));
      await tester.pumpAndSettle();
      expect(find.byType(NetworkFeaturesView), findsOneWidget);
    });
  });

  testWidgets('override and hand-back through the real automation', (
    tester,
  ) async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockStreamHandler(
          const EventChannel('dev.fluttercommunity.plus/connectivity_status'),
          MockStreamHandler.inline(onListen: (_, _) {}),
        );
    var network = _home;
    final action = _PlatformSetupAction();
    final container = ProviderContainer(
      overrides: [
        networkSettingProvider.overrideWithBuild(
          (_, _) => _settings(smartAutoStop: true),
        ),
        setupActionProvider.overrideWith(() => action),
        commonActionProvider.overrideWith(_NoTraffic.new),
        networkSnapshotReaderProvider.overrideWithValue(() async => network),
      ],
    );
    addTearDown(container.dispose);
    globalState.container = container;
    container.read(initProvider.notifier).value = true;
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: TestApp(
          child: _AutomationHost(
            child: Scaffold(body: ListView(children: const [AutoPauseCard()])),
          ),
        ),
      ),
    );
    final l = tester.element(find.byType(AutoPauseCard)).appLocalizations;
    Future<void> settle() async {
      await tester.pump(const Duration(seconds: 2));
      await tester.pumpAndSettle();
    }

    Future<void> resume() async {
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await settle();
    }

    await settle();
    await container.read(setupActionProvider.notifier).setRunning(true);
    await settle();
    expect(find.text(l.forkAutoPauseRunning), findsOneWidget);

    network = _office;
    await resume();
    expect(container.read(isStartProvider), false);
    expect(find.text(l.forkAutoPauseStoppedByRule), findsOneWidget);

    await tester.tap(find.byTooltip(l.forkAutoPauseStartAnyway));
    await settle();
    expect(container.read(isStartProvider), true);
    expect(find.text(l.forkAutoPauseOverridden), findsOneWidget);

    await resume();
    expect(container.read(isStartProvider), true);
    expect(find.text(l.forkAutoPauseOverridden), findsOneWidget);

    await tester.tap(find.byTooltip(l.forkAutoPauseResume));
    await settle();
    expect(container.read(isStartProvider), false);
    expect(find.text(l.forkAutoPauseStoppedByRule), findsOneWidget);
    expect(action.coreCalls, [true, false, true, false]);
  });
}
