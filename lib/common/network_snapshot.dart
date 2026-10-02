import 'dart:io';
import 'package:fl_clash/common/network_policy.dart';
import 'package:fl_clash/plugins/app.dart';

Future<NetworkSnapshot> readNetworkSnapshot() async {
  if (Platform.isAndroid) {
    final data = await app?.getNetworkAddresses();
    if (data == null) return const NetworkSnapshot();
    return NetworkSnapshot(
      addresses: List<String>.from(data['addresses'] as List? ?? const []),
      gateways: List<String>.from(data['gateways'] as List? ?? const []),
    );
  }
  final interfaces = await NetworkInterface.list(includeLoopback: false);
  final addresses = interfaces
      .where(
        (i) => !RegExp(r'^(utun|tun|tap|wg|lo|veth|docker)').hasMatch(i.name),
      )
      .expand((i) => i.addresses)
      .where((a) => a.type == InternetAddressType.IPv4)
      .map((a) => a.address)
      .toList();
  final gateways = <String>[];
  if (Platform.isMacOS || Platform.isLinux) {
    final result = await Process.run(
      Platform.isMacOS ? '/sbin/route' : 'ip',
      Platform.isMacOS
          ? ['-n', 'get', 'default']
          : ['route', 'show', 'default'],
    ).timeout(const Duration(seconds: 3));
    if (result.exitCode == 0) {
      final pattern = Platform.isMacOS
          ? RegExp(r'gateway:\s*(\d+(?:\.\d+){3})')
          : RegExp(r'via\s+(\d+(?:\.\d+){3})');
      gateways.addAll(pattern.allMatches('${result.stdout}').map((m) => m[1]!));
    }
  } else if (Platform.isWindows) {
    final result = await Process.run('route', [
      'print',
      '-4',
    ]).timeout(const Duration(seconds: 3));
    if (result.exitCode == 0) {
      gateways.addAll(
        RegExp(
          r'^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+(\d+(?:\.\d+){3})',
          multiLine: true,
        ).allMatches('${result.stdout}').map((m) => m[1]!),
      );
    }
  }
  return NetworkSnapshot(addresses: addresses, gateways: gateways);
}
