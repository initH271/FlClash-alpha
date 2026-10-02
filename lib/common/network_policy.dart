import 'package:fl_clash/models/network_features.dart';

const quicRejectRule = 'AND,((NETWORK,UDP),(DST-PORT,443)),REJECT';

Map<String, dynamic> applyNetworkFeatures(
  Map<String, dynamic> config,
  NetworkFeatureSettings settings,
) {
  final result = Map<String, dynamic>.from(config);
  if (settings.disableQuic) {
    final rules = List<String>.from(result['rules'] as List? ?? const []);
    result['rules'] = [
      quicRejectRule,
      ...rules.where((r) => r != quicRejectRule),
    ];
  }
  if (settings.overrideSniffer) {
    result['sniffer'] = {
      ...Map<String, dynamic>.from(result['sniffer'] as Map? ?? const {}),
      'enable': settings.snifferEnabled,
      'sniff': {
        'HTTP': {
          'ports': ['80', '8080-8880'],
        },
        'TLS': {
          'ports': ['443', '8443'],
        },
        'QUIC': {
          'ports': ['443', '8443'],
        },
      },
    };
  }
  if (settings.overrideNtp) {
    result['ntp'] = {
      ...Map<String, dynamic>.from(result['ntp'] as Map? ?? const {}),
      'enable': settings.ntpEnabled,
      'server': settings.ntpServer,
      'port': 123,
      'interval': 30,
      'write-to-system': false,
    };
  }
  return result;
}

class NetworkSnapshot {
  const NetworkSnapshot({this.addresses = const [], this.gateways = const []});

  final List<String> addresses;
  final List<String> gateways;
  bool get isEmpty => addresses.isEmpty && gateways.isEmpty;
}

class NetworkRules {
  static int? _address(String value) {
    final parts = value.trim().split('.');
    if (parts.length != 4) return null;
    var result = 0;
    for (final part in parts) {
      if (!RegExp(r'^\d{1,3}$').hasMatch(part)) return null;
      final number = int.parse(part);
      if (number > 255) return null;
      result = (result << 8) | number;
    }
    return result;
  }

  static bool _matches(String address, String rule) {
    final parts = rule.split('/');
    if (parts.length > 2) return false;
    final target = _address(parts.first);
    final value = _address(address);
    final prefix = parts.length == 1 ? 32 : int.tryParse(parts.last);
    if (target == null ||
        value == null ||
        prefix == null ||
        prefix < 0 ||
        prefix > 32) {
      return false;
    }
    final mask = prefix == 0 ? 0 : (0xffffffff << (32 - prefix)) & 0xffffffff;
    return (target & mask) == (value & mask);
  }

  static Iterable<String> _rules(String value) => value
      .split(RegExp(r'[,\n]'))
      .map((r) => r.trim())
      .where((r) => r.isNotEmpty);

  static bool isValid(String value) => _rules(value).every((rule) {
    final address = rule.toLowerCase().startsWith('gateway:')
        ? rule.substring(8).trim()
        : rule;
    final parts = address.split('/');
    if (_address(parts.first) == null || parts.length > 2) return false;
    final prefix = parts.length == 1 ? 32 : int.tryParse(parts.last);
    return prefix != null && prefix >= 0 && prefix <= 32;
  });

  static bool matches(NetworkSnapshot snapshot, String value) =>
      _rules(value).any((rule) {
        final gateway = rule.toLowerCase().startsWith('gateway:');
        final target = gateway ? rule.substring(8).trim() : rule;
        final addresses = gateway ? snapshot.gateways : snapshot.addresses;
        return addresses.any((address) => _matches(address, target));
      });
}

class AutomaticStopPolicy {
  bool _pausedByPolicy = false;
  int _userRevision = 0;

  bool get pausedByPolicy => _pausedByPolicy;

  void userIntent() {
    _userRevision++;
    _pausedByPolicy = false;
  }

  Future<void> reconcile({
    required bool enabled,
    required bool matches,
    required bool running,
    required Future<bool> Function(bool running) apply,
  }) async {
    final revision = _userRevision;
    if (enabled && matches && running) {
      _pausedByPolicy = true;
      try {
        final applied = await apply(false);
        if (revision == _userRevision && !applied) _pausedByPolicy = false;
      } catch (_) {
        if (revision == _userRevision) _pausedByPolicy = false;
        rethrow;
      }
    } else if ((!enabled || !matches) && _pausedByPolicy) {
      _pausedByPolicy = false;
      try {
        final applied = await apply(true);
        if (revision == _userRevision && !applied) _pausedByPolicy = true;
      } catch (_) {
        if (revision == _userRevision) _pausedByPolicy = true;
        rethrow;
      }
    }
  }
}
