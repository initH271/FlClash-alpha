import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/views/dashboard/widget_registry.dart';
import 'package:fl_clash/views/dashboard/widgets/extended_widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_test/flutter_test.dart';

import '../helpers/test_app.dart';

class _Profiles extends Profiles {
  @override
  List<Profile> build() => const [];
}

void main() {
  for (final small in [false, true]) {
    testWidgets('service card scrolls to the last result (small: $small)', (
      tester,
    ) async {
      await tester.pumpWidget(
        TestApp(
          wrapInProviderScope: true,
          homeBuilder: (child) => Scaffold(body: child),
          child: Align(
            alignment: Alignment.topLeft,
            child: SizedBox(
              width: small ? 180 : 360,
              child: MediaUnlockCard(small: small),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      final container = ProviderScope.containerOf(
        tester.element(find.byType(MediaUnlockCard)),
      );
      container
          .read(networkFeaturesProvider.notifier)
          .update(
            (settings) => settings.copyWith(
              serviceChecks: settings.serviceChecks.copyWith(
                platforms: MediaPlatform.values,
              ),
            ),
          );
      container
          .read(serviceCheckResultsProvider.notifier)
          .add(
            MediaUnlockResult(
              platform: MediaPlatform.values.last,
              status: MediaUnlockStatus.unlocked,
              region: 'JP',
            ),
          );
      await tester.pumpAndSettle();
      final list = find.byKey(const ValueKey('dashboard-service-results'));
      final scrollable = find.descendant(
        of: list,
        matching: find.byType(Scrollable),
      );
      expect(find.text(MediaPlatform.values.last.defaultName), findsNothing);
      await tester.scrollUntilVisible(
        find.byKey(ValueKey(MediaPlatform.values.last)),
        100,
        scrollable: scrollable,
        maxScrolls: 60,
      );
      expect(find.text(MediaPlatform.values.last.defaultName), findsOneWidget);
      expect(find.textContaining('JP'), findsOneWidget);
      expect(tester.takeException(), isNull);
      // A drag inside the card must not activate its tap-to-open sheet.
      expect(find.byType(CheckboxListTile), findsNothing);
    });
  }

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
