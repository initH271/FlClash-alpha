import 'dart:convert';

import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/enum/enum.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('fork-only dashboard widgets are dropped from a legacy config', () {
    final config = Config.fromJson({
      'appSettingProps': {
        'dashboardWidgets': ['networkSpeed', 'mediaUnlock', 'onlinePanel'],
      },
    });
    expect(
      config.appSettingProps.dashboardWidgets,
      contains(DashboardWidget.networkSpeed),
    );
    expect(
      config.appSettingProps.dashboardWidgets.map((item) => item.name),
      isNot(anyOf(contains('mediaUnlock'), contains('onlinePanel'))),
    );
    expect(config.networkProps.networkFeatures.disableQuic, false);
    expect(config.networkProps.networkFeatures.smartAutoStop, false);
  });

  test('new settings and widgets survive a config round trip', () {
    const config = Config(
      themeProps: defaultThemeProps,
      networkProps: NetworkProps(
        networkFeatures: NetworkFeatureSettings(
          disableQuic: true,
          smartAutoStop: true,
          smartAutoStopNetworks: 'gateway:192.168.1.1',
        ),
      ),
      appSettingProps: AppSettingProps(
        dashboardWidgets: DashboardWidget.values,
      ),
    );
    final restored = Config.fromJson(
      jsonDecode(jsonEncode(config)) as Map<String, dynamic>,
    );
    expect(
      restored.networkProps.networkFeatures.toJson(),
      config.networkProps.networkFeatures.toJson(),
    );
    expect(restored.appSettingProps.dashboardWidgets, DashboardWidget.values);
  });
}
