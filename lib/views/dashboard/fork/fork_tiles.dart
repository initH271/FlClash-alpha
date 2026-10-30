import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/l10n/l10n.dart';
import 'package:fl_clash/ui/icons/icons.dart';
import 'package:material_ui/material_ui.dart';

/// Upstream's registry hands every value it has no arm for to [forkTileOf].
class ForkTile {
  const ForkTile({
    required this.card,
    required this.glyph,
    required this.label,
  });

  final Widget Function() card;
  final Glyph glyph;
  final String Function(AppLocalizations appLocalizations) label;
}

const forkTilePrefix = 'fork';

final Map<DashboardWidget, ForkTile> forkTiles = {};

bool isForkTile(DashboardWidget widget) =>
    widget.name.startsWith(forkTilePrefix);

ForkTile forkTileOf(DashboardWidget widget) {
  final tile = forkTiles[widget];
  if (tile == null) {
    throw StateError('No fork tile registered for ${widget.name}');
  }
  return tile;
}
