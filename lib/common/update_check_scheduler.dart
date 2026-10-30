import 'dart:async';

class UpdateCheckScheduler {
  final Future<Map<String, dynamic>?> Function() load;
  final Future<void> Function(Map<String, dynamic>) notify;
  final DateTime Function() now;
  final void Function(Object) onError;
  final void Function(String) trace;
  final Duration interval;

  UpdateCheckScheduler({
    required this.load,
    required this.notify,
    required this.onError,
    this.now = DateTime.now,
    this.trace = _ignore,
    this.interval = const Duration(hours: 6),
  });

  Timer? _timer;
  Future<bool>? _checking;
  DateTime? _lastChecked;
  Map<String, dynamic>? _pending;
  final Set<String> _notified = {};
  bool _enabled = false;
  bool _foreground = true;
  bool _disposed = false;
  int _revision = 0;

  void setEnabled(bool enabled) {
    if (_disposed || _enabled == enabled) return;
    _enabled = enabled;
    if (!enabled) {
      _revision++;
      _pending = null;
      _lastChecked = null;
      _timer?.cancel();
    } else {
      unawaited(check());
    }
  }

  void setForeground(bool foreground) {
    if (_disposed || _foreground == foreground) return;
    _foreground = foreground;
    _timer?.cancel();
    if (foreground) unawaited(check());
  }

  Future<bool> check() {
    if (_disposed) return Future.value(false);
    if (!_enabled || !_foreground) {
      trace('skipped: enabled=$_enabled foreground=$_foreground');
      return Future.value(false);
    }
    if (_checking != null) return _checking!;
    final fetch = _pending == null;
    if (fetch &&
        _lastChecked != null &&
        now().difference(_lastChecked!) < interval) {
      trace('skipped: last check at $_lastChecked');
      _arm();
      return Future.value(false);
    }
    final result = Completer<bool>();
    _checking = result.future;
    unawaited(_run(_revision, fetch: fetch).then(result.complete));
    return result.future;
  }

  Future<bool> _run(int revision, {required bool fetch}) async {
    _timer?.cancel();
    try {
      if (fetch) {
        _lastChecked = now();
        trace('started');
        final release = await load();
        if (_disposed || !_enabled || revision != _revision) return false;
        trace(
          release == null ? 'no newer build' : 'found ${release['tag_name']}',
        );
        _pending = release;
      }
      final release = _pending;
      if (release == null || !_foreground) return false;
      final identity = '${release['build'] ?? release['tag_name']}';
      _pending = null;
      if (!_notified.add(identity)) {
        trace('already shown $identity');
        return false;
      }
      try {
        await notify(release);
      } catch (_) {
        _notified.remove(identity);
        rethrow;
      }
      return true;
    } catch (error) {
      if (!_disposed) onError(error);
      return false;
    } finally {
      _checking = null;
      if (!_disposed && _enabled && _foreground && revision != _revision) {
        scheduleMicrotask(() => unawaited(check()));
      } else {
        _arm();
      }
    }
  }

  void _arm() {
    _timer?.cancel();
    if (_disposed || !_enabled || !_foreground || _checking != null) return;
    final remaining = _lastChecked == null
        ? Duration.zero
        : interval - now().difference(_lastChecked!);
    _timer = Timer(remaining.isNegative ? Duration.zero : remaining, () {
      unawaited(check());
    });
  }

  void dispose() {
    _disposed = true;
    _revision++;
    _pending = null;
    _timer?.cancel();
  }
}

void _ignore(String _) {}
