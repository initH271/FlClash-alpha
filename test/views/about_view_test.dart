import 'package:fl_clash/state.dart';
import 'package:fl_clash/views/about.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:package_info_plus/package_info_plus.dart';

import '../helpers/test_app.dart';

void main() {
  testWidgets(
    'about credits the maintainer and exposes both project channels',
    (tester) async {
      globalState.packageInfo = PackageInfo(
        appName: 'FlClash',
        packageName: 'com.follow.clash.dev',
        version: '0.8.97',
        buildNumber: '42',
      );
      tester.view.physicalSize = const Size(1200, 1800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await tester.pumpWidget(
        const TestApp(
          wrapInProviderScope: true,
          locale: Locale('en'),
          child: AboutView(),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Aharon'), findsOneWidget);
      expect(
        tester
            .widget<CircleAvatar>(find.byType(CircleAvatar).first)
            .foregroundImage,
        const AssetImage('assets/images/avatar/aharon.png'),
      );
      expect(find.textContaining('initH271'), findsNothing);
      expect(find.textContaining('· GitHub'), findsOneWidget);
      expect(find.textContaining('· CNB'), findsOneWidget);
      expect(find.text('FlClash · chen08209'), findsOneWidget);
      expect(find.text('0.8.97 (42)'), findsOneWidget);
      expect(find.text('June2'), findsOneWidget);
      expect(find.text('Arue'), findsOneWidget);
    },
  );
}

