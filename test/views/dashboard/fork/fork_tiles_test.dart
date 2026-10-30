import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/models/models.dart';
import 'package:fl_clash/views/dashboard/fork/fork_tiles.dart';
import 'package:fl_clash/views/dashboard/widget_registry.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';

import '../../../helpers/test_app.dart';

/// Saved layouts store these names; a shipped one is never renamed.
const shippedForkTileNames = <String>{};

void main() {
  final forkValues = DashboardWidget.values.where(isForkTile).toSet();

  test('every fork value has a fork tile, and only fork values do', () {
    expect(forkTiles.keys.toSet(), forkValues);
    expect(forkValues.map((value) => value.name), shippedForkTileNames);
  });

  test('fork values sit in one block ahead of upstream values', () {
    final names = DashboardWidget.values.map((value) => value.name).toList();
    final upstreamStart = names.indexWhere(
      (name) => !name.startsWith(forkTilePrefix),
    );
    expect(names.take(upstreamStart).toSet(), shippedForkTileNames);
    expect(
      names.skip(upstreamStart).where((n) => n.startsWith(forkTilePrefix)),
      isEmpty,
    );
  });

  test('an upstream value never reaches the fork dispatch', () {
    for (final value in DashboardWidget.values.where((v) => !isForkTile(v))) {
      expect(() => forkTileOf(value), throwsStateError, reason: value.name);
    }
  });

  testWidgets('every value resolves a card, a glyph and a label', (
    tester,
  ) async {
    late BuildContext context;
    await tester.pumpWidget(
      TestApp(
        child: Builder(
          builder: (inner) {
            context = inner;
            return const SizedBox.shrink();
          },
        ),
      ),
    );
    for (final value in DashboardWidget.values) {
      expect(value.card, isA<Widget>(), reason: value.name);
      expect(value.glyph, isNotNull, reason: value.name);
      expect(value.label(context), isNotEmpty, reason: value.name);
    }
    for (final value in forkValues) {
      expect(
        value.label(context),
        forkTileOf(value).label(context.appLocalizations),
      );
    }
  });

  test('fork tiles stay out of the default layouts', () {
    expect(defaultDashboardWidgets.where(isForkTile), isEmpty);
    expect(platformDefaultDashboardWidgets.where(isForkTile), isEmpty);
  });

  test('a saved fork name this build does not know is dropped', () {
    expect(dashboardWidgetsFromJson(['currentOutbound', 'forkRetiredTile']), [
      DashboardWidget.currentOutbound,
    ]);
  });
}
