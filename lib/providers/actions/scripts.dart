part of '../action.dart';

@Riverpod(keepAlive: true)
class ScriptsAction extends _$ScriptsAction {
  @override
  void build() {}

  void putScript(Script script) {
    ref.read(scriptsProvider.notifier).put(script);
    _applyIfInUse(script.id);
  }

  /// Only [script]'s id is read; it may predate the downloads ahead of it.
  Future<void> updateScript(Script script, {String? url}) async {
    final updatingKeys = ref.read(updatingKeysProvider.notifier);
    final operation = updatingKeys.start(script.updatingKey);
    try {
      await _download(script.id, url);
    } finally {
      updatingKeys.stop(script.updatingKey, operation);
    }
  }

  Future<void> _download(int id, String? url) async {
    final before = await _stored(id);
    if (before == null) {
      return;
    }
    final response = await request.getTextResponseForUrl(url ?? before.url!);
    if ((await _stored(id))?.url != before.url) {
      return;
    }
    final saved = await before.save(response.data ?? '');
    final latest = await _stored(id);
    if (latest == null) {
      await File(await before.path).safeDelete();
      return;
    }
    putScript(
      latest.copyWith(
        url: url ?? latest.url,
        lastUpdateTime: saved.lastUpdateTime,
      ),
    );
  }

  Future<Script?> _stored(int id) async {
    return (await database.scriptsDao.query().get()).get(id);
  }

  void _applyIfInUse(int scriptId) {
    final profile = ref.read(currentProfileProvider);
    if (profile?.extendType != ExtendType.script ||
        profile?.scriptId != scriptId) {
      return;
    }
    ref.read(setupActionProvider.notifier).applyProfileDebounce(silence: true);
  }
}
