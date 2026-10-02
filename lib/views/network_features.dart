import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/common/network_policy.dart';
import 'package:fl_clash/models/network_features.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/widgets/widgets.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

class NetworkFeaturesView extends ConsumerWidget {
  const NetworkFeaturesView({super.key});

  static void show(BuildContext context) {
    showSheet(
      context: context,
      builder: (_) => AdaptiveSheetScaffold(
        title: context.appLocalizations.networkFeatures,
        body: const NetworkFeaturesView(),
      ),
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = context.appLocalizations;
    final settings = ref.watch(networkFeaturesProvider);
    void update(
      NetworkFeatureSettings Function(NetworkFeatureSettings) change,
    ) {
      ref.read(networkFeaturesProvider.notifier).update(change);
    }

    return ListView(
      padding: baseInfoEdgeInsets,
      children: [
        SwitchListTile(
          title: Text(l.smartAutoStop),
          subtitle: Text(l.smartAutoStopDesc),
          value: settings.smartAutoStop,
          onChanged: (value) => update((s) => s.copyWith(smartAutoStop: value)),
        ),
        TextFormField(
          initialValue: settings.smartAutoStopNetworks,
          maxLength: 2048,
          maxLines: 3,
          textInputAction: TextInputAction.done,
          decoration: InputDecoration(
            labelText: l.networkRules,
            helperText: l.networkRulesDesc,
          ),
          autovalidateMode: AutovalidateMode.onUserInteraction,
          validator: (value) =>
              NetworkRules.isValid(value ?? '') ? null : l.networkRulesInvalid,
          onFieldSubmitted: (value) {
            if (NetworkRules.isValid(value)) {
              update((s) => s.copyWith(smartAutoStopNetworks: value.trim()));
            }
          },
        ),
        SwitchListTile(
          title: Text(l.disableQuic),
          subtitle: Text(l.disableQuicDesc),
          value: settings.disableQuic,
          onChanged: (value) => update((s) => s.copyWith(disableQuic: value)),
        ),
        SwitchListTile(
          title: Text(l.snifferOverride),
          value: settings.overrideSniffer,
          onChanged: (value) =>
              update((s) => s.copyWith(overrideSniffer: value)),
        ),
        SwitchListTile(
          title: Text(l.sniffer),
          value: settings.snifferEnabled,
          onChanged: settings.overrideSniffer
              ? (value) => update((s) => s.copyWith(snifferEnabled: value))
              : null,
        ),
        SwitchListTile(
          title: Text(l.ntpOverride),
          value: settings.overrideNtp,
          onChanged: (value) => update((s) => s.copyWith(overrideNtp: value)),
        ),
        SwitchListTile(
          title: const Text('NTP'),
          value: settings.ntpEnabled,
          onChanged: settings.overrideNtp
              ? (value) => update((s) => s.copyWith(ntpEnabled: value))
              : null,
        ),
        TextFormField(
          initialValue: settings.ntpServer,
          maxLength: 253,
          textInputAction: TextInputAction.done,
          decoration: InputDecoration(labelText: l.ntpServer),
          onFieldSubmitted: (value) {
            if (value.trim().isNotEmpty) {
              update((s) => s.copyWith(ntpServer: value.trim()));
            }
          },
        ),
        if (system.isDesktop)
          SwitchListTile(
            title: Text(l.keepAwake),
            value: settings.keepAwake,
            onChanged: (value) => update((s) => s.copyWith(keepAwake: value)),
          ),
      ],
    );
  }
}
