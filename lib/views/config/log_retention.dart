import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/providers/providers.dart';
import 'package:fl_clash/widgets/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:material_ui/material_ui.dart';

class LogRetentionItem extends ConsumerWidget {
  const LogRetentionItem({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = context.appLocalizations;
    final days = ref.watch(
      appSettingProvider.select((value) => value.logRetentionDays),
    );
    return ListItem<int>.options(
      leading: const Icon(Icons.history_outlined),
      title: Text(l.logRetentionTitle),
      subtitle: Text('${l.logRetentionDays(days)}\n${l.logRetentionDesc}'),
      dialogTitle: l.logRetentionTitle,
      options: [
        1,
        7,
        14,
        30,
        if (![1, 7, 14, 30].contains(days)) days,
        0,
      ],
      value: days,
      textBuilder: (value) => value == 0
          ? l.custom
          : '${l.logRetentionDays(value)}${value == 14 ? ' (${l.defaultText})' : ''}',
      onChanged: (value) async {
        if (value == null) return;
        int? selected = value;
        if (value == 0) {
          final input = await dialogs.showCommonDialog<String>(
            context: context,
            child: InputDialog(
              title: l.logRetentionCustom,
              value: '$days',
              suffixText: l.logRetentionUnit,
              keyboardType: TextInputType.number,
              errorMaxLines: 3,
              validator: (value) {
                final number = int.tryParse(value ?? '');
                return number == null ||
                        number < 1 ||
                        number > maxLogRetentionDays
                    ? l.logRetentionInvalid
                    : null;
              },
            ),
          );
          selected = int.tryParse(input ?? '');
        }
        if (!context.mounted || selected == null) return;
        ref
            .read(appSettingProvider.notifier)
            .update((state) => state.copyWith(logRetentionDays: selected!));
      },
    );
  }
}
