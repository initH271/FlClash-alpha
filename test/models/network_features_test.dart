import 'dart:convert';

import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/views/dashboard/widget_registry.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('legacy config keeps its layout and disables new automation', () {
    final config = Config.fromJson({
      'appSettingProps': {
        'dashboardWidgets': ['networkSpeed', 'intranetIp'],
      },
    });
    expect(config.appSettingProps.dashboardWidgets, [
      DashboardWidget.networkSpeed,
      DashboardWidget.intranetIp,
    ]);
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
    expect(DashboardWidget.values.map((item) => item.widget).length, 23);
  });
}
