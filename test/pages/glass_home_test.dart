import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/pages/home.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/state.dart';
import 'package:fl_clash/widgets/widgets.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../helpers/test_app.dart';

void main() {
  for (final width in [320.0, 500.0]) {
    testWidgets(
      'floating home reserves safe area and uncovers keyboard at $width',
      (tester) async {
        tester.view.physicalSize = Size(width, 844);
        tester.view.devicePixelRatio = 1;
        tester.view.padding = const FakeViewPadding(bottom: 24);
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        addTearDown(tester.view.resetPadding);
        addTearDown(tester.view.resetViewInsets);
        final container = ProviderContainer(
          overrides: [
            navigationItemsStateProvider.overrideWithValue(
              NavigationItemsState(
                value: [
                  NavigationItem(
                    icon: const Icon(Icons.home),
                    label: PageLabel.dashboard,
                    builder: (_) => const _ScrollPage(),
                  ),
                  NavigationItem(
                    icon: const Icon(Icons.folder),
                    label: PageLabel.profiles,
                    builder: (_) => const SizedBox(),
                  ),
                  NavigationItem(
                    icon: const Icon(Icons.settings),
                    label: PageLabel.tools,
                    builder: (_) => const SizedBox(),
                  ),
                ],
              ),
            ),
          ],
        );
        addTearDown(container.dispose);
        globalState.container = container;
        container.read(viewSizeProvider.notifier).value = Size(width, 844);
        await tester.pumpWidget(
          UncontrolledProviderScope(
            container: container,
            child: const TestApp(includeNavigatorKey: false, child: HomePage()),
          ),
        );
        await tester.pumpAndSettle();
        final bar = tester.getRect(find.byType(NavigationBar));
        expect(bar.width, lessThanOrEqualTo(344));
        expect(bar.bottom, 844 - 24 - 8);
        final page = tester.element(find.byType(_ScrollPage));
        expect(BottomInsetScope.of(page), 56 + 16 + 24);
        await tester.drag(find.byType(ListView), const Offset(0, -2200));
        await tester.pumpAndSettle();
        expect(
          tester.getRect(find.text('last accessible row')).bottom,
          lessThan(bar.top),
        );
        tester.view.viewInsets = const FakeViewPadding(bottom: 300);
        await tester.pumpAndSettle();
        expect(find.byType(NavigationBar), findsNothing);
        expect(BottomInsetScope.of(page), 0);
        tester.view.resetViewInsets();
        await tester.pumpAndSettle();
        expect(find.byType(NavigationBar), findsOneWidget);
        expect(tester.takeException(), isNull);
      },
    );
  }
}

class _ScrollPage extends StatelessWidget {
  const _ScrollPage();
  @override
  Widget build(BuildContext context) => CommonScaffold(
    title: 'Scrollable page',
    body: ListView(
      padding: EdgeInsets.only(bottom: BottomInsetScope.of(context) + 16),
      children: [
        for (var index = 0; index < 20; index++)
          SizedBox(height: 60, child: Text('row $index')),
        const SizedBox(height: 40, child: Text('last accessible row')),
      ],
    ),
  );
}
