import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/state.dart';
import 'package:fl_clash/views/dashboard/dashboard.dart';
import 'package:fl_clash/views/dashboard/widget_registry.dart';
import 'package:fl_clash/views/dashboard/widgets/start_button.dart';
import 'package:fl_clash/views/profiles/profiles.dart';
import 'package:fl_clash/views/proxies/card.dart';
import 'package:fl_clash/widgets/widgets.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../helpers/test_app.dart';
import '../helpers/test_profiles.dart';

void main() {
  testWidgets('content scrolls behind chrome without covering its actions', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(320, 700);
    tester.view.devicePixelRatio = 1;
    tester.view.padding = const FakeViewPadding(top: 24, bottom: 24);
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.view.resetPadding);
    var actionCount = 0;
    var rowCount = 0;
    await tester.pumpWidget(
      TestApp(
        child: CommonScaffold(
          title: 'Content',
          floatingChrome: true,
          actions: [
            IconButton(
              tooltip: 'Edit',
              onPressed: () => actionCount++,
              icon: const Icon(Icons.edit),
            ),
          ],
          floatingActionButton: const SizedBox.shrink(),
          body: Builder(
            builder: (context) => ListView(
              padding: EdgeInsets.only(
                top: 16 + ContentStyleScope.of(context)!.topInset,
              ),
              children: [
                for (var index = 0; index < 15; index++)
                  ListTile(
                    key: ValueKey(index),
                    title: Text('Row $index'),
                    onTap: () => rowCount++,
                  ),
              ],
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    final header = find.byType(AppBar);
    expect(
      tester.getTopLeft(find.byKey(const ValueKey(0))).dy,
      tester.getBottomLeft(header).dy + 24,
    );
    await tester.drag(find.byType(ListView), const Offset(0, -50));
    await tester.pumpAndSettle();
    expect(
      tester.getTopLeft(find.byKey(const ValueKey(0))).dy,
      lessThan(tester.getBottomLeft(header).dy),
    );
    await tester.tap(find.byTooltip('Edit'));
    await tester.pumpAndSettle();
    expect(actionCount, 1);
    expect(rowCount, 0);
    expect(tester.takeException(), isNull);
  });

  testWidgets('effects can be disabled without removing primary actions', (
    tester,
  ) async {
    var count = 0;
    await tester.pumpWidget(
      TestApp(
        child: CommonScaffold(
          title: 'Content',
          floatingChrome: true,
          effectsEnabled: false,
          floatingActionButton: FloatingActionButton(
            onPressed: () => count++,
            child: const Icon(Icons.add),
          ),
          body: const SizedBox(),
        ),
      ),
    );
    await tester.pumpAndSettle();
    for (final filter in tester.widgetList<BackdropFilter>(
      find.byType(BackdropFilter),
    )) {
      expect(filter.enabled, isFalse);
    }
    await tester.tap(find.byType(FloatingActionButton));
    expect(count, 1);
    expect(tester.takeException(), isNull);
  });

  testWidgets('outgoing pages stop sampling and resume on return', (
    tester,
  ) async {
    var active = true;
    late StateSetter update;
    await tester.pumpWidget(
      TestApp(
        child: StatefulBuilder(
          builder: (context, setState) {
            update = setState;
            return PageActivityScope(
              isActive: active,
              child: const CommonScaffold(
                title: 'Content',
                floatingChrome: true,
                body: SizedBox(),
              ),
            );
          },
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(
      tester.widget<BackdropFilter>(find.byType(BackdropFilter)).enabled,
      isTrue,
    );
    update(() => active = false);
    await tester.pumpAndSettle();
    expect(
      tester.widget<BackdropFilter>(find.byType(BackdropFilter)).enabled,
      isFalse,
    );
    update(() => active = true);
    await tester.pumpAndSettle();
    expect(
      tester.widget<BackdropFilter>(find.byType(BackdropFilter)).enabled,
      isTrue,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'inline start keeps the configured grid and suppresses duplicate FAB',
    (tester) async {
      const entries = [
        DashboardWidget.startButton,
        DashboardWidget.connectionsCount,
      ];
      final container = ProviderContainer(
        overrides: [
          profilesProvider.overrideWith(
            () => TestProfiles(const [
              Profile(id: 1, autoUpdateDuration: Duration.zero),
            ]),
          ),
          dashboardStateProvider.overrideWithValue(
            const DashboardState(dashboardWidgets: entries),
          ),
        ],
      );
      addTearDown(container.dispose);
      globalState.container = container;
      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: const TestApp(child: DashboardView()),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.byType(StartButton), findsOneWidget);
      expect(
        tester.widget<Scaffold>(find.byType(Scaffold)).floatingActionButton,
        isNull,
      );
      expect(
        tester.widget<Grid>(find.byType(Grid)).children,
        entries.map((entry) => entry.widget).toList(),
      );
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets('proxy selection has a mark and selected semantics', (
    tester,
  ) async {
    for (final selected in [true, false]) {
      await tester.pumpWidget(
        TestApp(
          wrapInProviderScope: true,
          overrides: [
            profilesProvider.overrideWith(
              () => TestProfiles(const [
                Profile(id: 1, autoUpdateDuration: Duration.zero),
              ]),
            ),
            currentProfileIdProvider.overrideWithBuild((_, _) => 1),
            selectedProxyNameProvider(
              'Group',
            ).overrideWithValue(selected ? 'Node' : 'Other'),
          ],
          child: const ContentStyleScope(
            child: Center(
              child: SizedBox(
                width: 180,
                height: 100,
                child: ProxyCard(
                  groupName: 'Group',
                  proxy: Proxy(name: 'Node', type: 'VLESS'),
                  groupType: GroupType.Selector,
                  type: ProxyCardType.shrink,
                  testUrl: null,
                ),
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.byIcon(Icons.check_circle),
        selected ? findsOneWidget : findsNothing,
      );
      expect(
        find.byWidgetPredicate(
          (widget) =>
              widget is Semantics && widget.properties.selected == selected,
        ),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    }
    await tester.pumpWidget(const SizedBox());
    await tester.pump();
  });

  testWidgets('profile selection leaves its overflow menu reachable', (
    tester,
  ) async {
    int? selected;
    await tester.pumpWidget(
      TestApp(
        wrapInProviderScope: true,
        child: StatefulBuilder(
          builder: (context, setState) => ContentStyleScope(
            child: Scaffold(
              body: ProfileItem(
                profile: const Profile(
                  id: 1,
                  label: 'Profile',
                  autoUpdateDuration: Duration.zero,
                ),
                groupValue: selected,
                onChanged: (value) => setState(() => selected = value),
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Profile'));
    await tester.pumpAndSettle();
    expect(selected, 1);
    expect(find.byIcon(Icons.check_circle), findsOneWidget);
    await tester.tap(find.byIcon(Icons.more_vert));
    await tester.pumpAndSettle();
    expect(find.byType(CommonPopupMenu), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
