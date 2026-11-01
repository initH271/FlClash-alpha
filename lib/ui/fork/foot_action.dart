import 'package:fl_clash/ui/context.dart';
import 'package:fl_clash/ui/inherited.dart';
import 'package:material_ui/material_ui.dart';

/// Floats an extended FAB at the end of [body]'s foot, clear of its content.
class FloatingFootAction extends StatelessWidget {
  const FloatingFootAction({
    super.key,
    required this.action,
    required this.body,
  });

  final Widget action;
  final Widget body;

  static const _margin = BottomInsetScope.dockedSearchMargin;

  // An extended FloatingActionButton's height in Material 3.
  static const _actionHeight = 56.0;

  @override
  Widget build(BuildContext context) {
    return Stack(
      fit: StackFit.expand,
      children: [
        BottomInsetScope(
          inset: BottomInsetScope.of(context) + _margin + _actionHeight,
          child: body,
        ),
        Align(
          alignment: AlignmentDirectional.bottomEnd,
          child: Padding(
            padding: EdgeInsetsDirectional.only(
              end: _margin,
              bottom: _margin + context.bottomInset,
            ),
            child: action,
          ),
        ),
      ],
    );
  }
}
