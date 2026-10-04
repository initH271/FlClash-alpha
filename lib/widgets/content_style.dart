import 'package:fl_clash/common/common.dart';
import 'package:material_ui/material_ui.dart';

class ContentStyleScope extends InheritedWidget {
  final double topInset;
  final bool effectsEnabled;

  const ContentStyleScope({
    super.key,
    this.topInset = 0,
    this.effectsEnabled = true,
    required super.child,
  });

  static ContentStyleScope? of(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<ContentStyleScope>();

  @override
  bool updateShouldNotify(ContentStyleScope oldWidget) =>
      topInset != oldWidget.topInset ||
      effectsEnabled != oldWidget.effectsEnabled;
}

class ContentPanel extends StatelessWidget {
  final BorderRadius borderRadius;
  final bool selected;
  final bool clipChild;
  final Widget child;

  const ContentPanel({
    super.key,
    this.borderRadius = AppRadius.lg,
    this.selected = false,
    this.clipChild = true,
    required this.child,
  });

  @override
  Widget build(BuildContext context) {
    final colors = context.colorScheme;
    final highContrast = MediaQuery.highContrastOf(context);
    return DecoratedBox(
      decoration: ShapeDecoration(
        shape: AppShape.of(borderRadius).copyWith(
          side: BorderSide(
            color: selected
                ? colors.primary.withValues(alpha: highContrast ? 1 : .48)
                : colors.outlineVariant.withValues(
                    alpha: highContrast ? 1 : .45,
                  ),
            width: highContrast ? 1.5 : .6,
          ),
        ),
        color: highContrast
            ? (selected ? colors.secondaryContainer : colors.surfaceContainer)
            : null,
        gradient: highContrast
            ? null
            : LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: selected
                    ? [
                        Color.alphaBlend(
                          colors.primary.withValues(alpha: .10),
                          colors.surfaceContainerLow,
                        ),
                        Color.alphaBlend(
                          colors.primary.withValues(alpha: .035),
                          colors.surfaceContainerLow,
                        ),
                      ]
                    : [colors.surfaceContainerLowest, colors.surfaceContainer],
              ),
      ),
      child: clipChild
          ? ClipRSuperellipse(borderRadius: borderRadius, child: child)
          : child,
    );
  }
}

class ContentSection extends StatelessWidget {
  final String title;
  final List<Widget> children;

  const ContentSection({
    super.key,
    required this.title,
    required this.children,
  });

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.only(left: 12, bottom: 8),
          child: Text(
            title,
            style: context.textTheme.labelLarge?.copyWith(
              color: context.colorScheme.onSurfaceVariant,
            ),
          ),
        ),
        ContentPanel(
          borderRadius: AppRadius.xl,
          child: ListTileTheme(
            data: ListTileThemeData(
              iconColor: context.colorScheme.primary,
              contentPadding: const EdgeInsets.symmetric(horizontal: 16),
              titleTextStyle: context.textTheme.bodyLarge,
              subtitleTextStyle: context.textTheme.bodySmall?.copyWith(
                color: context.colorScheme.onSurfaceVariant,
              ),
            ),
            child: Column(
              children: [
                for (var index = 0; index < children.length; index++) ...[
                  children[index],
                  if (index + 1 < children.length)
                    Divider(
                      height: 1,
                      indent: 56,
                      endIndent: 16,
                      color: context.colorScheme.outlineVariant.withValues(
                        alpha: .45,
                      ),
                    ),
                ],
              ],
            ),
          ),
        ),
      ],
    ),
  );
}

class TonalStatusLabel extends StatelessWidget {
  final String label;
  final IconData icon;
  final Color color;
  final bool compact;

  const TonalStatusLabel({
    super.key,
    required this.label,
    required this.icon,
    required this.color,
    this.compact = false,
  });

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
    decoration: BoxDecoration(
      color: color.withValues(alpha: .10),
      borderRadius: AppRadius.sm,
    ),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 16, color: color),
        if (!compact) ...[
          const SizedBox(width: 4),
          Flexible(
            child: Text(
              label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: context.textTheme.bodySmall?.copyWith(
                color: context.colorScheme.onSurface,
              ),
            ),
          ),
        ],
      ],
    ),
  );
}
