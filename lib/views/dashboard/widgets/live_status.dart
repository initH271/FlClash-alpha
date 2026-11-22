import 'dart:async';

import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/core/core.dart';
import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/providers/mitm.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/state.dart';
import 'package:fl_clash/ui/icons/icons.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:prism_ui/prism_ui.dart';

import 'live_status_deck.dart';

/// What is happening now and still needs the user: one card each in the deck,
/// in this order of importance.
sealed class LiveStatus {
  const LiveStatus({this.preview});

  /// Set on a card the developer page shows, which may share its kind with
  /// another and whose actions do nothing.
  final String? preview;

  Object get key => preview ?? runtimeType;
}

/// The core's own phase. Starting and stopped lead the deck; a running core
/// is only there to reach its restart, so it comes last.
final class CoreLiveStatus extends LiveStatus {
  const CoreLiveStatus(this.phase, {super.preview});

  final CoreStatus phase;
}

final class MitmConsentStatus extends LiveStatus {
  const MitmConsentStatus(this.names, {super.preview});

  final List<String> names;
}

bool _isRunningCore(LiveStatus status) =>
    status is CoreLiveStatus && status.phase == CoreStatus.connected;

/// [separateCore] is a core in its own process, which the user can watch
/// start and restart; one inside the app only ever shows having stopped.
List<LiveStatus> watchLiveStatuses(
  WidgetRef ref, {
  required bool separateCore,
}) {
  final core = ref.watch(heldCoreStatusProvider);
  final awaitingConsent = ref.watch(mitmModulesToAgreeProvider);
  return [
    if (core == CoreStatus.disconnected ||
        separateCore && core == CoreStatus.connecting)
      CoreLiveStatus(core),
    if (awaitingConsent.isNotEmpty)
      MitmConsentStatus([for (final module in awaitingConsent) module.name]),
    if (separateCore && core == CoreStatus.connected)
      const CoreLiveStatus(CoreStatus.connected),
  ];
}

/// Opens the deck on one card of every kind, from the developer page.
void showLiveStatusPreview(BuildContext context) {
  final navigator = Navigator.of(context);
  final overlay = navigator.overlay!.context.findRenderObject()! as RenderBox;
  final top = MediaQuery.paddingOf(context).top;
  final anchor = Rect.fromLTWH(overlay.size.width - 60, top + 8, 44, 44);
  unawaited(
    navigator.push(
      LiveStatusRoute(
        anchor: anchor,
        separateCore: true,
        barrierColor: context.colorScheme.alertScrim,
        barrierLabel: context.appLocalizations.close,
        statuses: const [
          CoreLiveStatus(CoreStatus.disconnected, preview: 'stopped'),
          CoreLiveStatus(CoreStatus.connecting, preview: 'starting'),
          MitmConsentStatus(['Ads', 'Scripts'], preview: 'consent'),
          CoreLiveStatus(CoreStatus.connected, preview: 'running'),
        ],
      ),
    ),
  );
}

/// The dashboard's bar button: it wears the most important live status and
/// counts the rest. A running core alone shrinks it to a check, and with an
/// in-app core it is gone while nothing is happening.
class LiveStatusButton extends ConsumerWidget {
  const LiveStatusButton({super.key, this.separateCore});

  /// Whether the core runs in its own process; the build's core when null.
  final bool? separateCore;

  bool get _separateCore => separateCore ?? coreLib == null;

