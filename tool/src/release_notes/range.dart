import 'dart:io';

import '../changelog/git.dart';
import '../changelog/models.dart';
import '../changelog/parser.dart';
import '../changelog/render.dart';

final _alphaTag = RegExp(r'^alpha-\d+\.\d+\.\d+-(\d+)$');

class AlphaReleaseNotes {
  final String notes;
  final String baseTag;
  final String baseSha;
  final String sourceSha;
  final List<String> warnings;

  const AlphaReleaseNotes({
    required this.notes,
    required this.baseTag,
    required this.baseSha,
    required this.sourceSha,
    required this.warnings,
  });

  Map<String, dynamic> toJson() => {
    'notes': notes,
    'notesBaseTag': baseTag,
    'notesBaseSha': baseSha,
    'notesSourceSha': sourceSha,
  };

  static AlphaReleaseNotes generate({
    required String root,
    required String version,
    required int build,
    String? base,
    String source = 'HEAD',
  }) {
    if (build <= 0 || !RegExp(r'^\d+\.\d+\.\d+$').hasMatch(version)) {
      throw ArgumentError('Invalid alpha version or build');
    }
    final sourceSha = _git(root, [
      'rev-parse',
      '--verify',
      '--end-of-options',
      '$source^{commit}',
    ]);
    if (base != null) {
      final match = _alphaTag.firstMatch(base);
      if (match == null) throw ArgumentError('Invalid alpha base tag');
      try {
        _git(root, ['rev-parse', '--verify', 'refs/tags/$base^{commit}']);
      } on GitException {
        throw ArgumentError('Base tag does not exist');
      }
      if (int.parse(match[1]!) >= build) {
        throw ArgumentError('Base build is not smaller than this build');
      }
      final ancestor = Process.runSync('git', [
        'merge-base',
        '--is-ancestor',
        'refs/tags/$base',
        sourceSha,
      ], workingDirectory: root);
      if (ancestor.exitCode != 0) {
        throw ArgumentError('Base is not reachable from source');
      }
    }
    final tags =
        _git(root, [
            'tag',
            '--merged',
            sourceSha,
            '--list',
            'alpha-*',
          ]).split('\n').where((tag) {
            final match = _alphaTag.firstMatch(tag);
            return match != null && int.parse(match[1]!) < build;
          }).toList()
          ..sort((a, b) {
            final byBuild = int.parse(
              _alphaTag.firstMatch(b)![1]!,
            ).compareTo(int.parse(_alphaTag.firstMatch(a)![1]!));
            return byBuild != 0 ? byBuild : b.compareTo(a);
          });
    if (tags.isEmpty) {
      throw const FormatException(
        'No eligible previous alpha release; refusing to fall back to history',
      );
    }
    if (base != null && !tags.contains(base)) {
      throw ArgumentError('Base must be a reachable, older alpha release');
    }
    final baseTag = base ?? tags.first;
    final baseRef = 'refs/tags/$baseTag';
    final baseSha = _git(root, ['rev-parse', '$baseRef^{commit}']);
    final commits = _commits(root, baseRef, sourceSha);
    final parser = ChangelogParser();
    final seen = <String>{};
    final parsed = parser.parseAll(commits);
    final items = [
      for (final type in ChangelogType.values)
        for (final item in parsed.where((item) => item.type == type))
          if (seen.add(
            item.entry.text
                .replaceAll(RegExp(r'\s+'), ' ')
                .trim()
                .toLowerCase(),
          ))
            item,
    ];
    final release = ChangelogVersion(
      version: version,
      tag: 'alpha-$version-$build',
      date: '',
      groups: groupItems(items),
    );
    final rendered = renderRelease(release);
    return AlphaReleaseNotes(
      notes:
          'FlClash-alpha $version（构建 $build）\n\n'
          '${release.isEmpty ? rendered.replaceFirst(emptyVersionNote, '本版没有用户可见的变化。') : rendered}',
      baseTag: baseTag,
      baseSha: baseSha,
      sourceSha: sourceSha,
      warnings: List.unmodifiable(parser.warnings),
    );
  }
}

List<RawCommit> _commits(String root, String base, String source) {
  final output = _git(root, [
    'log',
    '--format=%H%x1f%P%x1f%s%x1f%b%x1e',
    '$base..$source',
  ]);
  return output.split('\x1e').where((record) => record.trim().isNotEmpty).map((
    record,
  ) {
    final fields = record.trim().split('\x1f');
    final merge = fields[1].split(' ').length > 1;
    final subject =
        merge &&
            fields[2].startsWith('Merge ') &&
            RegExp(
              r'^(Changelog|BREAKING[ -]CHANGE):',
              multiLine: true,
            ).hasMatch(fields[3])
        ? 'chore: merged changes'
        : fields[2];
    return RawCommit(hash: fields[0], subject: subject, body: fields[3]);
  }).toList();
}

String _git(String root, List<String> arguments) {
  final result = Process.runSync('git', arguments, workingDirectory: root);
  if (result.exitCode != 0) {
    throw GitException(result.stderr.toString().trim());
  }
  return result.stdout.toString().trim();
}
