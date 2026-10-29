import 'package:flutter_riverpod/flutter_riverpod.dart';

class NetworkUserIntent extends Notifier<int> {
  @override
  int build() => 0;

  void record() => state++;
}

final networkUserIntentProvider = NotifierProvider<NetworkUserIntent, int>(
  NetworkUserIntent.new,
);
