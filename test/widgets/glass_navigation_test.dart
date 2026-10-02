import 'package:fl_clash/widgets/glass.dart';
import 'package:fl_clash/widgets/glass_navigation.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

const destinations = [
  NavigationDestination(icon: Icon(Icons.home), label: 'Home', tooltip: ''),
  NavigationDestination(
    icon: Icon(Icons.folder),
    label: 'Profiles',
    tooltip: '',
  ),
  NavigationDestination(
    icon: Icon(Icons.settings),
    label: 'Settings',
    tooltip: '',
  ),
];
Widget frame(
  ValueChanged<int> onSelected, {
  int index = 0,
  bool reduced = false,
  bool highContrast = false,
  TextDirection direction = TextDirection.ltr,
  double scale = 1,
  bool effects = true,
  List<NavigationDestination> items = destinations,
}) => MaterialApp(
  home: MediaQuery(
    data: MediaQueryData(
      disableAnimations: reduced,
      highContrast: highContrast,
      textScaler: TextScaler.linear(scale),
    ),
    child: Directionality(
      textDirection: direction,
      child: Scaffold(
        body: Center(
          child: SizedBox(
            width: 304,
            child: GlassNavigationBar(
              destinations: items,
              selectedIndex: index,
              onSelected: onSelected,
              effectsEnabled: effects,
            ),
          ),
        ),
      ),
    ),
  ),
);
void main() {
  testWidgets(
    'long press previews without changing the route, commits once on release',
    (tester) async {
      final selected = <int>[];
      await tester.pumpWidget(frame(selected.add));
      final bar = tester.getRect(find.byType(GlassNavigationBar));
      final gesture = await tester.startGesture(
        Offset(bar.left + bar.width / 6, bar.center.dy),
      );
      await tester.pump(const Duration(milliseconds: 600));
      await gesture.moveTo(Offset(bar.right - bar.width / 6, bar.center.dy));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));
      expect(selected, isEmpty);
      expect(
        tester.widget<NavigationBar>(find.byType(NavigationBar)).selectedIndex,
        0,
      );
      expect(
        tester.getCenter(find.byKey(const ValueKey('glass-tab-indicator'))).dx,
        closeTo(bar.right - bar.width / 6, 2),
      );
      await gesture.up();
      await tester.pumpAndSettle();
      expect(selected, [2]);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets('cancel and outside release discard the preview', (tester) async {
    final selected = <int>[];
    await tester.pumpWidget(frame(selected.add));
    final bar = tester.getRect(find.byType(GlassNavigationBar));
    final gesture = await tester.startGesture(bar.center);
    await tester.pump(const Duration(milliseconds: 600));
    await gesture.moveTo(Offset(bar.right - 12, bar.center.dy));
    await gesture.cancel();
    await tester.pumpAndSettle();
    expect(selected, isEmpty);
    expect(
      tester.getCenter(find.byKey(const ValueKey('glass-tab-indicator'))).dx,
      closeTo(bar.left + bar.width / 6, .1),
    );
    final outside = await tester.startGesture(bar.center);
    await tester.pump(const Duration(milliseconds: 600));
    await outside.moveTo(Offset(bar.right + 80, bar.center.dy));
    await outside.up();
    await tester.pumpAndSettle();
    expect(selected, isEmpty);
  });
  testWidgets('an external route change invalidates a held gesture', (
    tester,
  ) async {
    final selected = <int>[];
    await tester.pumpWidget(frame(selected.add));
    final gesture = await tester.startGesture(
      tester.getCenter(find.byType(GlassNavigationBar)),
    );
    await tester.pump(const Duration(milliseconds: 600));
    await tester.pumpWidget(frame(selected.add, index: 2));
    await gesture.up();
    await tester.pumpAndSettle();
    expect(selected, isEmpty);
    expect(
      tester.widget<NavigationBar>(find.byType(NavigationBar)).selectedIndex,
      2,
    );
  });
  testWidgets('same-count destination replacement invalidates the preview', (
    tester,
  ) async {
    final selected = <int>[];
    await tester.pumpWidget(frame(selected.add));
    final gesture = await tester.startGesture(
      tester.getCenter(find.byType(GlassNavigationBar)),
    );
    await tester.pump(const Duration(milliseconds: 600));
    await tester.pumpWidget(
      frame(
        selected.add,
        items: [destinations[0], destinations[2], destinations[1]],
      ),
    );
    await gesture.up();
    await tester.pumpAndSettle();
    expect(selected, isEmpty);
    expect(
      tester.widget<NavigationBar>(find.byType(NavigationBar)).selectedIndex,
      0,
    );
  });
  testWidgets('RTL drag selects the visually matching destination', (
    tester,
  ) async {
    final selected = <int>[];
    await tester.pumpWidget(frame(selected.add, direction: TextDirection.rtl));
    final bar = tester.getRect(find.byType(GlassNavigationBar));
    final gesture = await tester.startGesture(
      Offset(bar.left + 20, bar.center.dy),
    );
    await tester.pump(const Duration(milliseconds: 600));
    await gesture.up();
    await tester.pumpAndSettle();
    expect(selected, [2]);
  });
  testWidgets(
    'tap and keyboard retain Material semantics with reduced motion',
    (tester) async {
      final selected = <int>[];
      final semantics = tester.ensureSemantics();
      await tester.pumpWidget(frame(selected.add, reduced: true, scale: 1.8));
      expect(
        tester.getSize(find.byType(NavigationBar)).height,
        greaterThan(56),
      );
      await tester.tap(find.byIcon(Icons.folder));
      await tester.pumpAndSettle();
      expect(selected, [1]);
      expect(
        tester.getSemantics(find.text('Home')),
        matchesSemantics(
          label: 'Home\nTab 1 of 3',
          isSelected: true,
          hasSelectedState: true,
          isButton: true,
          hasEnabledState: true,
          isEnabled: true,
          isFocusable: true,
          hasFocusAction: true,
          hasTapAction: true,
        ),
      );
      await tester.sendKeyEvent(LogicalKeyboardKey.tab);
      await tester.sendKeyEvent(LogicalKeyboardKey.enter);
      await tester.pumpAndSettle();
      expect(selected.length, greaterThan(1));
      expect(tester.takeException(), isNull);
      semantics.dispose();
    },
  );
  testWidgets('high contrast and low effects disable backdrop work', (
    tester,
  ) async {
    await tester.pumpWidget(frame((_) {}, highContrast: true));
    expect(
      tester
          .widget<BackdropFilter>(
            find.descendant(
              of: find.byType(GlassSurface),
              matching: find.byType(BackdropFilter),
            ),
          )
          .enabled,
      false,
    );
    await tester.pumpWidget(frame((_) {}, effects: false));
    expect(
      tester.widget<BackdropFilter>(find.byType(BackdropFilter)).enabled,
      false,
    );
  });
}
