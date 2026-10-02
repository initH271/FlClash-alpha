class NetworkFeatureSettings {
  const NetworkFeatureSettings({
    this.disableQuic = false,
    this.smartAutoStop = false,
    this.smartAutoStopNetworks = '',
    this.overrideSniffer = false,
    this.snifferEnabled = true,
    this.overrideNtp = false,
    this.ntpEnabled = true,
    this.ntpServer = 'time.apple.com',
    this.keepAwake = false,
  });

  final bool disableQuic;
  final bool smartAutoStop;
  final String smartAutoStopNetworks;
  final bool overrideSniffer;
  final bool snifferEnabled;
  final bool overrideNtp;
  final bool ntpEnabled;
  final String ntpServer;
  final bool keepAwake;

  static NetworkFeatureSettings safeFromJson(Object? value) {
    if (value is! Map<String, dynamic>) return const NetworkFeatureSettings();
    try {
      return NetworkFeatureSettings.fromJson(value);
    } catch (_) {
      return const NetworkFeatureSettings();
    }
  }

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is NetworkFeatureSettings &&
          disableQuic == other.disableQuic &&
          smartAutoStop == other.smartAutoStop &&
          smartAutoStopNetworks == other.smartAutoStopNetworks &&
          overrideSniffer == other.overrideSniffer &&
          snifferEnabled == other.snifferEnabled &&
          overrideNtp == other.overrideNtp &&
          ntpEnabled == other.ntpEnabled &&
          ntpServer == other.ntpServer &&
          keepAwake == other.keepAwake;

  @override
  int get hashCode => Object.hash(
    disableQuic,
    smartAutoStop,
    smartAutoStopNetworks,
    overrideSniffer,
    snifferEnabled,
    overrideNtp,
    ntpEnabled,
    ntpServer,
    keepAwake,
  );

  factory NetworkFeatureSettings.fromJson(Map<String, dynamic> json) =>
      NetworkFeatureSettings(
        disableQuic: json['disableQuic'] == true,
        smartAutoStop: json['smartAutoStop'] == true,
        smartAutoStopNetworks: json['smartAutoStopNetworks'] as String? ?? '',
        overrideSniffer: json['overrideSniffer'] == true,
        snifferEnabled: json['snifferEnabled'] as bool? ?? true,
        overrideNtp: json['overrideNtp'] == true,
        ntpEnabled: json['ntpEnabled'] as bool? ?? true,
        ntpServer: json['ntpServer'] as String? ?? 'time.apple.com',
        keepAwake: json['keepAwake'] == true,
      );

  Map<String, dynamic> toJson() => {
    'disableQuic': disableQuic,
    'smartAutoStop': smartAutoStop,
    'smartAutoStopNetworks': smartAutoStopNetworks,
    'overrideSniffer': overrideSniffer,
    'snifferEnabled': snifferEnabled,
    'overrideNtp': overrideNtp,
    'ntpEnabled': ntpEnabled,
    'ntpServer': ntpServer,
    'keepAwake': keepAwake,
  };

  NetworkFeatureSettings copyWith({
    bool? disableQuic,
    bool? smartAutoStop,
    String? smartAutoStopNetworks,
    bool? overrideSniffer,
    bool? snifferEnabled,
    bool? overrideNtp,
    bool? ntpEnabled,
    String? ntpServer,
    bool? keepAwake,
  }) => NetworkFeatureSettings(
    disableQuic: disableQuic ?? this.disableQuic,
    smartAutoStop: smartAutoStop ?? this.smartAutoStop,
    smartAutoStopNetworks: smartAutoStopNetworks ?? this.smartAutoStopNetworks,
    overrideSniffer: overrideSniffer ?? this.overrideSniffer,
    snifferEnabled: snifferEnabled ?? this.snifferEnabled,
    overrideNtp: overrideNtp ?? this.overrideNtp,
    ntpEnabled: ntpEnabled ?? this.ntpEnabled,
    ntpServer: ntpServer ?? this.ntpServer,
    keepAwake: keepAwake ?? this.keepAwake,
  );

  (bool, bool, bool, bool, bool, String) get profileOptions => (
    disableQuic,
    overrideSniffer,
    snifferEnabled,
    overrideNtp,
    ntpEnabled,
    ntpServer,
  );
}
