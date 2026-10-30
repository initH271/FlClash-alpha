import 'dart:async';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/common/network_policy.dart';
import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:wakelock_plus/wakelock_plus.dart';

mixin NetworkAutomationMixin<T extends ConsumerStatefulWidget>
    on ConsumerState<T>, WidgetsBindingObserver {
  final _policy = AutomaticStopPolicy();
  StreamSubscription<List<ConnectivityResult>>? _subscription;
  Timer? _debounce;
  int _revision = 0;
  bool _checking = false;
  bool _pending = false;
  bool _wakelockEnabled = false;
  bool _wakeTouched = false;
  String? _matchedRule;
  Future<void> _wakePending = Future.value();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    ref.listenManual(networkUserIntentProvider, (_, _) {
      _policy.userIntent();
      _publish();
      // Settles the intent against the network it was made on.
      _schedule();
    });
    ref.listenManual(networkResumeRequestProvider, (_, _) => _handBack());
    ref.listenManual(
      networkFeaturesProvider.select(
        (settings) => (settings.smartAutoStop, settings.smartAutoStopNetworks),
      ),
      (_, _) => _handBack(),
    );
    ref.listenManual(
      networkFeaturesProvider.select(
        (settings) => (
          settings.smartAutoStop,
          settings.smartAutoStopNetworks,
          settings.keepAwake,
        ),
      ),
      (_, _) {
        _syncSubscription();
        _schedule();
        unawaited(_syncWakelock());
      },
    );
    ref.listenManual(runTimeProvider.select((value) => value != null), (_, _) {
      unawaited(_syncWakelock());
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _syncSubscription();
      _schedule();
    });
  }

  void _syncSubscription() {
    if (ref.read(networkFeaturesProvider).smartAutoStop) {
      _subscription ??= Connectivity().onConnectivityChanged.listen(
        (_) => _schedule(),
        onError: (Object error) => commonPrint.log(
          'Network events: $error',
          logLevel: LogLevel.warning,
        ),
      );
    } else {
      unawaited(_subscription?.cancel());
      _subscription = null;
    }
  }

  Future<void> _syncWakelock() async {
    _wakePending = _wakePending.then((_) => _applyWakelock());
    await _wakePending;
  }

  Future<void> _applyWakelock() async {
    if (!system.isDesktop || !mounted) return;
    final enabled =
        ref.read(networkFeaturesProvider).keepAwake &&
        ref.read(runTimeProvider) != null;
    if (_wakelockEnabled == enabled) return;
    try {
      _wakeTouched = true;
      await WakelockPlus.toggle(enable: enabled);
      _wakelockEnabled = enabled;
    } catch (error) {
      commonPrint.log('Wake lock: $error', logLevel: LogLevel.warning);
    }
  }

  void _handBack() {
    _policy.resumeAutomatic();
    _publish();
    _schedule();
  }

  void _publish() {
    if (!mounted) return;
    ref
        .read(networkAutomationProvider.notifier)
        .publish(
          NetworkAutomationState(
            pausedByPolicy: _policy.pausedByPolicy,
            overridden: _policy.overridden,
            matchedRule: _matchedRule,
          ),
        );
  }

  void _schedule() {
    _revision++;
    _pending = true;
    _debounce?.cancel();
    _debounce = Timer(const Duration(seconds: 1), () => unawaited(_check()));
  }

  Future<void> _check() async {
    if (_checking || !mounted) return;
    _checking = true;
    try {
      while (_pending && mounted) {
        _pending = false;
        final revision = _revision;
        final settings = ref.read(networkFeaturesProvider);
        if (!settings.smartAutoStop) _matchedRule = null;
        if (!settings.smartAutoStop && !_policy.pausedByPolicy) continue;
        if (settings.smartAutoStop &&
            !NetworkRules.isValid(settings.smartAutoStopNetworks)) {
          continue;
        }
        final snapshot = settings.smartAutoStop
            ? await ref.read(networkSnapshotReaderProvider)()
            : const NetworkSnapshot();
        if (!mounted || revision != _revision) continue;
        if (settings.smartAutoStop && snapshot.isEmpty) continue;
        _matchedRule = NetworkRules.matchingRule(
          snapshot,
          settings.smartAutoStopNetworks,
        );
        await _policy.reconcile(
          enabled: settings.smartAutoStop,
          matches: _matchedRule != null,
          running: ref.read(runTimeProvider) != null,
          apply: (running) => ref
              .read(setupActionProvider.notifier)
              .setRunningAutomatically(running),
        );
        _publish();
      }
    } catch (error) {
      commonPrint.log('Network automation: $error', logLevel: LogLevel.warning);
    } finally {
      _checking = false;
      _publish();
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _schedule();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _revision++;
    _debounce?.cancel();
    unawaited(_subscription?.cancel());
    if (_wakeTouched) {
      unawaited(
        _wakePending
            .then((_) => WakelockPlus.disable())
            .catchError(
              (Object error) => commonPrint.log(
                'Wake lock cleanup: $error',
                logLevel: LogLevel.warning,
              ),
            ),
      );
    }
    super.dispose();
  }
}
