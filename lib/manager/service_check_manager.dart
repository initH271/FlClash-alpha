import 'package:fl_clash/providers/providers.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

class ServiceCheckManager extends ConsumerStatefulWidget {
  const ServiceCheckManager({super.key, required this.child});

  final Widget child;

  @override
  ConsumerState<ServiceCheckManager> createState() =>
      _ServiceCheckManagerState();
}

class _ServiceCheckManagerState extends ConsumerState<ServiceCheckManager>
    with WidgetsBindingObserver {
  late final ServiceCheckController _controller;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    ref.listenManual(serviceCheckControllerProvider, (_, _) {});
    final lifecycle = WidgetsBinding.instance.lifecycleState;
    _controller = ref.read(serviceCheckControllerProvider.notifier);
    _controller.setForeground(
      lifecycle == null || lifecycle == AppLifecycleState.resumed,
    );
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _controller.setForeground(state == AppLifecycleState.resumed);
  }

  @override
  Widget build(BuildContext context) => widget.child;

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _controller.setForeground(false);
    super.dispose();
  }
}
