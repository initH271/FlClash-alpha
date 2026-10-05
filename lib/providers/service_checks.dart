import 'dart:async';

import 'package:collection/collection.dart';
import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/common/media_unlock_checker.dart';
import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/models/models.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app.dart';
import 'config.dart';
import 'network_features.dart';
import 'state.dart';

typedef ServiceCheckRoutingState = ({int pending, int revision, bool failed});

class ServiceCheckRouting extends Notifier<ServiceCheckRoutingState> {
  final _pending = <int>{};
  final _primary = <int>{};
  int _counter = 0;
  int _latest = 0;

  @override
  ServiceCheckRoutingState build() => (pending: 0, revision: 0, failed: false);

  int begin({bool primary = true}) {
    final token = ++_counter;
    _pending.add(token);
    if (primary) {
      _primary.add(token);
      _latest = token;
    }
    state = (
      pending: _pending.length,
      revision: state.revision,
      failed: primary ? false : state.failed,
    );
    return token;
  }

  void end(int token, {required bool applied}) {
    if (!_pending.remove(token)) return;
    final latest = _primary.remove(token) && token == _latest;
    state = (
      pending: _pending.length,
      revision: state.revision + (latest && applied ? 1 : 0),
      failed: latest ? !applied : state.failed,
    );
  }
}

final serviceCheckRoutingProvider =
    NotifierProvider<ServiceCheckRouting, ServiceCheckRoutingState>(
      ServiceCheckRouting.new,
    );

final serviceCheckClientProvider = Provider<MediaUnlockChecker>(
  (ref) => MediaUnlockChecker(
    unifiedDelay: ref.watch(
      patchClashConfigProvider.select((settings) => settings.unifiedDelay),
    ),
  ),
);

final serviceCheckClockProvider = Provider<DateTime Function()>(
  (_) => DateTime.now,
);

final _serviceCheckSelectionProvider = Provider<Map<String, String>>((ref) {
  if (!ref.watch(initProvider)) return const {};
  return ref.watch(selectedMapProvider);
});

class ServiceCheckActivity {
  const ServiceCheckActivity({
    this.running = false,
    this.failed = false,
    this.lastChecked,
  });

  final bool running;
  final bool failed;
  final DateTime? lastChecked;
}

enum _CheckTrigger { manual, connect, route, panel, periodic }

class _CheckRequest {
  const _CheckRequest(this.revision, this.trigger);

  final int revision;
  final _CheckTrigger trigger;
}

class _CheckContext {
  const _CheckContext({
    required this.profile,
    required this.selected,
    required this.status,
    required this.running,
    required this.routingRevision,
    required this.effectiveRoutes,
    required this.suspended,
  });

  final int? profile;
  final Map<String, String> selected;
  final CoreStatus status;
  final bool running;
  final int routingRevision;
  final Map<String, String> effectiveRoutes;
  final bool suspended;
}

class ServiceCheckController extends Notifier<ServiceCheckActivity> {
  late MediaUnlockChecker _checker;
  late DateTime Function() _now;
  Timer? _debounce;
  Timer? _periodic;
  _CheckTrigger? _automaticWanted;
  _CheckRequest? _queued;
  _CheckTrigger? _active;
  bool _working = false;
  bool _running = false;
  bool _foreground = false;
  bool _panelOpen = false;
  bool _ready = false;
  bool _disposed = false;
  int _revision = 0;
  DateTime? _lastChecked;
  DateTime? _periodicAnchor;
  final _checkedPlatforms = <MediaPlatform>{};
  Map<String, String> _lastEffectiveRoutes = const {};

  ServiceCheckSettings get _settings =>
      ref.read(networkFeaturesProvider).serviceChecks;

  bool get _connected =>
      ref.read(initProvider) &&
      !ref.read(suspendProvider) &&
      ref.read(coreStatusProvider) == CoreStatus.connected &&
      ref.read(runTimeProvider) != null;

