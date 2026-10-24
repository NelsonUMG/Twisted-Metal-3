"""Verify an existing immutable publication before skipping duplicate creation."""
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def validate(release, manifest, version):
    if release['tag_name'] != version or manifest.get('version') != version:
        raise ValueError('Published version does not match the requested tag')
    assets = {asset['name']: asset for asset in release['assets']}
    expected = {'TM3Online-update.json'}
    for item in manifest['files']:
        name = 'tm3-' + item['sha256']
        asset = assets.get(name)
        if not asset or asset['size'] != item['size'] or asset.get('digest') != 'sha256:' + item['sha256']:
            raise ValueError('Missing or invalid published application file: ' + item['path'])
        expected.add(name)
    if set(assets) != expected:
        raise ValueError('Unexpected or missing release assets')


def main():
    repo = os.environ['GITHUB_REPOSITORY']
    tag = os.environ['RELEASE_TAG']
    headers = {'User-Agent': 'TM3-release-verifier', 'Accept': 'application/vnd.github+json'}
    if os.environ.get('GH_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['GH_TOKEN']
    try:
        with urlopen(Request(f'https://api.github.com/repos/{repo}/releases/tags/{tag}', headers=headers), timeout=30) as response:
            release = json.load(response)
    except HTTPError as exc:
        if exc.code != 404:
            raise
        release = None
    exists = bool(release and not release['draft'])
    if release and release['draft']:
        raise ValueError('An incomplete draft already exists; inspect it before publishing')
    if exists:
        asset = next(a for a in release['assets'] if a['name'] == 'TM3Online-update.json')
        # Public assets never receive the repository's authentication header.
        with urlopen(Request(asset['url'], headers={'User-Agent': 'TM3-release-verifier',
                     'Accept': 'application/octet-stream'}), timeout=30) as response:
            data = response.read(1024 * 1024 + 1)
        if len(data) != asset['size'] or 'sha256:' + hashlib.sha256(data).hexdigest() != asset.get('digest'):
            raise ValueError('Published manifest digest does not match')
        manifest = json.loads(data)
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'network'))
        from file_updater import validate_manifest
        validate_manifest(manifest, Path.cwd())
        validate(release, manifest, tag)
        print(f'{tag} is already published and verified; keeping its files unchanged.')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
            output.write('exists=' + str(exists).lower() + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
