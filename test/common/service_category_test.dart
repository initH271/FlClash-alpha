import 'package:fl_clash/common/service_category.dart';
import 'package:fl_clash/common/service_probe.dart';
import 'package:fl_clash/l10n/l10n.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';

void main() {
  test('every service lands in exactly one group', () {
    final groups = groupServiceTargets(ServiceTarget.values);
    final grouped = [for (final (_, members) in groups) ...members];

    expect(grouped, unorderedEquals(ServiceTarget.values));
    expect(grouped.toSet(), hasLength(grouped.length));
    expect([
      for (final (category, _) in groups) category,
    ], unorderedEquals(ServiceCategory.values));
    for (final (category, members) in groups) {
      expect(members, isNotEmpty, reason: category.name);
      expect(
        members.every((target) => target.category == category),
        isTrue,
        reason: category.name,
      );
    }
  });

  test('services sit in the groups people look for them in', () {
    final expected = {
      ServiceCategory.ai: [
        ServiceTarget.chatgpt,
        ServiceTarget.claude,
        ServiceTarget.gemini,
      ],
      ServiceCategory.streaming: [
        ServiceTarget.youtube,
        ServiceTarget.netflix,
        ServiceTarget.disneyPlus,
        ServiceTarget.primeVideo,
        ServiceTarget.spotify,
        ServiceTarget.bilibili,
      ],
      ServiceCategory.social: [
        ServiceTarget.tiktok,
        ServiceTarget.discord,
        ServiceTarget.telegram,
        ServiceTarget.x,
        ServiceTarget.instagram,
      ],
      ServiceCategory.finance: [
        ServiceTarget.okx,
        ServiceTarget.binance,
        ServiceTarget.bybit,
      ],
      ServiceCategory.developer: [ServiceTarget.google, ServiceTarget.github],
      ServiceCategory.gaming: [ServiceTarget.steam],
    };
    for (final MapEntry(key: category, value: targets) in expected.entries) {
      for (final target in targets) {
        expect(target.category, category, reason: target.id);
      }
    }
  });

  test('groups follow the saved order of their first service', () {
    final groups = groupServiceTargets([
      ServiceTarget.netflix,
      ServiceTarget.okx,
      ServiceTarget.claude,
      ServiceTarget.youtube,
    ]);

    expect(groups.map((group) => group.$1), [
      ServiceCategory.streaming,
      ServiceCategory.finance,
      ServiceCategory.ai,
    ]);
    expect(groups.first.$2, [ServiceTarget.netflix, ServiceTarget.youtube]);
  });

  test('every group is named in English and Chinese', () async {
    final english = await AppLocalizations.load(const Locale('en'));
    expect(
      [for (final category in ServiceCategory.values) category.label(english)],
      [
        'AI',
        'Streaming',
        'Social',
        'Exchanges & finance',
        'Developer & tools',
        'Gaming',
      ],
    );
    final chinese = await AppLocalizations.load(const Locale('zh', 'CN'));
    expect(ServiceCategory.finance.label(chinese), '交易所与金融');
    expect(ServiceCategory.streaming.label(chinese), '流媒体');
  });
}