  bool get _automaticAllowed =>
      _foreground && _ready && !ref.read(serviceCheckRoutingProvider).failed;

  @override
  ServiceCheckActivity build() {
    _checker = ref.read(serviceCheckClientProvider);
    _now = ref.read(serviceCheckClockProvider);
    _ready = _connected;
    ref.listen(serviceCheckClientProvider, (previous, next) {
      if (identical(previous, next)) return;
      final wanted = _automaticWanted;
      _invalidate();
      _checker = next;
      _automaticWanted = wanted;
      if (_panelOpen) panelOpened();
    });
    _lastEffectiveRoutes = _effectiveRoutes(ref.read(groupsProvider));
    if (_ready && _settings.onConnect) _automaticWanted = _CheckTrigger.connect;
    ref.listen(initProvider, (_, _) => _connectionChanged());
    ref.listen(suspendProvider, (_, _) => _connectionChanged());
    ref.listen(coreStatusProvider, (_, _) => _connectionChanged());
    ref.listen(runTimeProvider.select((value) => value != null), (_, _) {
      _connectionChanged();
    });
    ref.listen(_serviceCheckSelectionProvider, (_, _) => _routeChanged());
    ref.listen(currentProfileIdProvider, (_, _) => _routeChanged());
    ref.listen(groupsProvider.select(_effectiveRoutes), (_, next) {
      if (next.isEmpty) {
        final wanted = _automaticWanted;
        _invalidate();
        _automaticWanted = wanted;
        return;
      }
      final changed =
          _lastEffectiveRoutes.isNotEmpty &&
          !const MapEquality<String, String>().equals(
            _lastEffectiveRoutes,
            next,
          );
      _lastEffectiveRoutes = next;
      if (changed) _routeChanged();
    });
    ref.listen(serviceCheckRoutingProvider, _routingChanged);
    ref.listen(
      networkFeaturesProvider.select((value) => value.serviceChecks),
      _settingsChanged,
    );
    ref.onDispose(() {
      _disposed = true;
      _revision++;
      _debounce?.cancel();
      _periodic?.cancel();
      _checker.cancel();
    });
    return const ServiceCheckActivity();
  }

  bool get hasFreshResults {
    final checked = _lastChecked;
    return checked != null &&
        _now().difference(checked) >= Duration.zero &&
        _now().difference(checked) < _settings.cacheLifetime &&
        _settings.platforms.every(_checkedPlatforms.contains);
  }

  void _publish({bool running = false, bool failed = false}) {
    if (_disposed) return;
    _running = running;
    final revision = _revision;
    final activity = ServiceCheckActivity(
      running: running,
      failed: failed,
      lastChecked: _lastChecked,
    );
    // Closing a panel can cancel during widget teardown.
    scheduleMicrotask(() {
      if (!_disposed && revision == _revision) state = activity;
    });
  }

  void cancel() {
    _revision++;
    _queued = null;
    _automaticWanted = null;
    _debounce?.cancel();
    _checker.cancel();
    _publish();
  }

  void _invalidate() {
    cancel();
    _lastChecked = null;
    _checkedPlatforms.clear();
    ref.read(serviceCheckResultsProvider.notifier).clear();
    _publish();
  }

  void _connectionChanged() {
    _ready = _connected;
    _invalidate();
    if (_ready && _settings.onConnect) {
      _automaticWanted = _CheckTrigger.connect;
      _scheduleAutomatic(_CheckTrigger.connect);
    }
    _periodicAnchor = _now();
    _armPeriodic();
  }

  void _routeChanged() {
    final wanted = _automaticWanted;
    _invalidate();
    if (_ready && _settings.onRouteChange) {
      _automaticWanted = _CheckTrigger.route;
      _scheduleAutomatic(_CheckTrigger.route);
    } else if (_ready && wanted != null && _enabled(wanted)) {
      _automaticWanted = wanted;
      _scheduleAutomatic(wanted);
    }
  }