  void _open(BuildContext context) {
    final navigator = Navigator.of(context);
    final box = context.findRenderObject()! as RenderBox;
    final overlay = navigator.overlay!.context.findRenderObject()! as RenderBox;
    final anchor = box.localToGlobal(Offset.zero, ancestor: overlay) & box.size;
    unawaited(
      navigator.push(
        LiveStatusRoute(
          anchor: anchor,
          separateCore: _separateCore,
          barrierColor: context.colorScheme.alertScrim,
          barrierLabel: context.appLocalizations.close,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final statuses = watchLiveStatuses(ref, separateCore: _separateCore);
    final top = statuses.firstOrNull;
    return FadeScaleBox(
      alignment: Alignment.centerRight,
      child: switch (top) {
        null => const SizedBox.shrink(),
        _ when _isRunningCore(top) => _RunningCoreButton(
          key: const ValueKey(CoreStatus.connected),
          onPressed: () => _open(context),
        ),
        _ => _LiveStatusPill(
          key: ValueKey(_pillKindOf(top)),
          status: top,
          count: statuses.where((it) => !_isRunningCore(it)).length,
          onPressed: () => _open(context),
        ),
      },
    );
  }
}

Object _pillKindOf(LiveStatus status) => switch (status) {
  CoreLiveStatus(:final phase) => phase,
  _ => status.key,
};

class _RunningCoreButton extends StatelessWidget {
  const _RunningCoreButton({super.key, required this.onPressed});

  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final colorScheme = context.colorScheme;
    final fill = colorScheme.successContainer;
    final pane = TonalButtonTheme.glassOf(context)
        ? LiquidGlassStyle.tinted(colorScheme, fill)
        : null;
    return IconButton.filled(
      tooltip: context.appLocalizations.liveStatus,
      style: ButtonStyle.from(
        backgroundColor: pane == null ? fill : Colors.transparent,
        foregroundColor: colorScheme.onSuccessContainer,
        backgroundBuilder: pane == null
            ? null
            : LiquidGlass.buttonBackground((_) => pane),
        pressLook: PressLook.none,
      ),
      onPressed: onPressed,
      icon: const GlyphIcon(AppGlyphs.check, fill: 1),
    );
  }
}

/// The top status's glyph and, beside others, how many statuses there are;
/// the cards say the rest.
class _LiveStatusPill extends StatelessWidget {
  const _LiveStatusPill({
    super.key,
    required this.status,
    required this.count,
    required this.onPressed,
  });

  final LiveStatus status;
  final int count;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final appLocalizations = context.appLocalizations;
    final colorScheme = context.colorScheme;
    final (fill, content) = switch (status) {
      CoreLiveStatus(phase: CoreStatus.disconnected) => (
        colorScheme.errorContainer,
        colorScheme.onErrorContainer,
      ),
      MitmConsentStatus() => (
        colorScheme.warningContainer,
        colorScheme.onWarningContainer,
      ),
      _ => (null, null),
    };
    final label = switch (status) {
      CoreLiveStatus(phase: CoreStatus.disconnected) =>
        appLocalizations.coreStopped,
      CoreLiveStatus() => appLocalizations.connecting,
      MitmConsentStatus() => appLocalizations.mitmModulesTurnedOff,
    };
    final iconSize = globalState.measure.textHeight(AppTextStyle.subheadline);
    final icon = SizedBox.square(
      dimension: iconSize,
      child: switch (status) {
        CoreLiveStatus(phase: CoreStatus.disconnected) => const GlyphIcon(
          AppGlyphs.error,
          fill: 1,
        ),
        CoreLiveStatus() => Builder(
          builder: (context) =>
              ActivityIndicator(color: IconTheme.of(context).color),
        ),
        MitmConsentStatus() => const GlyphIcon(AppGlyphs.puzzle, fill: 1),
      },
    );
    final shown = count > 1 ? '$count' : null;
    final pane = TonalButtonTheme.glassOf(context) && fill != null
        ? LiquidGlassStyle.tinted(colorScheme, fill)
        : null;
    final style = ButtonStyle.from(
      backgroundColor: pane == null ? fill : Colors.transparent,
      foregroundColor: content,
      backgroundBuilder: pane == null
          ? null
          : LiquidGlass.buttonBackground((_) => pane),
      pressLook: PressLook.none,
    );
    return Semantics(
      label: shown == null ? label : '$label, $shown',
      excludeSemantics: true,
      button: true,
      child: shown != null
          ? Tooltip(
              message: appLocalizations.liveStatus,
              child: FilledButton.icon(
                onPressed: onPressed,
                style: style,
                icon: icon,
                label: Text(
                  shown,
                  style: const TextStyle(
                    fontFeatures: [FontFeature.tabularFigures()],
                  ),
                ),
              ),
            )
          : IconButton.filled(
              tooltip: appLocalizations.liveStatus,
              style: style,
              onPressed: onPressed,
              icon: icon,
            ),
    );
  }
}
