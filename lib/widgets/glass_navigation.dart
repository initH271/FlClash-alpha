import 'dart:math' as math;

import 'package:fl_clash/common/shape.dart';
import 'package:flutter/physics.dart';
import 'package:material_ui/material_ui.dart';

import 'glass.dart';

/// Keeps Material's focus, keyboard and tab semantics. A drag only previews
/// the capsule; authoritative selection changes once, on a valid release.
class GlassNavigationBar extends StatefulWidget {
  static const double height = 56;
  static const double margin = 8;
  static const double maxWidth = 344;
  static const double _labelSize = 11.5;

  static double heightFor(TextScaler scaler) {
    final scale =
        scaler.clamp(maxScaleFactor: 1.3).scale(_labelSize) / _labelSize;
    return height + math.max(0, scale - 1) * 18;
  }

  final List<NavigationDestination> destinations;
  final int selectedIndex;
  final ValueChanged<int> onSelected;
  final bool effectsEnabled;

  const GlassNavigationBar({
    super.key,
    required this.destinations,
    required this.selectedIndex,
    required this.onSelected,
    this.effectsEnabled = true,
  });

  @override
  State<GlassNavigationBar> createState() => _GlassNavigationBarState();
}

class _GlassNavigationBarState extends State<GlassNavigationBar>
    with TickerProviderStateMixin {
  static const double _indicatorInset = 6;
  static const double _iconSize = 20;
  static const double _iconTopInset = 6;
  static const double _materialIconSlot = 32;
  late final AnimationController _position;
  late final AnimationController _selection;
  bool _pressed = false;
  int? _preview;
  bool get _motion =>
      widget.effectsEnabled && !MediaQuery.disableAnimationsOf(context);

  @override
  void initState() {
    super.initState();
    _position = AnimationController.unbounded(
      vsync: this,
      value: widget.selectedIndex.toDouble(),
    );
    _selection = AnimationController(
      vsync: this,
      value: 1,
      duration: const Duration(milliseconds: 320),
    );
  }

  void _settle() {
    _position.stop();
    _selection.stop();
    _position.value = widget.selectedIndex.toDouble();
    _selection.value = 1;
    _preview = null;
    _pressed = false;
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_motion) _settle();
  }

  @override
  void didUpdateWidget(GlassNavigationBar oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!widget.effectsEnabled) _settle();
    final destinationsChanged =
        oldWidget.destinations.length != widget.destinations.length ||
        List.generate(widget.destinations.length, (index) => index).any(
          (index) =>
              oldWidget.destinations.length <= index ||
              oldWidget.destinations[index].label !=
                  widget.destinations[index].label,
        );
    if (oldWidget.selectedIndex != widget.selectedIndex ||
        destinationsChanged) {
      _preview = null;
      _pressed = false;
      _move(widget.selectedIndex, spring: false);
      if (_motion) _selection.forward(from: 0);
    }
  }

  void _move(int index, {required bool spring}) {
    if (!_motion) {
      _position.value = index.toDouble();
    } else if (spring) {
      _position.animateWith(
        SpringSimulation(
          SpringDescription.withDampingRatio(
            mass: 1,
            stiffness: 1500,
            ratio: .75,
          ),
          _position.value,
          index.toDouble(),
          0,
        ),
      );
    } else {
      _position.animateTo(
        index.toDouble(),
        duration: const Duration(milliseconds: 320),
        curve: Curves.decelerate,
      );
    }
  }

  int _indexAt(Offset local, double width) {
    final index = (local.dx / width * widget.destinations.length).floor();
    final clamped = index.clamp(0, widget.destinations.length - 1);
    return Directionality.of(context) == TextDirection.rtl
        ? widget.destinations.length - 1 - clamped
        : clamped;
  }

  void _cancel() {
    if (!mounted) return;
    setState(() {
      _preview = null;
      _pressed = false;
    });
    _move(widget.selectedIndex, spring: true);
  }

  @override
  void dispose() {
    _position.dispose();
    _selection.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final height = GlassNavigationBar.heightFor(
      MediaQuery.textScalerOf(context),
    );
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: GlassNavigationBar.maxWidth),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final width = constraints.maxWidth;
          final slot = width / widget.destinations.length;
          final indicatorWidth = slot - _indicatorInset * 2;
          const indicatorRadius = AppCorner.xl - _indicatorInset;
          final labelStyle = Theme.of(context).textTheme.labelSmall!.copyWith(
            fontSize: GlassNavigationBar._labelSize,
            fontWeight: FontWeight.w500,
            letterSpacing: 0,
          );
          final textScaler = MediaQuery.textScalerOf(
            context,
          ).clamp(maxScaleFactor: 1.3);
          final compactLabels = widget.destinations.any((destination) {
            final painter = TextPainter(
              text: TextSpan(text: destination.label, style: labelStyle),
              textScaler: textScaler,
              textDirection: Directionality.of(context),
            )..layout();
            final tooWide = painter.width > slot - 8;
            painter.dispose();
            return tooWide;
          });
          return GestureDetector(
            behavior: HitTestBehavior.opaque,
            onLongPressStart: (details) {
              final index = _indexAt(details.localPosition, width);
              setState(() {
                _preview = index;
                _pressed = true;
              });
              _move(index, spring: true);
            },
            onLongPressMoveUpdate: (details) {
              if (_preview == null) return;
              final index = _indexAt(details.localPosition, width);
              if (index == _preview) return;
              setState(() => _preview = index);
              _move(index, spring: true);
            },
            onLongPressEnd: (details) {
              final index = _preview;
              final inside =
                  details.localPosition.dx >= 0 &&
                  details.localPosition.dx <= width &&
                  details.localPosition.dy >= -height &&
                  details.localPosition.dy <= height * 2;
              _cancel();
              if (inside && index != null) widget.onSelected(index);
            },
            onLongPressCancel: _cancel,
            child: Listener(
              onPointerDown: (_) => setState(() => _pressed = true),
              onPointerUp: (_) {
                if (_preview == null) setState(() => _pressed = false);
              },
              onPointerCancel: (_) => _cancel(),
              child: TweenAnimationBuilder<double>(
                tween: Tween(end: _pressed && _motion ? 1.019 : 1),
                duration: _motion
                    ? const Duration(milliseconds: 380)
                    : Duration.zero,
                curve: Curves.easeOutQuint,
                builder: (context, scale, _) => Transform.scale(
                  scale: scale,
                  child: GlassSurface(
                    borderRadius: AppRadius.xl,
                    useSuperellipse: true,
                    refractionEnabled: false,
                    effectsEnabled: widget.effectsEnabled,
                    child: Stack(
                      children: [
                        Positioned.fill(
                          child: IgnorePointer(
                            child: AnimatedBuilder(
                              animation: Listenable.merge([
                                _position,
                                _selection,
                              ]),
                              builder: (context, _) {
                                final position =
                                    Directionality.of(context) ==
                                        TextDirection.rtl
                                    ? widget.destinations.length -
                                          1 -
                                          _position.value
                                    : _position.value;
                                return Stack(
                                  children: [
                                    Positioned(
                                      left: position * slot + _indicatorInset,
                                      top: _indicatorInset,
                                      bottom: _indicatorInset,
                                      width: indicatorWidth,
                                      child: DecoratedBox(
                                        key: const ValueKey(
                                          'glass-tab-indicator',
                                        ),
                                        decoration: ShapeDecoration(
                                          color: colors.primary.withValues(
                                            alpha:
                                                (MediaQuery.highContrastOf(
                                                      context,
                                                    )
                                                    ? .20
                                                    : .08) *
                                                (_motion
                                                    ? .8 +
                                                          .2 *
                                                              Curves.decelerate
                                                                  .transform(
                                                                    _selection
                                                                        .value,
                                                                  )
                                                    : 1),
                                          ),
                                          shape: AppShape.all(indicatorRadius),
                                        ),
                                      ),
                                    ),
                                  ],
                                );
                              },
                            ),
                          ),
                        ),
                        MediaQuery.removePadding(
                          context: context,
                          removeTop: true,
                          removeBottom: true,
                          removeLeft: true,
                          removeRight: true,
                          child: NavigationBarTheme(
                            data: NavigationBarThemeData(
                              height: height,
                              elevation: 0,
                              backgroundColor: Colors.transparent,
                              shadowColor: Colors.transparent,
                              surfaceTintColor: Colors.transparent,
                              indicatorColor: Colors.transparent,
                              indicatorShape: AppShape.full,
                              labelPadding: const EdgeInsets.only(
                                left: 4,
                                right: 4,
                              ),
                              labelBehavior:
                                  NavigationDestinationLabelBehavior.alwaysShow,
                              iconTheme: WidgetStateProperty.resolveWith(
                                (states) => IconThemeData(
                                  size: _iconSize,
                                  color: states.contains(WidgetState.selected)
                                      ? colors.primary
                                      : colors.onSurfaceVariant,
                                ),
                              ),
                              labelTextStyle: WidgetStateProperty.resolveWith(
                                (states) => Theme.of(context)
                                    .textTheme
                                    .labelSmall!
                                    .copyWith(
                                      fontSize: compactLabels
                                          ? 10.5
                                          : GlassNavigationBar._labelSize,
                                      height: 1.1,
                                      letterSpacing: 0,
                                      fontWeight: FontWeight.w500,
                                      color:
                                          states.contains(WidgetState.selected)
                                          ? colors.primary
                                          : colors.onSurfaceVariant,
                                      overflow: TextOverflow.ellipsis,
                                    ),
                              ),
                            ),
                            child: NavigationBar(
                              selectedIndex: widget.selectedIndex,
                              onDestinationSelected: widget.onSelected,
                              destinations: [
                                for (final destination in widget.destinations)
                                  // Compensate Material's fixed icon slot while keeping its full hit target.
                                  Transform.translate(
                                    offset: const Offset(
                                      0,
                                      (_iconSize -
                                              _materialIconSlot -
                                              _iconTopInset) /
                                          4,
                                    ),
                                    transformHitTests: false,
                                    child: NavigationDestination(
                                      key: destination.key,
                                      icon: Padding(
                                        padding: const EdgeInsets.only(
                                          top: _iconTopInset,
                                        ),
                                        child: destination.icon,
                                      ),
                                      selectedIcon:
                                          destination.selectedIcon == null
                                          ? null
                                          : Padding(
                                              padding: const EdgeInsets.only(
                                                top: _iconTopInset,
                                              ),
                                              child: destination.selectedIcon!,
                                            ),
                                      label: destination.label,
                                      tooltip: destination.tooltip,
                                      enabled: destination.enabled,
                                    ),
                                  ),
                              ],
                              animationDuration: _motion
                                  ? const Duration(milliseconds: 320)
                                  : Duration.zero,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}
