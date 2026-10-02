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
      props: const SheetProps(isScrollControlled: true),
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
        _NetworkRulesEditor(initialValue: settings.smartAutoStopNetworks),
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

class _NetworkRulesEditor extends ConsumerStatefulWidget {
  const _NetworkRulesEditor({required this.initialValue});
  final String initialValue;

  @override
  ConsumerState<_NetworkRulesEditor> createState() =>
      _NetworkRulesEditorState();
}

class _NetworkRulesEditorState extends ConsumerState<_NetworkRulesEditor> {
  final _fieldKey = GlobalKey<FormFieldState<String>>();
  late final TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.initialValue);
  }

  @override
  void didUpdateWidget(covariant _NetworkRulesEditor oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.initialValue != oldWidget.initialValue &&
        _controller.text == oldWidget.initialValue) {
      _controller.text = widget.initialValue;
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _save() {
    if (_fieldKey.currentState?.validate() != true) return;
    ref
        .read(networkFeaturesProvider.notifier)
        .update(
          (state) =>
              state.copyWith(smartAutoStopNetworks: _controller.text.trim()),
        );
  }

  @override
  Widget build(BuildContext context) {
    final l = context.appLocalizations;
    return Column(
      children: [
        TextFormField(
          key: _fieldKey,
          controller: _controller,
          maxLength: 2048,
          maxLines: 3,
          textInputAction: TextInputAction.done,
          decoration: InputDecoration(
            labelText: l.networkRules,
            helperText: l.networkRulesDesc,
            helperMaxLines: 7,
            errorMaxLines: 4,
          ),
          autovalidateMode: AutovalidateMode.onUserInteraction,
          validator: (value) =>
              NetworkRules.isValid(value ?? '') ? null : l.networkRulesInvalid,
          onFieldSubmitted: (_) => _save(),
        ),
        Align(
          alignment: Alignment.centerRight,
          child: FilledButton.icon(
            key: const ValueKey('save-network-rules'),
            onPressed: _save,
            icon: const Icon(Icons.save),
            label: Text(l.save),
          ),
        ),
      ],
    );
  }
}
