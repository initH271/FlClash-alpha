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
      child: FloatingActionButton(
        heroTag: null,
        splashColor: Colors.transparent,
        tooltip: context.appLocalizations.delayTest,
        onPressed: isTesting ? null : onPressed,
        child: isTesting
            ? const _ChargingBolt()
            : const GlyphIcon(AppGlyphs.bolt, fill: 1),
      ),
    );
  }
}

/// The idle bolt filling from below and fading back, or held half full where
/// animations are off.
class _ChargingBolt extends StatefulWidget {
  const _ChargingBolt();

  @override
  State<_ChargingBolt> createState() => _ChargingBoltState();
}

class _ChargingBoltState extends State<_ChargingBolt>
    with SingleTickerProviderStateMixin {
  static const _filling = Interval(0, 0.7, curve: Curves.easeInOut);
  static const _fading = Interval(0.7, 1);

  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1200),
  );

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (context.disableAnimations) {
      _controller.stop();
    } else if (!_controller.isAnimating) {
      _controller.repeat();
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final color = IconTheme.of(context).color!;
    final dim = color.withValues(alpha: 0.3);
    final isStill = context.disableAnimations;
    return RepaintBoundary(
      child: AnimatedBuilder(
        animation: _controller,
        builder: (_, child) {
          final progress = _controller.value;
          final level = isStill ? 0.5 : _filling.transform(progress);
          final lit = isStill
              ? color
              : Color.lerp(color, dim, _fading.transform(progress))!;
          return ShaderMask(
            blendMode: BlendMode.srcIn,
            shaderCallback: (bounds) => LinearGradient(
              begin: Alignment.bottomCenter,
              end: Alignment.topCenter,
              colors: [lit, lit, dim, dim],
              stops: [0, level, level, 1],
            ).createShader(bounds),
            child: child,
          );
        },
        child: const GlyphIcon(AppGlyphs.bolt, fill: 1),
      ),
    );
  }
}
