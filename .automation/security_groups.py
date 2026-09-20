import hashlib
import json

GROUPS = {
    'go-core': ('Go 核心依赖统一修复', 'core/go.mod', 'Go'),
    'rust-helper': ('Rust Helper 依赖统一修复', 'services/helper/Cargo.lock', 'crates.io'),
    'rust-api': ('Rust API 依赖统一修复', 'plugins/rust_api/rust/Cargo.lock', 'crates.io'),
}


def group_for(item):
    return next(slug for slug, (_, path, _) in GROUPS.items() if item['file'] == path)


def group_key(slug):
    return hashlib.sha256(json.dumps(['security-repair-group-v2', slug]).encode()).hexdigest()


def payload_for(slug):
    title, path, ecosystem = GROUPS[slug]
    return {'key': group_key(slug), 'group': slug, 'package': title,
            'file': path, 'ecosystem': ecosystem, 'history': [], 'component_keys': [], 'auto_resolved': False}


def repair_branch(payload):
    if payload.get('group') in GROUPS:
        return 'security/group-' + payload['group']
    return 'security/fix-' + payload['key'][:12]
