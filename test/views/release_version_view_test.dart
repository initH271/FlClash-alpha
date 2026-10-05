import 'package:fl_clash/state.dart';
import 'package:fl_clash/views/about.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:package_info_plus/package_info_plus.dart';

import '../helpers/test_app.dart';

void main() {
  setUpAll(() {
    globalState.packageInfo = PackageInfo(
      appName: 'FlClash-alpha',
      packageName: 'com.follow.clash.dev',
      version: '0.8.98-alpha.13',
      buildNumber: '2026094013',
    );
  });

  Future<void> mount(WidgetTester tester, DateTime? date) async {
    tester.view.physicalSize = const Size(1200, 1800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(
      TestApp(
        wrapInProviderScope: true,
        locale: const Locale('en'),
        child: AboutView(releaseDateLoader: () async => date),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets(
    'about separates fork version, upstream, date and build details',
    (tester) async {
      await mount(tester, DateTime.utc(2026, 10, 6));
      expect(find.text('0.8.98-alpha.13'), findsOneWidget);
      expect(find.text('Upstream version: 0.8.98'), findsOneWidget);
      expect(find.text('Release date: 2026-10-06'), findsOneWidget);
      expect(find.text('2026094013'), findsNothing);
      await tester.tap(find.text('Version details'));
      await tester.pumpAndSettle();
      expect(find.text('Internal build number'), findsOneWidget);
      expect(find.text('2026094013'), findsOneWidget);
    },
  );

  testWidgets(
    'missing publication date keeps version usable without inventing a date',
    (tester) async {
      await mount(tester, null);
      expect(find.text('0.8.98-alpha.13'), findsOneWidget);
      expect(find.text('Release date: Unknown'), findsOneWidget);
    },
  );
}
