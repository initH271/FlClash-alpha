import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/common/theme.dart';
import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/state.dart';
import 'package:fl_clash/views/dashboard/widget_registry.dart';
import 'package:fl_clash/widgets/grid.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';

import '../helpers/test_app.dart';

class _Profiles extends Profiles {
  @override
  List<Profile> build() => const [
    Profile(id: 1, label: 'Layout test', autoUpdateDuration: Duration.zero),
  ];
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
  for (final width in [320.0, 390.0, 900.0]) {
    for (final scale in [1.0, 1.4]) {
      for (final locale in [const Locale('zh', 'CN'), const Locale('ru')]) {
        testWidgets('dashboard text fits at $width / $scale / $locale', (
          tester,
        ) async {
          tester.view.physicalSize = Size(width, 1300);
          tester.view.devicePixelRatio = 1;
          addTearDown(tester.view.resetPhysicalSize);
          addTearDown(tester.view.resetDevicePixelRatio);
          await tester.pumpWidget(
            TestApp(
              locale: locale,
              setTheme: false,
              wrapInProviderScope: true,
              overrides: [profilesProvider.overrideWith(_Profiles.new)],
              child: Builder(
                builder: (context) {
                  globalState.theme = CommonTheme.of(context, scale);
                  globalState.measure = Measure.of(context, scale);
                  return MediaQuery(
                    data: MediaQuery.of(
                      context,
                    ).copyWith(textScaler: TextScaler.linear(scale)),
                    child: Align(
                      alignment: Alignment.topCenter,
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Grid(
                          crossAxisCount: width - 32 < 480
                              ? 8
                              : width - 32 <= 840
                              ? 12
                              : 16,
                          crossAxisSpacing: 14,
                          mainAxisSpacing: 14,
                          children: entries
                              .map((entry) => entry.widget)
                              .toList(),
                        ),
                      ),
                    ),
                  );
                },
              ),
            ),
          );
          await tester.pumpAndSettle();
          expect(tester.takeException(), isNull);
          for (final element in find.byType(RichText).evaluate()) {
            final paragraph = element.renderObject! as RenderParagraph;
            expect(
              paragraph.size.height + 0.5,
              greaterThanOrEqualTo(
                paragraph.getMinIntrinsicHeight(paragraph.size.width),
              ),
              reason: 'Clipped text: ${paragraph.text.toPlainText()}',
            );
          }
          await tester.pumpWidget(const SizedBox());
          await tester.pump();
        });
      }
    }
  }
  for (final width in [137.0, 175.0]) {
    testWidgets('running dashboard control fits $width at 120 hours', (
      tester,
    ) async {
      await tester.pumpWidget(
        TestApp(
          setTheme: false,
          wrapInProviderScope: true,
          overrides: [
            profilesProvider.overrideWith(_Profiles.new),
            runTimeProvider.overrideWithValue(120 * 60 * 60 * 1000),
            suspendProvider.overrideWithValue(false),
          ],
          child: Builder(
            builder: (context) {
              globalState.theme = CommonTheme.of(context, 1.4);
              globalState.measure = Measure.of(context, 1.4);
              return MediaQuery(
                data: MediaQuery.of(
                  context,
                ).copyWith(textScaler: const TextScaler.linear(1.4)),
                child: Center(
                  child: SizedBox(
                    width: width,
                    child: DashboardWidget.startButton.widget.child,
                  ),
                ),
              );
            },
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      expect(find.text('20:00:00', findRichText: true), findsNothing);
      expect(find.text('120:00:00', findRichText: true), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
      await tester.pump();
    });
  }
}
