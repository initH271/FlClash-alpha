import 'dart:convert';

import 'package:fl_clash/models/models.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('defaults enable event checks and leave periodic checks opt-in', () {
    const settings = ServiceCheckSettings();
    expect(settings.onConnect, isTrue);
    expect(settings.onRouteChange, isTrue);
    expect(settings.onPanelOpen, isTrue);
    expect(settings.periodic, isFalse);
    expect(settings.interval, const Duration(minutes: 15));
    expect(settings.cacheLifetime, const Duration(minutes: 10));
    expect(settings.platforms, hasLength(30));
    expect(settings.platforms, contains(MediaPlatform.telegram));
    expect(settings.platforms, contains(MediaPlatform.github));
    expect(settings.platforms, contains(MediaPlatform.coinbase));
  });

  test('settings and selected services survive full config serialization', () {
    const features = NetworkFeatureSettings(
      disableQuic: true,
      serviceChecks: ServiceCheckSettings(
        onConnect: false,
        onRouteChange: false,
        onPanelOpen: false,
        periodic: true,
        intervalMinutes: 5,
        cacheMinutes: 30,
        platforms: [MediaPlatform.telegram, MediaPlatform.github],
      ),
    );
    const config = Config(
      themeProps: defaultThemeProps,
      networkProps: NetworkProps(networkFeatures: features),
    );
    final restored = Config.fromJson(
      jsonDecode(jsonEncode(config)) as Map<String, dynamic>,
    );
    expect(restored.networkProps.networkFeatures, features);
    expect(restored.networkProps.networkFeatures.hashCode, features.hashCode);
    expect(restored.networkProps.networkFeatures.serviceChecks.platforms, [
      MediaPlatform.telegram,
      MediaPlatform.github,
    ]);
  });

  test(
    'legacy config gains safe defaults without losing existing network settings',
    () {
      final settings = NetworkFeatureSettings.fromJson({'disableQuic': true});
      expect(settings.disableQuic, isTrue);
      expect(settings.serviceChecks, const ServiceCheckSettings());
    },
  );

  test('explicit empty selection is preserved', () {
    final settings = ServiceCheckSettings.fromJson({'platforms': []});
    expect(settings.platforms, isEmpty);
    expect(ServiceCheckSettings.fromJson(settings.toJson()).platforms, isEmpty);
  });

  test(
    'unknown names are ignored and selections are deduplicated in saved order',
    () {
      final settings = ServiceCheckSettings.fromJson({
        'platforms': ['telegram', 'unknown', null, 'github', 'telegram'],
      });
      expect(settings.platforms, [
        MediaPlatform.telegram,
        MediaPlatform.github,
      ]);
    },
  );

  test(
    'malformed and out-of-range durations cannot create a tight timer loop',
    () {
      final settings = ServiceCheckSettings.fromJson({
        'intervalMinutes': -10,
        'cacheMinutes': 100000,
        'periodic': true,
      });
      expect(settings.interval, const Duration(minutes: 1));
      expect(settings.cacheLifetime, const Duration(days: 1));
      expect(
        ServiceCheckSettings.fromJson({
          'intervalMinutes': 'invalid',
        }).intervalMinutes,
        15,
      );
      expect(ServiceCheckSettings.fromJson(null), const ServiceCheckSettings());
    },
  );

  test('service settings do not alter profile setup parameters', () {
    const settings = NetworkFeatureSettings(disableQuic: true);
    final changed = settings.copyWith(
      serviceChecks: const ServiceCheckSettings(
        periodic: true,
        intervalMinutes: 5,
      ),
    );
    expect(changed.profileOptions, settings.profileOptions);
    expect(changed, isNot(settings));
  });
}
