import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/views/config/log_retention.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import '../helpers/test_app.dart';

Future<ProviderContainer> mount(WidgetTester tester) async {
  final c = ProviderContainer(
    overrides: [
      viewSizeProvider.overrideWithBuild((_, _) => const Size(800, 600)),
    ],
  );
  addTearDown(c.dispose);
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: c,
      child: const TestApp(child: Scaffold(body: LogRetentionItem())),
    ),
  );
  await tester.pumpAndSettle();
  return c;
}

void main() {
  testWidgets('default, presets and a custom positive period persist', (
    tester,
  ) async {
    final c = await mount(tester);
    expect(c.read(appSettingProvider).logRetentionDays, 14);
    await tester.tap(find.text('Core log retention'));
    await tester.pumpAndSettle();
    expect(find.text('1 day'), findsOneWidget);
    expect(find.text('7 days'), findsOneWidget);
    expect(find.text('14 days (Default)'), findsOneWidget);
    expect(find.text('30 days'), findsOneWidget);
    await tester.tap(find.text('7 days'));
    await tester.pumpAndSettle();
    expect(c.read(appSettingProvider).logRetentionDays, 7);
    await tester.tap(find.text('Core log retention'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Custom'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextFormField), '21');
    await tester.tap(find.text('Submit'));
    await tester.pumpAndSettle();
    expect(c.read(appSettingProvider).logRetentionDays, 21);
    final restored = AppSettingProps.fromJson(
      c.read(appSettingProvider).toJson(),
    );
    expect(restored.logRetentionDays, 21);
  });
  testWidgets(
    'invalid custom input and cancellation do not change saved period',
    (tester) async {
      final c = await mount(tester);
      await tester.tap(find.text('Core log retention'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Custom'));
      await tester.pumpAndSettle();
      for (final input in ['0', '-1', 'bad', '36501']) {
        await tester.enterText(find.byType(TextFormField), input);
        await tester.tap(find.text('Submit'));
        await tester.pumpAndSettle();
        expect(
          find.text('Enter a whole number of days between 1 and 36500'),
          findsOneWidget,
        );
        expect(c.read(appSettingProvider).logRetentionDays, 14);
      }
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(c.read(appSettingProvider).logRetentionDays, 14);
    },
  );
}
