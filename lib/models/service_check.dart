import 'package:collection/collection.dart';

import 'media_unlock.dart';

class ServiceCheckSettings {
  const ServiceCheckSettings({
    this.onConnect = true,
    this.onRouteChange = true,
    this.onPanelOpen = true,
    this.periodic = false,
    this.intervalMinutes = 15,
    this.cacheMinutes = 10,
    this.platforms = defaultServiceCheckPlatforms,
  });

  final bool onConnect;
  final bool onRouteChange;
  final bool onPanelOpen;
  final bool periodic;
  final int intervalMinutes;
  final int cacheMinutes;
  final List<MediaPlatform> platforms;

  Duration get interval => Duration(minutes: intervalMinutes.clamp(1, 1440));
  Duration get cacheLifetime => Duration(minutes: cacheMinutes.clamp(1, 1440));

  factory ServiceCheckSettings.fromJson(Object? value) {
    if (value is! Map) return const ServiceCheckSettings();
    bool flag(String key, bool fallback) =>
        value[key] is bool ? value[key] as bool : fallback;
    int minutes(String key, int fallback) {
      final number = value[key];
      return number is num && number.isFinite
          ? number.round().clamp(1, 1440)
          : fallback;
    }

    final names = value['platforms'];
    final byName = {
      for (final platform in MediaPlatform.values) platform.name: platform,
    };
    return ServiceCheckSettings(
      onConnect: flag('onConnect', true),
      onRouteChange: flag('onRouteChange', true),
      onPanelOpen: flag('onPanelOpen', true),
      periodic: flag('periodic', false),
      intervalMinutes: minutes('intervalMinutes', 15),
      cacheMinutes: minutes('cacheMinutes', 10),
      platforms: names is List
          ? List.unmodifiable(
              names
                  .map((name) => byName[name])
                  .whereType<MediaPlatform>()
                  .toSet(),
            )
          : defaultServiceCheckPlatforms,
    );
  }

  Map<String, dynamic> toJson() => {
    'onConnect': onConnect,
    'onRouteChange': onRouteChange,
    'onPanelOpen': onPanelOpen,
    'periodic': periodic,
    'intervalMinutes': intervalMinutes,
    'cacheMinutes': cacheMinutes,
    'platforms': platforms.map((platform) => platform.name).toList(),
  };

  ServiceCheckSettings copyWith({
    bool? onConnect,
    bool? onRouteChange,
    bool? onPanelOpen,
    bool? periodic,
    int? intervalMinutes,
    int? cacheMinutes,
    List<MediaPlatform>? platforms,
  }) => ServiceCheckSettings(
    onConnect: onConnect ?? this.onConnect,
    onRouteChange: onRouteChange ?? this.onRouteChange,
    onPanelOpen: onPanelOpen ?? this.onPanelOpen,
    periodic: periodic ?? this.periodic,
    intervalMinutes: intervalMinutes ?? this.intervalMinutes,
    cacheMinutes: cacheMinutes ?? this.cacheMinutes,
    platforms: platforms == null
        ? this.platforms
        : List.unmodifiable(platforms),
  );

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is ServiceCheckSettings &&
          onConnect == other.onConnect &&
          onRouteChange == other.onRouteChange &&
          onPanelOpen == other.onPanelOpen &&
          periodic == other.periodic &&
          intervalMinutes == other.intervalMinutes &&
          cacheMinutes == other.cacheMinutes &&
          const ListEquality<MediaPlatform>().equals(
            platforms,
            other.platforms,
          );

  @override
  int get hashCode => Object.hash(
    onConnect,
    onRouteChange,
    onPanelOpen,
    periodic,
    intervalMinutes,
    cacheMinutes,
    const ListEquality<MediaPlatform>().hash(platforms),
  );
}
