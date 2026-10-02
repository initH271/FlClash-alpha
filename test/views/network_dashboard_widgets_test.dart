import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/views/dashboard/widget_registry.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_test/flutter_test.dart';

import '../helpers/test_app.dart';

class _Profiles extends Profiles {
  @override
  List<Profile> build() => const [];
}

void main() {
  const entries = [
    DashboardWidget.networkSpeedSmall,
    DashboardWidget.connectionsCount,
    DashboardWidget.ipv6Switch,
    DashboardWidget.wakelockSwitch,
    DashboardWidget.dnsOverride,
    DashboardWidget.snifferOverride,
    DashboardWidget.ntpOverride,
    DashboardWidget.providersInfo,
    DashboardWidget.fcmStatus,
    DashboardWidget.onlinePanel,
    DashboardWidget.mediaUnlock,
    DashboardWidget.mediaUnlockSmall,
    DashboardWidget.startButton,
  ];
  for (final entry in entries) {
    testWidgets('${entry.name} renders in a compact dashboard cell', (
      tester,
    ) async {
      await tester.pumpWidget(
        TestApp(
          wrapInProviderScope: true,
          overrides: [profilesProvider.overrideWith(_Profiles.new)],
          homeBuilder: (child) => Scaffold(body: child),
          child: Align(
            alignment: Alignment.topLeft,
            child: SizedBox(width: 220, child: entry.widget.child),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      await tester.pump();
    });
  }
}