  void _routingChanged(
    ServiceCheckRoutingState? previous,
    ServiceCheckRoutingState next,
  ) {
    if (next.pending > 0) {
      final wanted = _automaticWanted;
      _invalidate();
      _automaticWanted = wanted;
      return;
    }
    if (next.failed) {
      _automaticWanted = null;
      _debounce?.cancel();
    } else if (_automaticAllowed) {
      final wanted = _automaticWanted;
      if (wanted != null) {
        _scheduleAutomatic(wanted);
      }
    }
    if (_queued != null) unawaited(_drain());
    _armPeriodic();
  }

  bool _enabled(_CheckTrigger trigger) => switch (trigger) {
    _CheckTrigger.manual => true,
    _CheckTrigger.connect => _settings.onConnect,
    _CheckTrigger.route => _settings.onRouteChange,
    _CheckTrigger.panel => _settings.onPanelOpen,
    _CheckTrigger.periodic => _settings.periodic,
  };

  void _settingsChanged(
    ServiceCheckSettings? previous,
    ServiceCheckSettings next,
  ) {
    if (!const ListEquality<MediaPlatform>().equals(
      previous?.platforms,
      next.platforms,
    )) {
      cancel();
    }
    final wanted = _automaticWanted;
    if (wanted != null && !_enabled(wanted)) {
      _automaticWanted = null;
      _debounce?.cancel();
    }
    final active = _active;
    if (active != null && active != _CheckTrigger.manual && !_enabled(active)) {
      cancel();
    }
    if (_panelOpen && next.onPanelOpen && previous?.onPanelOpen != true) {
      panelOpened();
    }
    if (next.periodic && previous?.periodic != true) _periodicAnchor = _now();
    _armPeriodic();
  }

  void setForeground(bool foreground) {
    if (_disposed) return;
    if (_foreground == foreground) return;
    _foreground = foreground;
    if (!foreground) {
      _periodic?.cancel();
      _debounce?.cancel();
      final active = _active;
      if (active != null && active != _CheckTrigger.manual) {
        cancel();
        _automaticWanted = active;
      }
      return;
    }
    final wanted = _automaticWanted;
    if (wanted != null) _scheduleAutomatic(wanted);
    _armPeriodic();
  }

  void panelOpened() {
    _panelOpen = true;
    if (!_settings.onPanelOpen || !_automaticAllowed || hasFreshResults) return;
    if (_debounce?.isActive == true ||
        ref.read(serviceCheckRoutingProvider).pending > 0) {
      _automaticWanted ??= _CheckTrigger.panel;
    } else {
      _request(_CheckTrigger.panel);
    }
  }

  void panelClosed() {
    if (_disposed) return;
    _panelOpen = false;
    cancel();
  }

  void toggleManual() {
    if (_running) {
      cancel();
      return;
    }
    _debounce?.cancel();
    _automaticWanted = null;
    _request(_CheckTrigger.manual);
  }

  void _scheduleAutomatic(_CheckTrigger trigger) {
    if (!_automaticAllowed || !_enabled(trigger)) return;
    _automaticWanted = trigger;
    _debounce?.cancel();
    _debounce = Timer(const Duration(seconds: 3), () {
      if (_disposed || !_automaticAllowed || !_enabled(trigger)) return;
      if (ref.read(serviceCheckRoutingProvider).pending > 0) return;
      _automaticWanted = null;
      _request(trigger);
    });
  }

  void _armPeriodic() {
    _periodic?.cancel();
    if (_disposed ||
        !_automaticAllowed ||
        !_settings.periodic ||
        _settings.platforms.isEmpty) {
      return;
    }
    _periodicAnchor ??= _now();
    final remaining = _periodicAnchor!
        .add(_settings.interval)
        .difference(_now());
    _periodic = Timer(remaining.isNegative ? Duration.zero : remaining, () {
      if (_disposed) return;
      _periodicAnchor = _now();
      if (ref.read(serviceCheckRoutingProvider).pending > 0 ||
          _debounce?.isActive == true) {
        _automaticWanted ??= _CheckTrigger.periodic;
      } else {
        _request(_CheckTrigger.periodic);
      }
      _armPeriodic();
    });
  }

