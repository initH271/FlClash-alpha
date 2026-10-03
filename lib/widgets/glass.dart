import 'dart:ui' as ui;

import 'package:fl_clash/common/shape.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter/rendering.dart';

import 'inherited.dart';

/// Bounded navigation chrome, with an Impeller refraction filter and a
/// frosted fallback. The shader program is shared; shader uniforms are not.
class GlassSurface extends StatefulWidget {
  final Widget child;
  final BorderRadius borderRadius;
  final bool effectsEnabled;
  final bool refractionEnabled;

  const GlassSurface({
    super.key,
    this.borderRadius = AppRadius.full,
    this.effectsEnabled = true,
    this.refractionEnabled = true,
    required this.child,
  });

  @override
  State<GlassSurface> createState() => _GlassSurfaceState();
}

class _GlassSurfaceState extends State<GlassSurface> {
  static Future<ui.FragmentProgram?>? _program;
  ui.FragmentShader? _shader;

  static Future<ui.FragmentProgram?> _loadProgram() async {
    try {
      return await ui.FragmentProgram.fromAsset(
        'shaders/navigation_glass.frag',
      );
    } catch (_) {
      // Unsupported drivers and a missing asset retain a readable surface.
      return null;
    }
  }

  @override
  void initState() {
    super.initState();
    if (ui.ImageFilter.isShaderFilterSupported) {
      (_program ??= _loadProgram()).then((program) {
        if (!mounted || program == null) return;
        setState(() => _shader = program.fragmentShader());
      });
    }
  }

  @override
  void dispose() {
    _shader?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final media = MediaQuery.of(context);
    final dark = colors.brightness == Brightness.dark;
    final effects =
        widget.effectsEnabled &&
        !media.highContrast &&
        PageActivityScope.isActiveOf(context);
    final refract = effects && widget.refractionEnabled && _shader != null;
    final tint = colors.surfaceContainerLow.withValues(
      alpha: media.highContrast || !effects ? .97 : (refract ? .85 : .76),
    );
    final sigma = refract ? 4.0 : 12.0;
    final filter = ui.ImageFilter.blur(sigmaX: sigma, sigmaY: sigma);
    return DecoratedBox(
      decoration: BoxDecoration(
        borderRadius: widget.borderRadius,
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: dark ? .06 : .13),
            blurRadius: 8,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: ClipRRect(
        borderRadius: widget.borderRadius,
        child: BackdropFilter(
          enabled: effects,
          filter: filter,
          child: _GlassBounds(
            shader: refract ? _shader : null,
            pixelRatio: View.of(context).devicePixelRatio,
            borderRadius: widget.borderRadius,
            child: DecoratedBox(
              decoration: BoxDecoration(
                color: tint,
                borderRadius: widget.borderRadius,
                border: Border.all(
                  width: .5,
                  color: (dark ? Colors.white : Colors.black).withValues(
                    alpha: dark ? .10 : .07,
                  ),
                ),
              ),
              child: widget.child,
            ),
          ),
        ),
      ),
    );
  }
}

class _GlassBounds extends SingleChildRenderObjectWidget {
  final ui.FragmentShader? shader;
  final double pixelRatio;
  final BorderRadius borderRadius;
  const _GlassBounds({
    required this.shader,
    required this.pixelRatio,
    required this.borderRadius,
    required super.child,
  });
  @override
  RenderObject createRenderObject(BuildContext context) =>
      _RenderGlassBounds(shader, pixelRatio, borderRadius);
  @override
  void updateRenderObject(
    BuildContext context,
    _RenderGlassBounds renderObject,
  ) {
    renderObject
      ..shader = shader
      ..pixelRatio = pixelRatio
      ..borderRadius = borderRadius
      ..markNeedsCompositingBitsUpdate()
      ..markNeedsPaint();
  }
}

class _RenderGlassBounds extends RenderProxyBox {
  ui.FragmentShader? shader;
  double pixelRatio;
  BorderRadius borderRadius;
  _RenderGlassBounds(this.shader, this.pixelRatio, this.borderRadius);
  @override
  bool get alwaysNeedsCompositing => child != null && shader != null;

  @override
  void paint(PaintingContext context, Offset offset) {
    final effect = shader;
    if (effect == null || size.isEmpty) {
      layer = null;
      super.paint(context, offset);
      return;
    }
    final origin = localToGlobal(Offset.zero);
    final end = localToGlobal(size.bottomRight(Offset.zero));
    final physicalScale = (end.dx - origin.dx) / size.width * pixelRatio;
    final corners = borderRadius.toRRect(Offset.zero & size).scaleRadii();
    effect
      ..setFloat(2, (end.dx - origin.dx) * pixelRatio)
      ..setFloat(3, (end.dy - origin.dy) * pixelRatio)
      ..setFloat(4, corners.tlRadiusX * physicalScale)
      ..setFloat(5, corners.trRadiusX * physicalScale)
      ..setFloat(6, corners.brRadiusX * physicalScale)
      ..setFloat(7, corners.blRadiusX * physicalScale);
    final backdrop = (layer as BackdropFilterLayer?) ?? BackdropFilterLayer();
    backdrop.filter = ui.ImageFilter.shader(effect);
    layer = backdrop;
    context.pushLayer(backdrop, super.paint, offset);
  }
}
