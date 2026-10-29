# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

HEADER = 'X-ALC-Operator'

ROLE_LEVEL = {'observer': 1, 'duty': 2, 'admin': 3}
ROLE_LABEL = {'observer': '观察员', 'duty': '值班员', 'admin': '管理员'}

ACTION_MIN_ROLE = {
    'dispose': 'duty',
    'note': 'duty',
    'weather-mode-to-virtual': 'admin',
    'weather-mode-to-measured': 'observer',
    'radar-tiles': 'observer',
}

@dataclass(frozen=True)
class Identity:
    role: str
    raw: Optional[str]
    valid: bool

    @property
    def level(self) -> int:
        return ROLE_LEVEL.get(self.role, 1)

    @property
    def label(self) -> str:
        return ROLE_LABEL.get(self.role, self.role)

    def allows(self, action: str) -> bool:
        need = ACTION_MIN_ROLE.get(action, 'admin')
        return self.level >= ROLE_LEVEL[need]

def identify(headers) -> Identity:
    raw = (headers.get(HEADER) or '').strip()
    if not raw:
        return Identity(role='observer', raw=None, valid=True)
    role = raw.lower()
    if role in ROLE_LEVEL:
        return Identity(role=role, raw=raw, valid=True)
    return Identity(role='observer', raw=raw, valid=False)

def deny_message(identity: Identity, action: str) -> str:
    need = ROLE_LABEL[ACTION_MIN_ROLE.get(action, 'admin')]
    if not identity.valid:
        return ('请求头 %s 的值 `%s` 不认识（可选：observer / duty / admin）；'
                '本操作需要%s' % (HEADER, identity.raw, need))
    if action.startswith('weather-mode'):
        hint = '切换气象通道需要「管理员」权限'
        return '%s。你当前是「%s」，可在「设置 → 操作员角色」中切换。' % (hint, identity.label)
    return '本操作需要%s及以上；当前身份：%s（请求头 %s）' % (
        need, identity.label, identity.raw or '未提供，按观察员处理')
