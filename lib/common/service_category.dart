import 'package:fl_clash/common/service_probe.dart';
import 'package:fl_clash/l10n/l10n.dart';

enum ServiceCategory {
  ai,
  streaming,
  social,
  finance,
  developer,
  gaming;

  String label(AppLocalizations localizations) => switch (this) {
    ServiceCategory.ai => localizations.serviceCategoryAi,
    ServiceCategory.streaming => localizations.serviceCategoryStreaming,
    ServiceCategory.social => localizations.serviceCategorySocial,
    ServiceCategory.finance => localizations.serviceCategoryFinance,
    ServiceCategory.developer => localizations.serviceCategoryDeveloper,
    ServiceCategory.gaming => localizations.serviceCategoryGaming,
  };
}

extension ServiceTargetCategory on ServiceTarget {
  // Exhaustive, so a service added without a group fails to compile.
  ServiceCategory get category => switch (this) {
    ServiceTarget.chatgpt ||
    ServiceTarget.claude ||
    ServiceTarget.gemini => ServiceCategory.ai,
    ServiceTarget.youtube ||
    ServiceTarget.netflix ||
    ServiceTarget.disneyPlus ||
    ServiceTarget.primeVideo ||
    ServiceTarget.spotify ||
    ServiceTarget.bilibili => ServiceCategory.streaming,
    ServiceTarget.telegram ||
    ServiceTarget.x ||
    ServiceTarget.instagram ||
    ServiceTarget.discord ||
    ServiceTarget.tiktok => ServiceCategory.social,
    ServiceTarget.okx ||
    ServiceTarget.binance ||
    ServiceTarget.bybit => ServiceCategory.finance,
    ServiceTarget.google || ServiceTarget.github => ServiceCategory.developer,
    ServiceTarget.steam => ServiceCategory.gaming,
  };
}

/// Groups follow the saved order of their first service, and keep it inside.
List<(ServiceCategory, List<ServiceTarget>)> groupServiceTargets(
  Iterable<ServiceTarget> targets,
) {
  final groups = <ServiceCategory, List<ServiceTarget>>{};
  for (final target in targets) {
    (groups[target.category] ??= []).add(target);
  }
  return [for (final MapEntry(:key, :value) in groups.entries) (key, value)];
}
