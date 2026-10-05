import 'dart:convert';
import 'dart:io';

import 'package:args/args.dart';

import 'src/release_notes/range.dart';

void main(List<String> arguments) {
  final parser = ArgParser()
    ..addOption('repo', defaultsTo: '.')
    ..addOption('version', mandatory: true)
    ..addOption('build', mandatory: true)
    ..addOption('source', defaultsTo: 'HEAD')
    ..addOption('base');
  try {
    final args = parser.parse(arguments);
    final result = AlphaReleaseNotes.generate(
      root: args.option('repo')!,
      version: args.option('version')!,
      build: int.parse(args.option('build')!),
      source: args.option('source')!,
      base: args.option('base'),
    );
    for (final warning in result.warnings) {
      stderr.writeln(warning);
    }
    stderr.writeln(
      'notes base ${result.baseTag} (${result.baseSha}) -> ${result.sourceSha}',
    );
    stdout.writeln(jsonEncode(result.toJson()));
  } catch (error) {
    stderr.writeln('Release notes failed: $error');
    exitCode = 1;
  }
}
