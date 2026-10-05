import 'dart:convert';

import 'package:dio/dio.dart';

const alphaBuildOffset = 2026094000;
final _upstreamVersion = RegExp(r'^\d+\.\d+\.\d+$');
final _displayVersion = RegExp(r'^(\d+\.\d+\.\d+)-alpha\.([1-9]\d*)$');
final _releaseTag = RegExp(r'^alpha-(\d+\.\d+\.\d+)-(\d+)$');

class AppReleaseIdentity {
  final String upstreamVersion;
  final int? revision;
  final int? build;
  final String displayVersion;
  final bool hasDisplayVersion;

  const AppReleaseIdentity({
    required this.upstreamVersion,
    required this.revision,
    required this.build,
    required this.displayVersion,
    this.hasDisplayVersion = false,
  });

  factory AppReleaseIdentity.installed(String version, String buildNumber) {
    final build = int.tryParse(buildNumber);
    final match = _displayVersion.firstMatch(version);
    final upstream = match?[1] ?? version;
    final revision = match != null
        ? int.parse(match[2]!)
        : _upstreamVersion.hasMatch(version) &&
              build != null &&
              build > alphaBuildOffset
        ? build - alphaBuildOffset
        : null;
    return AppReleaseIdentity(
      upstreamVersion: upstream,
      revision: revision,
      build: build,
      displayVersion: revision == null
          ? '$version ($buildNumber)'
          : '$upstream-alpha.$revision',
      hasDisplayVersion: match != null,
    );
  }

  String? get releaseTag =>
      _upstreamVersion.hasMatch(upstreamVersion) &&
          build != null &&
          build! > alphaBuildOffset
      ? hasDisplayVersion
            ? 'v$displayVersion'
            : 'alpha-$upstreamVersion-$build'
      : null;
}

String releaseDisplayVersion(Map<String, dynamic> release) {
  final supplied = release['displayVersion'];
  if (supplied is String && _displayVersion.hasMatch(supplied)) return supplied;
  final tag = release['tag_name'] as String? ?? '';
  if (tag.startsWith('v') && _displayVersion.hasMatch(tag.substring(1))) {
    return tag.substring(1);
  }
  final match = _releaseTag.firstMatch(tag);
  if (match == null) return tag;
  final build = int.parse(match[2]!);
  if (build <= alphaBuildOffset) return tag;
  return '${match[1]}-alpha.${build - alphaBuildOffset}';
}

DateTime? parseReleaseDate(Object? value) {
  if (value is! String) return null;
  final match = RegExp(r'^(\d{4})-(\d{2})-(\d{2})T').firstMatch(value);
  if (match == null || !RegExp(r'(Z|[+-]\d{2}:\d{2})$').hasMatch(value)) {
    return null;
  }
  final year = int.parse(match[1]!);
  final month = int.parse(match[2]!);
  final day = int.parse(match[3]!);
  final date = DateTime.utc(year, month, day);
  if (date.year != year || date.month != month || date.day != day) return null;
  return DateTime.tryParse(value);
}

String formatReleaseDate(DateTime value) {
  final date = value.toLocal();
  return '${date.year}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}';
}

class ReleaseDateClient {
  final Dio dio;
  final _dates = <String, DateTime>{};

  ReleaseDateClient(this.dio);

  Future<DateTime?> lookup(String? tag, CancelToken token) async {
    if (tag == null ||
        !(_releaseTag.hasMatch(tag) ||
            (tag.startsWith('v') &&
                _displayVersion.hasMatch(tag.substring(1))))) {
      return null;
    }
    if (_dates[tag] case final cached?) return cached;
    for (final base in [
      'https://api.github.com/repos/initH271/FlClash-alpha/releases/tags',
      'https://api.cnb.cool/507space/FlClash-alpha/-/releases/tags',
    ]) {
      if (token.isCancelled) return null;
      try {
        final options =
            Options(
                responseType: ResponseType.json,
                sendTimeout: const Duration(seconds: 3),
                receiveTimeout: const Duration(seconds: 3),
              ).compose(
                dio.options,
                '$base/${Uri.encodeComponent(tag)}',
                cancelToken: token,
              )
              ..connectTimeout = const Duration(seconds: 3);
        final response = await dio.fetch<Object?>(options);
        final data = response.data is String
            ? jsonDecode(response.data as String)
            : response.data;
        if (data is! Map ||
            data['tag_name'] != tag ||
            data['draft'] == true ||
            data['prerelease'] == true) {
          continue;
        }
        final date = parseReleaseDate(data['published_at']);
        if (date != null) {
          _dates[tag] = date;
          return date;
        }
      } catch (_) {
        if (token.isCancelled) return null;
      }
    }
    return null;
  }
}
