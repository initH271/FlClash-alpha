import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/ui/icons/icons.dart';
import 'package:fl_clash/ui/ui.dart';
import 'package:fl_clash/views/dashboard/style.dart';
import 'package:fl_clash/views/dashboard/widgets/card.dart';
import 'package:fl_clash/views/network_features.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

enum AutoPauseView { off, stoppedByRule, stopped, running, overridden }

AutoPauseView autoPauseViewOf({
  required bool enabled,
  required bool running,
  required NetworkAutomationState automation,
}) {
  if (!enabled) return AutoPauseView.off;
  if (!running) {
    return automation.pausedByPolicy
        ? AutoPauseView.stoppedByRule
        : AutoPauseView.stopped;
  }
  return automation.overridden && automation.matchedRule != null
      ? AutoPauseView.overridden
      : AutoPauseView.running;
}

class AutoPauseCard extends ConsumerWidget {
  const AutoPauseCard({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final appLocalizations = context.appLocalizations;
    final enabled = ref.watch(
      networkFeaturesProvider.select((settings) => settings.smartAutoStop),
    );
    final running = ref.watch(isStartProvider);
    final automation = ref.watch(networkAutomationProvider);
    final rule = enabled ? automation.matchedRule : null;
    final view = autoPauseViewOf(
      enabled: enabled,
      running: running,
      automation: automation,
    );
    final (label, tone) = switch (view) {
      AutoPauseView.off => (
        appLocalizations.forkAutoPauseOff,
        DashboardChipTone.idle,
      ),
      AutoPauseView.stoppedByRule => (
        appLocalizations.forkAutoPauseStoppedByRule,
        DashboardChipTone.warn,
      ),
      AutoPauseView.stopped => (
        appLocalizations.forkAutoPauseStopped,
        DashboardChipTone.idle,
      ),
      AutoPauseView.running => (
        appLocalizations.forkAutoPauseRunning,
        DashboardChipTone.ok,
      ),
      AutoPauseView.overridden => (
        appLocalizations.forkAutoPauseOverridden,
        DashboardChipTone.warn,
      ),
    };
    final action = switch (view) {
      AutoPauseView.overridden => DashboardIconButton(
        glyph: AppGlyphs.reset,
        tooltip: appLocalizations.forkAutoPauseResume,
        onPressed: () =>
            ref.read(networkResumeRequestProvider.notifier).request(),
      ),
      AutoPauseView.stoppedByRule ||
      AutoPauseView.stopped when rule != null => DashboardIconButton(
        glyph: AppGlyphs.toggleOn,
        tooltip: appLocalizations.forkAutoPauseStartAnyway,
        onPressed: () =>
            ref.read(setupActionProvider.notifier).setRunning(true),
      ),
      _ => null,
    };
    final detail = switch (view) {
      AutoPauseView.off => appLocalizations.forkAutoPauseOffHint,
      AutoPauseView.overridden => appLocalizations.forkAutoPauseOverrideHint,
      _ when rule != null => appLocalizations.forkAutoPauseMatched(rule),
      _ => appLocalizations.forkAutoPauseNoMatch,
    };
    return DashboardCard(
      semanticLabel: appLocalizations.forkAutoPause,
      onTap: () => BaseNavigator.push(context, const NetworkFeaturesView()),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        spacing: 8,
        children: [
          DashboardCardHeader(
            glyph: AppGlyphs.wifiOff,
            title: appLocalizations.forkAutoPause,
            chevron: true,
            trailing: [?action],
          ),
          Align(
            alignment: AlignmentDirectional.centerStart,
            child: DashboardChip(label: label, tone: tone, dot: true),
          ),
          if (view == AutoPauseView.overridden && rule != null)
            Text(
              appLocalizations.forkAutoPauseMatched(rule),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: DashboardText.rowTitle(context),
            ),
          Text(
            detail,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: DashboardText.label(context),
          ),
        ],
      ),
    );
  }
}
