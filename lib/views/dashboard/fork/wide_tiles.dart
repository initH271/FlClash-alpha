import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

import 'fork_tiles.dart';

/// Upstream's wide grid is hard-coded and never reads the saved list, so this
/// scroll view around it adds the saved fork tiles below.
class ForkTilesScrollView extends ConsumerWidget {
  const ForkTilesScrollView({
    super.key,
    required this.platform,
    required this.gap,
    required this.tilesPadding,
    this.physics,
    this.padding,
    required this.child,
  });

  final SupportPlatform platform;
  final double gap;
  final EdgeInsetsGeometry tilesPadding;
  final ScrollPhysics? physics;
  final EdgeInsetsGeometry? padding;
  final Widget child;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final saved = ref.watch(
      dashboardStateProvider.select((state) => state.dashboardWidgets),
    );
    final tiles = [
      for (final widget in saved)
        if (isForkTile(widget) && widget.platforms.contains(platform)) widget,
    ];
    return SingleChildScrollView(
      physics: physics,
      padding: padding,
      child: tiles.isEmpty
          ? child
          : Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                child,
                Padding(
                  padding: tilesPadding,
                  child: _ForkTilesColumns(tiles: tiles, gap: gap),
                ),
              ],
            ),
    );
  }
}

/// Independent columns, so a tile growing in one opens no hole in the other.
class _ForkTilesColumns extends StatelessWidget {
  const _ForkTilesColumns({required this.tiles, required this.gap});

  final List<DashboardWidget> tiles;
  final double gap;

  @override
  Widget build(BuildContext context) {
    Widget column(int remainder) => Expanded(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        spacing: gap,
        children: [
          for (final (index, tile) in tiles.indexed)
            if (index % 2 == remainder)
              RepaintBoundary(
                key: ValueKey(tile),
                child: forkTileOf(tile).card(),
              ),
        ],
      ),
    );
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      spacing: gap,
      children: [column(0), column(1)],
    );
  }
}
