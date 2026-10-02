import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:fl_clash/models/media_unlock.dart';

class NetworkUserIntent extends Notifier<int> {
  @override
  int build() => 0;

  void record() => state++;
}

final networkUserIntentProvider = NotifierProvider<NetworkUserIntent, int>(
  NetworkUserIntent.new,
);

class ServiceCheckResults
    extends Notifier<Map<MediaPlatform, MediaUnlockResult>> {
  @override
  Map<MediaPlatform, MediaUnlockResult> build() => const {};

  void add(MediaUnlockResult result) =>
      state = {...state, result.platform: result};

  void clear() => state = const {};
}

final serviceCheckResultsProvider =
    NotifierProvider<
      ServiceCheckResults,
      Map<MediaPlatform, MediaUnlockResult>
    >(ServiceCheckResults.new);
