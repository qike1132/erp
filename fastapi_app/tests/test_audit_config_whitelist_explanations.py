"""F3-5：audit_config.yaml 每个层白名单文件都必须有可复核的豁免说明。"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG = ROOT / 'scripts' / 'prod_audit' / 'audit_config.yaml'


def test_every_layer_whitelist_file_has_explanation():
    data = yaml.safe_load(CONFIG.read_text(encoding='utf-8'))
    explained = {
        (item['layer'], item['file'])
        for item in data.get('whitelist_explanations', [])
    }

    missing = []
    for layer_id, layer_cfg in data['layers'].items():
        for filename in layer_cfg.get('whitelist', []) or []:
            if (layer_id, filename) not in explained:
                missing.append(f'{layer_id}:{filename}')

    assert not missing, f'以下白名单缺少 explanation: {missing}'
