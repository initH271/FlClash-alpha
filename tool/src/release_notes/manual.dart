import '../changelog/models.dart';

const manualNotesPath = '.github/release-notes.md';

/// Matches the zh_CN group titles in the update dialog.
const manualGroupTitles = <ChangelogType, String>{
  ChangelogType.breaking: '要注意',
  ChangelogType.feat: '新玩意儿',
  ChangelogType.fix: '修好了',
  ChangelogType.perf: '更快了',
  ChangelogType.revert: '撤回了',
};

class ManualNotes {
  const ManualNotes({required this.groups, required this.warnings});

  final List<ChangelogGroup>? groups;
  final List<String> warnings;
}

/// The section is bound to a version so a forgotten file falls back instead of
/// repeating last release's copy. A malformed section throws: quietly shipping
/// generated text is the one outcome its author would not notice.
ManualNotes parseManualNotes(String? source, String version) {
  final lines = (source ?? '').split('\n').map((line) => line.trimRight());
  final sections = <List<String>>[];
  final others = <String>[];
  var hasStrayBullet = false;
  List<String>? current;
  for (final line in lines) {
    if (line.startsWith('## ')) {
      final heading = line.substring(3).trim().replaceFirst(RegExp('^v'), '');
      current = null;
      if (heading == version) {
        sections.add(current = <String>[]);
      } else {
        others.add(heading);
      }
    } else if (current != null) {
      current.add(line);
    } else if (others.isEmpty && line.startsWith('- ')) {
      hasStrayBullet = true;
    }
  }
  if (sections.length > 1) {
    throw FormatException('$manualNotesPath: "## $version" appears twice');
  }
  if (sections.isEmpty) {
    return ManualNotes(
      groups: null,
      warnings: [
        if (others.isNotEmpty)
          ('$manualNotesPath has no "## $version" section (found '
              '${others.join(', ')}); using generated entries.')
        else if (hasStrayBullet)
          ('$manualNotesPath has bullets but no "## $version" heading; using '
              'generated entries.'),
      ],
    );
  }
  return ManualNotes(
    groups: _parseSection(sections.single, version),
    warnings: const <String>[],
  );
}

List<ChangelogGroup> _parseSection(List<String> lines, String version) {
  Never fail(String problem) => throw FormatException(
    '$manualNotesPath, section "## $version": $problem. Expected "### <title>" '
    'lines (${manualGroupTitles.values.join(' / ')}) followed by "- <text>" '
    'lines. Delete the section to use generated entries.',
  );
  final titles = {
    for (final entry in manualGroupTitles.entries) entry.value: entry.key,
  };
  final entries = <ChangelogType, List<ChangelogEntry>>{};
  ChangelogType? type;
  var index = 0;
  for (final line in lines) {
    if (line.trim().isEmpty) {
      continue;
    }
    if (line.startsWith('### ')) {
      final title = line.substring(4).trim();
      type = titles[title] ?? fail('unknown group "$title"');
      if (entries.containsKey(type)) {
        fail('group "$title" appears twice');
      }
      entries[type] = <ChangelogEntry>[];
    } else if (line.startsWith('- ')) {
      final text = line.substring(2).trim();
      if (type == null) {
        fail('"$line" is not under a group');
      }
      if (text.isEmpty || text.contains('<!--') || text.contains('-->')) {
        fail('"$line" has no usable text');
      }
      index++;
      entries[type]!.add(ChangelogEntry(id: 'note-$index', text: text));
    } else {
      fail('cannot read "$line"');
    }
  }
  for (final entry in entries.entries) {
    if (entry.value.isEmpty) {
      fail('group "${manualGroupTitles[entry.key]}" has no entries');
    }
  }
  if (entries.isEmpty) {
    fail('it has no entries');
  }
  return <ChangelogGroup>[
    for (final type in ChangelogType.values)
      if (entries[type] case final list?)
        ChangelogGroup(type: type, entries: list),
  ];
}
