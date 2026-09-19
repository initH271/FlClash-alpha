import 'dart:io';

import 'package:dio/dio.dart';
import 'package:fl_clash/common/common.dart';
import 'package:fl_clash/common/update_download.dart';
import 'package:fl_clash/widgets/dialog.dart';
import 'package:material_ui/material_ui.dart';

bool _updateDialogOpen = false;

Future<void> showAppUpdateDialog(
  BuildContext context,
  Map<String, dynamic> release,
) async {
  if (_updateDialogOpen) return;
  _updateDialogOpen = true;
  try {
    await dialogs.showCommonDialog<void>(
      context: context,
      dismissible: false,
      child: AppUpdateDialog(release: release),
    );
  } finally {
    _updateDialogOpen = false;
  }
}

class AppUpdateDialog extends StatefulWidget {
  final Map<String, dynamic> release;
  final UpdateDownload? downloader;
  final UpdateInstaller installer;

  const AppUpdateDialog({
    super.key,
    required this.release,
    this.downloader,
    this.installer = const UpdateInstaller(),
  });

  @override
  State<AppUpdateDialog> createState() => _AppUpdateDialogState();
}

class _AppUpdateDialogState extends State<AppUpdateDialog>
    with WidgetsBindingObserver {
  CancelToken? _token;
  File? _file;
  double? _progress;
  bool _verifying = false;
  bool _failed = false;
  bool _installing = false;
  bool _permission = false;
  bool _opened = false;
  String? _source;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _download();
  }

  Future<void> _download() async {
    final token = CancelToken();
    _token = token;
    setState(() {
      _file = null;
      _failed = false;
      _verifying = false;
      _progress = null;
      _permission = false;
      _opened = false;
    });
    try {
      final downloader =
          widget.downloader ??
          UpdateDownload.network(request.dio, widget.installer);
      final file = await downloader.fetch(
        widget.release,
        token,
        (count, total) {
          if (!mounted || token.isCancelled) return;
          setState(() {
            _verifying = false;
            _progress = total > 0 ? (count / total).clamp(0.0, 1.0) : null;
          });
        },
        () {
          if (mounted && !token.isCancelled) setState(() => _verifying = true);
        },
        onSource: (source) {
          if (mounted && !token.isCancelled) setState(() => _source = source);
        },
      );
      if (mounted && !token.isCancelled) setState(() => _file = file);
    } catch (error) {
      commonPrint.log('App update download failed: $error');
      if (mounted) setState(() => _failed = true);
    }
  }

  Future<void> _install() async {
    if (_installing || _file == null) return;
    setState(() => _installing = true);
    try {
      final result = await widget.installer.install(_file!, widget.release);
      if (mounted) {
        setState(() {
          _permission = result == 'permission';
          _opened = result == 'opened';
        });
      }
    } catch (error) {
      commonPrint.log('App update installer failed: $error');
      if (mounted) setState(() => _failed = true);
    } finally {
      if (mounted) setState(() => _installing = false);
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed && _permission && !_installing) {
      _resumePermission();
    }
  }

  Future<void> _resumePermission() async {
    try {
      if (await widget.installer.canInstall() && mounted && _permission) {
        _permission = false;
        await _install();
      }
    } catch (error) {
      commonPrint.log('App update permission check failed: $error');
    }
  }

  @override
  void dispose() {
    _token?.cancel('Update dialog closed');
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final l10n = context.appLocalizations;
    final ready = _file != null;
    final status = _failed
        ? l10n.updateDownloadFailed
        : _permission
        ? l10n.updateInstallPermission
        : _opened
        ? l10n.updateInstallerOpened
        : ready
        ? l10n.updateReady
        : _verifying
        ? l10n.updateVerifying
        : l10n.updateDownloading;
    return PopScope(
      canPop: !_installing,
      child: CommonDialog(
        title: l10n.discoverNewVersion,
        actions: [
          TextButton(
            onPressed: _installing ? null : () => Navigator.of(context).pop(),
            child: Text(l10n.close),
          ),
          if (_failed)
            TextButton(onPressed: _download, child: Text(l10n.updateRetry))
          else if (ready)
            FilledButton(
              onPressed: _installing ? null : _install,
              child: Text(l10n.installUpdate),
            ),
        ],
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              '${widget.release['tag_name']} · ${_source ?? widget.release['source']}',
            ),
            const SizedBox(height: 12),
            Text(status),
            if (!ready && !_failed) ...[
              const SizedBox(height: 12),
              LinearProgressIndicator(value: _verifying ? null : _progress),
              if (!_verifying && _progress != null)
                Text('${(_progress! * 100).toStringAsFixed(0)}%'),
            ],
            const SizedBox(height: 16),
            Text(widget.release['body'] as String? ?? ''),
          ],
        ),
      ),
    );
  }
}
