import 'package:fl_clash/enum/enum.dart';
import 'package:fl_clash/views/dashboard/widgets/widgets.dart';
import 'package:fl_clash/widgets/widgets.dart';

import 'widgets/extended_widgets.dart';

extension DashboardWidgetView on DashboardWidget {
  GridItem get widget => switch (this) {
    DashboardWidget.networkSpeedSmall => const GridItem(
      crossAxisCellCount: 4,
      child: NetworkSpeedSmall(),
    ),
    DashboardWidget.connectionsCount => const GridItem(
      crossAxisCellCount: 8,
      child: ConnectionStatusCard(),
    ),
    DashboardWidget.ipv6Switch => const GridItem(
      crossAxisCellCount: 4,
      child: FeatureSwitchCard(kind: FeatureSwitchKind.ipv6),
    ),
    DashboardWidget.wakelockSwitch => const GridItem(
      crossAxisCellCount: 4,
      child: FeatureSwitchCard(kind: FeatureSwitchKind.wake),
    ),
    DashboardWidget.dnsOverride => const GridItem(
      crossAxisCellCount: 4,
      child: FeatureSwitchCard(kind: FeatureSwitchKind.dns),
    ),
    DashboardWidget.snifferOverride => const GridItem(
      crossAxisCellCount: 4,
      child: FeatureSwitchCard(kind: FeatureSwitchKind.sniffer),
    ),
    DashboardWidget.ntpOverride => const GridItem(
      crossAxisCellCount: 4,
      child: FeatureSwitchCard(kind: FeatureSwitchKind.ntp),
    ),
    DashboardWidget.providersInfo => const GridItem(
      crossAxisCellCount: 4,
      child: ProvidersInfo(),
    ),
    DashboardWidget.fcmStatus => const GridItem(
      crossAxisCellCount: 4,
      child: ConnectionStatusCard(fcm: true),
    ),
    DashboardWidget.onlinePanel => const GridItem(
      crossAxisCellCount: 4,
      child: OnlinePanel(),
    ),
    DashboardWidget.mediaUnlock => const GridItem(
      crossAxisCellCount: 8,
      child: MediaUnlockCard(),
    ),
    DashboardWidget.mediaUnlockSmall => const GridItem(
      crossAxisCellCount: 4,
      child: MediaUnlockCard(small: true),
    ),
    DashboardWidget.startButton => const GridItem(
      crossAxisCellCount: 4,
      child: DashboardStartCard(),
    ),
    DashboardWidget.networkSpeed => const GridItem(
      crossAxisCellCount: 8,
      child: NetworkSpeed(),
    ),
    DashboardWidget.outboundModeV2 => const GridItem(
      crossAxisCellCount: 8,
      child: OutboundModeV2(),
    ),
    DashboardWidget.outboundMode => const GridItem(
      crossAxisCellCount: 4,
      child: OutboundMode(),
    ),
    DashboardWidget.trafficUsage => const GridItem(
      crossAxisCellCount: 4,
      child: TrafficUsage(),
    ),
    DashboardWidget.networkDetection => const GridItem(
      crossAxisCellCount: 4,
      child: NetworkDetection(),
    ),
    DashboardWidget.tunButton => const GridItem(
      crossAxisCellCount: 4,
      child: TUNButton(),
    ),
    DashboardWidget.vpnButton => const GridItem(
      crossAxisCellCount: 4,
      child: VpnButton(),
    ),
    DashboardWidget.systemProxyButton => const GridItem(
      crossAxisCellCount: 4,
      child: SystemProxyButton(),
    ),
    DashboardWidget.intranetIp => const GridItem(
      crossAxisCellCount: 4,
      child: IntranetIP(),
    ),
    DashboardWidget.memoryInfo => const GridItem(
      crossAxisCellCount: 4,
      child: MemoryInfo(),
    ),
  };
}

DashboardWidget dashboardWidgetOf(GridItem gridItem) {
  return DashboardWidget.values.firstWhere((item) => item.widget == gridItem);
}
