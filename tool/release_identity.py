import argparse
import json
import os
import pathlib
import re


BUILD_OFFSET = 2026094000


def release_identity(metadata):
    upstream = metadata.get('upstreamVersion', metadata.get('version'))
    build = metadata.get('build')
    revision = metadata.get('revision')
    if (not isinstance(upstream, str) or not re.fullmatch(r'\d+\.\d+\.\d+', upstream)
            or upstream != metadata.get('version')
            or type(build) is not int or not 0 < build <= 2100000000):
        raise ValueError('Invalid release version or build')
    if revision is None:
        revision = build - BUILD_OFFSET if build > BUILD_OFFSET else build
    if type(revision) is not int or revision < 1:
        raise ValueError('Release revision must be a positive integer')
    if build > BUILD_OFFSET and revision != build - BUILD_OFFSET:
        raise ValueError('Release revision does not match the internal build sequence')
    display = f'{upstream}-alpha.{revision}'
    supplied = metadata.get('displayVersion')
    if supplied is not None and supplied != display:
        raise ValueError('Display version does not match upstream and revision')
    return {'upstreamVersion': upstream, 'revision': revision,
            'displayVersion': display, 'build': build,
            'tag': f'v{display}' if supplied is not None else f'alpha-{upstream}-{build}'}


def next_release(metadata, upstream=None):
    current = release_identity(metadata)
    result = dict(metadata, build=current['build'] + 1,
                  revision=current['revision'] + 1,
                  upstreamVersion=upstream or current['upstreamVersion'],
                  version=upstream or current['upstreamVersion'])
    result.pop('displayVersion', None)
    result['displayVersion'] = release_identity(result)['displayVersion']
    return result


def verify_native_identity(metadata, application_id, build, version_name):
    identity = release_identity(metadata)
    expected_name = metadata.get('displayVersion', metadata['version'])
    if (application_id != metadata['applicationId']
            or build != identity['build'] or version_name != expected_name):
        raise ValueError('APK identity does not match release metadata')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--metadata', default='.github/release.json')
    parser.add_argument('--github-output', action='store_true')
    parser.add_argument('--field', choices=('upstreamVersion', 'revision',
                                           'displayVersion', 'build', 'tag'))
    args = parser.parse_args()
    identity = release_identity(json.loads(pathlib.Path(args.metadata).read_text()))
    if args.github_output:
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            for key, value in identity.items():
                output.write(f'{key}={value}\n')
    elif args.field:
        print(identity[args.field])
    else:
        print(json.dumps(identity))


if __name__ == '__main__':
    main()
