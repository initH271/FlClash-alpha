import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/ui/fork/foot_action.dart';
import 'package:fl_clash/ui/icons/icons.dart';
import 'package:fl_clash/widgets/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

/// Floats the delay test over the foot of [child], where a thumb reaches it.
class ProxiesDelayTestFab extends StatelessWidget {
  const ProxiesDelayTestFab({
    super.key,
    required this.onPressed,
    required this.child,
  });

  final VoidCallback onPressed;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return FloatingFootAction(
      action: _DelayTestButton(onPressed: onPressed),
      body: child,
    );
  }
}

class _DelayTestButton extends ConsumerWidget {
  const _DelayTestButton({required this.onPressed});

  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final hasGroups = ref.watch(
      proxiesTabStateProvider.select((state) => state.groups.isNotEmpty),
    );
    if (!hasGroups) {
      return const SizedBox.shrink();
    }
    final isTesting = ref.watch(currentGroupDelayTestingProvider);
    return ElasticPress(
      enabled: !isTesting,
      child: FloatingActionButton.extended(
        heroTag: null,
        splashColor: Colors.transparent,
        onPressed: isTesting ? null : onPressed,
        icon: isTesting
            ? const CommonCircleLoading()
            : const GlyphIcon(AppGlyphs.bolt, fill: 1),
        label: Text(context.appLocalizations.delayTest),
      ),
    );
  }
}
