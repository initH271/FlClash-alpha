import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/views/network_features.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../helpers/test_app.dart';

void main() {
  testWidgets(
    'network settings validate and save their input and dependent toggles',
    (tester) async {
      await tester.pumpWidget(
        TestApp(
          locale: const Locale('zh', 'CN'),
          wrapInProviderScope: true,
          homeBuilder: (child) => Scaffold(body: child),
          child: const NetworkFeaturesView(),
        ),
      );
      await tester.pumpAndSettle();
      final container = ProviderScope.containerOf(
        tester.element(find.byType(NetworkFeaturesView)),
      );
      final l = tester
          .element(find.byType(NetworkFeaturesView))
          .appLocalizations;
      await tester.enterText(find.byType(TextFormField).first, 'invalid');
      await tester.testTextInput.receiveAction(TextInputAction.done);
      await tester.pump();
      expect(
        container.read(networkFeaturesProvider).smartAutoStopNetworks,
        isEmpty,
      );
      expect(find.textContaining('请输入有效'), findsOneWidget);
      const rules = '192.168.1.0/24,\ngateway:192.168.1.1';
      await tester.enterText(find.byType(TextFormField).first, rules);
      await tester.testTextInput.receiveAction(TextInputAction.done);
      await tester.pump();
      expect(
        container.read(networkFeaturesProvider).smartAutoStopNetworks,
        rules,
      );
      Future<void> toggle(String label) async {
        final tile = find.widgetWithText(SwitchListTile, label);
        await tester.ensureVisible(tile);
        await tester.pumpAndSettle();
        await tester.tap(tile);
        await tester.pumpAndSettle();
      }

      expect(
        tester
            .widget<SwitchListTile>(
              find.widgetWithText(SwitchListTile, l.sniffer),
            )
            .onChanged,
        isNull,
      );
      await toggle(l.smartAutoStop);
      await toggle(l.disableQuic);
      await toggle(l.snifferOverride);
      await toggle(l.sniffer);
      await toggle(l.ntpOverride);
      await toggle('NTP');
      final ntp = find.byType(TextFormField).last;
      await tester.ensureVisible(ntp);
      await tester.enterText(ntp, 'pool.ntp.org');
      await tester.testTextInput.receiveAction(TextInputAction.done);
      await tester.pump();
      final settings = container.read(networkFeaturesProvider);
      expect(settings.smartAutoStop, isTrue);
      expect(settings.disableQuic, isTrue);
      expect(settings.overrideSniffer, isTrue);
      expect(settings.snifferEnabled, isFalse);
      expect(settings.overrideNtp, isTrue);
      expect(settings.ntpEnabled, isFalse);
      expect(settings.ntpServer, 'pool.ntp.org');
      if (system.isDesktop) {
        await toggle(l.keepAwake);
        expect(container.read(networkFeaturesProvider).keepAwake, isTrue);
      }
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('multiline rules require an explicit save after physical Enter', (
    tester,
  ) async {
    await tester.pumpWidget(
      TestApp(
        locale: const Locale('zh', 'CN'),
        wrapInProviderScope: true,
        homeBuilder: (child) => Scaffold(body: child),
        child: const NetworkFeaturesView(),
      ),
    );
    await tester.pumpAndSettle();
    final container = ProviderScope.containerOf(
      tester.element(find.byType(NetworkFeaturesView)),
    );
    await tester.enterText(find.byType(TextFormField).first, '10.20.0.0/16');
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pump();
    expect(
      container.read(networkFeaturesProvider).smartAutoStopNetworks,
      isEmpty,
    );
    await tester.ensureVisible(
      find.byKey(const ValueKey('save-network-rules')),
    );
    await tester.tap(find.byKey(const ValueKey('save-network-rules')));
    await tester.pumpAndSettle();
    expect(
      container.read(networkFeaturesProvider).smartAutoStopNetworks,
      '10.20.0.0/16',
    );
    await tester.enterText(find.byType(TextFormField).first, 'invalid');
    await tester.tap(find.byKey(const ValueKey('save-network-rules')));
    await tester.pumpAndSettle();
    expect(
      container.read(networkFeaturesProvider).smartAutoStopNetworks,
      '10.20.0.0/16',
    );
    expect(find.textContaining('请输入有效'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