  void _request(_CheckTrigger trigger) {
    if (_disposed || _settings.platforms.isEmpty) return;
    if (trigger != _CheckTrigger.manual &&
        (!_automaticAllowed || !_enabled(trigger) || _running)) {
      return;
    }
    if (trigger == _CheckTrigger.panel && hasFreshResults) return;
    _queued = _CheckRequest(++_revision, trigger);
    _publish(running: true);
    unawaited(_drain());
  }

  Map<String, String> _effectiveRoutes(List<Group> groups) => {
    for (final group in groups)
      if (group.realNow.isNotEmpty) group.name: group.realNow,
  };

  _CheckContext _context() => _CheckContext(
    profile: ref.read(currentProfileIdProvider),
    selected: Map.of(ref.read(selectedMapProvider)),
    status: ref.read(coreStatusProvider),
    running: ref.read(runTimeProvider) != null,
    routingRevision: ref.read(serviceCheckRoutingProvider).revision,
    effectiveRoutes: _effectiveRoutes(ref.read(groupsProvider)),
    suspended: ref.read(suspendProvider),
  );

  bool _current(_CheckRequest request, _CheckContext context) {
    if (_disposed || request.revision != _revision) return false;
    final routing = ref.read(serviceCheckRoutingProvider);
    return routing.pending == 0 &&
        routing.revision == context.routingRevision &&
        ref.read(currentProfileIdProvider) == context.profile &&
        ref.read(coreStatusProvider) == context.status &&
        ref.read(suspendProvider) == context.suspended &&
        (ref.read(runTimeProvider) != null) == context.running &&
        const MapEquality<String, String>().equals(
          ref.read(selectedMapProvider),
          context.selected,
        ) &&
        const MapEquality<String, String>().equals(
          _effectiveRoutes(ref.read(groupsProvider)),
          context.effectiveRoutes,
        ) &&
        request.revision == _revision;
  }

  Future<void> _drain() async {
    if (_working || _disposed) return;
    _working = true;
    try {
      while (!_disposed && _queued != null) {
        if (ref.read(serviceCheckRoutingProvider).pending > 0) break;
        final request = _queued!;
        _queued = null;
        if (request.revision != _revision) continue;
        if (request.trigger != _CheckTrigger.manual && !_automaticAllowed) {
          _publish();
          continue;
        }
        _active = request.trigger;
        _periodicAnchor = _now();
        _lastChecked = null;
        _checkedPlatforms.clear();
        ref.read(serviceCheckResultsProvider.notifier).clear();
        _publish(running: true);
        final platforms = List<MediaPlatform>.of(_settings.platforms);
        final context = _context();
        if (!_current(request, context)) {
          _active = null;
          continue;
        }
        try {
          final results = await _checker.checkAll(
            platforms: platforms,
            onProgress: (result) {
              if (_current(request, context)) {
                ref.read(serviceCheckResultsProvider.notifier).add(result);
              }
            },
          );
          if (_current(request, context)) {
            _lastChecked = _now();
            _periodicAnchor = _lastChecked;
            _checkedPlatforms.addAll(results.keys);
            _publish();
          }
        } catch (error) {
          if (_current(request, context)) {
            commonPrint.log(
              'Service checks failed (${error.runtimeType})',
              logLevel: LogLevel.warning,
            );
            _publish(failed: true);
          }
        } finally {
          _active = null;
        }
      }
    } finally {
      _working = false;
      if (!_disposed) _armPeriodic();
    }
  }
}

final serviceCheckControllerProvider =
    NotifierProvider<ServiceCheckController, ServiceCheckActivity>(
      ServiceCheckController.new,
    );
