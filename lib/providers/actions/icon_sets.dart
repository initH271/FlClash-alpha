part of '../action.dart';

@Riverpod(keepAlive: true)
class IconSetsAction extends _$IconSetsAction {
  @override
  void build() {}

  Future<IconSet> importUrl(String url, {String name = ''}) async {
    final existing = (await database.iconSetsDao.query().get())
        .where((item) => item.url == url)
        .firstOrNull;
    if (existing != null) {
      return sync(existing, name: name.isEmpty ? null : name);
    }
    final content = await _download(url);
    return _put(
      IconSet(
        id: snowflake.id,
        name: _nameOf(name, content.name, url.urlFileName.fileStem),
        url: url,
        icons: content.icons,
        lastUpdateTime: DateTime.now(),
      ),
    );
  }

  IconSet importContent(String fileName, String content) {
    final parsed = _parse(content);
    return _put(
      IconSet(
        id: snowflake.id,
        name: _nameOf('', parsed.name, fileName.fileStem),
        icons: parsed.icons,
        lastUpdateTime: DateTime.now(),
      ),
    );
  }

  /// Only [iconSet]'s id is read; it may predate the downloads ahead of it.
  Future<IconSet> sync(IconSet iconSet, {String? name, String? url}) async {
    final before = await _stored(iconSet.id);
    if (before == null) {
      return iconSet;
    }
    final content = await _download(url ?? before.url);
    final latest = await _stored(iconSet.id);
    if (latest == null || latest.url != before.url) {
      return latest ?? iconSet;
    }
    return _put(
      latest.copyWith(
        name: name ?? latest.name,
        url: url ?? latest.url,
        icons: content.icons,
        lastUpdateTime: DateTime.now(),
      ),
    );
  }

  Future<IconSet?> _stored(int id) async {
    final rows =
        ref.read(iconSetsProvider).value ??
        await database.iconSetsDao.query().get();
    return rows.where((item) => item.id == id).firstOrNull;
  }

  IconSet _put(IconSet iconSet) {
    ref.read(iconSetsProvider.notifier).put(iconSet);
    return iconSet;
  }

  String _nameOf(String name, String parsedName, String fallback) {
    for (final candidate in [name, parsedName, fallback]) {
      if (candidate.trim().isNotEmpty) {
        return candidate.trim();
      }
    }
    return currentAppLocalizations.iconSets;
  }

  Future<({String name, List<IconSetIcon> icons})> _download(String url) async {
    final response = await request.getTextResponseForUrl(url);
    return _parse(response.data ?? '');
  }

  ({String name, List<IconSetIcon> icons}) _parse(String content) {
    try {
      return parseIconSet(content);
    } on FormatException {
      throw MessageException(currentAppLocalizations.invalidIconSet);
    }
  }
}
