import 'package:fl_clash/common/network_policy.dart';
import 'package:fl_clash/common/network_snapshot.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

class NetworkUserIntent extends Notifier<int> {
  @override
  int build() => 0;

  void record() => state++;
}

final networkUserIntentProvider = NotifierProvider<NetworkUserIntent, int>(
  NetworkUserIntent.new,
);

class NetworkResumeRequest extends Notifier<int> {
  @override
  int build() => 0;

  void request() => state++;
}

final networkResumeRequestProvider =
    NotifierProvider<NetworkResumeRequest, int>(NetworkResumeRequest.new);

final networkSnapshotReaderProvider =
    Provider<Future<NetworkSnapshot> Function()>((_) => readNetworkSnapshot);

@immutable
class NetworkAutomationState {
  const NetworkAutomationState({
    this.pausedByPolicy = false,
    this.overridden = false,
    this.matchedRule,
  });

  final bool pausedByPolicy;
  final bool overridden;

  /// Null until a check has seen the network match one of the rules.
  final String? matchedRule;

  @override
  bool operator ==(Object other) =>
      other is NetworkAutomationState &&
      other.pausedByPolicy == pausedByPolicy &&
      other.overridden == overridden &&
      other.matchedRule == matchedRule;

  @override
  int get hashCode => Object.hash(pausedByPolicy, overridden, matchedRule);
}

/// What network automation last decided; only its manager writes here.
class NetworkAutomation extends Notifier<NetworkAutomationState> {
  @override
  NetworkAutomationState build() => const NetworkAutomationState();

  void publish(NetworkAutomationState value) => state = value;
}

final networkAutomationProvider =
    NotifierProvider<NetworkAutomation, NetworkAutomationState>(
      NetworkAutomation.new,
    );
